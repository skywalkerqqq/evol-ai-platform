"""指标口径的测试。

重点不是「公式算得对吗」，而是**该报的报、不该报的不报**：
区间必须可复现、样本不足必须拒绝给区间、分层求和必须等于总体、
异常必须被自动检出而不是等人看表。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import metrics  # noqa: E402


def rec(i, pred, obs, model="b2-0.6.1", created="09-10"):
    return {"id": f"R{i:03d}", "pred": pred, "obs": obs, "model": model, "created": created}


class TestBootstrap(unittest.TestCase):
    def setUp(self):
        self.pairs = [(1.0, 1.2), (2.0, 1.9), (3.0, 3.4), (4.0, 3.8), (5.0, 5.3), (6.0, 5.6)]

    def test_deterministic(self):
        """固定 seed：同一份数据必须每次算出同一个区间，否则报告不可复核。"""
        a = metrics.bootstrap_ci(self.pairs, metrics.mae)
        b = metrics.bootstrap_ci(self.pairs, metrics.mae)
        self.assertEqual(a, b)

    def test_higher_confidence_wider_interval(self):
        """置信度越高区间必须越宽（alpha 越小越宽）。"""
        pairs = [(i * 1.0, i * 1.0 + (0.3 if i % 2 else -0.2)) for i in range(1, 13)]
        ci99 = metrics.bootstrap_ci(pairs, metrics.mae, alpha=0.01)
        ci90 = metrics.bootstrap_ci(pairs, metrics.mae, alpha=0.10)
        self.assertLessEqual(ci99["lo"], ci90["lo"])
        self.assertGreaterEqual(ci99["hi"], ci90["hi"])
        self.assertGreater(ci99["hi"] - ci99["lo"], ci90["hi"] - ci90["lo"])

    def test_bounds_ordered(self):
        ci = metrics.bootstrap_ci(self.pairs, metrics.mae)
        self.assertLessEqual(ci["lo"], ci["hi"])

    def test_none_when_too_few(self):
        """样本不足时返回 None——这是「不该报」，不是「算不出」。"""
        self.assertIsNone(metrics.bootstrap_ci([(1.0, 1.0)] * (metrics.MIN_N - 1), metrics.mae))
        self.assertIsNotNone(metrics.bootstrap_ci([(1.0, 1.0)] * metrics.MIN_N, metrics.mae))

    def test_r2_is_pearson_square(self):
        r = metrics.pearson(self.pairs)
        self.assertAlmostEqual(metrics.r2(self.pairs), r * r, places=9)


class TestStratify(unittest.TestCase):
    def setUp(self):
        self.records = (
            [rec(i, 5 + i * 0.1, 5 + i * 0.12) for i in range(11)]          # 主组 n=11
            + [rec(20 + i, 4 + i * 0.3, 4 + i * 0.32, "b2-0.5.4") for i in range(5)]  # n=5
            + [rec(30 + i, 6, 6.1, "esm-lora-r3") for i in range(2)]        # n=2 样本不足
        )

    def test_group_sizes_sum_to_total(self):
        rows = metrics.stratify(self.records, lambda r: r["model"])
        self.assertEqual(sum(g["n"] for g in rows), len(self.records))

    def test_sorted_by_size_desc(self):
        rows = metrics.stratify(self.records, lambda r: r["model"])
        self.assertEqual([g["n"] for g in rows], sorted([g["n"] for g in rows], reverse=True))

    def test_small_group_refuses_interval(self):
        rows = metrics.stratify(self.records, lambda r: r["model"])
        small = [g for g in rows if g["group"] == "esm-lora-r3"][0]
        self.assertFalse(small["reliable"])
        self.assertIsNone(small["r2_ci"])
        self.assertIsNone(small["mae_ci"])
        self.assertIn("样本不足", small["warn"])

    def test_large_group_has_interval(self):
        rows = metrics.stratify(self.records, lambda r: r["model"])
        big = [g for g in rows if g["group"] == "b2-0.6.1"][0]
        self.assertTrue(big["reliable"])
        self.assertIsNotNone(big["r2_ci"])

    def test_all_groups_covered(self):
        rows = metrics.stratify(self.records, lambda r: r["model"])
        self.assertEqual({g["group"] for g in rows}, {"b2-0.6.1", "b2-0.5.4", "esm-lora-r3"})


class TestHoldout(unittest.TestCase):
    def test_split_preserves_total(self):
        records = [rec(i, 5, 5.1, created=f"09-{i + 1:02d}") for i in range(10)] + \
                  [rec(20 + i, 6, 6.1, created=f"10-{i + 1:02d}") for i in range(5)]
        s = metrics.holdout_split(records, "10-01")
        self.assertEqual(s["retro"]["n"] + s["prospective"]["n"], len(records))
        self.assertEqual(s["retro"]["n"], 10)
        self.assertEqual(s["prospective"]["n"], 5)

    def test_cutoff_edge_is_prospective(self):
        """边界当天的记录算前瞻集（冻结日之后，含当日）。"""
        records = [rec(1, 5, 5.0, created="09-30"), rec(2, 5, 5.0, created="10-01")]
        s = metrics.holdout_split(records, "10-01")
        self.assertEqual((s["retro"]["n"], s["prospective"]["n"]), (1, 1))

    def test_empty_side_does_not_crash(self):
        s = metrics.holdout_split([rec(1, 5, 5.1, created="10-20")], "10-01")
        self.assertEqual(s["retro"]["n"], 0)
        self.assertEqual(s["prospective"]["n"], 1)


class TestAnomalies(unittest.TestCase):
    def test_detects_worse_group(self):
        """一组几乎无相关、另一组高度相关 → 必须报出来。"""
        records = (
            [rec(i, 5 + (i % 3) * 0.1, 5 + ((i * 7) % 5) * 0.2, "bad") for i in range(11)]
            + [rec(20 + i, 4 + i * 0.1, 4.05 + i * 0.1, "good") for i in range(9)]
        )
        overall = metrics._block(records)
        rows = metrics.stratify(records, lambda r: r["model"])
        an = metrics.strat_anomalies(rows, overall)
        self.assertTrue(any(a["group"] == "bad" for a in an), an)

    def test_ignores_unreliable_group(self):
        """样本不足的组不判异常——它的指标本来就不该看。"""
        records = [rec(i, 5, 5.0, "big") for i in range(10)] + [rec(20, 1, 9.0, "tiny"), rec(21, 9, 1.0, "tiny")]
        overall = metrics._block(records)
        rows = metrics.stratify(records, lambda r: r["model"])
        an = metrics.strat_anomalies(rows, overall)
        self.assertFalse(any(a["group"] == "tiny" for a in an))

    def test_clean_case_no_anomaly(self):
        records = [rec(i, 5 + i * 0.05, 5 + i * 0.05) for i in range(12)]
        overall = metrics._block(records)
        rows = metrics.stratify(records, lambda r: r["model"])
        self.assertEqual(metrics.strat_anomalies(rows, overall), [])


class TestModelCard(unittest.TestCase):
    def setUp(self):
        self.records = (
            [rec(i, 5 + i * 0.1, 5 + i * 0.1, "b2-0.6.1") for i in range(10)]
            + [rec(20 + i, 4 + i * 0.2, 4 + i * 0.22, "b2-0.5.4", "10-15") for i in range(6)]
        )
        self.card = metrics.model_card(self.records, cutoff="10-01")

    def test_markdown_has_all_sections(self):
        md = self.card["markdown"]
        for sec in ("总体指标", "分层指标", "前瞻 / 回溯", "局限性与已知偏差", "使用边界",
                    "结局审计", "敏感性"):
            self.assertIn(sec, md)

    def test_limitations_always_present(self):
        self.assertGreaterEqual(len(self.card["limitations"]), 4)
        joined = "".join(self.card["limitations"])
        self.assertIn("阳性率", joined)          # 必须自曝选择性录入偏差（PRD §8.2）
        self.assertIn("前瞻盲测", joined)
        self.assertIn("R²", joined)              # 区间也必须跟指标一起出现

    def test_stable_across_calls(self):
        again = metrics.model_card(self.records, cutoff="10-01")
        self.assertEqual(self.card["overall"]["r2"], again["overall"]["r2"])
        self.assertEqual(self.card["overall"]["r2_ci"], again["overall"]["r2_ci"])

    def test_n2_group_flagged_in_limitations(self):
        """n=2 时 R² 必然≈1.0，必须在局限性里点明是退化值。"""
        records = [rec(i, 5, 5.1) for i in range(8)] + [rec(20, 4, 4.2, "tiny"), rec(21, 6, 6.3, "tiny")]
        card = metrics.model_card(records)
        small_txt = [x for x in card["limitations"] if "退化" in x or "样本量 < 5" in x]
        self.assertTrue(small_txt, card["limitations"])

    def test_anomaly_appears_in_limitations(self):
        records = (
            [rec(i, 5 + (i % 3) * 0.1, 5 + ((i * 7) % 5) * 0.2, "bad") for i in range(11)]
            + [rec(20 + i, 4 + i * 0.1, 4.05 + i * 0.1, "good") for i in range(9)]
        )
        card = metrics.model_card(records)
        self.assertTrue(card["anomalies"])
        self.assertTrue(any("必须单独归因" in x for x in card["limitations"]))


if __name__ == "__main__":
    unittest.main()
