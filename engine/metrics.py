"""预测-实验闭环的统计口径。

一次记录 = 一个构建体的「模型预测值」与「湿实验实测值」的配对。

这里的取舍比公式本身重要：
  1. 18 条记录算出来的 R²=0.58，95% 区间可能跨到 0.2–0.8。**不给区间的点估计
     就是误导**，所以主指标一律带 bootstrap 区间。
  2. 按模型版本分层后，样本量会掉到个位数。**n<5 不给区间，直接标「不可用」**，
     而不是照算一个看起来很像样的数。
  3. 前瞻/回溯必须分开看。回溯集上的指标只能证明「拟合得住历史」，不能证明能用。
  4. 区间用固定 seed，保证同一份数据每次算出来一模一样——否则报告无法复核。
  5. **台账本身可能是选择性录入的产物。** 没人愿意录失败实验，于是「成功的档案」
     算出来的 R² 天然偏高。所以这里不假设台账干净，而是先审计结局分布，
     再用 tipping-point 分析回答「要看错到什么程度才会推翻结论」。
"""

import datetime
import math
import random

MIN_N = 5                 # 低于这个样本量不给置信区间
BOOT_N = 2000
BOOT_SEED = 20261028      # 固定，保证可复现
ALPHA = 0.05

# ---- 结局口径：记录的是「实验本身」的结局，不是模型好坏
OUTCOME_LABEL = {"hit": "达阈值", "miss": "未达阈值", "fail": "技术失败"}
OUTCOMES = tuple(OUTCOME_LABEL)
HIT_RATE_ALARM = 0.80     # 阳性率超过这条线，就该怀疑只录了成功案例
HIT_RATE_WARN = 0.60
MISS_RATIOS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
SENS_REPEATS = 40         # 敏感性分析每个比例重复次数（取中位数消除单次抽样抖动）
TIP_LEVEL = 0.2           # R² 跌破这里，结论完全崩塌
TARGET_R2 = 0.55          # PRD 定的达标线：跌破它就不再满足验收标准


def mae(pairs) -> float:
    return sum(abs(p - o) for p, o in pairs) / len(pairs) if pairs else 0.0


def sigma(pairs) -> float:
    if not pairs:
        return 0.0
    return math.sqrt(sum((p - o) ** 2 for p, o in pairs) / len(pairs))


def pearson(pairs) -> float:
    n = len(pairs)
    if n < 2:
        return 0.0
    mp = sum(p for p, _ in pairs) / n
    mo = sum(o for _, o in pairs) / n
    cov = sum((p - mp) * (o - mo) for p, o in pairs)
    vp = sum((p - mp) ** 2 for p, _ in pairs)
    vo = sum((o - mo) ** 2 for _, o in pairs)
    if vp <= 0 or vo <= 0:
        return 0.0
    return cov / math.sqrt(vp * vo)


def r2(pairs) -> float:
    r = pearson(pairs)
    return r * r


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(pairs) -> float:
    if len(pairs) < 2:
        return 0.0
    rp = _ranks([p for p, _ in pairs])
    ro = _ranks([o for _, o in pairs])
    return pearson(list(zip(rp, ro)))


def bootstrap_ci(pairs, stat, n_boot: int = BOOT_N, alpha: float = ALPHA,
                 seed: int = BOOT_SEED):
    """percentile bootstrap 置信区间。

    样本量不足 MIN_N 时返回 None——不是"算不出来"，是**不该报**。
    """
    n = len(pairs)
    if n < MIN_N:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(n_boot):
        vals.append(stat([pairs[rng.randrange(n)] for _ in range(n)]))
    vals.sort()
    lo = vals[max(0, int(n_boot * alpha / 2))]
    hi = vals[min(n_boot - 1, int(n_boot * (1 - alpha / 2)) - 1)]
    return {"lo": round(lo, 3), "hi": round(hi, 3),
            "n_boot": n_boot, "alpha": alpha, "seed": seed}


def valid(records) -> list:
    """可计入统计的记录：必须有有效实测读数。

    技术失败（fail）的实测值是 0 或占位符，把它当「实测低」喂进 MAE/R² 会凭空
    放大误差——那不是模型不准，是实验没做成。所以一律剔除，单独报失败率。
    """
    return [r for r in records if (r.get("outcome") or "hit") != "fail"]


