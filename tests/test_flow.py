import concurrent.futures
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from codex_subchats.core import Store, deliver, doctor, dump, observe_probe, parse_events, reconcile, resolve_stopped, worker
from codex_subchats.cli import send
FAKE = Path(__file__).with_name('fake_codex.py').resolve()

class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cwd = self.root / '工作区 with spaces'
        self.cwd.mkdir()
        self.store = Store(self.root / 'state')
        self.parent = str(uuid.uuid4())
        self.config = {'command': [sys.executable, str(FAKE)], 'child_model': 'test-model',
                       'parent_model_expected': 'test-parent', 'sandbox': 'read-only'}
        dump(self.store.root / 'config.json', self.config)
    def tearDown(self):
        for process in self.store.workers:
            process.wait(timeout=5)
        self.tmp.cleanup()
    def await_run(self, run_id, notification=False):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            run = self.store.get(run_id)
            if run['status'] in {'completed','failed','cancelled','interrupted'}:
                if not notification or (run['notification'] and run['notification']['status'] in {'queued','ambiguous'}):
                    return run
            time.sleep(0.03)
        self.fail('run did not finish: ' + repr(self.store.get(run_id)))
    def test_three_round_transport_exact_thread_and_models(self):
        run = self.store.start(str(self.cwd), 'round 1', self.parent)
        thread = None
        for i in range(1,4):
            done = self.await_run(run['id'], True)
            self.assertEqual(done['status'], 'completed')
            self.assertEqual(done['notification']['status'], 'queued')
            self.assertFalse(done['notification']['model_execution_verified'])
            thread = thread or done['thread_id']
            self.assertEqual(done['thread_id'], thread)
            if i < 3: run = send(self.store, done['session_id'], 'round ' + str(i+1))
        calls = [json.loads(l) for l in (self.cwd/'exec-calls.jsonl').read_text().splitlines()]
        self.assertEqual(len(calls),3)
        self.assertEqual({c['thread'] for c in calls},{thread})
        for c in calls: self.assertEqual(c['args'][c['args'].index('--model')+1], 'test-model')
        self.assertEqual(len((self.cwd/'queue-calls.jsonl').read_text().splitlines()),3)
    def test_concurrent_duplicate_requests_only_one_execution(self):
        def submit(_): return self.store.start(str(self.cwd),'one',self.parent,request_key='same',launch=False)['id']
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            ids = list(pool.map(submit,range(5)))
        self.assertEqual(len(set(ids)),1)
        worker(self.store,ids[0]); worker(self.store,ids[0])
        self.assertEqual(len((self.cwd/'exec-calls.jsonl').read_text().splitlines()),1)
        with self.assertRaises(ValueError):
            self.store.start(str(self.cwd),'different',self.parent,request_key='same',launch=False)
    def test_overlapping_directory_reserved(self):
        run = self.store.start(str(self.cwd),'one',launch=False)
        nested=self.cwd/'nested'; nested.mkdir()
        with self.assertRaisesRegex(ValueError,'reserved'): self.store.start(str(nested),'two',launch=False)
        self.store.cancel(run['id']); worker(self.store,run['id'])
        self.assertEqual(self.store.get(run['id'])['status'],'cancelled')
    def test_failed_and_missing_terminal_are_not_success(self):
        for prompt in ('FAIL','NO_TERMINAL'):
            done=self.await_run(self.store.start(str(self.cwd),prompt,self.parent)['id'],True)
            self.assertEqual(done['status'],'failed')
    def test_wrong_resume_identity_is_not_rebound(self):
        first=self.await_run(self.store.start(str(self.cwd),'first')['id'])
        wrong=self.await_run(send(self.store,first['session_id'],'WRONG')['id'])
        self.assertEqual(wrong['status'],'failed')
        self.assertIn('Resumed a different thread',wrong['event_validation']['errors'])
        again=self.await_run(send(self.store,first['session_id'],'again')['id'])
        self.assertEqual(again['thread_id'],first['thread_id'])
    def test_cancel_running_process_does_not_notify(self):
        run=self.store.start(str(self.cwd),'HANG',self.parent)
        deadline=time.monotonic()+5
        while not self.store.get(run['id']).get('child_pid') and time.monotonic()<deadline: time.sleep(.02)
        self.store.cancel(run['id'])
        done=self.await_run(run['id'])
        self.assertEqual(done['status'],'cancelled')
        self.assertIsNone(done['notification'])
        self.assertFalse(done['busy'])
    @unittest.skipIf(os.name == 'nt', 'POSIX process-group regression')
    def test_cancel_kills_descendant_after_leader_exits(self):
        run=self.store.start(str(self.cwd),'TREE_HANG')
        pid_file=self.cwd/'descendant.pid'
        deadline=time.monotonic()+5
        while not pid_file.exists() and time.monotonic()<deadline: time.sleep(.02)
        self.assertTrue(pid_file.exists())
        pid=int(pid_file.read_text())
        try:
            self.store.cancel(run['id'])
            self.assertEqual(self.await_run(run['id'])['status'],'cancelled')
            time.sleep(.1)
            heartbeat=(self.cwd/'heartbeat').read_text()
            time.sleep(.2)
            self.assertEqual((self.cwd/'heartbeat').read_text(),heartbeat)
        finally:
            try: os.kill(pid,signal.SIGKILL)
            except ProcessLookupError: pass
    def test_ready_outbox_survives_reopen_delivers_once(self):
        run=self.store.start(str(self.cwd),'one',self.parent,launch=False)
        self.store.finish(run['id'],'completed')
        reopened=Store(self.store.root)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda _:deliver(reopened,run['id']),range(3)))
        self.assertEqual(len((self.cwd/'queue-calls.jsonl').read_text().splitlines()),1)
        self.assertEqual(reopened.get(run['id'])['notification']['status'],'queued')
    def test_ambiguous_and_sending_not_retried(self):
        (self.cwd/'bad-ack').touch()
        done=self.await_run(self.store.start(str(self.cwd),'one',self.parent)['id'],True)
        self.assertEqual(done['notification']['status'],'ambiguous')
        deliver(self.store,done['id'])
        self.assertEqual(reconcile(self.store)['delivery_workers_requested'],[])
        with self.store.db() as db: db.execute("UPDATE outbox SET status='sending' WHERE run_id=?",(done['id'],))
        self.assertEqual(reconcile(self.store)['delivery_workers_requested'],[])
        self.assertEqual(len((self.cwd/'queue-calls.jsonl').read_text().splitlines()),1)
    def test_orphan_retains_reservation_after_reopen(self):
        run=self.store.start(str(self.cwd),'one',launch=False)
        self.store.update_run(run['id'],status='running')
        reopened=Store(self.store.root)
        with self.assertRaisesRegex(ValueError,'reserved'): reopened.start(str(self.cwd),'two',launch=False)
        self.assertEqual(reconcile(reopened)['delivery_workers_requested'],[])
        reopened.finish(run['id'],'interrupted',error='Operator confirmed stopped')
        self.assertFalse(reopened.get(run['id'])['busy'])
    def test_doctor_no_model_or_host_claim(self):
        result=doctor(self.config)
        self.assertTrue(result['exec_shape_supported']); self.assertTrue(result['queue_shape_supported'])
        self.assertFalse(result['model_access_verified']); self.assertFalse(result['ide_auto_wake_verified'])
        self.assertFalse((self.cwd/'exec-calls.jsonl').exists())
    def test_probe_requires_parent_assistant_but_no_auto_claim(self):
        run=self.store.probe(self.parent,str(self.cwd),0)
        deadline=time.monotonic()+5
        while self.store.get(run['id'])['notification']['status'] in {'ready','sending'} and time.monotonic()<deadline: time.sleep(.02)
        rollout=self.root/'rollout.jsonl'
        events=[{'type':'session_meta','payload':{'id':self.parent}},
                {'type':'response_item','payload':{'role':'user','content':[{'text':run['probe_token']}]}}]
        rollout.write_text('\n'.join(map(json.dumps,events)),encoding='utf-8')
        self.assertFalse(observe_probe(self.store,run['id'],rollout)['assistant_reply_observed'])
        events[-1]['payload']['role']='assistant'
        rollout.write_text('\n'.join(map(json.dumps,events)),encoding='utf-8')
        observed=observe_probe(self.store,run['id'],rollout)
        self.assertTrue(observed['assistant_reply_observed']); self.assertFalse(observed['automatic_execution_verified'])
        events[0]['payload']['id']=str(uuid.uuid4())
        rollout.write_text('\n'.join(map(json.dumps,events)),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'exact parent'): observe_probe(self.store,run['id'],rollout)
    def test_interrupted_identity_recovery_and_invalid_identity(self):
        run=self.store.start(str(self.cwd),'one',launch=False)
        thread=str(uuid.uuid4())
        events=self.store.artifact(run['id'])/'events.jsonl'
        events.write_text(json.dumps({'type':'thread.started','thread_id':None})+'\n')
        self.assertFalse(parse_events(events)['valid'])
        self.assertIsNone(parse_events(events)['thread_id'])
        events.write_text(json.dumps({'type':'thread.started','thread_id':thread})+'\n')
        self.store.update_run(run['id'],status='running')
        interrupted=resolve_stopped(self.store,run['id'])
        self.assertEqual(interrupted['status'],'interrupted')
        resumed=self.await_run(send(self.store,run['session_id'],'after confirmed stop')['id'])
        self.assertEqual(resumed['thread_id'],thread)
    def test_delayed_probe_can_be_cancelled_before_send(self):
        run=self.store.probe(self.parent,str(self.cwd),0.5)
        cancelled=self.store.cancel(run['id'])
        self.assertEqual(cancelled['notification']['status'],'cancelled')
        for process in self.store.workers: process.wait(timeout=5)
        self.assertFalse((self.cwd/'queue-calls.jsonl').exists())
    def test_mcp_eof_does_not_cancel_worker(self):
        requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}},
                  {'jsonrpc':'2.0','method':'notifications/initialized'},
                  {'jsonrpc':'2.0','id':2,'method':'tools/list'},
                  {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'subchat_start','arguments':{
                      'cwd':str(self.cwd),'prompt':'DELAY','parent_thread':self.parent,'request_key':'mcp-start'}}},
                  {'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'subchat_cancel','arguments':{}}}]
        proc=subprocess.run([sys.executable,'-m','codex_subchats','--state',str(self.store.root),'mcp'],
                            input='\n'.join(map(json.dumps,requests))+'\n',capture_output=True,text=True,timeout=5)
        self.assertEqual(proc.returncode,0,proc.stderr)
        replies=[json.loads(l) for l in proc.stdout.splitlines()]
        self.assertEqual(len(replies),4); self.assertEqual(len(replies[1]['result']['tools']),5)
        self.assertTrue(replies[3]['result']['isError'])
        run=json.loads(replies[2]['result']['content'][0]['text'])
        self.assertEqual(self.await_run(run['id'],True)['status'],'completed')

if __name__=='__main__': unittest.main()
