"""数据资产目录。

把「哪些数据能商用、哪些能训练」做成一等公民的清单，而不是藏在页脚的一句话。
关键规则：**未标注用途的数据默认不可训练**——这正是数据治理的第一条红线。
"""

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS_PATH = ROOT / "data" / "assets.json"

# 三类用途的语义：训练 > 评测 > 检索（权限是单向递减的）
USAGE_ORDER = {"训练": 0, "评测": 1, "检索": 2}
USAGE_PILL = {"训练": "t", "评测": "v", "检索": "a"}

_cache = {"mtime": None, "data": None}


def load_assets() -> list:
    """读资产清单，带 mtime 缓存（和 targets.py 同一套路）。"""
    mtime = ASSETS_PATH.stat().st_mtime if ASSETS_PATH.exists() else None
    if _cache["data"] is not None and _cache["mtime"] == mtime:
        return _cache["data"]
    data = json.loads(ASSETS_PATH.read_text(encoding="utf-8"))
    _cache["mtime"] = mtime
    _cache["data"] = data
    return data


def summarize(assets: list) -> list:
    """按类别汇总：每类条数、可训练条数。"""
    cats = {}
    for a in assets:
        c = a["category"]
        cats.setdefault(c, {"total": 0, "train": 0})
        cats[c]["total"] += 1
        if a["usage"] == "训练":
            cats[c]["train"] += 1
    return [
        {"category": c, "total": v["total"], "train": v["train"]}
        for c, v in sorted(cats.items())
    ]


def directory(query: str = None, sort_by: str = None, desc: bool = False) -> dict:
    """返回资产目录：汇总 + 明细（支持检索与排序）。"""
    assets = load_assets()
    rows = list(assets)

    if query:
        q = query.strip().lower()
        rows = [a for a in rows if
                q in a["name"].lower() or q in a["category"].lower()
                or q in a["owner"].lower() or q in a["license"].lower()]

    if sort_by in ("name", "category", "owner", "usage", "size"):
        rows = sorted(rows, key=lambda a: a.get(sort_by, "").lower(), reverse=desc)

    for a in rows:
        a["pill"] = USAGE_PILL.get(a["usage"], "a")

    return {
        "summary": summarize(assets),
        "rows": rows,
        "total": len(assets),
        "matched": len(rows),
        "note": "未标注用途的数据默认不可训练；「训练 > 评测 > 检索」权限单向递减。",
    }
