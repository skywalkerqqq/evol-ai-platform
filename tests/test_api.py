"""接口集成测试：起一个临时端口的服务，用真实 HTTP 走一遍主要路径。

注意：使用临时数据库，不会污染 data/evol.db。
"""

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as server  # noqa: E402

DEMO = (Path(__file__).resolve().parent.parent / "data" / "demo_construct.txt").read_text(encoding="utf-8").strip()


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        server.DB_PATH = Path(cls.tmp.name) / "test.db"
        server.init_db()
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.tmp.cleanup()

    # ---- helpers
    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path):
        with urllib.request.urlopen(self.url(path), timeout=5) as r:
            return json.loads(r.read().decode())

    def post(self, path, payload):
        req = urllib.request.Request(
            self.url(path), data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())

    def delete(self, rid):
        req = urllib.request.Request(self.url("/api/records/" + urllib.parse.quote(rid)),
                                     method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())

    # ---- cases
    def test_health(self):
        self.assertTrue(self.get("/api/health")["ok"])

    def test_static_index(self):
        with urllib.request.urlopen(self.url("/"), timeout=5) as r:
            self.assertIn("EVOL-AI", r.read().decode())

    def test_analyze(self):
        d = self.post("/api/analyze", {"sequence": DEMO})
        self.assertEqual(d["length"], len(DEMO))
        self.assertEqual(len(d["scores"]), 5)
        self.assertIn("verdict", d)
        self.assertTrue(d["risks"])

    def test_analyze_rejects_short(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/analyze", {"sequence": "ATG"})

    def test_optimize(self):
        d = self.post("/api/optimize", {"sequence": DEMO, "options": {"cpg_free": True}})
        self.assertEqual(d["after"]["cpg"], 0)
        self.assertGreater(d["changes"]["codons_changed"], 0)

    def test_targets_default_and_weights(self):
        base = self.get("/api/targets")
        self.assertEqual(len(base["rows"]), 6)
        heavy = self.get('/api/targets?weights=' + urllib.parse.quote(
            json.dumps({"genetics": 0, "omics": 0, "lit": 0, "druggable": 0, "safety": 40, "conserve": 0})))
        self.assertNotEqual([r["name"] for r in base["rows"]],
                            [r["name"] for r in heavy["rows"]])

    def test_records_crud(self):
        before = self.get("/api/records")
        n0 = before["metrics"]["n"]
        self.post("/api/records", {"id": "TEST-001", "pred": 6.1, "obs": 5.8, "model": "b2-0.6.1"})
        mid = self.get("/api/records")
        self.assertEqual(mid["metrics"]["n"], n0 + 1)
        self.assertTrue(any(r["id"] == "TEST-001" for r in mid["rows"]))

        req = urllib.request.Request(self.url("/api/records/TEST-001"), method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as r:
            after = json.loads(r.read().decode())
        self.assertEqual(after["metrics"]["n"], n0)

    def test_outcome_fail_excluded_from_metrics(self):
        """技术失败记录必须落库，但不得改变计入指标的条数。"""
        n0 = self.get("/api/records")["metrics"]["n"]
        self.post("/api/records", {"id": "FAIL-X", "pred": 6.0, "obs": 0,
                                   "model": "b2-0.6.1", "outcome": "fail", "note": "转染效率过低"})
        mid = self.get("/api/records")
        self.assertEqual(mid["metrics"]["n"], n0, "技术失败不得计入指标")
        self.assertEqual(mid["metrics"]["n_fail"], 1)
        self.assertEqual(mid["metrics"]["audit"]["counts"]["fail"], 1)
        self.assertTrue(any(r["id"] == "FAIL-X" for r in mid["rows"]), "仍应出现在台账里")
        self.delete("FAIL-X")
        self.assertEqual(self.get("/api/records")["metrics"]["n_fail"], 0)

    def test_outcome_rejects_unknown_value(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post("/api/records", {"id": "BAD-Y", "pred": 6, "obs": 6, "outcome": "maybe"})
        self.assertEqual(cm.exception.code, 400)

    def test_audit_present_in_records(self):
        a = self.get("/api/records")["metrics"]["audit"]
        self.assertIn(a["level"], ("ok", "warn", "alarm"))
        self.assertEqual(sum(a["counts"].values()), a["total"])

    def test_model_card_sensitivity(self):
        card = self.get("/api/model-card")
        s = card["sensitivity"]
        self.assertTrue(s["available"])
        self.assertEqual(len(s["curve"]), 6)
        self.assertEqual(s["curve"][0]["r2"], card["overall"]["r2"], "0% 缺失必须等于原始 R²")
        self.assertIsNotNone(s["tip_target"])
        self.assertIn("敏感性", card["markdown"])

    def test_models(self):
        data = self.get("/api/models")
        rows = data["rows"]
        self.assertGreater(len(rows), 5)
        af3 = next(m for m in rows if m["n"] == "AlphaFold3")
        self.assertLess(af3["ls"], data["veto_threshold"])
        self.assertTrue(af3["vetoed"])
        self.assertEqual(af3["rank"], len(rows), "否决项必须由服务端排到末位")
        self.assertEqual(data["best"], rows[0]["n"])

    def test_model_card(self):
        card = self.get("/api/model-card")
        self.assertEqual(card["overall"]["n"], 18)
        self.assertTrue(card["overall"]["r2_ci"])
        self.assertGreaterEqual(len(card["by_model"]), 2)
        self.assertIn("局限性", card["markdown"])
        # 分层样本量必须与总体一致，否则就是漏记录
        self.assertEqual(sum(g["n"] for g in card["by_model"]), card["overall"]["n"])

    def test_model_card_cutoff_affects_split(self):
        a = self.get("/api/model-card?cutoff=09-15")["holdout"]["retro"]["n"]
        b = self.get("/api/model-card?cutoff=10-15")["holdout"]["retro"]["n"]
        self.assertGreater(b, a)

    def test_infer_submit_and_poll(self):
        """提交推理任务 → 轮询到 done → 结果含三要素。"""
        import time
        d = self.post("/api/infer", {"payload_aa": "MKTAYIAKQRQISFVKSHFSRQDILDLW",
                                     "hexon_aa": "MAADDDDDGSAASVPR"})
        self.assertTrue(d["ok"])
        tid = d["task"]["id"]
        self.assertIn(d["task"]["status"], ("queued", "running", "done"))
        deadline = time.time() + 5
        while time.time() < deadline:
            t = self.get("/api/infer/" + tid)["task"]
            if t["status"] in ("done", "failed"):
                break
            time.sleep(0.05)
        self.assertEqual(t["status"], "done")
        self.assertIn("repro", t["result"])
        self.assertEqual(t["result"]["repro"]["input_hash"], t["input_hash"])

    def test_infer_requires_both_sequences(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post("/api/infer", {"payload_aa": "MKTAYIA"})
        self.assertEqual(cm.exception.code, 400)

    def test_assets_directory(self):
        d = self.get("/api/assets")
        self.assertEqual(d["total"], 12)
        self.assertTrue(d["summary"])
        self.assertEqual(len(d["rows"]), 12)

    def test_assets_search(self):
        d = self.get("/api/assets?q=" + urllib.parse.quote("组学"))
        self.assertEqual(d["matched"], 3)
        self.assertTrue(all("组学" in a["category"] for a in d["rows"]))

    def test_records_export_csv(self):
        req = urllib.request.Request(self.url("/api/records/export.csv"))
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read().decode("utf-8")
        self.assertIn("id,pred,obs,model", body.splitlines()[0])
        self.assertTrue(body.startswith("\ufeff"), "CSV 需带 UTF-8 BOM")


if __name__ == "__main__":
    unittest.main(verbosity=2)
