"""Small stdio MCP adapter: one JSON-RPC message per line, no network listener."""
import json
import sqlite3
import sys

from . import __version__
from .cli import send, show


def obj(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


STRING = {"type": "string", "minLength": 1}
TOOLS = [
    {"name": "subchat_start", "description": "Launch an independent CLI session. Returns immediately; end your turn to allow queue consumption. Use a separate worktree for writing. Parent UUID must come from the actual IDE host, never guessed.",
     "inputSchema": obj({"cwd": STRING, "prompt": STRING, "parent_thread": STRING, "request_key": STRING}, ("cwd", "prompt", "request_key"))},
    {"name": "subchat_send", "description": "Continue the exact managed child session with its pinned model and cwd. Refuses overlapping active runs.",
     "inputSchema": obj({"session_id": STRING, "prompt": STRING, "request_key": STRING}, ("session_id", "prompt", "request_key"))},
    {"name": "subchat_status", "description": "Read a saved result. queued means transport acceptance, never proof the parent model executed.",
     "inputSchema": obj({"run_id": STRING}, ("run_id",))},
    {"name": "subchat_cancel", "description": "Request cancellation of a running child. Does not undo edits or retract an already queued event.",
     "inputSchema": obj({"run_id": STRING}, ("run_id",))},
    {"name": "subchat_list", "description": "List the most recent 100 local runs.", "inputSchema": obj({})},
]


def call(store, name, arguments):
    tool = next((t for t in TOOLS if t["name"] == name), None)
    if tool is None:
        raise ValueError("Unknown tool")
    schema = tool["inputSchema"]
    if not isinstance(arguments, dict) or set(arguments) - set(schema["properties"]) or set(schema["required"]) - set(arguments):
        raise ValueError("Invalid tool arguments")
    if any(not isinstance(value, str) or not value.strip() for value in arguments.values()):
        raise ValueError("Tool arguments must be nonempty strings")
    if name == "subchat_start":
        return store.start(**arguments)
    if name == "subchat_send":
        return send(store, **arguments)
    if name == "subchat_status":
        return show(store, arguments["run_id"])
    if name == "subchat_cancel":
        return store.cancel(arguments["run_id"])
    return store.list()


def serve(store):
    initialized = False
    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
                raise ValueError("Invalid JSON-RPC request")
            if "id" not in request:
                continue
            method = request["method"]
            params = request.get("params", {})
            if not isinstance(params, dict):
                raise ValueError("params must be an object")
            if method == "initialize":
                supported = {"2024-11-05", "2025-03-26", "2025-06-18"}
                version = params.get("protocolVersion")
                result = {"protocolVersion": version if version in supported else "2025-06-18",
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "codex-subchats", "version": __version__}}
                initialized = True
            elif method == "ping":
                result = {}
            elif not initialized:
                raise ValueError("Initialize first")
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                try:
                    value = call(store, params.get("name"), params.get("arguments", {}))
                    result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
                except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
                    result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            else:
                response = {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32601, "message": "Method not found"}}
                print(json.dumps(response), flush=True)
                continue
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except (ValueError, TypeError) as exc:
            response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                        "error": {"code": -32700 if isinstance(exc, json.JSONDecodeError) else -32600, "message": str(exc)}}
        print(json.dumps(response, ensure_ascii=False), flush=True)