def outcome_audit(records) -> dict:
    """审计台账的结局分布：只录成功的台账会系统性高估模型。

    这一条是 PRD §8.2「负样本对称」的落地。判断依据是阳性率，不是样本量——
    18 条全阳性的台账比 200 条全阳性的台账更「干净」，也更不可信。
    """
    counts = {k: 0 for k in OUTCOMES}
    for r in records:
        counts[r.get("outcome") or "hit"] += 1

    total = len(records)
    measurable = counts["hit"] + counts["miss"]
    hit_rate = counts["hit"] / measurable if measurable else 0.0
    fail_rate = counts["fail"] / total if total else 0.0

    if measurable == 0:
        level = "alarm"
        verdict = "没有任何可测量记录（全部技术失败），指标无法计算。先救实验，别谈模型。"
    elif hit_rate >= HIT_RATE_ALARM:
        level = "alarm"
        verdict = (f"阳性率 {hit_rate:.0%}，超过 {HIT_RATE_ALARM:.0%} 警戒线。"
                   "真实筛选的命中率远低于此——台账大概率只留了成功的实验。"
                   "此时 MAE / R² 是**乐观偏差的上界**，不是模型能力。")
    elif hit_rate >= HIT_RATE_WARN:
        level = "warn"
        verdict = (f"阳性率 {hit_rate:.0%} 偏高，仍可能存在选择性录入。"
                   "建议补录被放弃的批次，再看指标是否稳定。")
    else:
        level = "ok"
        verdict = f"阳性率 {hit_rate:.0%}，结局分布可接受，指标偏差在可控范围。"

    out = {
        "total": total,
        "counts": counts,
        "labels": OUTCOME_LABEL,
        "measurable": measurable,
        "hit_rate": round(hit_rate, 3),
        "fail_rate": round(fail_rate, 3),
        "alarm_rate": HIT_RATE_ALARM,
        "level": level,
        "verdict": verdict,
    }
    unattr = [r["id"] for r in records
              if (r.get("outcome") or "hit") == "fail" and not (r.get("note") or "").strip()]
    if unattr:
        out["unattributed"] = unattr
    return out


