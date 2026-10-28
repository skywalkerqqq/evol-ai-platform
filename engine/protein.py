"""蛋白理化与序列风险特征。

这里**只做能用公式精确定义的计算**——每一项都有明确的出处与算法，
不包含任何训练出来的预测器。目的是回答「这个构建体翻译出来的蛋白
能不能好好表达/纯化/成药」，而不是「它长什么样」。

明确不做的事：不预测二级结构、不预测结构、不预测免疫原性。
那些要么需要 Boltz-2/ESMFold 这类模型，要么需要湿实验，硬编一个
数字出来比不给更糟。

参考口径：
  GRAVY / 疏水性      Kyte & Doolittle (1982)
  脂肪族指数           Ikai (1980)
  等电点 / 净电荷       Bjellqvist 等 pKa 参数（EMBOSS 实现口径）
  摩尔吸光系数          Pace 等 (1995)，还原态
  N-糖基化基序         N-X-S/T，X ≠ P
"""

from .codon_table import DNA_CODON_TABLE, translate
from .sequence import clean

# Kyte & Doolittle 疏水性标度
KD = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5, "Q": -3.5, "E": -3.5,
    "G": -0.4, "H": -3.2, "I": 4.5, "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8,
    "P": -1.6, "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}

# 平均残基质量（Da），最后加一个 H2O
RESIDUE_MASS = {
    "G": 57.0519, "A": 71.0788, "S": 87.0782, "P": 97.1167, "V": 99.1326,
    "T": 101.1051, "C": 103.1388, "L": 113.1594, "I": 113.1594, "N": 114.1038,
    "D": 115.0886, "Q": 128.1307, "K": 128.1741, "E": 129.1155, "M": 131.1926,
    "H": 137.1411, "F": 147.1766, "R": 156.1875, "Y": 163.1760, "W": 186.2132,
}
WATER = 18.01524

# 解离常数（EMBOSS pK 口径）
PKA = {
    "N_term": 8.6, "C_term": 3.6, "K": 10.8, "R": 12.5, "H": 6.5,
    "D": 3.9, "E": 4.1, "C": 8.5, "Y": 10.1,
}

WINDOW = 7                     # 疏水性滑窗宽度
TM_WINDOW_THRESHOLD = 1.6      # 窗口均值超过它，视为潜在跨膜/强疏水段


def _net_charge(protein: str, ph: float) -> float:
    """给定 pH 下的净电荷（Henderson-Hasselbalch 累加）。"""
    q = 0.0
    # 正电荷基团
    q += 1.0 / (1.0 + 10 ** (ph - PKA["N_term"]))
    for aa, n in (("K", protein.count("K")), ("R", protein.count("R")),
                  ("H", protein.count("H"))):
        q += n / (1.0 + 10 ** (ph - PKA[aa]))
    # 负电荷基团
    q -= 1.0 / (1.0 + 10 ** (PKA["C_term"] - ph))
    for aa, n in (("D", protein.count("D")), ("E", protein.count("E")),
                  ("C", protein.count("C")), ("Y", protein.count("Y"))):
        q -= n / (1.0 + 10 ** (PKA[aa] - ph))
    return q


def isoelectric_point(protein: str) -> float:
    """二分求解净电荷为 0 的 pH。"""
    lo, hi = 0.0, 14.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _net_charge(protein, mid) > 0:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 2)


def hydrophobic_profile(protein: str, window: int = WINDOW) -> list:
    """滑窗平均疏水性。窗口内出现非标准残基就跳过该窗。"""
    out = []
    n = len(protein)
    if n < window:
        return out
    for i in range(n - window + 1):
        seg = protein[i:i + window]
        vals = [KD.get(c) for c in seg]
        if any(v is None for v in vals):
            continue
        out.append({"i": i, "mean": round(sum(vals) / window, 2)})
    return out


def glycosylation_sites(protein: str) -> list:
    """N-X-S/T 基序，X 不能是脯氨酸。返回 1-based 起始位点。"""
    hits = []
    for i in range(len(protein) - 2):
        a, b, c = protein[i], protein[i + 1], protein[i + 2]
        if a == "N" and b != "P" and c in ("S", "T"):
            hits.append({"pos": i + 1, "motif": protein[i:i + 3]})
    return hits


