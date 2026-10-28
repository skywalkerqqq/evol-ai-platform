"""候选模型评估矩阵。

这张表要回答的不是「哪个模型最强」，而是「哪个能进管线」。
两个判据分开：
  ① 硬门槛：许可分 < 60 一票否决。**不管精度多高**——AlphaFold3 精度 93，
     但权重是 CC BY-NC-SA 不可商用，进管线就是给未来埋法律风险。
  ② 综合分：只有过了门槛的模型才比这个。

排序也一样：被否决的排到末尾，且不参与"最优"的讨论。
"""

LICENSE_VETO = 60

DIMS = [
    ("ls", "许可"),
    ("acc", "精度"),
    ("fit", "任务匹配"),
    ("deploy", "部署成本"),
    ("interp", "可解释性"),
    ("comm", "社区活跃度"),
]

# 许可分只做门槛，**不进加权平均**。否则「许可差」被折算成分数摊薄，
# 与「一票否决」的语义直接矛盾。
SCORE_DIMS = [k for k, _ in DIMS if k != "ls"]

MODELS = [
    {"n": "Boltz-2", "task": "结构 + 结合亲和力", "lic": "MIT", "ls": 100, "acc": 92, "fit": 96,
     "deploy": 78, "interp": 62, "comm": 88, "stars": "≈8.5k", "verdict": "已上线"},
    {"n": "Protenix", "task": "AF3 级共折叠", "lic": "Apache-2.0", "ls": 95, "acc": 90, "fit": 82,
     "deploy": 70, "interp": 58, "comm": 66, "stars": "≈4.2k", "verdict": "评估中 · 兜底"},
    {"n": "AlphaFold3", "task": "共折叠（对照）", "lic": "CC BY-NC-SA", "ls": 25, "acc": 93, "fit": 60,
     "deploy": 40, "interp": 55, "comm": 75, "stars": "≈8.5k", "verdict": "仅 benchmark"},
    {"n": "ESM-2 / ESMFold", "task": "序列表征 / 单链折叠", "lic": "MIT", "ls": 100, "acc": 80, "fit": 90,
     "deploy": 92, "interp": 48, "comm": 85, "stars": "≈4.2k", "verdict": "已上线"},
    {"n": "RDKit / DeepChem", "task": "描述符 / ADMET", "lic": "BSD / MIT", "ls": 100, "acc": 72, "fit": 74,
     "deploy": 98, "interp": 80, "comm": 92, "stars": "2.5k+", "verdict": "已上线"},
    {"n": "Scanpy", "task": "单细胞组学", "lic": "BSD-3", "ls": 100, "acc": 85, "fit": 88,
     "deploy": 95, "interp": 72, "comm": 90, "stars": "2k+", "verdict": "已上线"},
    {"n": "Open Targets", "task": "靶点-疾病证据", "lic": "CC0 / Apache-2.0", "ls": 100, "acc": 82, "fit": 86,
     "deploy": 84, "interp": 76, "comm": 80, "stars": "org", "verdict": "已接入"},
    {"n": "PaperQA2", "task": "文献证据链 RAG", "lic": "Apache-2.0", "ls": 95, "acc": 70, "fit": 80,
     "deploy": 90, "interp": 85, "comm": 72, "stars": "≈8k", "verdict": "评估中"},
    {"n": "DiffDock", "task": "小分子对接", "lic": "MIT", "ls": 100, "acc": 68, "fit": 45,
     "deploy": 88, "interp": 50, "comm": 70, "stars": "≈1.6k", "verdict": "备选（不优先）"},
    {"n": "CodonFM", "task": "密码子表征", "lic": "待法务核", "ls": 60, "acc": 74, "fit": 78,
     "deploy": 82, "interp": 70, "comm": 55, "stars": "≈1.1k", "verdict": "评估中"},
]


def rank(weights: dict | None = None, veto: int = LICENSE_VETO) -> dict:
    """给所有候选模型打分排序，并执行许可一票否决。

    weights 可选，形如 {"acc": 2, "ls": 3}；缺省等权。
    """
    weights = weights or {}
    rows = []
    for m in MODELS:
        wsum = sum(weights.get(k, 1) for k in SCORE_DIMS) or 1
        total = sum(m[k] * weights.get(k, 1) for k in SCORE_DIMS) / wsum
        vetoed = m["ls"] < veto
        rows.append({
            **m,
            "total": round(total, 1),
            "vetoed": vetoed,
            "decision": "一票否决 · 许可不可商用" if vetoed else m["verdict"],
            "reason": (f"许可分 {m['ls']} < 门槛 {veto}（{m['lic']}）；"
                       f"其精度分 {m['acc']} 是本表最高，仍然不得进管线"
                       if vetoed else ""),
        })
    # 否决项一律沉底，不参与"最优"竞争
    rows.sort(key=lambda r: (r["vetoed"], -r["total"], r["n"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    passed = [r for r in rows if not r["vetoed"]]
    return {
        "dims": [{"key": k, "label": lbl} for k, lbl in DIMS],
        "score_dims": SCORE_DIMS,
        "rows": rows,
        "veto_threshold": veto,
        "best": passed[0]["n"] if passed else None,
        "vetoed": [r["n"] for r in rows if r["vetoed"]],
        "note": "许可分只作门槛（<60 一票否决），不参与加权；被否决项沉底，不进入最优候选。",
    }