def sensitivity_missing(records, ratios=MISS_RATIOS, seed: int = BOOT_SEED,
                        repeats: int = SENS_REPEATS, target: float = TARGET_R2) -> dict:
    """tipping-point 分析：若有 x% 的阴性样本从未入库，指标会变成什么样。

    这不是「预测未来」，是**用显式假设回答一个反问**：当前结论要看错到什么程度才会崩。
    三条假设必须跟着数字一起给出，否则曲线就是装饰：

      1. 未入库样本的预测值按已入库预测分布重采样 —— 模型对它们同样打了分，
         不会因为「后来失败了」就凭空预测得低。
      2. 未入库样本的实测值取已入库实测分布的 P20 附近，且**与预测值独立** ——
         模型没预判出它们会失败，这正是偏差的来源。
      3. 每个比例重复 {repeats} 次取中位数：单次抽样会出现「多加几个点 R² 反而升」
         的抖动（抽到低预测值恰好与低实测值一致），那是指标噪声，不是规律。

    这是**假设性边界分析**，不是对现实的测量。
    """
    recs = valid(records)
    pairs = [(r["pred"], r["obs"]) for r in recs]
    n = len(pairs)
    if n < MIN_N:
        return {"available": False,
                "reason": f"有效记录 {n} 条 < {MIN_N}，敏感性分析无意义，先补数据",
                "curve": []}

    preds = [p for p, _ in pairs]
    obss = sorted(o for _, o in pairs)
    low_obs = obss[max(0, int(round(0.2 * (len(obss) - 1))))]
    rng = random.Random(seed)

    def _median(xs):
        s = sorted(xs)
        k = len(s)
        return s[k // 2] if k % 2 else (s[k // 2 - 1] + s[k // 2]) / 2

    def _q(xs, q):
        s = sorted(xs)
        return s[min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))]

    curve = []
    for ratio in ratios:
        m = int(round(n * ratio / (1 - ratio))) if ratio > 0 else 0
        r2s, maes, sps = [], [], []
        for _ in range(repeats):
            ext = list(pairs)
            for _ in range(m):
                p = rng.choice(preds)
                o = max(0.0, low_obs + rng.gauss(0, 0.4))
                ext.append((p, o))
            r2s.append(r2(ext)); maes.append(mae(ext)); sps.append(spearman(ext))
        curve.append({
            "miss_rate": ratio,
            "n_syn": m,
            "n_eff": n + m,
            "mae": round(_median(maes), 3),
            "r2": round(_median(r2s), 3),
            "spearman": round(_median(sps), 3),
            # 不是置信区间，是重复随机化的 25–75 分位，用来看抖动幅度
            "r2_band": [round(_q(r2s, .25), 3), round(_q(r2s, .75), 3)],
            "r2_spread": round(_q(r2s, .75) - _q(r2s, .25), 3),
        })

    tip = next((c["miss_rate"] for c in curve if c["r2"] < TIP_LEVEL), None)
    tip_t = next((c["miss_rate"] for c in curve if c["r2"] < target), None)
    base = curve[0]["r2"]
    # 单调性自检：缺失越多指标反而越好，说明假设或抽样有问题，必须报出来
    non_mono = [curve[i]["miss_rate"] for i in range(1, len(curve))
                if curve[i]["r2"] > curve[i - 1]["r2"] + 0.02]
    if base < target:
        verdict = (f"基线 R² 仅 {base}，本身已低于目标线 {target}——"
                   "在没有任何缺失样本的情况下就不达标，先解决模型本身，偏差分析排在其后。")
    elif tip_t is None:
        verdict = (f"在 0–{max(ratios):.0%} 的缺失范围内 R² 始终 ≥ {target}，"
                   "结论对「漏录阴性」不敏感。")
    else:
        verdict = (f"只需 {tip_t:.0%} 的阴性样本从未入库，R² 就从 {base} 跌破目标线 {target}。"
                   "真实管线里漏录失败批次的比例远不止此——"
                   "所以当前的 R² 不能当模型能力引用，只能当「这批成功案例上的拟合度」引用。")

    return {
        "available": True,
        "base_r2": base,
        "tip_level": TIP_LEVEL,
        "target_r2": target,
        "tipping_point": tip,
        "tip_target": tip_t,
        "curve": curve,
        "repeats": repeats,
        "low_obs": round(low_obs, 2),
        "non_monotonic": non_mono,
        "assumptions": [
            "未入库样本的预测值按已入库预测分布重采样——模型对它们同样打了分。",
            f"未入库样本的实测值取已入库实测分布的 P20（{round(low_obs, 2)}）附近抖动，"
            "且与预测值独立——模型没预判出它们会失败，这正是偏差的来源。",
            f"每个比例重复 {repeats} 次取中位数；r2_band 是重复随机化的 25–75 分位，"
            "用来看抖动幅度，不是置信区间。",
            "这是假设性边界分析，回答「要看错到什么程度才推翻结论」，不是对现实的测量。",
        ],
        "seed": seed,
        "note": (f"曲线上每个点 = 假设有这么多阴性样本从未入库时的重算中位数。"
                 f"tip_target 取 R² 首次跌破目标线 {target} 的比例，"
                 f"tipping_point 取首次跌破 {TIP_LEVEL}（崩塌线）的比例。"),
        "verdict": verdict,
    }


def _block(records, min_n: int = MIN_N) -> dict:
    """一组记录的全套指标 + 区间 + 可信度判定。"""
    pairs = [(r["pred"], r["obs"]) for r in records]
    n = len(pairs)
    s = sigma(pairs)
    out = {
        "n": n,
        "mae": round(mae(pairs), 3),
        "r2": round(r2(pairs), 3),
        "spearman": round(spearman(pairs), 3),
        "sigma": round(s, 3),
        "reliable": n >= min_n,
    }
    if n >= min_n:
        out["mae_ci"] = bootstrap_ci(pairs, mae)
        out["r2_ci"] = bootstrap_ci(pairs, r2)
        out["spearman_ci"] = bootstrap_ci(pairs, spearman)
    else:
        out["mae_ci"] = out["r2_ci"] = out["spearman_ci"] = None
        out["warn"] = f"n={n} < {min_n}，样本不足，区间不可用；此组数字仅供登记，不得用于结论"
    return out


def stratify(records, key, min_n: int = MIN_N) -> list:
    """按 key(record) 分组，逐组给指标。

    分组后求和必须等于总体（有单测保证），否则就是漏了记录。
    """
    groups = {}
    for r in records:
        groups.setdefault(key(r), []).append(r)
    out = []
    for g in sorted(groups):
        blk = _block(groups[g], min_n)
        blk["group"] = g
        out.append(blk)
    out.sort(key=lambda x: (-x["n"], x["group"]))
    return out


