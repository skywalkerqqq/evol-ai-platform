"""引擎单测：只测可复算的部分（评分与启发式不测绝对值，只测不变量）。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import metrics, optimize, sequence, targets  # noqa: E402

DEMO = (Path(__file__).resolve().parent.parent / "data" / "demo_construct.txt").read_text(encoding="utf-8").strip()


class TestAnalyze(unittest.TestCase):
    def test_gc_exact(self):
        a = sequence.analyze("GCGCATAT" * 10)          # 50% GC, 80 bp
        self.assertAlmostEqual(a["gc"], 50.0, places=1)
        self.assertEqual(a["length"], 80)

    def test_homopolymer_detected(self):
        a = sequence.analyze("ATG" + "A" * 9 + "GCT" * 20)
        self.assertTrue(any(r["base"] == "A" and r["len"] >= 9 for r in a["runs"]))

    def test_restriction_site_detected(self):
        a = sequence.analyze("GCTAGCTAGCTAGC" + "GAATTC" + "TTGACCTGACCTGACC")
        names = {s["name"] for s in a["sites"]}
        self.assertIn("EcoRI", names)

    def test_cpg_count(self):
        a = sequence.analyze("CGCGCG" + "ATATAT" * 10)
        self.assertEqual(a["cpg"], 3)

    def test_short_sequence_rejected(self):
        with self.assertRaises(ValueError):
            sequence.analyze("ATGC")

    def test_verdict_is_one_of_three(self):
        a = sequence.analyze(DEMO)
        self.assertIn(a["verdict"], ("建议下单", "可下单 · 需复核", "建议优化后下单"))
        self.assertTrue(0 <= a["composite"] <= 100)

    def test_risks_have_required_fields(self):
        a = sequence.analyze(DEMO)
        self.assertGreater(len(a["risks"]), 0)
        for r in a["risks"]:
            self.assertEqual(set(r), {"lv", "t", "p", "d", "a"})
            self.assertIn(r["lv"], ("hi", "md", "lo"))


class TestOptimize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = optimize.optimize(DEMO)

    def test_protein_unchanged(self):
        self.assertEqual(sequence.translate(DEMO), sequence.translate(self.res["sequence"]))

    def test_cpg_removed(self):
        self.assertGreater(self.res["before"]["cpg"], 0)
        self.assertEqual(self.res["after"]["cpg"], 0)

    def test_no_long_homopolymer_left(self):
        after = sequence.analyze(self.res["sequence"])
        self.assertFalse([r for r in after["runs"] if r["len"] >= 6])

    def test_no_restriction_sites_left(self):
        after = sequence.analyze(self.res["sequence"])
        self.assertEqual(len(after["sites"]), 0)

    def test_length_preserved(self):
        # 输入 CDS 不是 3 的整数倍时尾部会被截掉，最多差 2 nt，并如实报告
        self.assertLessEqual(abs(len(self.res["sequence"]) - len(DEMO)), 2)
        prefix = DEMO.find("ATG")
        self.assertEqual((len(self.res["sequence"]) - prefix) % 3, 0)
        self.assertEqual(self.res["changes"]["truncated_nt"], len(DEMO) % 3)

    def test_changes_reported(self):
        c = self.res["changes"]
        self.assertGreater(c["codons_changed"], 0)
        self.assertLessEqual(c["nt_changed"], len(DEMO))
        self.assertTrue(0 < c["identity_pct"] <= 100)

    def test_requires_start_codon(self):
        with self.assertRaises(ValueError):
            optimize.optimize("GCT" * 30)


class TestMetrics(unittest.TestCase):
    def test_mae(self):
        self.assertAlmostEqual(metrics.mae([(1, 2), (3, 3)]), 0.5)

    def test_perfect_correlation(self):
        pairs = [(1, 2), (2, 4), (3, 6), (4, 8)]
        self.assertAlmostEqual(metrics.pearson(pairs), 1.0, places=6)
        self.assertAlmostEqual(metrics.spearman(pairs), 1.0, places=6)

    def test_spearman_monotonic_nonlinear(self):
        pairs = [(1, 1), (2, 4), (3, 9), (4, 16)]
        self.assertAlmostEqual(metrics.spearman(pairs), 1.0, places=6)
        self.assertLess(metrics.pearson(pairs), 1.0)

    def test_summary_flags_outlier(self):
        rows = [{"id": f"A{i}", "pred": 5, "obs": 5} for i in range(10)]
        rows[0]["pred"] = 9
        s = metrics.summarize(rows)
        self.assertIn("A0", s["flagged"])
        self.assertEqual(s["n"], 10)


class TestTargets(unittest.TestCase):
    def test_ranks_are_sorted_and_scored(self):
        data = targets.rank()
        scores = [r["score"] for r in data["rows"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual([r["rank"] for r in data["rows"]], list(range(1, len(scores) + 1)))

    def test_weights_change_order(self):
        base = targets.rank()
        self.assertEqual(base["rows"][0]["name"], "膀胱癌 NMIBC")
        before = [r["name"] for r in base["rows"]]
        safety_only = targets.rank({"genetics": 0, "omics": 0, "lit": 0,
                                    "druggable": 0, "safety": 40, "conserve": 0})
        after = [r["name"] for r in safety_only["rows"]]
        # 只看安全性时，结直肠癌肝转移（70）应排在 前列腺癌（66）之前
        self.assertLess(before.index("前列腺癌 mCRPC"), before.index("结直肠癌肝转移"))
        self.assertLess(after.index("结直肠癌肝转移"), after.index("前列腺癌 mCRPC"))

    def test_score_bounds(self):
        for r in targets.rank()["rows"]:
            self.assertTrue(0 <= r["score"] <= 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
