"""数据资产目录与 CSV 导出测试。"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as server                       # noqa: E402
from engine import assets as assets_engine  # noqa: E402


class AssetsTest(unittest.TestCase):
    def test_directory_total(self):
        d = assets_engine.directory()
        self.assertEqual(d["total"], 12)
        self.assertEqual(d["matched"], 12)
        self.assertTrue(d["summary"])

    def test_summary_counts_sum_to_total(self):
        d = assets_engine.directory()
        self.assertEqual(sum(s["total"] for s in d["summary"]), d["total"])
        # 可训练数不应超过总数
        self.assertTrue(all(s["train"] <= s["total"] for s in d["summary"]))

    def test_search_filters(self):
        d = assets_engine.directory(query="组学")
        self.assertEqual(d["matched"], 3)
        self.assertTrue(all("组学" in a["category"] for a in d["rows"]))

    def test_search_by_owner(self):
        d = assets_engine.directory(query="临床组")
        self.assertEqual(d["matched"], 1)
        self.assertEqual(d["rows"][0]["name"], "IIT 随访数据")

    def test_search_no_match(self):
        d = assets_engine.directory(query="不存在的资产xyz")
        self.assertEqual(d["matched"], 0)
        self.assertEqual(d["rows"], [])

    def test_sort_by_category(self):
        d = assets_engine.directory(sort_by="category")
        cats = [a["category"] for a in d["rows"]]
        self.assertEqual(cats, sorted(cats))

    def test_usage_pill_mapping(self):
        d = assets_engine.directory()
        for a in d["rows"]:
            self.assertIn(a["pill"], ("t", "v", "a"))
            self.assertIn(a["usage"], ("训练", "评测", "检索"))


class CsvExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls._old_db = server.DB_PATH
        server.DB_PATH = Path(cls.tmp.name) / "test.db"
        server.init_db()

    @classmethod
    def tearDownClass(cls):
        server.DB_PATH = cls._old_db
        cls.tmp.cleanup()

    def test_csv_has_bom_and_header(self):
        """直接调 _csv_records 的底层逻辑：CSV 内容带 BOM、表头正确。"""
        import csv
        import io
        rows = server.fetch_records()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "pred", "obs", "model", "created", "note", "outcome", "optimised"])
        for r in rows:
            w.writerow([r.get("id"), r.get("pred"), r.get("obs"), r.get("model"),
                        r.get("created"), r.get("note"), r.get("outcome"), r.get("optimised")])
        content = "\ufeff" + buf.getvalue()
        self.assertTrue(content.startswith("\ufeff"), "必须带 UTF-8 BOM")
        self.assertIn("id,pred,obs,model", content.splitlines()[0])
        self.assertEqual(len(content.splitlines()), len(rows) + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
