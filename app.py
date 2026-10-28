#!/usr/bin/env python3
"""EVOL-AI · 本地服务。

只依赖标准库：HTTP 服务 + SQLite + 静态文件。
启动：python app.py  →  http://127.0.0.1:8000
"""

import json
import sqlite3
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine import (assets as assets_engine, inference as inf_engine, metrics,
                    models as models_engine, optimize as opt_engine,
                    protein as prot_engine, sequence as seq_engine,
                    targets as tgt_engine)

WEB = ROOT / "web"
DB_PATH = ROOT / "data" / "evol.db"

SEED = [
    ("ECD-AI-001", 6.8, 6.4, "b2-0.6.1", "09-02", ""),
    ("ECD-AI-002", 5.9, 6.2, "b2-0.6.1", "09-03", ""),
    ("ECD-AI-003", 7.1, 6.9, "b2-0.6.1", "09-05", ""),
    ("ECD-AI-004", 4.8, 4.1, "b2-0.5.4", "09-08", ""),
    ("ECD-AI-005", 6.2, 5.8, "b2-0.5.4", "09-10", ""),
    ("ECD-AI-006", 5.4, 6.0, "b2-0.6.1", "09-12", ""),
    ("ECD-AI-007", 7.6, 6.7, "b2-0.6.1", "09-15", ""),
    ("ECD-AI-008", 3.9, 4.4, "b2-0.5.4", "09-18", ""),
    ("ECD-AI-009", 6.5, 6.1, "b2-0.6.1", "09-21", ""),
    ("ECD-AI-010", 5.1, 4.6, "b2-0.5.4", "09-24", ""),
    ("ECD-AI-011", 8.2, 5.6, "b2-0.6.1", "09-27", "payload 长度超出训练分布"),
    ("ECD-AI-012", 6.0, 6.3, "b2-0.6.1", "09-30", ""),
    ("ECD-AI-013", 5.6, 5.2, "b2-0.5.4", "10-04", ""),
    ("ECD-AI-014", 7.0, 6.6, "b2-0.6.1", "10-08", ""),
    ("ECD-AI-015", 4.4, 4.9, "esm-lora-r3", "10-12", ""),
    ("ECD-AI-016", 6.7, 6.4, "b2-0.6.1", "10-16", ""),
    ("ECD-AI-017", 5.2, 5.5, "esm-lora-r3", "10-21", ""),
    ("ECD-AI-018", 6.9, 6.2, "b2-0.6.1", "10-25", ""),
]


# ---------------------------------------------------------------- DB
@contextmanager
def db():
    """每次调用开一个独立连接，退出时必定关闭。

    sqlite3.Connection 的 with 语句只管事务提交/回滚，不关连接；
    不显式 close 会一直占着 db 文件句柄（Windows 上连临时目录都删不掉）。
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS records(
            id TEXT PRIMARY KEY, pred REAL NOT NULL, obs REAL NOT NULL,
            model TEXT NOT NULL, created TEXT NOT NULL, note TEXT DEFAULT '',
            optimised INTEGER DEFAULT 0, outcome TEXT DEFAULT 'hit')""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tasks(
            id TEXT PRIMARY KEY, status TEXT NOT NULL,
            input_hash TEXT NOT NULL, input_yaml TEXT NOT NULL,
            model TEXT NOT NULL, created TEXT NOT NULL,
            started TEXT, finished TEXT,
            result TEXT, error TEXT)""")
        # 老库没有 outcome 列：补上并默认 'hit'。
        # 这个默认值本身就是问题所在——历史台账里活下来的记录，通常都是成功的那些。
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(records)")}
        if "outcome" not in cols:
            conn.execute("ALTER TABLE records ADD COLUMN outcome TEXT DEFAULT 'hit'")
        if conn.execute("SELECT COUNT(*) c FROM records").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO records(id,pred,obs,model,created,note) VALUES(?,?,?,?,?,?)", SEED)


def fetch_records():
    with db() as conn:
        rows = conn.execute("SELECT * FROM records ORDER BY created DESC").fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- 任务队列
