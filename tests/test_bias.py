"""台账偏差审计与敏感性分析的测试。

这一层的断言不是"输出好看"，而是钉住三条容易被悄悄破坏的性质：
  1. 技术失败的记录绝不进 MAE / R² —— 否则实验失败会被算成模型误差；
  2. 缺失阴性样本越多，指标只能变差 —— 曲线出现"加错点反而变好"就是方法有问题；
  3. 同一份数据 + 同一 seed，结论必须一模一样 —— 否则报告无法复核。
"""

import unittest

from engine import metrics


def rec(rid, pred, obs, outcome="hit", model="b2-0.6.1", created="10-01", note=""):
    return {"id": rid, "pred": pred, "obs": obs, "model": model,
            "created": created, "note": note, "outcome": outcome}


class TestOutcomeFilter(unittest.TestCase):
    """技术失败的记录必须被挡在统计之外。"""

    def test_fail_excluded_from_metrics(self):
        recs = [rec("A", 6.0, 6.1), rec("B", 5.0, 5.2),
                rec("C", 7.0, 0.0, outcome="fail")]      # 失败记录的 obs 是占位 0
        s = metrics.summarize(recs)
        self.assertEqual(s["n"], 2)                       # 只算两条
        self.assertEqual(s["n_total"], 3)
        self.assertEqual(s["n_fail"], 1)
        # 若把 0 算进去，MAE 会从 0.15 涨到 ~2.4
        self.assertAlmostEqual(s["mae"], 0.15, places=2)

    def test_fail_not_flagged_as_sigma_outlier(self):
        """失败记录偏差巨大，但不该进 2σ 异常列表——那不是预测错误。"""
        recs = [rec(f"R{i}", 6.0 + (i % 3) * 0.1, 6.05) for i in range(8)]
        recs.append(rec("FAIL", 6.2, 0.0, outcome="fail"))
        s = metrics.summarize(recs)
        self.assertNotIn("FAIL", s["flagged"])

    def test_missing_outcome_defaults_to_hit(self):
        """老库没有 outcome 列（值为 None）时按达阈值处理，不能崩。"""
        recs = [{"id": "A", "pred": 6.0, "obs": 6.1, "model": "m", "created": "10-01", "note": ""}]
        a = metrics.outcome_audit(recs)
        self.assertEqual(a["counts"]["hit"], 1)
        self.assertEqual(len(metrics.valid(recs)), 1)

    def test_all_fail_gives_zero_measurable(self):
        recs = [rec("A", 6.0, 0.0, outcome="fail"), rec("B", 5.0, 0.0, outcome="fail")]
        a = metrics.outcome_audit(recs)
        self.assertEqual(a["measurable"], 0)
        self.assertEqual(a["level"], "alarm")


class TestOutcomeAudit(unittest.TestCase):
    """阳性率判定：只录成功的台账必须被拦下来。"""

    def _mk(self, hit, miss, fail=0):
        out = [rec(f"H{i}", 6, 6) for i in range(hit)]
        out += [rec(f"M{i}", 6, 4, outcome="miss") for i in range(miss)]
        out += [rec(f"F{i}", 6, 0, outcome="fail", note="滴度不足") for i in range(fail)]
        return out

    def test_all_hits_is_alarm(self):
        a = metrics.outcome_audit(self._mk(18, 0))
        self.assertEqual(a["hit_rate"], 1.0)
        self.assertEqual(a["level"], "alarm")
        self.assertIn("乐观偏差", a["verdict"])

    def test_boundary_alarm_at_threshold(self):
        # 8/10 = 80%，正好等于警戒线 → 仍判 alarm（用 >=）
        self.assertEqual(metrics.outcome_audit(self._mk(8, 2))["level"], "alarm")

    def test_warn_band(self):
        # 7/10 = 70%，在 60%–80% 之间 → warn
        self.assertEqual(metrics.outcome_audit(self._mk(7, 3))["level"], "warn")

    def test_ok_below_warn(self):
        # 5/10 = 50% → ok
        self.assertEqual(metrics.outcome_audit(self._mk(5, 5))["level"], "ok")

    def test_fail_rate_reported(self):
        a = metrics.outcome_audit(self._mk(5, 5, fail=5))
        self.assertAlmostEqual(a["fail_rate"], 1 / 3, places=3)
        self.assertEqual(a["total"], 15)

    def test_unattributed_fail_listed(self):
        recs = [rec("A", 6, 6), rec("F1", 6, 0, outcome="fail", note=""),
                rec("F2", 6, 0, outcome="fail", note="包装滴度不足")]
        a = metrics.outcome_audit(recs)
        self.assertEqual(a["unattributed"], ["F1"])       # 有归因的不该被列出


