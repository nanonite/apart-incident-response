"""Single researcher event stream, protected against ordinary update/delete operations."""
import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class EventStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
                    batch_id TEXT NOT NULL, run_id TEXT, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
                  BEGIN SELECT RAISE(ABORT, 'append-only events'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
                  BEGIN SELECT RAISE(ABORT, 'append-only events'); END;
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=20)

    def append(self, batch_id, kind, payload, run_id=None):
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            last = db.execute('SELECT hash FROM events ORDER BY seq DESC LIMIT 1').fetchone()
            previous = last[0] if last else '0' * 64
            event = dict(schema_version='1.0', event_id=uuid.uuid4().hex, batch_id=batch_id,
                         run_id=run_id, kind=kind, timestamp=now(), payload=payload)
            encoded = canonical(event)
            hashed = hashlib.sha256((previous + encoded).encode()).hexdigest()
            seq = db.execute('INSERT INTO events(event_id,batch_id,run_id,kind,payload,previous_hash,hash) VALUES (?,?,?,?,?,?,?)',
                             (event['event_id'], batch_id, run_id, kind, encoded, previous, hashed)).lastrowid
            return dict(event, seq=seq, previous_hash=previous, hash=hashed)

    def read(self, batch_id=None):
        with self.connect() as db:
            if batch_id is None:
                rows = db.execute('SELECT seq,payload,previous_hash,hash FROM events ORDER BY seq').fetchall()
            else:
                rows = db.execute('SELECT seq,payload,previous_hash,hash FROM events WHERE batch_id=? ORDER BY seq', (batch_id,)).fetchall()
        return [dict(json.loads(payload), seq=seq, previous_hash=previous, hash=hashed) for seq, payload, previous, hashed in rows]

    def verify(self):
        previous = '0' * 64
        for event in self.read():
            material = {k: v for k, v in event.items() if k not in ('seq', 'hash', 'previous_hash')}
            if event['previous_hash'] != previous or event['hash'] != hashlib.sha256((previous + canonical(material)).encode()).hexdigest():
                return False
            previous = event['hash']
        return True
