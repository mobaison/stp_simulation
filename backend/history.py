"""A disk-backed recorder for one local simulation server."""
import csv
import io
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from itertools import chain
from pathlib import Path
from uuid import uuid4

from engine import FIELDS


def now():
    return datetime.now(timezone.utc).isoformat()


class Recorder:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.active = None
        with self.db() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, started TEXT, updated TEXT, status TEXT, summary TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS steps (session TEXT REFERENCES sessions(id) ON DELETE CASCADE, n INTEGER, payload TEXT, PRIMARY KEY(session,n))')
            db.execute("UPDATE sessions SET status='interrupted' WHERE status='active'")
        self.count = self.events = 0
        self.previous = set()

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def append(self, state, controls):
        key = self.active or uuid4().hex
        alerts = set(state['alerts'])
        new = sorted(alerts - self.previous)
        step = {'time_s': state['time_s'], 'controls': controls, 'new_alerts': new,
                'snapshot': {k: v for k, v in state.items() if k != 'history'}}
        count = self.count + 1
        summary = dict(total_steps=count, total_simulated_seconds=state['time_s'],
                       total_energy_kwh=state['energy_kwh'], final_effluent=state['effluent_quality'],
                       effluent_basis='discharge',
                       total_alerts_triggered=self.events + len(new))
        stamp = now()
        with self.db() as db:
            if not self.active:
                db.execute("INSERT INTO sessions VALUES (?,?,?,'active','{}')", (key, stamp, stamp))
            db.execute('INSERT INTO steps VALUES (?,?,?)', (key, count, json.dumps(step)))
            db.execute('UPDATE sessions SET updated=?,summary=? WHERE id=?', (stamp, json.dumps(summary), key))
        self.active, self.count, self.previous = key, count, alerts
        self.events += len(new)

    def finish(self):
        if self.active:
            with self.db() as db:
                db.execute("UPDATE sessions SET status='complete',updated=? WHERE id=?", (now(), self.active))
            self.active = None
            self.count = self.events = 0
            self.previous.clear()

    def sessions(self, key=None):
        query = "SELECT * FROM sessions WHERE status!='active'"
        with self.db() as db:
            rows = db.execute(query + (' AND id=?' if key else '') + ' ORDER BY updated DESC', (key,) if key else ())
            return [dict(session_id=i, started_at=s, ended_at=e, status=status, **json.loads(summary))
                    for i, s, e, status, summary in rows]

    def steps(self, key):
        with self.db() as db:
            for row, in db.execute('SELECT payload FROM steps WHERE session=? ORDER BY n', (key,)):
                yield json.loads(row)

    def delete(self, key):
        with self.db() as db:
            return db.execute("DELETE FROM sessions WHERE id=? AND status!='active'", (key,)).rowcount


def csv_lines(steps):
    def flat(step):
        snap = step['snapshot']
        row = {'time_s': step['time_s'], 'energy_kwh': snap['energy_kwh'], 'treated_flow_gpm': snap['flows_gpm'].get('treated_out', 0),
               'alerts': ' | '.join(snap['alerts']), 'new_alerts': ' | '.join(step['new_alerts'])}
        quality = snap.get('effluent_quality', {})
        row.update({k+'_mg_L': quality.get(k) for k in FIELDS})
        row.update({'control_'+k: v for k, v in step['controls'].items()})
        row.update({k+'_level_pct': v['pct'] for k, v in snap['tanks'].items()})
        row.update({'tmp_'+str(k)+'_kPa': v for k, v in snap['membrane_tmp_kpa'].items()})
        return row
    first = next(steps, None)
    if first is None:
        return
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(flat(first)))
    writer.writeheader()
    for step in chain([first], steps):
        writer.writerow(flat(step))
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate()
