"""CLI entry point. All configuration writes are confined to the tool state directory."""
import argparse
import json
import os
import sqlite3
from pathlib import Path
import sys

from .core import (Store, canonical, default_state, deliver, doctor, dump,
                   observe_probe, reconcile, resolve_executable, resolve_stopped, uid, worker)


def parser():
    p = argparse.ArgumentParser(description="Experimental independent Codex sessions; IDE wake requires live acceptance")
    p.add_argument("--state", type=Path, default=default_state())
    commands = p.add_subparsers(dest="action", required=True)
    init = commands.add_parser("init", help="Create tool-local configuration; never edits Codex config")
    init.add_argument("--codex", required=True, help="Native executable path; Windows requires codex.exe")
    init.add_argument("--queue-codex", help="Optional separate native binary matching the original IDE host")
    init.add_argument("--child-model", required=True)
    init.add_argument("--parent-model", help="Expected existing IDE model, recorded only; queue cannot override it")
    init.add_argument("--provider", help="Existing configured Codex provider key; child only")
    init.add_argument("--effort", help="Requested effort; no assumption about model/provider support")
    init.add_argument("--sandbox", choices=["read-only", "workspace-write"], default="read-only")
    init.add_argument("--skip-git-repo-check", action="store_true")
    commands.add_parser("doctor", help="Read CLI version/help only; makes no model calls")
    start = commands.add_parser("start", help="Start an independent child and immediately return")
    start.add_argument("--cwd", required=True)
    start.add_argument("--prompt-file", type=Path, required=True)
    start.add_argument("--parent-thread")
    start.add_argument("--request-key")
    send = commands.add_parser("send", help="Resume the exact managed child thread")
    send.add_argument("--session", required=True)
    send.add_argument("--prompt-file", type=Path, required=True)
    send.add_argument("--request-key")
    commands.add_parser("list")
    for name in ("show", "cancel", "_worker", "_deliver"):
        commands.add_parser(name).add_argument("run_id")
    commands.add_parser("reconcile", help="Deliver ready events only; never retries ambiguous sends")
    recovery = commands.add_parser("resolve-stopped", help="Release an orphan reservation after manual process inspection")
    recovery.add_argument("run_id")
    recovery.add_argument("--confirm-stopped", action="store_true", required=True)
    probe = commands.add_parser("probe-wake", help="Queue a nonce after a delay; potentially invokes the parent's model")
    probe.add_argument("--parent-thread", required=True)
    probe.add_argument("--cwd", required=True)
    probe.add_argument("--delay", type=float, default=15)
    observe = commands.add_parser("observe-probe", help="Read a supplied parent rollout; never claims automatic execution")
    observe.add_argument("run_id")
    observe.add_argument("--parent-rollout", type=Path, required=True)
    commands.add_parser("mcp", help="Serve minimal MCP over stdio; workers survive EOF")
    return p


def send(store, session_id, prompt, request_key=None):
    session_id = uid(session_id)
    with store.db() as db:
        row = db.execute("SELECT data FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not row:
        raise ValueError("Unknown session ID")
    session = json.loads(row[0])
    return store.start(session["cwd"], prompt, session_id=session_id, request_key=request_key)


def show(store, run_id):
    result = store.get(run_id)
    path = store.artifact(run_id)
    final = path / "last-message.txt"
    result["artifacts"] = str(path)
    # Bound tool response size; the complete result stays on disk.
    if final.exists():
        with final.open(encoding="utf-8", errors="replace") as stream:
            text = stream.read(20001)
        result["last_message"] = text[:20000]
        result["last_message_truncated"] = len(text) > 20000
    return result


def run(args):
    store = Store(args.state)
    if args.action == "init":
        path = store.root / "config.json"
        if path.exists():
            raise ValueError("Configuration exists; inspect and edit this tool's config.json explicitly")
        config = {"command": [resolve_executable(args.codex)], "child_model": args.child_model,
                  "parent_model_expected": args.parent_model, "provider": args.provider,
                  "effort": args.effort, "sandbox": args.sandbox,
                  "skip_git_repo_check": args.skip_git_repo_check}
        if args.queue_codex:
            config["queue_command"] = [resolve_executable(args.queue_codex)]
        # Exclusive creation avoids overwriting a concurrent initializer.
        with path.open("x", encoding="utf-8") as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
        return {"config": str(path), "parent_model_control": "Configure in the original IDE session; queue inherits it"}
    if args.action == "doctor":
        result = doctor(store.config())
        dump(store.root / "doctor.json", result)
        return result
    if args.action == "start":
        return store.start(args.cwd, args.prompt_file.read_text(encoding="utf-8-sig"), args.parent_thread, request_key=args.request_key)
    if args.action == "send":
        return send(store, args.session, args.prompt_file.read_text(encoding="utf-8-sig"), args.request_key)
    if args.action == "show":
        return show(store, args.run_id)
    if args.action == "list":
        return store.list()
    if args.action == "cancel":
        return store.cancel(args.run_id)
    if args.action == "reconcile":
        return reconcile(store)
    if args.action == "resolve-stopped":
        return resolve_stopped(store, args.run_id)
    if args.action == "probe-wake":
        return store.probe(args.parent_thread, args.cwd, args.delay)
    if args.action == "observe-probe":
        return observe_probe(store, args.run_id, args.parent_rollout)
    if args.action == "_worker":
        worker(store, uid(args.run_id))
    elif args.action == "_deliver":
        deliver(store, uid(args.run_id))
    elif args.action == "mcp":
        from .mcp import serve
        serve(store)
    return None


def main():
    # MCP and command output must stay UTF-8 under native Windows consoles too.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if os.name != "nt":
        os.umask(0o077)
    args = parser().parse_args()
    try:
        value = run(args)
        if value is not None:
            print(json.dumps(value, ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
