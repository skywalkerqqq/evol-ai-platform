"""靶点 / 适应症优先级评估。

数据来自 data/targets.json（内部整理，非公开数据库直连）。评分是一个可调的
加权模型——它的价值在于把「拍脑袋选适应症」变成可复盘的排序，而不是给出真值。
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

DIMS = [
    {"key": "genetics", "label": "遗传学证据", "default": 15},
    {"key": "omics", "label": "组学差异", "default": 25},
    {"key": "lit", "label": "文献强度", "default": 15},
    {"key": "druggable", "label": "可成药性", "default": 15},
    {"key": "safety", "label": "安全性", "default": 15},
    {"key": "conserve", "label": "跨物种保守性", "default": 15},
]

_cache = {"mtime": None, "rows": []}


def load_targets() -> list:
    path = DATA_DIR / "targets.json"
    mtime = path.stat().st_mtime
    if _cache["mtime"] != mtime:
        _cache["rows"] = json.loads(path.read_text(encoding="utf-8"))["targets"]
        _cache["mtime"] = mtime
    return _cache["rows"]


def rank(weights: dict | None = None) -> dict:
    weights = weights or {d["key"]: d["default"] for d in DIMS}
    total = sum(weights.get(d["key"], 0) for d in DIMS) or 1
    rows = []
    for t in load_targets():
        score = sum(t[d["key"]] * weights.get(d["key"], 0) for d in DIMS) / total
        rows.append({**t, "score": round(score, 1)})
    rows.sort(key=lambda r: -r["score"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return {"dims": DIMS, "rows": rows, "weights": weights}