def low_complexity_frac(protein: str, window: int = 20) -> float:
    """低复杂度占比：20 aa 滑窗中，出现次数最多的两种残基占比 ≥ 60% 的窗口比例。"""
    n = len(protein)
    if n < window:
        return 0.0
    hits = 0
    total = 0
    for i in range(n - window + 1):
        seg = protein[i:i + window]
        counts = {}
        for c in seg:
            counts[c] = counts.get(c, 0) + 1
        top2 = sum(sorted(counts.values(), reverse=True)[:2])
        total += 1
        if top2 / window >= 0.6:
            hits += 1
    return round(hits / max(1, total), 3)


def hydrophobic_runs(profile: list, threshold: float = TM_WINDOW_THRESHOLD,
                     window: int = WINDOW) -> list:
    """把超阈值的滑窗合并成连续段，只保留真正成片的疏水区。

    单个超阈窗口在球状蛋白的疏水核里很常见，不足以说明什么；
    真正的跨膜螺旋约 19 aa，对应 13 个连续窗口。所以按「连续长度」判。
    """
    runs, cur = [], []
    for p in profile:
        if p["mean"] >= threshold:
            if cur and p["i"] != cur[-1]["i"] + 1:
                runs.append(cur)
                cur = []
            cur.append(p)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    out = []
    for r in runs:
        out.append({
            "start": r[0]["i"] + 1,                                     # 1-based
            "end": r[-1]["i"] + window,
            "span": r[-1]["i"] + window - r[0]["i"],
            "windows": len(r),
            "peak": max(x["mean"] for x in r),
        })
    return sorted(out, key=lambda x: x["start"])