def holdout_split(records, cutoff: str) -> dict:
    """按建档日期切成「回溯集 / 前瞻集」。

    口径说明：真实场景里 cutoff 应该是**模型冻结日**，冻结之后的记录才算盲测。
    这里的日期是演示数据，切分方式与真实一致，结论不能当成绩。
    """
    retro = [r for r in records if r["created"] < cutoff]
    pros = [r for r in records if r["created"] >= cutoff]
    return {
        "cutoff": cutoff,
        "retro": _block(retro),
        "prospective": _block(pros),
        "note": "cutoff 应取模型冻结日；冻结后的记录才算前瞻盲测。演示数据的日期是造出来的，"
                "两组差异不代表泛化能力。",
    }


def _ci_txt(ci) -> str:
    return f"[{ci['lo']}, {ci['hi']}]" if ci else "—（样本不足）"


def strat_anomalies(by_model: list, overall: dict, gap: float = 0.3) -> list:
    """分层异常检测：某组 R² 与总体差得离谱，就说明总体均值在骗人。

    只对 reliable 的组判——样本不足的组连指标都不该看，更不能拿来说异常。
    """
    out = []
    base = overall["r2"]
    for g in by_model:
        if not g["reliable"]:
            continue
        d = g["r2"] - base
        if abs(d) >= gap:
            out.append({
                "group": g["group"], "n": g["n"], "r2": g["r2"], "overall_r2": base,
                "delta": round(d, 3),
                "level": "worse" if d < 0 else "better",
                "msg": (f"{g['group']}（n={g['n']}）的 R²={g['r2']}，"
                        f"比总体 {base} {'低' if d < 0 else '高'} {abs(round(d, 3))}。"
                        f"总体指标掩盖了这个差异，必须单独归因。"),
            })
    return out