class TestSensitivity(unittest.TestCase):
    """tipping-point 分析：假设显式、结论单调、可复现。"""

    @classmethod
    def setUpClass(cls):
        # 造一份 R² 明显偏低的台账，让 tipping point 落在可观测范围内
        cls.recs = [
            rec("A", 6.8, 6.4), rec("B", 5.9, 6.2), rec("C", 7.1, 6.9),
            rec("D", 4.8, 4.1), rec("E", 6.2, 5.8), rec("F", 5.4, 6.0),
            rec("G", 7.6, 6.7), rec("H", 3.9, 4.4), rec("I", 6.5, 6.1),
            rec("J", 5.1, 4.6), rec("K", 8.2, 5.6), rec("L", 6.0, 6.3),
        ]
        cls.s = metrics.sensitivity_missing(cls.recs)

    def test_available_and_shaped(self):
        self.assertTrue(self.s["available"])
        self.assertEqual(len(self.s["curve"]), len(metrics.MISS_RATIOS))
        self.assertEqual(self.s["curve"][0]["miss_rate"], 0.0)
        self.assertEqual(self.s["curve"][0]["n_syn"], 0)

    def test_baseline_matches_raw_metric(self):
        """0% 缺失的那一点必须等于原始 R²，否则整个曲线不可信。"""
        pairs = [(r["pred"], r["obs"]) for r in self.recs]
        self.assertAlmostEqual(self.s["base_r2"], round(metrics.r2(pairs), 3), places=3)

    def test_monotonic_degradation(self):
        """缺失越多只能越差。出现回升说明合成方式有偏，必须报出来。"""
        r2s = [c["r2"] for c in self.s["curve"]]
        self.assertEqual(self.s["non_monotonic"], [],
                         f"曲线非单调：{r2s}")
        self.assertLess(r2s[-1], r2s[0])

    def test_tipping_point_is_first_breach(self):
        tip = self.s["tip_target"]
        self.assertIsNotNone(tip)
        # 该比例之前都应在目标线之上，该比例本身已跌破
        for c in self.s["curve"]:
            if c["miss_rate"] < tip:
                self.assertGreaterEqual(c["r2"], self.s["target_r2"])
            elif c["miss_rate"] == tip:
                self.assertLess(c["r2"], self.s["target_r2"])

    def test_reproducible(self):
        again = metrics.sensitivity_missing(self.recs)
        self.assertEqual([c["r2"] for c in self.s["curve"]],
                         [c["r2"] for c in again["curve"]])

    def test_assumptions_are_disclosed(self):
        """假设必须跟着数字一起给出，否则曲线就是装饰。"""
        joined = "".join(self.s["assumptions"])
        self.assertIn("重采样", joined)
        self.assertIn("独立", joined)
        self.assertIn("不是对现实的测量", joined)

    def test_fail_records_ignored(self):
        """技术失败记录不该参与敏感性分析的基线。"""
        with_fail = self.recs + [rec("F", 6.0, 0.0, outcome="fail", note="污染")]
        s2 = metrics.sensitivity_missing(with_fail)
        self.assertAlmostEqual(s2["base_r2"], self.s["base_r2"], places=3)

    def test_too_few_records_unavailable(self):
        s = metrics.sensitivity_missing([rec("A", 6, 6), rec("B", 5, 5)])
        self.assertFalse(s["available"])
        self.assertIn("先补数据", s["reason"])

    def test_band_brackets_median(self):
        for c in self.s["curve"][1:]:
            lo, hi = c["r2_band"]
            self.assertLessEqual(lo, c["r2"] + 0.001)
            self.assertGreaterEqual(hi, c["r2"] - 0.001)


class TestCardIntegration(unittest.TestCase):
    """模型卡必须把审计与敏感性带进 limitations，不能只藏在字段里。"""

    def test_card_carries_audit_and_sensitivity(self):
        recs = [rec(f"R{i}", 6.0 + i * 0.05, 6.1 - i * 0.02) for i in range(8)]
        recs.append(rec("MISS", 7.0, 3.0, outcome="miss"))
        recs.append(rec("FAIL", 6.5, 0.0, outcome="fail", note="转染效率过低"))
        card = metrics.model_card(recs, cutoff="10-01")

        self.assertEqual(card["overall"]["n"], 9)         # FAIL 被剔除
        self.assertEqual(card["audit"]["counts"]["fail"], 1)
        self.assertTrue(card["sensitivity"]["available"])
        self.assertIn("结局审计", card["markdown"])
        self.assertIn("技术失败", card["markdown"])

    def test_fail_rate_mentioned_in_limitations(self):
        recs = [rec(f"R{i}", 6.0 + i * 0.05, 6.1 - i * 0.02) for i in range(8)]
        recs.append(rec("FAIL", 6.5, 0.0, outcome="fail", note="污染"))
        card = metrics.model_card(recs)
        joined = "".join(card["limitations"])
        self.assertIn("技术失败", joined)
        self.assertIn("模型误差", joined)

    def test_baseline_below_target_has_own_sentence(self):
        """基线本身不达标时，不能输出「只需 0% 漏录就跌破」这种荒谬结论。"""
        recs = [rec(f"R{i}", 6.0, 6.0 + (-1) ** i * 0.5) for i in range(8)]  # R² 接近 0
        s = metrics.sensitivity_missing(recs)
        self.assertLess(s["base_r2"], s["target_r2"])
        self.assertIn("本身已低于目标线", s["verdict"])
        self.assertNotIn("只需 0%", s["verdict"])


if __name__ == "__main__":
    unittest.main()
