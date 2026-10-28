"""推理任务系统测试：状态机、可复现性、失败处理、规范化。

独立于 HTTP 层，直接测 engine.inference 和 app 的任务队列函数。
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as server                       # noqa: E402
from engine import inference as inf        # noqa: E402


PAYLOAD = "MKTAYIAKQRQISFVKSHFSRQDILDLW"
HEXON = "MAADDDDDGSAASVPR"


class NormalizeTest(unittest.TestCase):
    def test_normalize_strips_case_and_whitespace(self):
        a = inf.normalize_input(PAYLOAD, HEXON)
        b = inf.normalize_input("  mkta yia kqrqisfvkshfsrqdildlw ", " maa ddddd gsaasvpr ")
        self.assertEqual(a["payload_aa"], b["payload_aa"])
        self.assertEqual(a["hexon_aa"], b["hexon_aa"])
        self.assertEqual(a["input_hash"], b["input_hash"])

    def test_normalize_changes_hash_on_different_input(self):
        a = inf.normalize_input(PAYLOAD, HEXON)
        c = inf.normalize_input("DIFFERENTSEQUENCE", HEXON)
        self.assertNotEqual(a["input_hash"], c["input_hash"])


class MockBackendTest(unittest.TestCase):
    def test_same_input_same_output(self):
        norm = inf.normalize_input(PAYLOAD, HEXON)
        r1 = inf.MockBackend().run(norm)
        r2 = inf.MockBackend().run(norm)
        self.assertEqual(r1, r2)

    def test_different_input_different_output(self):
        n1 = inf.normalize_input(PAYLOAD, HEXON)
        n2 = inf.normalize_input("ANOTHERSEQUENCEAAA", HEXON)
        r1 = inf.MockBackend().run(n1)
        r2 = inf.MockBackend().run(n2)
        self.assertNotEqual((r1["mean_plddt"], r1["ptm"]), (r2["mean_plddt"], r2["ptm"]))

    def test_repro_elements_present(self):
        norm = inf.normalize_input(PAYLOAD, HEXON)
        r = inf.MockBackend().run(norm)
        repro = r["repro"]
        self.assertIn("image_digest", repro)
        self.assertIn("weight_hash", repro)
        self.assertEqual(repro["input_hash"], norm["input_hash"])

    def test_plddt_bounds(self):
        norm = inf.normalize_input(PAYLOAD, HEXON)
        r = inf.MockBackend().run(norm)
        self.assertEqual(len(r["plddt"]), r["n_res"])
        self.assertTrue(all(0 <= v <= 100 for v in r["plddt"]))
        self.assertTrue(0 <= r["ptm"] <= 1)
        self.assertTrue(0 <= r["binder"] <= 1)

    def test_boltz_backend_unavailable_raises(self):
        norm = inf.normalize_input(PAYLOAD, HEXON)
        with self.assertRaises(RuntimeError):
            inf.BoltzBackend(backend_available=False).run(norm)


class TaskQueueTest(unittest.TestCase):
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

    def test_submit_runs_to_done(self):
        prep = inf.build_task_payload(PAYLOAD, HEXON)
        task = server.submit_task(prep["norm"], prep["task_id"])
        self.assertIn(task["status"], (inf.QUEUED, inf.RUNNING, inf.DONE))
        # 轮询直到结束（mock 后端亚秒级完成）
        deadline = time.time() + 5
        while time.time() < deadline:
            task = server.get_task(prep["task_id"])
            if task["status"] in (inf.DONE, inf.FAILED):
                break
            time.sleep(0.05)
        self.assertEqual(task["status"], inf.DONE)
        self.assertIsNotNone(task["result"])
        self.assertIn("mean_plddt", task["result"])
        self.assertIn("repro", task["result"])

    def test_input_hash_recorded(self):
        prep = inf.build_task_payload(PAYLOAD, HEXON)
        server.submit_task(prep["norm"], prep["task_id"])
        task = server.get_task(prep["task_id"])
        self.assertEqual(task["input_hash"], prep["norm"]["input_hash"])

    def test_list_tasks(self):
        rows = server.list_tasks()
        self.assertIsInstance(rows, list)
        # 至少包含上一个测试提交的任务
        self.assertTrue(any(r["model"] == inf.MockBackend().name for r in rows))

    def test_get_missing_task_none(self):
        self.assertIsNone(server.get_task("nonexistent"))


if __name__ == "__main__":
    unittest.main()
