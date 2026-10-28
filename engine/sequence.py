"""载体序列分析。

所有指标都是可复算的确定量（GC / CpG / 酶切位点 / 同聚物 / 串联重复 / 密码子），
只有五维评分是启发式映射——它只用于排序与提示，不作为实验结论。
"""

from .codon_table import RARE_CODONS, translate

BASES = "ACGT"

ENZYMES = [
    ("EcoRI", "GAATTC"), ("BamHI", "GGATCC"), ("HindIII", "AAGCTT"), ("XhoI", "CTCGAG"),
    ("NheI", "GCTAGC"), ("KpnI", "GGTACC"), ("SalI", "GTCGAC"), ("NotI", "GCGGCCGC"),
    ("PacI", "TTAATTAA"), ("PmeI", "GTTTAAAC"), ("SwaI", "ATTTAAAT"), ("AscI", "GGCGCGCC"),
    ("MluI", "ACGCGT"), ("BglII", "AGATCT"), ("SpeI", "ACTAGT"), ("SphI", "GCATGC"),
]

IMMUNO_MOTIFS = ["GTCGTT", "GACGTT", "AACGTT", "TCGTCA"]   # TLR9 相关 CpG 基序


def clean(seq: str) -> str:
    return "".join(ch for ch in (seq or "").upper() if ch in "ACGTN")


def count_motif(seq: str, motif: str) -> int:
    n, i = 0, seq.find(motif)
    while i != -1:
        n += 1
        i = seq.find(motif, i + 1)
    return n


def find_runs(seq: str, minimum: int = 6):
    out, i, n = [], 0, len(seq)
    while i < n:
        j = i
        while j + 1 < n and seq[j + 1] == seq[i]:
            j += 1
        if j - i + 1 >= minimum:
            out.append({"base": seq[i], "start": i + 1, "len": j - i + 1})
        i = j + 1
    return out


def find_tandem(seq: str, max_hits: int = 6):
    out = []
    for k in (3, 4, 5, 6):
        i = 0
        while i + k <= len(seq):
            unit = seq[i:i + k]
            rep = 1
            while seq[i + rep * k:i + (rep + 1) * k] == unit:
                rep += 1
            if rep >= 4:
                out.append({"unit": unit, "start": i + 1, "rep": rep, "len": k * rep})
                i += rep * k - 1
            else:
                i += 1
    out.sort(key=lambda x: -x["len"])
    return out[:max_hits]


