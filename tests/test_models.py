"""模型矩阵的测试。

核心要钉住的是一条业务规则：**许可分低于门槛的模型必须沉底，
哪怕它的综合分比上面那个更高。** 这条规则如果只是"前端顺手标个红"，
改一行 CSS 就失效了，所以必须在后端可测。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import models  # noqa: E402


class TestRank(unittest.TestCase):
    def setUp(self):
        self.r = models.rank()
        self.rows = self.r["rows"]

    def test_all_models_ranked_contiguously(self):
        self.assertEqual([x["rank"] for x in self.rows], list(range(1, len(models.MODELS) + 1)))

    def test_vetoed_always_last(self):
        flags = [x["vetoed"] for x in self.rows]
        self.assertEqual(flags, sorted(flags), "否决项必须沉底")

    def test_af3_vetoed_despite_highest_accuracy(self):
        af3 = [x for x in self.rows if x["n"] == "AlphaFold3"][0]
        self.assertTrue(af3["vetoed"])
        self.assertEqual(af3["rank"], len(self.rows))
        self.assertEqual(af3["acc"], max(x["acc"] for x in self.rows), "AF3 精度应为全表最高")
        self.assertIn("一票否决", af3["decision"])

    def test_vetoed_can_outscore_a_passing_model(self):
        """这条是整个规则的意义所在：分数更高，但许可不过，仍然排最后。"""
        last, second_last = self.rows[-1], self.rows[-2]
        self.assertTrue(last["vetoed"])
        self.assertFalse(second_last["vetoed"])
        self.assertGreater(last["total"], second_last["total"])

    def test_best_is_never_vetoed(self):
        best = [x for x in self.rows if x["n"] == self.r["best"]][0]
        self.assertFalse(best["vetoed"])
        self.assertEqual(best["rank"], 1)

    def test_license_not_in_score(self):
        """许可是门槛，不能同时进加权平均，否则等于把否决权摊薄成分数。"""
        self.assertNotIn("ls", self.r["score_dims"])
        self.assertIn("ls", [d["key"] for d in self.r["dims"]])

    def test_threshold_boundary(self):
        """恰好等于门槛不算否决（规则是 < 门槛）。"""
        codonfm = [x for x in self.rows if x["n"] == "CodonFM"][0]
        self.assertEqual(codonfm["ls"], self.r["veto_threshold"])
        self.assertFalse(codonfm["vetoed"])

    def test_custom_threshold(self):
        strict = models.rank(veto=100)
        self.assertGreater(len(strict["vetoed"]), 1)
        self.assertTrue(all(x["vetoed"] for x in strict["rows"] if x["ls"] < 100))

    def test_weights_change_order(self):
        """把精度权重拉到最高，高精度模型应上升。"""
        base = [x["n"] for x in self.rows]
        heavy_acc = [x["n"] for x in models.rank({"acc": 20})["rows"]]
        self.assertNotEqual(base, heavy_acc)
        self.assertIn("AlphaFold3", heavy_acc[-1:])          # 否决项仍沉底
        self.assertLess(heavy_acc.index("Boltz-2"), base.index("Boltz-2"))

    def test_total_within_bounds(self):
        for x in self.rows:
            self.assertGreaterEqual(x["total"], 0)
            self.assertLessEqual(x["total"], 100)


if __name__ == "__main__":
    unittest.main()
