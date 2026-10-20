"""SQLite coordination and detached, bounded Codex invocations. No third-party runtime."""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def uid(value=None):
    return str(uuid.UUID(value)) if value else str(uuid.uuid4())


def canonical(path):
    return os.path.normcase(str(Path(path).expanduser().resolve(strict=True)))


def default_state():
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) if os.name == "nt" else Path.home() / ".local" / "state"
    return base / "codex-subchats"


def dump(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def process_options(detached=False):
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW
        if detached:
            flags |= subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        return {"creationflags": flags}
    return {"start_new_session": True}


def stop_process(proc):
    """Only called with a Popen owned by this live worker, never a saved PID."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        result = subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                capture_output=True, timeout=15, **process_options())
        if result.returncode and proc.poll() is None:
            raise RuntimeError("taskkill failed; process state needs inspection")
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        # The leader may exit while descendants ignore TERM and keep writing.
        # This worker created the private process group; finish cancelling it.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait(timeout=10)


class Store:
    def __init__(self, root):
        self.workers = []
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = self.root / "state.sqlite3"
        with self.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, thread_id TEXT UNIQUE, data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, session_id TEXT, cwd TEXT NOT NULL,
                status TEXT NOT NULL, busy INTEGER NOT NULL, request_key TEXT UNIQUE,
                data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS outbox (
                run_id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL);
            ''')

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def config(self):
        return json.loads((self.root / "config.json").read_text(encoding="utf-8"))

    def artifact(self, run_id):
        path = self.root / "runs" / uid(run_id)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def get(self, run_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (uid(run_id),)).fetchone()
            if not row:
                raise ValueError("Unknown run ID")
            data = json.loads(row["data"])
            data.update(id=row["id"], session_id=row["session_id"], status=row["status"], busy=bool(row["busy"]))
            out = db.execute("SELECT * FROM outbox WHERE run_id=?", (row["id"],)).fetchone()
            data["notification"] = ({**json.loads(out["data"]), "status": out["status"]} if out else None)
            return data

    def list(self):
        with self.db() as db:
            return [dict(row) for row in db.execute("SELECT id,session_id,cwd,status,busy FROM runs ORDER BY rowid DESC LIMIT 100")]

    def update_run(self, run_id, **changes):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            data = json.loads(row["data"])
            status = changes.pop("status", row["status"])
            busy = changes.pop("busy", row["busy"])
            data.update(changes)
            db.execute("UPDATE runs SET status=?,busy=?,data=? WHERE id=?", (status, busy, json.dumps(data), run_id))

    def start(self, cwd, prompt, parent_thread=None, session_id=None, request_key=None, launch=True):
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("A nonempty, self-contained prompt is required")
        cwd = canonical(cwd)
        if not Path(cwd).is_dir():
            raise ValueError("cwd must be a directory")
        parent_thread = uid(parent_thread) if parent_thread else None
        request_key = request_key or uid()
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 200:
            raise ValueError("Invalid request_key")
        config = self.config()
        run_id = uid()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT id,data,session_id FROM runs WHERE request_key=?", (request_key,)).fetchone()
            if old:
                old_data = json.loads(old["data"])
                if (old_data["cwd"], old_data["prompt"], old_data["requested_session"], old_data["requested_parent"]) != (cwd, prompt, session_id, parent_thread):
                    raise ValueError("request_key already belongs to a different request")
                return self.get(old["id"])
            requested_session, requested_parent = session_id, parent_thread
            if session_id:
                row = db.execute("SELECT * FROM sessions WHERE id=?", (uid(session_id),)).fetchone()
                if not row or not row["thread_id"]:
                    raise ValueError("Session has no recoverable thread ID")
                session = json.loads(row["data"])
                if session["cwd"] != cwd:
                    raise ValueError("Resume must use the original working directory")
                parent_thread = session["parent_thread"]
                config = session["config"]
                thread_id = row["thread_id"]
            else:
                session_id, thread_id = uid(), None
                session = {"cwd": cwd, "parent_thread": parent_thread, "config": config}
            for row in db.execute("SELECT cwd,session_id,id FROM runs WHERE busy=1"):
                a, b = Path(row["cwd"]), Path(cwd)
                if row["session_id"] == session_id or a == b or a in b.parents or b in a.parents:
                    raise ValueError("Overlapping workspace or session reserved by run " + row["id"])
            if not requested_session:
                db.execute("INSERT INTO sessions VALUES (?,?,?)", (session_id, None, json.dumps(session)))
            data = {"cwd": cwd, "prompt": prompt, "parent_thread": parent_thread,
                    "requested_session": requested_session, "requested_parent": requested_parent,
                    "thread_id": thread_id, "config": config, "created_at": time.time(),
                    "cancel_requested": False, "request_key": request_key}
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (run_id, session_id, cwd, "pending", 1, request_key, json.dumps(data)))
        if launch:
            try:
                self.launch(run_id, "_worker")
            except Exception as exc:
                self.update_run(run_id, status="failed", busy=0, error="Worker launch failed: " + str(exc))
                raise
        return self.get(run_id)

    def launch(self, run_id, action):
        self.workers = [process for process in self.workers if process.poll() is None]
        artifact = self.artifact(run_id)
        # Pin our package source for workers even when launched from an unrelated cwd.
        env = os.environ.copy()
        source = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = source + os.pathsep + env.get("PYTHONPATH", "")
        with (artifact / "worker.log").open("ab") as log:
            process = subprocess.Popen([sys.executable, "-m", "codex_subchats", "--state", str(self.root), action, run_id],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env,
                             cwd=str(self.root), close_fds=True, **process_options(detached=True))
        self.workers.append(process)
        threading.Thread(target=process.wait, daemon=True).start()

    def cancel(self, run_id):
        run = self.get(run_id)
        if run["status"] == "probe":
            with self.db() as db:
                changed = db.execute("UPDATE outbox SET status='cancelled' WHERE run_id=? AND status='ready'", (run["id"],)).rowcount
                if changed:
                    db.execute("UPDATE runs SET status='cancelled' WHERE id=?", (run["id"],))
            return self.get(run_id)
        if run["status"] in TERMINAL:
            return run
        self.update_run(run_id, cancel_requested=True)
        return self.get(run_id)

    def finish(self, run_id, status, **details):
        """One durable terminal transition plus outbox insertion in the same transaction."""
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row["status"] in TERMINAL:
                return
            data = json.loads(row["data"])
            data.update(details, completed_at=time.time())
            db.execute("UPDATE runs SET status=?,busy=0,data=? WHERE id=?", (status, json.dumps(data), run_id))
            if data["parent_thread"] and status != "cancelled":
                message = ("codex-subchats task event\n" + json.dumps({"run_id": run_id, "session_id": row["session_id"],
                           "child_thread_id": data.get("thread_id"), "status": status}, ensure_ascii=False) +
                           "\nUse subchat_status or codex-subchats show to read the saved result, then review it within the existing task. "
                           "This event is a transport notification; it is not proof of task success.")
                out = {"parent_thread": data["parent_thread"], "message": message, "cwd": data["cwd"],
                       "config": data["config"], "model_execution_verified": False}
                db.execute("INSERT OR IGNORE INTO outbox VALUES (?,?,?)", (run_id, "ready", json.dumps(out)))

    def probe(self, parent_thread, cwd, delay=15):
        parent_thread, cwd = uid(parent_thread), canonical(cwd)
        if not 0 <= delay <= 300:
            raise ValueError("Probe delay must be between 0 and 300 seconds")
        run_id, token = uid(), "SUBCHATS_WAKE_" + uuid.uuid4().hex
        data = {"cwd": cwd, "created_at": time.time(), "probe_token": token, "parent_thread": parent_thread}
        out = {"cwd": cwd, "config": self.config(), "parent_thread": parent_thread,
               "message": "Wake feasibility probe. Reply with exactly: " + token,
               "not_before": time.time() + delay, "model_execution_verified": False}
        with self.db() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (run_id, None, cwd, "probe", 0, uid(), json.dumps(data)))
            db.execute("INSERT INTO outbox VALUES (?,?,?)", (run_id, "ready", json.dumps(out)))
        self.launch(run_id, "_deliver")
        return self.get(run_id)


def resolve_executable(executable):
    path = shutil.which(executable)
    if not path:
        raise ValueError("Codex executable not found: " + executable)
    if os.name == "nt" and Path(path).suffix.lower() != ".exe":
        raise ValueError("Use a native codex.exe path, not a cmd/ps1 shim")
    return str(Path(path).resolve())


def doctor(config):
    command = config["command"]
    checks = {}
    for name, args in [("version", ["--version"]), ("exec", ["exec", "--help"]),
                       ("resume", ["exec", "resume", "--help"]), ("queue_version", ["--version"]), ("queue", ["queue", "--help"])]:
        try:
            executable = config.get("queue_command", command) if name.startswith("queue") else command
            result = subprocess.run(executable + args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, **process_options())
            checks[name] = {"returncode": result.returncode, "text": (result.stdout + result.stderr)[-16000:]}
        except (OSError, subprocess.TimeoutExpired) as exc:
            checks[name] = {"returncode": None, "text": str(exc)}
    exec_ok = checks["exec"]["returncode"] == 0 and all(flag in checks["exec"]["text"] for flag in ["--json", "--model", "--sandbox", "--output-last-message"])
    queue_ok = checks["queue"]["returncode"] == 0 and all(flag in checks["queue"]["text"] for flag in ["--thread", "--message"])
    return {"checks": checks, "exec_shape_supported": exec_ok,
            "resume_help_available": checks["resume"]["returncode"] == 0,
            "queue_shape_supported": queue_ok, "child_model_requested": config["child_model"],
            "parent_model_expected": config.get("parent_model_expected"),
            "model_access_verified": False, "ide_auto_wake_verified": False}


def command_for(run, artifact):
    config = run["config"]
    args = config["command"] + ["exec", "--json", "--model", config["child_model"],
            "--sandbox", config["sandbox"], "-c", 'approval_policy="never"',
            "--output-last-message", str(artifact / "last-message.txt")]
    if config.get("provider"):
        args += ["-c", "model_provider=" + json.dumps(config["provider"])]
    if config.get("effort"):
        args += ["-c", "model_reasoning_effort=" + json.dumps(config["effort"])]
    if config.get("skip_git_repo_check"):
        args += ["--skip-git-repo-check"]
    if run.get("thread_id"):
        args += ["resume", uid(run["thread_id"])]
    return args + ["-"]


def parse_events(path, expected_thread=None):
    thread, completed, errors = None, 0, []
    if not path.exists():
        return {"thread_id": expected_thread, "valid": False, "errors": ["Missing event stream"]}
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                kind = event.get("type")
                if kind == "thread.started":
                    observed = str(uuid.UUID(event["thread_id"]))
                    if thread and thread != observed:
                        errors.append("Multiple thread IDs")
                    thread = observed
                elif kind == "turn.completed":
                    completed += 1
                elif kind in {"turn.failed", "error"}:
                    errors.append(kind)
            except (ValueError, KeyError, AttributeError, TypeError):
                errors.append("Invalid event line " + str(number))
    if not thread:
        errors.append("Missing thread.started")
    if expected_thread and thread != expected_thread:
        errors.append("Resumed a different thread")
    if completed != 1:
        errors.append("Expected exactly one turn.completed")
    return {"thread_id": thread, "valid": not errors, "errors": errors}


def worker(store, run_id):
    with store.db() as db:
        changed = db.execute("UPDATE runs SET status='running' WHERE id=? AND status='pending'", (run_id,)).rowcount
    if not changed:
        return
    run = store.get(run_id)
    artifact = store.artifact(run_id)
    proc = None
    try:
        dump(artifact / "request.json", run)
        if run["cancel_requested"]:
            store.finish(run_id, "cancelled")
            return
        args = command_for(run, artifact)
        dump(artifact / "command.json", {"argv": args, "cwd": run["cwd"], "model_is_requested_not_attested": True})
        (artifact / "prompt.txt").write_text(run["prompt"], encoding="utf-8")
        with (artifact / "prompt.txt").open("rb") as inp, (artifact / "events.jsonl").open("wb") as out, (artifact / "stderr.log").open("wb") as err:
            proc = subprocess.Popen(args, stdin=inp, stdout=out, stderr=err, cwd=run["cwd"], **process_options())
            store.update_run(run_id, worker_pid=os.getpid(), child_pid=proc.pid)
            cancelled = False
            while proc.poll() is None:
                if not run.get("thread_id"):
                    # The identity event is at the start of JSONL; save it before a possible crash.
                    with (artifact / "events.jsonl").open(encoding="utf-8", errors="replace") as early:
                        lines = early.read(65536).splitlines()
                    for line in lines:
                        try:
                            event = json.loads(line)
                            if event.get("type") == "thread.started":
                                run["thread_id"] = str(uuid.UUID(event["thread_id"]))
                                store.update_run(run_id, thread_id=run["thread_id"])
                                break
                        except (ValueError, TypeError, KeyError, AttributeError):
                            continue
                if store.get(run_id)["cancel_requested"]:
                    cancelled = True
                    stop_process(proc)
                    break
                time.sleep(0.2)
            code = proc.wait()
        events = parse_events(artifact / "events.jsonl", run.get("thread_id"))
        # Only bind a newly created session when identity is unambiguous, even on a failed turn.
        identity_errors = {"Multiple thread IDs", "Resumed a different thread", "Missing thread.started"}
        if events["thread_id"] and not identity_errors.intersection(events["errors"]):
            with store.db() as db:
                db.execute("UPDATE sessions SET thread_id=? WHERE id=?", (events["thread_id"], run["session_id"]))
        status = "cancelled" if cancelled else "completed" if code == 0 and events["valid"] else "failed"
        store.finish(run_id, status, thread_id=events["thread_id"], exit_code=code, event_validation=events)
    except BaseException as exc:
        # If termination fails, retain the reservation: an unknown process must not gain a second writer.
        try:
            if proc is not None:
                stop_process(proc)
        except Exception as stop_error:
            store.update_run(run_id, status="needs_attention", error=str(exc), stop_error=str(stop_error))
            return
        store.finish(run_id, "failed", error=str(exc))
    deliver(store, run_id)


def deliver(store, run_id):
    with store.db() as db:
        row = db.execute("SELECT * FROM outbox WHERE run_id=?", (run_id,)).fetchone()
    if not row or row["status"] != "ready":
        return
    data = json.loads(row["data"])
    while time.time() < data.get("not_before", 0):
        time.sleep(min(0.5, data["not_before"] - time.time()) if data["not_before"] > time.time() else 0)
    with store.db() as db:
        claimed = db.execute("UPDATE outbox SET status='sending' WHERE run_id=? AND status='ready'", (run_id,)).rowcount
    if not claimed:
        return
    artifact = store.artifact(run_id)
    status = "ambiguous"
    args = data["config"].get("queue_command", data["config"]["command"]) + ["queue", "--thread", data["parent_thread"], "--message", data["message"]]
    try:
        result = subprocess.run(args, cwd=data["cwd"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, **process_options())
        (artifact / "queue.stdout").write_text(result.stdout, encoding="utf-8")
        (artifact / "queue.stderr").write_text(result.stderr, encoding="utf-8")
        ack = re.fullmatch(r"Queued message ([0-9a-fA-F-]{36}) for thread ([0-9a-fA-F-]{36})\.", result.stdout.strip())
        if result.returncode == 0 and ack and uid(ack[2]) == data["parent_thread"]:
            data["message_id"] = uid(ack[1])
            status = "queued"
        else:
            data["error"] = "No matching queue acknowledgment; inspect before retrying"
        data["exit_code"] = result.returncode
    except Exception as exc:
        data["error"] = str(exc)
    data["attempted_at"] = time.time()
    with store.db() as db:
        db.execute("UPDATE outbox SET status=?,data=? WHERE run_id=?", (status, json.dumps(data), run_id))


def reconcile(store):
    """Retry only never-attempted durable events, not sends with uncertain outcomes."""
    with store.db() as db:
        ids = [r[0] for r in db.execute("SELECT run_id FROM outbox WHERE status='ready'")]
    for run_id in ids:
        store.launch(run_id, "_deliver")
    return {"delivery_workers_requested": ids, "note": "sending/ambiguous are not retried; running tasks are not relaunched"}


def resolve_stopped(store, run_id):
    """Operator-confirmed process stop; recover identity from retained events, never replay work."""
    run = store.get(run_id)
    if not run["busy"]:
        return run
    events = parse_events(store.artifact(run_id) / "events.jsonl", run.get("thread_id"))
    bad_identity = {"Multiple thread IDs", "Resumed a different thread", "Missing thread.started"}
    thread = events["thread_id"]
    if thread and not bad_identity.intersection(events["errors"]):
        with store.db() as db:
            db.execute("UPDATE sessions SET thread_id=? WHERE id=?", (thread, run["session_id"]))
    store.finish(run["id"], "interrupted", error="Operator confirmed worker and child process tree stopped",
                 thread_id=thread, event_validation=events)
    return store.get(run_id)


def observe_probe(store, run_id, rollout):
    """Read-only corroboration. Cannot establish absence of human interaction."""
    run = store.get(run_id)
    token = run.get("probe_token")
    if not token:
        raise ValueError("Not a wake probe")
    identity, replies = None, []
    with Path(rollout).open(encoding="utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                continue  # Live rollout can end in a partial line.
            payload = event.get("payload", {})
            if event.get("type") == "session_meta":
                identity = payload.get("id")
            if event.get("type") == "response_item" and payload.get("role") == "assistant":
                content = payload.get("content", [])
                text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
                if text.strip() == token:
                    replies.append({"timestamp": event.get("timestamp"), "text": text})
    if identity != run["parent_thread"]:
        raise ValueError("Rollout does not identify the exact parent thread")
    evidence = {"parent_thread": identity, "matching_assistant_replies": replies,
                "assistant_reply_observed": bool(replies), "automatic_execution_verified": False,
                "remaining_check": "Confirm original VS Code turn ended, no manual Send/Resume/input, and record extension/CLI versions"}
    dump(store.artifact(run_id) / "observation.json", evidence)
    return evidence