# 后台线程池：结构推理是「提交 → 排队 → 运行 → 落库」的异步任务。
# 生产环境把这里换成真正的任务队列（Celery / Nextflow），接口不变。
POOL = ThreadPoolExecutor(max_workers=2)


def _now():
    import datetime
    return datetime.datetime.now().strftime("%m-%d %H:%M:%S")


def _task_row(row) -> dict:
    d = dict(row)
    if d.get("result"):
        d["result"] = json.loads(d["result"])
    return d


def submit_task(norm: dict, task_id: str) -> dict:
    """写入一条 queued 任务，并交给后台线程池执行。"""
    with db() as conn:
        conn.execute(
            "INSERT INTO tasks(id,status,input_hash,input_yaml,model,created)"
            " VALUES(?,?,?,?,?,?)",
            (task_id, inf_engine.QUEUED, norm["input_hash"], norm["yaml"],
             inf_engine.ACTIVE_BACKEND.name, _now()))
    POOL.submit(_run_task, task_id, norm)
    return get_task(task_id)


def _run_task(task_id: str, norm: dict):
    """后台执行：置 running → 跑后端 → 置 done/failed。"""
    with db() as conn:
        conn.execute(
            "UPDATE tasks SET status=?, started=? WHERE id=?",
            (inf_engine.RUNNING, _now(), task_id))
    try:
        result = inf_engine.ACTIVE_BACKEND.run(norm)
        with db() as conn:
            conn.execute(
                "UPDATE tasks SET status=?, finished=?, result=? WHERE id=?",
                (inf_engine.DONE, _now(), json.dumps(result), task_id))
    except Exception as exc:                       # noqa: BLE001
        with db() as conn:
            conn.execute(
                "UPDATE tasks SET status=?, finished=?, error=? WHERE id=?",
                (inf_engine.FAILED, _now(), str(exc), task_id))