def describe(raw_dna: str) -> dict:
    """从 DNA 构建体出发，翻译后给出理化与序列风险画像。"""
    seq = clean(raw_dna)
    start = seq.find("ATG")
    if start < 0:
        raise ValueError("未找到起始密码子 ATG，无法翻译")
    prefix, cds = seq[:start], seq[start:]
    truncated = 0
    if len(cds) % 3:
        truncated = len(cds) % 3
        cds = cds[:len(cds) - truncated]

    protein = translate(cds)
    # translate 遇到终止密码子会输出 '*'，计算前剔除
    body = protein.rstrip("*")
    n_aa = len(body)
    if n_aa == 0:
        raise ValueError("CDS 翻译结果为空")

    mw = sum(RESIDUE_MASS.get(c, 0.0) for c in body) + WATER
    gravy = round(sum(KD.get(c, 0.0) for c in body) / n_aa, 3)
    aromaticity = round(sum(body.count(c) for c in "FWY") / n_aa, 3)
    aliphatic = round(100 * (
        body.count("A") / n_aa
        + 2.9 * body.count("V") / n_aa
        + 3.9 * (body.count("I") + body.count("L")) / n_aa
    ), 1)

    profile = hydrophobic_profile(body)
    runs = hydrophobic_runs(profile)
    # 真跨膜螺旋约 19 aa，留余量取 15；10–14 aa 只算伸展疏水段（多为球状蛋白疏水核）
    tm_runs = [r for r in runs if r["span"] >= 15]
    stretch_runs = [r for r in runs if 10 <= r["span"] < 15]
    max_win = max(profile, key=lambda p: p["mean"]) if profile else None

    composition = {c: body.count(c) for c in sorted(set(body), key=lambda x: -body.count(x))}
    top2 = sum(sorted(composition.values(), reverse=True)[:2])
    glyc = glycosylation_sites(body)
    lcr = low_complexity_frac(body)

    basic = body.count("K") + body.count("R")
    acidic = body.count("D") + body.count("E")

    # ---- 风险判定（全部基于可复核的数值阈值，不是模型打分）
    risks = []
    if tm_runs:
        top = max(tm_runs, key=lambda r: r["span"])
        risks.append({
            "lv": "hi", "t": "成片强疏水段（疑似跨膜/疏水结构域）",
            "d": f"{len(tm_runs)} 处连续窗口均值 ≥ {TM_WINDOW_THRESHOLD}，最长 {top['start']}–{top['end']} aa"
                 f"（跨 {top['span']} aa，峰值 {top['peak']}）",
            "a": "若设计为可溶性 payload，需确认是否为跨膜结构域；分泌型表达注意包涵体",
        })
    elif stretch_runs:
        top = max(stretch_runs, key=lambda r: r["span"])
        risks.append({"lv": "md", "t": "伸展疏水段",
                      "d": f"{top['start']}–{top['end']} aa（跨 {top['span']} aa，峰值 {top['peak']}），"
                           f"未达跨膜长度（≥15 aa）",
                      "a": "球状蛋白疏水核的常见特征；若该区暴露于表面则关注聚集与包涵体"})
    elif max_win and max_win["mean"] >= 2.6:
        risks.append({"lv": "lo", "t": "局部强疏水峰",
                      "d": f"{max_win['i'] + 1}–{max_win['i'] + WINDOW} aa 均值 {max_win['mean']}，未成片",
                      "a": "多为埋藏残基；无需单独处理"})
    if gravy > 0.2:
        risks.append({"lv": "md", "t": "整体偏疏水",
                      "d": f"GRAVY {gravy} > 0.2，可溶性表达难度上升",
                      "a": "考虑低温诱导/融合助溶标签，纯化前先做可溶性分级"})
    if glyc:
        risks.append({"lv": "md", "t": f"N-糖基化基序 {len(glyc)} 处",
                      "d": "位点 " + "、".join(f"{g['motif']}@{g['pos']}" for g in glyc[:4]),
                      "a": "若在真核表达系统中生产，需验证糖型；糖基化会改变分子量与活性"})
    if lcr > 0.15:
        risks.append({"lv": "md", "t": "低复杂度区占比偏高",
                      "d": f"{round(lcr * 100, 1)}% 的 20 aa 窗口为低复杂度",
                      "a": "可能形成无序区，纯化易降解；也常是免疫原性热点，需实验确认"})
    if top2 / n_aa > 0.28:
        risks.append({"lv": "lo", "t": "氨基酸组成偏窄",
                      "d": f"最高两种残基占 {round(top2 / n_aa * 100, 1)}%",
                      "a": "检查是否为重复序列设计；重复序列易引发重组丢失"})
    if truncated:
        risks.append({"lv": "lo", "t": f"CDS 尾部 {truncated} nt 未参与翻译",
                      "d": "长度非 3 的倍数，尾部不构成完整密码子",
                      "a": "确认是设计如此还是序列录入有误"})
    if "*" in body:
        risks.append({"lv": "hi", "t": "CDS 内部存在终止密码子",
                      "d": f"位置 {body.find('*') + 1} aa 处提前终止",
                      "a": "会导致截短表达，必须核对读框与序列"})
    elif not protein.endswith("*"):
        risks.append({"lv": "md", "t": "缺少终止密码子",
                      "d": "CDS 末尾未检出 TAA/TAG/TGA",
                      "a": "补终止密码子，否则翻译可能通读进入骨架序列"})

    return {
        "cds_nt": len(cds),
        "truncated_nt": truncated,
        "n_aa": n_aa,
        "mw_kda": round(mw / 1000, 2),
        "gravy": gravy,
        "aromaticity": aromaticity,
        "aliphatic_index": aliphatic,
        "pI": isoelectric_point(body),
        "charge_ph7": round(_net_charge(body, 7.0), 2),
        "ext_coeff_280": 5500 * body.count("W") + 1490 * body.count("Y"),
        "cys": body.count("C"),
        "basic": basic,
        "acidic": acidic,
        "n_glyc": len(glyc),
        "glyc_sites": glyc,
        "low_complexity_frac": lcr,
        "hydro_window": WINDOW,
        "tm_threshold": TM_WINDOW_THRESHOLD,
        "hydrophobic_runs": runs,
        "hydrophobic_peak": max_win,
        "profile": profile,
        "composition": composition,
        "risks": risks,
        "protein": body,
        "prefix_nt": len(prefix),
        "note": "理化量为公式精确计算；二级结构/三维结构/免疫原性未经模型预测，需 Boltz-2 或湿实验。",
    }
