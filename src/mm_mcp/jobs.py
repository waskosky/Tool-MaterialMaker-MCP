"""Persistent bounded local jobs shared by browser and MCP processes.

A worker holds an OS lock for the entire native build. Cancellation is cooperative
and terminates the worker-owned subprocess; it never claims a running GPU shader
can be instantaneously interrupted inside an attached artist session.
"""
import json
import hashlib
from pathlib import Path
import sqlite3
from contextlib import contextmanager
import threading
import time
import uuid
from mm_mcp.core import ServiceError, canonical, file_lock, identifier

class JobQueue:
    def __init__(self, root, handler, max_pending=64):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'jobs.sqlite3'; self.handler=handler; self.max_pending=max_pending
        self.stop_event=threading.Event(); self.thread=None; self.start_lock=threading.Lock()
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, state TEXT, request TEXT,
                         result TEXT, cancel INTEGER, created REAL, updated REAL, request_hash TEXT)""")
    @contextmanager
    def _db(self,timeout=30):
        db=sqlite3.connect(self.path,timeout=timeout)
        db.row_factory=sqlite3.Row; db.execute('PRAGMA journal_mode=WAL')
        try:
            with db:
                yield db
        finally:
            db.close()
    def submit(self,request):
        return self.submit_many([request])[0]
    def submit_many(self,requests):
        """Validate a bounded batch, then admit all jobs in one queue transaction."""
        if not isinstance(requests,list) or not 1<=len(requests)<=32:
            raise ServiceError('JOB_LIMIT','Submit between 1 and 32 jobs together.')
        rows=[]; total=0
        for request in requests:
            if not isinstance(request,dict):
                raise ServiceError('REQUEST_TYPE','Job request must be an object.')
            raw=canonical(request); encoded=raw.encode(); total+=len(encoded)
            if total>8*1024*1024:
                raise ServiceError('JOB_LIMIT','Job batch exceeds 8 MiB.')
            job='j_'+uuid.uuid4().hex; now=time.time()
            rows.append((job,'queued',raw,None,0,now,now,hashlib.sha256(encoded).hexdigest()))
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            pending=db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
            if pending+len(rows)>self.max_pending:
                raise ServiceError('QUEUE_FULL','Local queue is full; finish or cancel work first.')
            db.executemany('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',rows)
        self.start()
        return [self.get(row[0]) for row in rows]
    def get(self,job_id):
        identifier(job_id,'job ID')
        with self._db() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        if row is None:
            raise ServiceError('JOB_NOT_FOUND','Job not found.')
        return {'ok':True,'job_id':job_id,'state':row['state'],'cancel_requested':bool(row['cancel']),
                'created':row['created'],'updated':row['updated'],
                'result':json.loads(row['result']) if row['result'] else None}
    def cancel(self,job_id):
        self.get(job_id)
        with self._db() as db:
            db.execute("UPDATE jobs SET cancel=1,state=CASE WHEN state='queued' THEN 'cancelled' ELSE state END,updated=? WHERE id=? AND state IN ('queued','running')",(time.time(),job_id))
        return self.get(job_id)
    def _cancelled(self,job_id):
        if self.stop_event.is_set():
            return True
        with self._db() as db:
            row=db.execute('SELECT cancel FROM jobs WHERE id=?',(job_id,)).fetchone()
            return row is None or bool(row[0])
    def start(self):
        with self.start_lock:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.thread=threading.Thread(target=self._loop,name='mm-material-worker',daemon=True)
            self.thread.start()
    def active(self):
        with self._db() as db:
            return db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running') LIMIT 1").fetchone() is not None
    @contextmanager
    def idle_transaction(self):
        """Keep idle inspection and reconfiguration atomic with all submissions.

        BEGIN IMMEDIATE also covers other JobQueue instances/processes sharing
        the workspace. Never hold this transaction for a render or a version probe.
        """
        with self._db(timeout=.05) as db:
            try:
                db.execute('BEGIN IMMEDIATE')
            except sqlite3.OperationalError as exc:
                raise ServiceError('SETUP_BUSY','Finish or cancel pending work before changing native settings.') from exc
            if db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running') LIMIT 1").fetchone():
                raise ServiceError('SETUP_BUSY','Finish or cancel pending work before changing native settings.')
            yield
    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=12)
    def run_one(self):
        with file_lock(self.root/'.worker.lock',timeout=.05):
            with self._db() as db:
                db.execute('BEGIN IMMEDIATE')
                # The global worker lock is held here. Any older running row belongs
                # to a worker that exited without recording completion.
                db.execute("UPDATE jobs SET state='failed', result=?,updated=? WHERE state='running'",
                           (canonical({'ok':False,'code':'INTERRUPTED','error':'Previous worker exited before completion; resubmit explicitly.'}),time.time()))
                row=db.execute("SELECT * FROM jobs WHERE state='queued' AND cancel=0 ORDER BY created LIMIT 1").fetchone()
                if row is None:
                    return False
                db.execute("UPDATE jobs SET state='running',updated=? WHERE id=?",(time.time(),row['id']))
            job=row['id']
            try:
                result=self.handler(json.loads(row['request']),cancel=lambda:self._cancelled(job))
                state='complete' if result.get('ok') else 'failed'
                if self._cancelled(job):
                    state='cancelled'; result={'ok':False,'code':'CANCELLED','error':'Job cancelled; any completed immutable build remains unselected.'}
            except ServiceError as exc:
                result=exc.result(); state='cancelled' if exc.code=='CANCELLED' else 'failed'
            except Exception as exc:
                result={'ok':False,'code':'WORKER_ERROR','error':str(exc)}; state='failed'
            with self._db() as db:
                db.execute('UPDATE jobs SET state=?,result=?,updated=? WHERE id=?',(state,canonical(result),time.time(),job))
            return True
    def _loop(self):
        while not self.stop_event.is_set():
            try:
                worked=self.run_one()
            except ServiceError as exc:
                if exc.code!='BUSY':
                    self.stop_event.set()
                worked=False
            except sqlite3.Error:
                worked=False
            if not worked:
                self.stop_event.wait(.25)