def get_task(task_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _task_row(row) if row else None


def list_tasks():
    with db() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created DESC").fetchall()
    return [_task_row(r) for r in rows]


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "EVOLAI/0.4"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    # ---- helpers
    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _query(self):
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    def _csv_records(self):
        """台账导出 CSV：带 UTF-8 BOM，Excel 打开中文不乱码。

        outcome 列如实导出（技术失败也导出，不参与指标但保留在台账里）。
        """
        import csv
        import io
        rows = fetch_records()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "pred", "obs", "model", "created", "note", "outcome", "optimised"])
        for r in rows:
            writer.writerow([r.get("id"), r.get("pred"), r.get("obs"),
                             r.get("model"), r.get("created"), r.get("note"),
                             r.get("outcome"), r.get("optimised")])
        # BOM：让 Excel 识别 UTF-8，避免中文乱码
        body = ("\ufeff" + buf.getvalue()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         'attachment; filename="evol-records.csv"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- routes
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/health":
                return self._json({"ok": True, "service": "EVOL-AI", "version": "0.4"})

            if path == "/api/targets":
                raw = (self._query().get("weights") or [None])[0]
                weights = json.loads(raw) if raw else None
                return self._json(tgt_engine.rank(weights))

            if path == "/api/records":
                rows = fetch_records()
                return self._json({"rows": rows, "metrics": metrics.summarize(rows)})

            if path == "/api/metrics":
                return self._json(metrics.summarize(fetch_records()))

            if path == "/api/models":
                return self._json(models_engine.rank())

            if path == "/api/assets":
                q = self._query()
                return self._json(assets_engine.directory(
                    query=(q.get("q") or [None])[0],
                    sort_by=(q.get("sort") or [None])[0],
                    desc=(q.get("desc") or ["0"])[0] == "1"))

            if path == "/api/records/export.csv":
                return self._csv_records()

            if path == "/api/model-card":
                raw = (self._query().get("cutoff") or ["10-01"])[0]
                return self._json(metrics.model_card(fetch_records(), cutoff=raw))

            if path == "/api/demo":
                demo = (ROOT / "data" / "demo_construct.txt")
                return self._json({"sequence": demo.read_text(encoding="utf-8").strip()})

            if path == "/api/infer":
                return self._json({"rows": list_tasks(), "backend": inf_engine.ACTIVE_BACKEND.name})

            if path.startswith("/api/infer/"):
                task_id = urllib.parse.unquote(path.rsplit("/", 1)[-1])
                task = get_task(task_id)
                if not task:
                    return self._json({"ok": False, "error": "任务不存在"}, 404)
                return self._json({"ok": True, "task": task})

            return self._static(path)
        except Exception as exc:                      # noqa: BLE001
            return self._json({"ok": False, "error": str(exc)}, 400)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/analyze":
                seq = self._body().get("sequence", "")
                result = seq_engine.analyze(seq)
                return self._json({"ok": True, **result})

            if path == "/api/optimize":
                body = self._body()
                opts = body.get("options") or {}
                result = opt_engine.optimize(
                    body.get("sequence", ""),
                    cpg_free=bool(opts.get("cpg_free", True)),
                    avoid_sites=bool(opts.get("avoid_sites", True)),
                    avoid_tandem=bool(opts.get("avoid_tandem", True)),
                    max_run=int(opts.get("max_run", 5)),
                )
                return self._json({"ok": True, **result})

            if path == "/api/protein":
                seq = self._body().get("sequence", "")
                return self._json({"ok": True, **prot_engine.describe(seq)})

            if path == "/api/infer":
                b = self._body()
                payload = str(b.get("payload_aa") or "").strip()
                hexon = str(b.get("hexon_aa") or "").strip()
                if not payload or not hexon:
                    return self._json(
                        {"ok": False, "error": "需要 payload 与 hexon 两条蛋白序列"}, 400)
                prep = inf_engine.build_task_payload(payload, hexon)
                task = submit_task(prep["norm"], prep["task_id"])
                return self._json({"ok": True, "task": task})

            if path == "/api/records":
                b = self._body()
                rid = str(b.get("id") or "").strip()
                if not rid:
                    return self._json({"ok": False, "error": "缺少构建体编号"}, 400)
                try:
                    pred, obs = float(b["pred"]), float(b["obs"])
                except (KeyError, TypeError, ValueError):
                    return self._json({"ok": False, "error": "预测值/实测值需为数字"}, 400)
                import datetime
                outcome = str(b.get("outcome") or "hit").strip().lower()
                if outcome not in metrics.OUTCOMES:
                    return self._json(
                        {"ok": False, "error": f"结局只能是 {list(metrics.OUTCOMES)}"}, 400)
                created = b.get("created") or datetime.date.today().strftime("%m-%d")
                with db() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO records"
                        "(id,pred,obs,model,created,note,outcome) VALUES(?,?,?,?,?,?,?)",
                        (rid, pred, obs, b.get("model") or "b2-0.6.1", created,
                         b.get("note") or "", outcome))
                rows = fetch_records()
                return self._json({"ok": True, "rows": rows, "metrics": metrics.summarize(rows)})

            return self._json({"ok": False, "error": "未知接口"}, 404)
        except Exception as exc:                      # noqa: BLE001
            return self._json({"ok": False, "error": str(exc)}, 400)

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/records/"):
            rid = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            with db() as conn:
                conn.execute("DELETE FROM records WHERE id = ?", (rid,))
            rows = fetch_records()
            return self._json({"ok": True, "rows": rows, "metrics": metrics.summarize(rows)})
        return self._json({"ok": False, "error": "未知接口"}, 404)

    # ---- static
    def _static(self, path):
        rel = path.lstrip("/") or "index.html"
        target = (WEB / rel).resolve()
        if not str(target).startswith(str(WEB.resolve())) or not target.is_file():
            target = WEB / "index.html"
        ctype = {
            ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8", ".json": "application/json",
            ".png": "image/png", ".svg": "image/svg+xml",
        }.get(target.suffix, "application/octet-stream")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    init_db()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"EVOL-AI 已启动 → http://127.0.0.1:{port}")
    print("Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
