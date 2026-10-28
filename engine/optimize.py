"""同义密码子优化。

目标：在**不改变蛋白序列**的前提下，压掉合成与基因组稳定性上的已知风险位点，
同时按人源密码子偏好提升表达。这是一个约束满足问题，用贪心 + 逐级放宽求解。

约束优先级（从强到弱）：同聚物 > 酶切位点 > CpG > 串联重复。
放不开时按级降约束，并把降级次数如实报告出来——不假装全部满足。
"""

from .codon_table import AA_TO_CODONS, HUMAN_USAGE, DNA_CODON_TABLE, translate
from .sequence import ENZYMES, analyze, clean

CONTEXT = 12
MAX_RUN_RELAX = [5, 6, 7, 8]      # 依次放宽的同聚物上限


def _tail_ok(tail: str, codon: str, opts: dict) -> bool:
    ctx = (tail[-CONTEXT:] + codon).upper()

    max_run = opts["max_run"]
    if len(ctx) >= max_run:
        last = ctx[-1]
        if ctx[-max_run:] == last * max_run:
            return False

    if opts["avoid_sites"]:
        for _, motif in ENZYMES:
            if motif in ctx:
                return False

    if opts["cpg_free"]:
        # 密码子内部，以及跨密码子接缝（...C | G...）都要拦
        if "CG" in codon or (tail.endswith("C") and codon.startswith("G")):
            return False

    if opts["avoid_tandem"] and len(ctx) >= 9:
        if ctx[-3:] == ctx[-6:-3] == ctx[-9:-6]:
            return False

    return True


def optimize(raw: str, cpg_free: bool = True, avoid_sites: bool = True,
             avoid_tandem: bool = True, max_run: int = 5) -> dict:
    seq = clean(raw)
    start = seq.find("ATG")
    if start < 0:
        raise ValueError("未找到起始密码子 ATG，无法按 CDS 优化")
    prefix, cds = seq[:start], seq[start:]
    truncated = 0
    if len(cds) % 3 != 0:
        truncated = len(cds) % 3
        cds = cds[:len(cds) - truncated]
    protein = translate(cds)

    # 放宽顺序：先牺牲串联重复，再牺牲酶切位点，CpG 尽量守到最后
    ladder = [
        dict(cpg_free=cpg_free, avoid_sites=avoid_sites, avoid_tandem=avoid_tandem, max_run=max_run),
        dict(cpg_free=cpg_free, avoid_sites=avoid_sites, avoid_tandem=False, max_run=max_run),
        dict(cpg_free=cpg_free, avoid_sites=False, avoid_tandem=False, max_run=max_run),
        dict(cpg_free=False, avoid_sites=False, avoid_tandem=False, max_run=8),
    ]

    out, relax_hits, backtracks = [], [], 0
    built = prefix                      # 已生成的序列（含 5' 前缀），用于取上下文
    for idx, aa in enumerate(protein):
        original = cds[idx * 3:idx * 3 + 3]
        cands = AA_TO_CODONS.get(aa)
        if not cands:                      # X / 未知密码子：原样保留
            out.append(original)
            built += original
            continue

        ordered = sorted(cands, key=lambda c: -HUMAN_USAGE.get(c, 0))
        chosen, level_used = None, 0

        # 1) 先按最严约束试
        for c in ordered:
            if _tail_ok(built, c, ladder[0]):
                chosen = c
                break

        # 2) 全都不行时先回溯上一个密码子，而不是急着放宽当前位点
        if chosen is None and out:
            prev_cands = AA_TO_CODONS.get(protein[idx - 1], [])
            stem = built[:-3]
            for alt in sorted(prev_cands, key=lambda c: -HUMAN_USAGE.get(c, 0)):
                if alt == out[-1] or not _tail_ok(stem, alt, ladder[0]):
                    continue
                for c in ordered:
                    if _tail_ok(stem + alt, c, ladder[0]):
                        out[-1] = alt
                        built = stem + alt
                        chosen, level_used = c, 0
                        backtracks += 1
                        break
                if chosen:
                    break

        # 3) 仍不行，才按级放宽
        if chosen is None:
            for level in range(1, len(ladder)):
                for c in ordered:
                    if _tail_ok(built, c, ladder[level]):
                        chosen, level_used = c, level
                        break
                if chosen:
                    break

        if chosen is None:
            chosen, level_used = ordered[0], len(ladder)

        out.append(chosen)
        built += chosen
        relax_hits.append(level_used)

    new_cds = "".join(out)
    new_seq = prefix + new_cds
    assert translate(new_cds) == protein, "同义优化改变了蛋白序列"

    before = analyze(seq)
    after = analyze(new_seq)
    edits = sum(1 for i, c in enumerate(new_cds) if c != cds[i])
    codon_diffs = sum(1 for i in range(len(protein))
                      if new_cds[i * 3:i * 3 + 3] != cds[i * 3:i * 3 + 3])
    level_names = ["全部满足", "放宽：串联重复", "放宽：酶切位点", "放宽：CpG"]
    relax_stat = {}
    for lv in relax_hits:
        relax_stat[level_names[lv]] = relax_stat.get(level_names[lv], 0) + 1

    return {
        "sequence": new_seq,
        "protein": protein,
        "changes": {
            "codons": len(protein), "codons_changed": codon_diffs,
            "nt_changed": edits,
            "nt_changed_pct": round(edits / max(1, len(cds)) * 100, 1),
            "identity_pct": round((len(cds) - edits) / max(1, len(cds)) * 100, 1),
            "truncated_nt": truncated,
            "backtracks": backtracks,
        },
        "relaxation": relax_stat,
        "before": {k: before[k] for k in
                   ("gc", "cpg", "cpg_per_100", "cpg_ratio", "rare_frac", "verdict",
                    "composite", "scores", "risks")},
        "after": {k: after[k] for k in
                  ("gc", "cpg", "cpg_per_100", "cpg_ratio", "rare_frac", "verdict",
                   "composite", "scores", "risks", "length")},
        "after_detail": after,
    }
