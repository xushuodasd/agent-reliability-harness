"""Durable local budget state machine. No HTTP or credential integration."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path


MAX_INTEGER = 2**63 - 1


class LedgerError(ValueError):
    """Budget denied, conflicting replay, or invalid persistent state."""


def _integer(value, *, positive=False):
    if type(value) is not int or not (int(positive) <= value <= MAX_INTEGER):
        raise LedgerError('expected bounded nonnegative integer' if not positive else 'expected bounded positive integer')


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value):
        raise LedgerError('expected opaque ASCII identifier, at most 128 characters')


def _config(config):
    if (not isinstance(config, dict) or set(config) != {'schema_version', 'plan_sha256', 'max_tokens', 'max_nanousd'}
            or config['schema_version'] != 'pilot-budget-ledger/1'
            or not isinstance(config['plan_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', config['plan_sha256'])):
        raise LedgerError('invalid ledger configuration')
    _integer(config['max_tokens'], positive=True)
    _integer(config['max_nanousd'], positive=True)
    return config


def _totals(requests, config):
    used_tokens = used_cost = held_tokens = held_cost = 0
    blocked = False
    for item in requests.values():
        if item['status'] == 'settled':
            used_tokens += item['actual_tokens']
            used_cost += item['actual_nanousd']
            blocked |= item['actual_tokens'] > item['tokens'] or item['actual_nanousd'] > item['nanousd']
        else:
            held_tokens += item['tokens']
            held_cost += item['nanousd']
            blocked |= item['status'] == 'unknown'
    return {'used_tokens': used_tokens, 'used_nanousd': used_cost,
            'held_tokens': held_tokens, 'held_nanousd': held_cost, 'blocked': blocked,
            'remaining_tokens': max(0, config['max_tokens'] - used_tokens - held_tokens),
            'remaining_nanousd': max(0, config['max_nanousd'] - used_cost - held_cost)}


def _apply(requests, config, event):
    """Apply one validated transition; False denotes an identical non-authorizing replay."""
    if not isinstance(event, dict):
        raise LedgerError('event must be an object')
    kind = event.get('kind')
    keys = {'kind', 'request_id'}
    if kind == 'reserve':
        keys |= {'episode_id', 'operation', 'tokens', 'nanousd'}
    elif kind == 'settle':
        keys |= {'tokens', 'nanousd'}
    elif kind != 'unknown':
        raise LedgerError('unknown event kind')
    if set(event) != keys:
        raise LedgerError('invalid event fields')
    request_id = event['request_id']
    _identifier(request_id)
    if kind != 'unknown':
        _integer(event['tokens'])
        _integer(event['nanousd'])
    old = requests.get(request_id)
    if kind == 'reserve':
        _identifier(event['episode_id'])
        if event['operation'] not in ('action', 'preflight', 'fallback'):
            raise LedgerError('invalid request operation')
        declared = {key: value for key, value in event.items() if key != 'kind'}
        if old is not None:
            if any(old[key] != value for key, value in declared.items()):
                raise LedgerError('request identity was reused with different reservation')
            return False
        totals = _totals(requests, config)
        if (totals['blocked'] or event['tokens'] > totals['remaining_tokens']
                or event['nanousd'] > totals['remaining_nanousd']):
            raise LedgerError('budget blocked or insufficient')
        requests[request_id] = {**declared, 'status': 'pending', 'actual_tokens': None, 'actual_nanousd': None}
    else:
        if old is None:
            raise LedgerError('request was never reserved')
        if kind == 'unknown' and old['status'] == 'unknown':
            return False
        if kind == 'settle' and old['status'] == 'settled':
            if (old['actual_tokens'], old['actual_nanousd']) == (event['tokens'], event['nanousd']):
                return False
            raise LedgerError('conflicting settlement')
        if old['status'] != 'pending':
            raise LedgerError('request is already terminal')
        old['status'] = 'unknown' if kind == 'unknown' else 'settled'
        if kind == 'settle':
            old['actual_tokens'], old['actual_nanousd'] = event['tokens'], event['nanousd']
    return True


class BudgetLedger:
    """Single-host SQLite transactions; reopening never grants a send authorization."""

    def __init__(self, path: Path, plan_sha256: str):
        self.path, self.plan_sha256 = Path(path).resolve(), plan_sha256
        self.snapshot()  # mode=ro: a missing or corrupt ledger must not be recreated.

    @classmethod
    def create(cls, path: Path, plan_sha256: str, *, max_tokens: int, max_nanousd: int):
        config = _config({'schema_version': 'pilot-budget-ledger/1', 'plan_sha256': plan_sha256,
                          'max_tokens': max_tokens, 'max_nanousd': max_nanousd})
        path = Path(path)
        with path.open('xb'):
            pass
        db = sqlite3.connect(path)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('''
                CREATE TABLE config (id INTEGER PRIMARY KEY CHECK(id=1), record TEXT NOT NULL);
                CREATE TABLE events (sequence INTEGER PRIMARY KEY, record TEXT NOT NULL);
                CREATE TRIGGER config_no_update BEFORE UPDATE ON config
                    BEGIN SELECT RAISE(ABORT, 'immutable config'); END;
                CREATE TRIGGER config_no_delete BEFORE DELETE ON config
                    BEGIN SELECT RAISE(ABORT, 'immutable config'); END;
                CREATE TRIGGER events_no_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'append only'); END;
                CREATE TRIGGER events_no_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'append only'); END;
            ''')
            db.execute('INSERT INTO config VALUES (1, ?)', (json.dumps(config, sort_keys=True),))
            db.commit()
        finally:
            db.close()
        return cls(path, plan_sha256)

    @contextmanager
    def _connection(self, *, write=False):
        db = sqlite3.connect(self.path.as_uri() + ('?mode=rw' if write else '?mode=ro'),
                             uri=True, isolation_level=None, timeout=5)
        try:
            if write:
                db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _read(self, db):
        rows = db.execute('SELECT id, record FROM config').fetchall()
        if len(rows) != 1 or rows[0][0] != 1:
            raise LedgerError('missing or ambiguous configuration')
        config = _config(json.loads(rows[0][1]))
        if config['plan_sha256'] != self.plan_sha256:
            raise LedgerError('frozen plan hash differs')
        requests = {}
        count = 0
        for sequence, record in db.execute('SELECT sequence, record FROM events ORDER BY sequence'):
            count += 1
            if sequence != count or not _apply(requests, config, json.loads(record)):
                raise LedgerError('invalid or repeated persistent event')
        return config, requests, count

    def snapshot(self):
        with self._connection() as db:
            config, requests, count = self._read(db)
            return {'config': config, **_totals(requests, config),
                    'event_count': count, 'requests': list(requests.values())}

    def _record(self, event):
        with self._connection(write=True) as db:
            config, requests, count = self._read(db)
            changed = _apply(requests, config, event)
            if changed:
                db.execute('INSERT INTO events VALUES (?, ?)', (count + 1, json.dumps(event, sort_keys=True)))
            return changed

    def reserve(self, request_id, episode_id, operation, *, tokens, nanousd):
        return self._record({'kind': 'reserve', 'request_id': request_id, 'episode_id': episode_id,
                             'operation': operation, 'tokens': tokens, 'nanousd': nanousd})

    def settle(self, request_id, *, tokens, nanousd):
        return self._record({'kind': 'settle', 'request_id': request_id, 'tokens': tokens, 'nanousd': nanousd})

    def mark_unknown(self, request_id):
        return self._record({'kind': 'unknown', 'request_id': request_id})