def model_card(records, cutoff: str = "10-01", model_name: str = "miRNA-RDR1 响应模型 v0",
               min_n: int = MIN_N) -> dict:
    """生成模型卡：结局审计 + 总体 + 分层 + 前瞻/回溯 + 敏感性 + 局限性。

    注意所有统计量都建立在 `valid(records)` 上——技术失败的记录被剔除，
    剔除了几条会写在模型卡里，不能悄悄少算。
    """
    recs = valid(records)
    audit = outcome_audit(records)
    overall = _block(recs)
    by_model = stratify(recs, lambda r: r["model"], min_n)
    split = holdout_split(recs, cutoff)
    anomalies = strat_anomalies(by_model, overall)
    sens = sensitivity_missing(recs)

    small = [g["group"] for g in by_model if not g["reliable"]]
    limitations = [
        f"样本量 {overall['n']} 条，R² 的 95% 区间为 {_ci_txt(overall['r2_ci'])}；"
        "区间宽度即不确定性，不能只引点估计。",
        audit["verdict"],
        sens["verdict"] if sens["available"] else sens["reason"],
        "无前瞻盲测：预测与实测同批产生，只能证明拟合历史，不能证明可用。",
    ]
    if audit["counts"]["fail"]:
        limitations.append(
            f"{audit['counts']['fail']} 条技术失败记录（占 {audit['fail_rate']:.0%}）"
            "未计入任何指标；失败率本身是构建体设计的信号，不应当作模型误差。")
    if small:
        limitations.append(f"分层后 {len(small)} 组样本量 < {min_n}（{'、'.join(small)}），"
                           "这些组的指标不得单独引用；n=2 时 R² 必然接近 1.0，是退化值不是好结果。")
    if overall["n"] < 30:
        limitations.append("n < 30，Spearman 对单个异常点敏感，排秩结论需扩样后复算。")
    for a in anomalies:
        limitations.append(a["msg"])

    rows = "\n".join(
        f"| {g['group']} | {g['n']} | {g['mae']} | {_ci_txt(g['mae_ci'])} | "
        f"{g['r2']} | {_ci_txt(g['r2_ci'])} | {g['spearman']} | "
        f"{'是' if g['reliable'] else '**否·样本不足**'} |"
        for g in by_model)

    oc = audit["counts"]
    sens_rows = "\n".join(
        f"| {c['miss_rate']:.0%} | {c['n_eff']} | {c['mae']} | {c['r2']} | "
        f"[{c['r2_band'][0]}, {c['r2_band'][1]}] |"
        for c in sens["curve"]) if sens["available"] else ""

    md = f"""# 模型卡 · {model_name}

生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
台账 {audit['total']} 条 · 计入指标 {overall['n']} 条 · 剔除技术失败 {oc['fail']} 条
置信区间：percentile bootstrap（{BOOT_N} 次，α={ALPHA}，seed={BOOT_SEED}）

## 0. 台账结局审计

| 结局 | 条数 |
|---|---|
| 达阈值 | {oc['hit']} |
| 未达阈值 | {oc['miss']} |
| 技术失败（不计入指标） | {oc['fail']} |

阳性率 **{audit['hit_rate']:.0%}**（警戒线 {audit['alarm_rate']:.0%}）· 技术失败率 {audit['fail_rate']:.0%}

**{audit['verdict']}**

## 1. 总体指标

| 指标 | 点估计 | 95% 区间 |
|---|---|---|
| MAE（×10⁹ VP/mL） | {overall['mae']} | {_ci_txt(overall['mae_ci'])} |
| R² | {overall['r2']} | {_ci_txt(overall['r2_ci'])} |
| Spearman ρ | {overall['spearman']} | {_ci_txt(overall['spearman_ci'])} |

## 2. 分层指标（按模型版本）

| 模型版本 | n | MAE | MAE 区间 | R² | R² 区间 | ρ | 可信 |
|---|---|---|---|---|---|---|---|
{rows}

## 3. 分层异常（自动检出）

{chr(10).join('- ' + a['msg'] for a in anomalies) if anomalies else '未检出显著分层异常（各可信组 R² 与总体差值 < 0.3）。'}

## 4. 前瞻 / 回溯

以 `{split['cutoff']}` 为界：

| 集合 | n | MAE | R² | ρ |
|---|---|---|---|---|
| 回溯集 | {split['retro']['n']} | {split['retro']['mae']} | {split['retro']['r2']} | {split['retro']['spearman']} |
| 前瞻集 | {split['prospective']['n']} | {split['prospective']['mae']} | {split['prospective']['r2']} | {split['prospective']['spearman']} |

{split['note']}

## 5. 缺失阴性样本的敏感性（tipping point）

{f"| 假设未入库比例 | 有效 n | MAE | R²（中位数） | 25–75 分位 |{chr(10)}|---|---|---|---|---|{chr(10)}{sens_rows}" if sens["available"] else sens["reason"]}

**{sens['verdict'] if sens['available'] else ''}**

假设条件（缺一不可）：
{chr(10).join('- ' + a for a in sens.get('assumptions', []))}

## 6. 局限性与已知偏差

{chr(10).join('- ' + x for x in limitations)}

## 7. 使用边界

本模型仅用于**候选排序与淘汰**，不用于单独放行进入动物实验。最终判断权在实验与研发负责人。
"""
    return {
        "model": model_name,
        "cutoff": cutoff,
        "audit": audit,
        "sensitivity": sens,
        "overall": overall,
        "by_model": by_model,
        "holdout": split,
        "anomalies": anomalies,
        "limitations": limitations,
        "boot": {"n_boot": BOOT_N, "alpha": ALPHA, "seed": BOOT_SEED, "min_n": min_n},
        "markdown": md,
    }


def summarize(records) -> dict:
    """台账页用的轻量汇总。

    n 是「计入指标」的条数，n_total 是台账实际条数——两个数都要给，
    否则界面上「表里有 21 行但 n=18」会让人以为漏算了。
    """
    recs = valid(records)
    pairs = [(r["pred"], r["obs"]) for r in recs]
    s = sigma(pairs)
    flagged = [r["id"] for r in recs if abs(r["pred"] - r["obs"]) > 2 * s] if s else []
    r = pearson(pairs)
    return {
        "n": len(pairs),
        "n_total": len(records),
        "n_fail": len(records) - len(pairs),
        "mae": round(mae(pairs), 3),
        "r2": round(r * r, 3),
        "pearson": round(r, 3),
        "spearman": round(spearman(pairs), 3),
        "sigma": round(s, 3),
        "flagged": flagged,
        "audit": outcome_audit(records),
    }