def gc_windows(seq: str, win: int = 30, step: int = 3):
    out = []
    for i in range(0, max(0, len(seq) - win) + 1, step):
        w = seq[i:i + win]
        gc = sum(1 for ch in w if ch in "GC") / win * 100
        out.append({"x": round((i + win / 2) / len(seq), 4), "v": round(gc, 1)})
    return out


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def analyze(raw: str) -> dict:
    seq = clean(raw)
    n = len(seq)
    if n < 30:
        raise ValueError("序列过短（至少 30 bp）")

    cnt = {b: seq.count(b) for b in BASES}
    gc = (cnt["G"] + cnt["C"]) / n * 100
    at_skew = (cnt["A"] - cnt["T"]) / max(1, cnt["A"] + cnt["T"])
    gc_skew = (cnt["G"] - cnt["C"]) / max(1, cnt["G"] + cnt["C"])

    cpg = count_motif(seq, "CG")
    cpg_per_100 = cpg / n * 100
    exp_cpg = (cnt["C"] * cnt["G"]) / n
    cpg_ratio = cpg / exp_cpg if exp_cpg else 0.0

    islands, win, step = [], 200, 100
    for i in range(0, max(0, n - win) + 1, step):
        w = seq[i:i + win]
        g, c, cg = w.count("G"), w.count("C"), count_motif(w, "CG")
        w_gc = (g + c) / win
        w_exp = (c * g) / win
        if w_gc > 0.5 and (cg / w_exp if w_exp else 0) > 0.6:
            islands.append({"start": i + 1, "len": win})

    runs = find_runs(seq)
    tandem = find_tandem(seq)

    sites = []
    for name, motif in ENZYMES:
        i = seq.find(motif)
        while i != -1:
            sites.append({"name": name, "motif": motif, "pos": i + 1})
            i = seq.find(motif, i + 1)

    immuno = []
    for m in IMMUNO_MOTIFS:
        i = seq.find(m)
        while i != -1:
            immuno.append({"motif": m, "pos": i + 1})
            i = seq.find(m, i + 1)

    kozak = any(m in seq[:60] for m in ("GCCACCATGG", "GCCGCCATGG", "ACCACCATGG"))
    start_codon = seq.find("ATG") + 1
    poly_a = count_motif(seq, "AATAAA")
    splice = count_motif(seq, "GGTAAG") + count_motif(seq, "AAGGTGAG")
    e2f = count_motif(seq, "TTTCGCGC") + count_motif(seq, "TTTGCGCGC")
    sp1 = count_motif(seq, "GGGCGG")

    cds_start = seq.find("ATGG")
    cds_start = cds_start if cds_start >= 0 else 0
    codons = rare = 0
    for i in range(cds_start, n - 2, 3):
        codons += 1
        if seq[i:i + 3] in RARE_CODONS:
            rare += 1
    rare_frac = rare / codons if codons else 0.0

    gc_dev = abs(gc - 50)
    expression = _clamp(100 - gc_dev * 2.1 - (0 if kozak else 18) - rare_frac * 130 - (0 if start_codon else 10))
    stability = _clamp(100 - len(runs) * 15 - len(tandem) * 8 - (20 if n > 36000 else 0))
    immuno_safety = _clamp(100 - cpg_per_100 * 4.4 - len(immuno) * 9)
    manufacture = _clamp(100 - max(0, gc - 65) * 2.8 - max(0, 42 - gc) * 2.6
                         - len(runs) * 12 - len(tandem) * 5)
    selectivity = _clamp(40 + e2f * 10 + sp1 * 2 + (6 if "TTTCGCGC" in seq else 0))

    scores = {
        "表达强度": round(expression, 1),
        "基因组稳定性": round(stability, 1),
        "免疫安全": round(immuno_safety, 1),
        "制造可行性": round(manufacture, 1),
        "肿瘤选择性": round(selectivity, 1),
    }
    composite = sum(scores.values()) / len(scores)

    risks = []
    if gc < 42 or gc > 65:
        risks.append({"lv": "hi", "t": "GC 含量越界", "p": f"全序列 GC {gc:.1f}%",
                      "d": "偏离 42–65% 易导致合成难度上升或表达下降",
                      "a": "对 CDS 做同义替换把 GC 拉回 48–60%"})
    if not kozak:
        risks.append({"lv": "md", "t": "Kozak 序列偏弱", "p": f"ATG @ {start_codon or '未检出'}",
                      "d": "翻译起始效率可能不足", "a": "替换为 GCCACCATGG"})
    for r in runs[:3]:
        risks.append({"lv": "hi" if r["len"] >= 8 else "md", "t": "同聚物长串",
                      "p": f"{r['base']}×{r['len']} @ {r['start']}",
                      "d": "合成/克隆易发生滑移错配，测序易出现假信号",
                      "a": "拆分同义密码子打断连续碱基"})
    for t in tandem[:2]:
        risks.append({"lv": "md", "t": "串联重复", "p": f"{t['unit']}×{t['rep']} @ {t['start']}",
                      "d": "腺病毒基因组高重复区易发生重排丢失",
                      "a": "同义突变打断重复单元"})
    if immuno:
        pos = " · ".join(f"{x['motif']}@{x['pos']}" for x in immuno[:3])
        risks.append({"lv": "md", "t": "免疫刺激 CpG 基序", "p": pos,
                      "d": "TLR9 激活可能加速载体清除、降低体内持续表达",
                      "a": "同义去除或替换为低刺激同义密码子"})
    if cpg_per_100 > 6:
        risks.append({"lv": "md", "t": "CpG 密度偏高", "p": f"{cpg_per_100:.1f} / 100 bp",
                      "d": "病毒载体通常要求 CpG 抑制（CpG-depletion）",
                      "a": "执行 CpG-free 同义优化"})
    if rare_frac > 0.14:
        risks.append({"lv": "md", "t": "稀有密码子占比高", "p": f"{rare_frac * 100:.1f}%",
                      "d": "可能拖慢翻译延伸，影响滴度", "a": "按人源密码子频率重编码"})
    if splice:
        risks.append({"lv": "lo", "t": "潜在隐蔽剪接位点", "p": f"{splice} 处",
                      "d": "转录本可能被异常剪接", "a": "同义破坏 GGTAAG 类供体位点"})
    if poly_a:
        risks.append({"lv": "lo", "t": "内部 polyA 信号", "p": f"{poly_a} 处 AATAAA",
                      "d": "过早终止转录，降低全长转录本比例", "a": "若无功能需求则同义移除"})
    for s in sites:
        risks.append({"lv": "lo", "t": f"酶切位点 {s['name']}", "p": f"{s['motif']} @ {s['pos']}",
                      "d": "克隆/鉴定可用；若落在功能区需确认不干扰",
                      "a": "保留并写入构建体图谱，或同义移除"})

    hi = sum(1 for r in risks if r["lv"] == "hi")
    md = sum(1 for r in risks if r["lv"] == "md")
    if composite >= 70 and hi == 0 and md <= 2:
        verdict = "建议下单"
    elif composite >= 52 and hi == 0:
        verdict = "可下单 · 需复核"
    else:
        verdict = "建议优化后下单"

    return {
        "length": n,
        "gc": round(gc, 2), "at_skew": round(at_skew, 3), "gc_skew": round(gc_skew, 3),
        "counts": cnt,
        "cpg": cpg, "cpg_per_100": round(cpg_per_100, 2), "cpg_ratio": round(cpg_ratio, 2),
        "cpg_islands": islands,
        "runs": runs, "tandem": tandem, "sites": sites, "immuno": immuno,
        "kozak": kozak, "start_codon": start_codon, "poly_a": poly_a,
        "splice": splice, "e2f": e2f, "sp1": sp1,
        "rare": rare, "codons": codons, "rare_frac": round(rare_frac, 3),
        "scores": scores, "composite": round(composite, 1),
        "verdict": verdict, "risks": risks,
        "gc_windows": gc_windows(seq),
        "protein": translate(seq)[:1200],
    }
