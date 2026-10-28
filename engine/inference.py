"""结构推理任务系统。

把「结构预测」从一次同步调用升级成一个**可复现、可追溯的异步任务**。

核心思想：本机没有 GPU，跑不了真正的 Boltz-2。但「提交 → 排队 → 运行 → 落库 →
复现三要素」这条工程链路，是可以 100% 真实做出来的。于是：

  - 定义统一的 `InferenceBackend` 接口；
  - 内置 `MockBackend`：确定性伪随机，模拟 Boltz-2 的一次前向（同输入 + 同 seed
    → 完全相同的输出，可复现）；
  - 预留 `BoltzBackend`：接上云 GPU / 集群后，把它的 `run()` 换成真正的推理即可。

可复现三要素（缺一不可）：
  1. 镜像 digest  —— 跑推理的容器镜像；
  2. 权重 hash    —— 模型权重文件；
  3. 输入 hash    —— 规范化后的输入 YAML + MSA。
"""

import datetime
import hashlib
import random
import time

# ---- 任务状态机 ----------------------------------------------------------
# queued → running → done
#                 ↘ failed
QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
STATES = (QUEUED, RUNNING, DONE, FAILED)

# ---- 后端元数据 ----------------------------------------------------------
# 镜像 digest 与权重 hash 是「配置」，不随输入变化。生产环境替换成真实值。
MOCK_IMAGE_DIGEST = "sha256:mock-boltz2-9f2c41b7e0a3d5f8"
MOCK_WEIGHT_HASH = "boltz2_aff.ckpt · 3ad97e02c41b9f2a"
BOLTZ_IMAGE_DIGEST = "sha256:boltz2-1.1.0-cuda12.4-f8a1c9e2"
BOLTZ_WEIGHT_HASH = "boltz2_aff.ckpt · a1b2c3d4e5f6"  # 接入真实权重后替换


def normalize_input(payload_aa: str, hexon_aa: str) -> dict:
    """把两条蛋白序列规范化成一个确定的输入描述，并计算输入 hash。

    规范化保证：同样的两条序列，无论大小写 / 空白差异，都得到同一个 hash。
    这是可复现三要素里「输入 hash」的来源。
    """
    pa = "".join(payload_aa.split()).upper()
    ha = "".join(hexon_aa.split()).upper()
    yaml_text = (
        "version: 1\n"
        "sequences:\n"
        "  - protein:\n"
        "      id: A\n"
        "      sequence: " + pa + "\n"
        "  - protein:\n"
        "      id: B\n"
        "      sequence: " + ha + "\n"
        "properties:\n"
        "  - affinity:\n"
        "      binder: B\n"
    )
    input_hash = hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()[:16]
    return {
        "payload_aa": pa,
        "hexon_aa": ha,
        "yaml": yaml_text,
        "input_hash": input_hash,
    }


class InferenceBackend:
    """抽象后端：所有结构推理都走这个接口，方便换真实 GPU 后端。"""

    name = "abstract"

    def image_digest(self) -> str:
        raise NotImplementedError

    def weight_hash(self) -> str:
        raise NotImplementedError

    def run(self, norm: dict) -> dict:
        """执行一次推理，返回结果 dict。必须在有限时间内返回。"""
        raise NotImplementedError


class MockBackend(InferenceBackend):
    """确定性 mock：模拟 Boltz-2 前向，产出结构可复现的 pLDDT / pTM / 结合概率。

    不是瞎随机——用输入 hash 作 seed，所以**同输入同输出**；不同输入才不同结果。
    这一点本身就是在演示「可复现」到底意味着什么。
    """

    name = "mock-boltz2"

    def __init__(self, seed: int = 20261028):
        self._seed = seed

    def image_digest(self) -> str:
        return MOCK_IMAGE_DIGEST

    def weight_hash(self) -> str:
        return MOCK_WEIGHT_HASH

    def run(self, norm: dict) -> dict:
        # 模拟一次前向的耗时（真实 Boltz-2 单卡约 1–3 分钟，这里缩到亚秒级便于演示）
        time.sleep(0.4)
        rng = random.Random(self._seed ^ int(norm["input_hash"], 16))

        n = max(len(norm["payload_aa"]), 20)
        # 生成一条 pLDDT 曲线：整体高置信，夹几个柔性环（低置信段）
        plddt = []
        i = 0
        while i < n:
            # 每隔一段安排一个柔性环
            if rng.random() < 0.12:
                loop_len = rng.randint(6, 18)
                for _ in range(loop_len):
                    if len(plddt) >= n:
                        break
                    plddt.append(round(38 + rng.uniform(0, 12), 1))
                i += loop_len
            else:
                plddt.append(round(82 + rng.uniform(0, 14), 1))
                i += 1
        plddt = plddt[:n]
        mean_plddt = round(sum(plddt) / len(plddt), 1)

        ptm = round(min(0.99, 0.72 + rng.uniform(0, 0.2)), 3)
        binder = round(min(0.98, 0.55 + rng.uniform(0, 0.3)), 3)

        # 可复现三要素落进结果里
        return {
            "model": self.name,
            "n_res": n,
            "plddt": plddt,
            "mean_plddt": mean_plddt,
            "ptm": ptm,
            "binder": binder,
            "repro": {
                "image_digest": self.image_digest(),
                "weight_hash": self.weight_hash(),
                "input_hash": norm["input_hash"],
            },
        }


class BoltzBackend(InferenceBackend):
    """真实 Boltz-2 后端占位。

    接入步骤（接上云 GPU / 集群后替换 run()）：
      1. 把 payload/hexon 写成 YAML + MSA（Boltz 输入格式）；
      2. 调 `boltz predict --input x.yaml --output_dir ...`；
      3. 解析输出的 pLDDT / pTM / ipTM / 结合概率；
      4. 把真实镜像 digest / 权重 hash 填进 image_digest() / weight_hash()。
    """

    name = "boltz2"

    def __init__(self, backend_available: bool = False):
        self._available = backend_available

    def image_digest(self) -> str:
        return BOLTZ_IMAGE_DIGEST

    def weight_hash(self) -> str:
        return BOLTZ_WEIGHT_HASH

    def run(self, norm: dict) -> dict:
        if not self._available:
            raise RuntimeError(
                "Boltz-2 后端未接入：需要 GPU + 权重 + MSA。当前环境回退到 mock 后端。")
        raise NotImplementedError("接入真实 Boltz-2 后实现此方法")


# 默认后端：本机无 GPU，用 mock。切换生产环境只需改这一行。
ACTIVE_BACKEND = MockBackend()


def set_backend(backend: InferenceBackend):
    global ACTIVE_BACKEND
    ACTIVE_BACKEND = backend


def get_backend() -> InferenceBackend:
    return ACTIVE_BACKEND


def make_task_id(norm: dict) -> str:
    """任务 ID：时间戳 + 输入 hash 前缀 + 随机后缀。

    后缀保证同一秒内重复提交相同输入也不会撞 ID（UNIQUE 约束）。
    """
    ts = datetime.datetime.now().strftime("%m%d%H%M%S")
    nonce = random.SystemRandom().randrange(0, 100000)
    return f"bz-{ts}-{norm['input_hash'][:6]}-{nonce:05d}"


def build_task_payload(payload_aa: str, hexon_aa: str) -> dict:
    """提交任务前的准备：规范化输入 + 生成 task id。"""
    norm = normalize_input(payload_aa, hexon_aa)
    return {
        "task_id": make_task_id(norm),
        "norm": norm,
    }
