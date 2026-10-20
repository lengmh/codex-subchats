"""Transport double; never calls a model or simulates automatic IDE execution."""
import json
from pathlib import Path
import sys
import subprocess
import time
import uuid
args = sys.argv[1:]
if '--version' in args:
    print('fake-codex transport-only'); sys.exit(0)
if '--help' in args:
    print('--json --model --sandbox --output-last-message --thread --message resume'); sys.exit(0)
if args[0] == 'queue':
    thread = args[args.index('--thread') + 1]
    with Path('queue-calls.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps({'thread': thread, 'message': args[args.index('--message') + 1]}) + '\n')
    print('ambiguous' if Path('bad-ack').exists() else 'Queued message ' + str(uuid.uuid4()) + ' for thread ' + thread + '.')
    sys.exit(0)
prompt = sys.stdin.read()
thread = args[args.index('resume') + 1] if 'resume' in args else str(uuid.uuid4())
if prompt == 'WRONG': thread = str(uuid.uuid4())
print(json.dumps({'type': 'thread.started', 'thread_id': thread}), flush=True)
print(json.dumps({'type': 'turn.started'}), flush=True)
with Path('exec-calls.jsonl').open('a', encoding='utf-8') as f:
    f.write(json.dumps({'thread': thread, 'prompt': prompt, 'args': args}) + '\n')
if prompt == 'TREE_HANG':
    code = "import os,signal,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path('descendant.pid').write_text(str(os.getpid())); exec(\"while True:\\n Path('heartbeat').write_text(str(time.time()))\\n time.sleep(.05)\")"
    subprocess.Popen([sys.executable, '-c', code])
    time.sleep(30)
if prompt == 'HANG': time.sleep(30)
if prompt == 'DELAY': time.sleep(0.6)
if prompt == 'FAIL':
    print(json.dumps({'type': 'turn.failed'})); sys.exit(1)
if prompt == 'NO_TERMINAL': sys.exit(0)
Path(args[args.index('--output-last-message') + 1]).write_text('done: ' + prompt, encoding='utf-8')
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'done: ' + prompt}}))
print(json.dumps({'type': 'turn.completed'}), flush=True)
