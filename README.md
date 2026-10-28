<div align="center">

# 🧬 EVOL-AI

**AI 驱动的新药研发体系**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-131%20passed-brightgreen.svg)](#-跑测试)
[![Dependencies](https://img.shields.io/badge/dependencies-zero-blue.svg)](#-快速开始)

**中文** | [English](README.en.md)

</div>

> 把「跨物种机制发现 → 载体序列设计 → 体内验证」串成一条**可审计、可复利**的数据管线，让每一次湿实验都成为下一次预测的训练数据。

序列分析、同义密码子优化、靶点加权排序、预测–实验闭环台账，全部是真实计算 + 真实落库。

---

## 🚀 快速开始

```bash
cd evol-ai-platform
python app.py 8000        # 仅需 Python 3.10+，零第三方依赖
# 打开 http://127.0.0.1:8000
```

首次启动自动建 `data/evol.db` 并种入 18 条演示台账记录。

### 🧪 跑测试

```bash
python -m unittest discover -s tests -v   # 131 项单测全绿
node tools/e2e.js                          # 74 项真浏览器端到端（需先启动服务 + Playwright）
```

---

## 📁 目录

```
app.py                  HTTP 服务 + 路由 + SQLite（http.server，零依赖）
engine/
  codon_table.py        标准遗传密码 + Kazusa 人类密码子频率 + translate
  sequence.py           序列分析（GC/skew/CpG/同聚物/串联重复/16 种酶切位点/
                        免疫刺激基序/Kozak/隐蔽剪接/polyA/E2F/Sp1/稀有密码子）
  optimize.py           同义密码子优化（CSP：贪心 + 单步回溯 + 逐级放宽）
  targets.py            靶点六维加权排序
  protein.py            蛋白理化（MW/pI/GRAVY/脂肪族指数/ε280/疏水段/N-糖基化）
  metrics.py            MAE/R²/Spearman + bootstrap 区间 + 分层 + 前瞻切分 + 模型卡
  models.py             候选模型打分与许可一票否决
  assets.py             数据资产目录（检索 / 排序 / 权限）
  inference.py          可插拔推理任务系统（队列 / 持久化 / 三要素落盘）
data/
  targets.json          6 条适应症 × 六维评分 + 证据链
  demo_construct.txt    455 bp 示例构建体（人工注入 6 类风险位点）
  assets.json           演示数据资产目录
web/                    前端：index.html / app.js / styles.css，全部计算走 fetch
tests/                  131 项单测（序列/优化/蛋白/指标/偏差/模型/推理/资产/API/压测）
tools/e2e.js            Playwright 端到端
```

---

## 📡 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/targets?weights={...}` | 靶点排序；带 weights 则按给定权重重算 |
| GET | `/api/records` | 台账全量 + 实时指标 |
| GET | `/api/metrics` | 仅指标 |
| GET | `/api/models` | 候选模型矩阵（综合分 + 许可一票否决 + 排序）|
| GET | `/api/model-card?cutoff=10-01` | 模型卡：分层指标 / bootstrap 区间 / 分层异常 / 前瞻回溯 |
| GET | `/api/assets?q=&sort=` | 数据资产目录（检索 / 排序）|
| GET | `/api/demo` | 示例构建体序列 |
| GET | `/api/records/export.csv` | 台账导出 CSV（UTF-8 BOM）|
| POST | `/api/analyze` | `{sequence}` → 全量分析结果 |
| POST | `/api/optimize` | `{sequence, options}` → 优化序列 + 前后对比 + 放宽报告 |
| POST | `/api/protein` | `{sequence}` → 理化画像 + 序列风险 |
| POST | `/api/infer` | `{sequence}` → 提交结构推理任务（异步）|
| POST | `/api/records` | `{id,pred,obs,model,note,outcome}` → 写入台账 |
| DELETE | `/api/records/<id>` | 删除并返回新指标 |

### 一个真实例子

```bash
curl -s http://127.0.0.1:8000/api/demo \
  | python -c "import json,sys;print(json.load(sys.stdin)['sequence'])" > /tmp/s.txt
curl -s -X POST http://127.0.0.1:8000/api/optimize \
  -H 'Content-Type: application/json' \
  -d "{\"sequence\":\"$(cat /tmp/s.txt)\",\"options\":{\"cpg_free\":true,\"avoid_sites\":true}}"
```

示例构建体优化结果：

| 指标 | 优化前 | 优化后 |
|---|---|---|
| CpG / 100 bp | 7.9 | **0.0** |
| 风险条目 | 7 条 | **0 条** |
| 综合分 | 70.8 | **86.2** |
| 蛋白序列 | — | **零改动**（代码内 assert 保证）|
| 求解回溯 | — | 34 次 |

---

## 🎯 三个设计上的硬选择

1. **同义优化是约束满足问题，不是查表替换。** 前一个密码子以 C 结尾、当前氨基酸所有同义密码子都以 G 开头时（如 Glu 只有 GAA/GAG），接缝必然产生 CpG。这时不能悄悄放宽约束，必须**回溯上一个密码子**。放宽阶梯也重排过：CpG 守到最后，先牺牲串联重复。界面会把放宽次数和回溯次数如实报出来。

2. **不假装满足不了的条件。** CDS 长度不是 3 的倍数时，尾部余数无法构成完整密码子，引擎既不硬凑也不静默丢弃，而是在 `changes.truncated_nt` 里报出，界面用黄条明确提示。

3. **没接入的部分不放编造的数字。** 结构推理做成**可插拔的异步任务系统**（`engine/inference.py`）：提交 → 排队 → 运行 → 落库，结果强制附带可复现三要素（镜像 digest / 权重 hash / 输入 hash）。当前跑**确定性 mock 后端**——同输入同输出、不同输入不同结果，有单测钉住。接上云 GPU 后把 `ACTIVE_BACKEND` 换成 `BoltzBackend` 一处即可。蛋白理化（分子量 / pI / GRAVY / 脂肪族指数 / 疏水滑窗 / N-糖基化）是真实公式精确值；模型评分是启发式映射，界面常驻「演示数据」标签。

   疏水段阈值是校准过的：从「单个 7 aa 窗口」改成「连续 ≥15 aa」才判跨膜，避免把 EGFP 的 β-桶疏水核误报成跨膜螺旋，两种情形都有单测固定。

---

## 📊 指标口径

小样本回归最容易犯的错是只报一个点估计，所以主指标**一律带区间**：

```
总体      n=18  MAE 0.58 [0.41, 0.85]   R² 0.58 [0.20, 0.89]   ρ 0.80
b2-0.6.1  n=11  R² 0.00 [0.00, 0.82]    ← 自动判为分层异常
b2-0.5.4  n= 5  R² 0.72 [0.02, 1.00]
esm-lora  n= 2  R² 1.00 —（样本不足，不得引用）
```

五条硬规矩，都在 `engine/metrics.py`：

1. **区间固定 seed**——同一份数据每次算出一模一样的结果。
2. **n < 5 不给区间**，并标「不得单独引用」。
3. **分层异常自动检出**——某组 R² 与总体差 ≥0.3 就报警。
4. **前瞻 / 回溯分开看**——cutoff 取模型冻结日，冻结后的记录才算盲测。
5. **先审台账，再算指标**——指标再漂亮，如果台账只有成功案例，也只是「成功案例上的拟合度」。

模型卡可一键导出 Markdown，局限性是**强制项**：阴性样本未标注、无前瞻盲测、n<30 时 Spearman 不稳，都跟着指标一起引用。

---

## ⚠️ 台账本身可能是选择性录入的产物

没人愿意录失败实验，于是「成功案例档案」算出来的 R² 天然偏高。这里做了三件事：

**一、区分三种结局，技术失败不进指标。** `outcome` 取 `hit`（达阈值）/ `miss`（阴性但有读数）/ `fail`（技术失败，无有效读数）。`fail` 记录照样落库（失败率本身是构建体设计的信号），但不参与任何指标。界面会显示「计入指标 18 条」和「台账 19 条，1 条技术失败未计入」，数字对不上时明说，不让人猜。

**二、审计阳性率，超线直接报警。** 演示台账 18 条全达阈值——阳性率 100%，工具立刻判 `疑似选择性录入`：真实筛选的命中率远低于此，此时 MAE / R² 是**乐观偏差的上界**，不是模型能力。

**三、tipping-point：看到错到什么程度才推翻结论。** `sensitivity_missing` 假设有 x% 阴性样本从未入库，重算指标并画曲线。演示数据的 tipping point = **10%**——只需一成阴性样本漏录，R² 就从 0.584 跌破目标线 0.55。三条假设必须跟曲线一起显示，否则曲线只是装饰。

---

## 🚧 已知边界

- 结构推理后端当前为**确定性 mock**，不是真实 Boltz-2 前向——界面已标注，数字不可当模型能力引用；但任务队列、持久化、三要素落盘是真实工程，接入真实后端只改 `ACTIVE_BACKEND` 一处。
- 组学分析（Scanpy）、文献 RAG（PaperQA2）属 M2，未实现。
- 数据资产目录已接后端，支持检索与排序；「训练 > 评测 > 检索」权限单向递减，未标注用途的数据默认不可训练。
- 模型矩阵分数是内部评估口径（人工打分），但排序、综合分与许可否决由后端计算，规则可测。
- 无鉴权，仅限本机使用；患者样本相关数据未纳入本版。

---

<div align="center">

[MIT](LICENSE) © [skywalkerqqq](https://github.com/skywalkerqqq)

</div>
