"""推理任务并发压测：验证任务队列能扛住并发提交，不丢任务、不撞 ID、不串结果。

用临时数据库直接测 submit_task / get_task（绕过 HTTP 层，聚焦队列逻辑本身）。
"""

import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as server                       # noqa: E402
from engine import inference as inf        # noqa: E402


PAYLOAD = "MKTAYIAKQRQISFVKSHFSRQDILDLW"
HEXON = "MAADDDDDGSAASVPR"
N_CONCURRENT = 20


class StressTest(unittest.TestCase):
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

    def test_concurrent_submissions_all_done(self):
        """20 个并发提交 → 全部 done，无 UNIQUE 冲突，无状态错乱。"""
        # 每个任务用不同 payload（保证 input_hash 不同），模拟真实并发
        payloads = [PAYLOAD + ("A" * i) for i in range(N_CONCURRENT)]
        preps = [inf.build_task_payload(p, HEXON) for p in payloads]
        ids = [p["task_id"] for p in preps]

        # 并发提交
        def submit(prep):
            server.submit_task(prep["norm"], prep["task_id"])

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(submit, preps))

        # 轮询到全部结束
        deadline = time.time() + 15
        done_count = 0
        while time.time() < deadline:
            tasks = [server.get_task(i) for i in ids]
            done_count = sum(1 for t in tasks if t and t["status"] in (inf.DONE, inf.FAILED))
            if done_count == N_CONCURRENT:
                break
            time.sleep(0.1)

        tasks = [server.get_task(i) for i in ids]
        self.assertTrue(all(t is not None for t in tasks), "不能有任务丢失")
        self.assertEqual(done_count, N_CONCURRENT, "20 个任务应全部结束")
        self.assertTrue(all(t["status"] == inf.DONE for t in tasks),
                        f"不应有 failed/卡住的任务：{[t['status'] for t in tasks]}")

    def test_task_ids_unique(self):
        """并发提交生成的 task_id 不能重复（否则 UNIQUE 约束会静默覆盖）。"""
        payloads = [PAYLOAD + ("G" * i) for i in range(N_CONCURRENT)]
        preps = [inf.build_task_payload(p, HEXON) for p in payloads]
        ids = [p["task_id"] for p in preps]
        self.assertEqual(len(ids), len(set(ids)), "task_id 必须全局唯一")

    def test_result_matches_input_hash(self):
        """每个任务的结果 input_hash 必须与提交时一致——不能串结果。"""
        payloads = [PAYLOAD + ("C" * i) for i in range(10)]
        preps = [inf.build_task_payload(p, HEXON) for p in payloads]

        with ThreadPoolExecutor(max_workers=5) as ex:
            list(ex.map(lambda pp: server.submit_task(pp["norm"], pp["task_id"]), preps))

        deadline = time.time() + 15
        while time.time() < deadline:
            if all(server.get_task(p["task_id"])["status"] in (inf.DONE, inf.FAILED)
                   for p in preps):
                break
            time.sleep(0.1)

        for prep in preps:
            t = server.get_task(prep["task_id"])
            self.assertEqual(t["status"], inf.DONE)
            self.assertEqual(t["result"]["repro"]["input_hash"], prep["norm"]["input_hash"],
                             "结果的三要素 input_hash 必须等于提交时的输入 hash")


if __name__ == "__main__":
    unittest.main(verbosity=2)
