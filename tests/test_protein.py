"""蛋白理化计算单测。

原则：能被公式复算的才断言精确值；阈值型判定只测「该报的报了、不该报的没报」。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import protein  # noqa: E402

DEMO = (Path(__file__).resolve().parent.parent / "data" / "demo_construct.txt").read_text(encoding="utf-8").strip()


class TestPhysChem(unittest.TestCase):
    def test_translation_and_length(self):
        d = protein.describe("ATGGCCTAA")                     # M A *
        self.assertEqual(d["n_aa"], 2)
        self.assertEqual(d["protein"], "MA")

    def test_molecular_weight(self):
        d = protein.describe("ATGGCCTAA")
        # M 131.1926 + A 71.0788 + H2O 18.01524 = 220.28664 Da
        self.assertAlmostEqual(d["mw_kda"], 0.22, places=2)

    def test_gravy_exact(self):
        d = protein.describe("ATGGCCTAA")
        self.assertAlmostEqual(d["gravy"], (1.9 + 1.8) / 2, places=3)

    def test_gravy_hydrophobic_vs_hydrophilic(self):
        # 全 L（强疏水）vs 全 D（强亲水），GRAVY 必须一正一负
        self.assertGreater(protein.describe("ATG" + "CTG" * 20 + "TAA")["gravy"], 0.2)
        self.assertLess(protein.describe("ATG" + "GAT" * 20 + "TAA")["gravy"], -0.2)

    def test_isoelectric_point_consistency(self):
        """pI 的定义：该点上净电荷≈0；且 pH7 的电荷符号要和 pI 与 7 的大小关系一致。"""
        for cds in ("ATG" + "GAT" * 10 + "TAA",      # 酸性 → pI 偏小
                    "ATG" + "AAA" * 10 + "TAA"):     # 碱性 → pI 偏大
            d = protein.describe(cds)
            # pI 输出保留两位小数，回代必然有残差，取 0.05 作为容差
            self.assertLess(abs(protein._net_charge(d["protein"], d["pI"])), 0.05)
            if d["pI"] < 7:
                self.assertLess(d["charge_ph7"], 0)
            elif d["pI"] > 7:
                self.assertGreater(d["charge_ph7"], 0)

    def test_pi_ordering(self):
        acidic = protein.describe("ATG" + "GAT" * 10 + "TAA")["pI"]
        basic = protein.describe("ATG" + "AAA" * 10 + "TAA")["pI"]
        self.assertLess(acidic, basic)

    def test_aliphatic_index_formula(self):
        # ATG 带一个 M，所以是 11 个残基里 10 个 A → 100 × (10/11)
        d = protein.describe("ATG" + "GCT" * 10 + "TAA")
        self.assertAlmostEqual(d["aliphatic_index"], round(100 * 10 / 11, 1), places=1)

    def test_composition_sums_to_length(self):
        d = protein.describe(DEMO)
        self.assertEqual(sum(d["composition"].values()), d["n_aa"])

    def test_extinction_coefficient(self):
        d = protein.describe("ATG" + "TGG" * 3 + "TAA")       # 3 个 W
        self.assertEqual(d["ext_coeff_280"], 3 * 5500)


class TestMotifs(unittest.TestCase):
    def test_glyc_motif_found(self):
        sites = protein.glycosylation_sites("MNSSTASNQTA")
        self.assertEqual(sites[0]["motif"], "NSS")
        self.assertEqual(sites[1]["motif"], "NQT")

    def test_glyc_motif_excludes_proline(self):
        self.assertEqual(protein.glycosylation_sites("MNPSA"), [])

    def test_requires_start_codon(self):
        with self.assertRaises(ValueError):
            protein.describe("GCT" * 30)

    def test_truncated_reported(self):
        d = protein.describe("ATG" + "GCT" * 9 + "GG")        # 尾部多 2 nt
        self.assertEqual(d["truncated_nt"], 2)
        self.assertEqual(d["n_aa"], 10)

    def test_internal_stop_flagged(self):
        d = protein.describe("ATG" + "GCT" * 5 + "TAA" + "GCT" * 5 + "TAA")
        self.assertTrue(any("终止密码子" in r["t"] for r in d["risks"]))
        self.assertEqual([r for r in d["risks"] if "内部" in r["t"]][0]["lv"], "hi")

    def test_missing_stop_flagged(self):
        d = protein.describe("ATG" + "GCT" * 20)
        self.assertTrue(any("缺少终止密码子" in r["t"] for r in d["risks"]))


class TestHydrophobicRuns(unittest.TestCase):
    def test_tm_segment_detected_as_high(self):
        """20 个连续疏水残基应被判为疑似跨膜（hi）。"""
        seg = "CTG" * 20                                      # 20 × L
        d = protein.describe("ATG" + seg + "GGT" * 10 + "TAA")
        self.assertTrue(any(r["lv"] == "hi" for r in d["risks"]),
                        [r["t"] for r in d["risks"]])
        self.assertGreaterEqual(d["hydrophobic_runs"][0]["span"], 15)

    def test_short_stretch_not_high(self):
        """12 aa 的疏水段不足以判跨膜——球状蛋白疏水核不该被误报成 hi。"""
        seg = "CTG" * 4                                       # 12 × L
        d = protein.describe("ATG" + "GGT" * 10 + seg + "GGT" * 10 + "TAA")
        self.assertFalse(any(r["lv"] == "hi" for r in d["risks"]),
                         [r["t"] for r in d["risks"]])
        self.assertTrue(any("伸展疏水段" in r["t"] for r in d["risks"]))

    def test_runs_are_consecutive(self):
        d = protein.describe(DEMO)
        prof = {p["i"]: p["mean"] for p in d["profile"]}
        for r in d["hydrophobic_runs"]:
            for i in range(r["start"] - 1, r["end"] - protein.WINDOW + 1):
                self.assertGreaterEqual(prof[i], d["tm_threshold"])

    def test_profile_bounds(self):
        d = protein.describe(DEMO)
        self.assertTrue(all(-4.6 <= p["mean"] <= 4.6 for p in d["profile"]))
        self.assertEqual(len(d["profile"]), d["n_aa"] - d["hydro_window"] + 1)


if __name__ == "__main__":
    unittest.main()
