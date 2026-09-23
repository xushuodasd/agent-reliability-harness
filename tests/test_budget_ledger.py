import tempfile
import json
import multiprocessing
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier
import unittest
from pathlib import Path

from pilot_harness.budget_ledger import BudgetLedger, LedgerError


def reserve_in_process(path, plan, request_id, barrier, results):
    ledger = BudgetLedger(Path(path), plan)
    barrier.wait(timeout=10)
    try:
        result = ledger.reserve(request_id, 'ep', 'action', tokens=6, nanousd=60)
    except LedgerError:
        result = 'denied'
    results.put(result)


class BudgetLedgerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'budget.sqlite3'
        self.plan = 'a' * 64

    def create(self):
        return BudgetLedger.create(self.path, self.plan, max_tokens=10, max_nanousd=100)

    def test_invalid_limits_and_units_are_rejected_without_changes(self):
        for value in (True, 0, -1, 1.5, '10', 2**63):
            with self.subTest(limit=value), self.assertRaises(LedgerError):
                BudgetLedger.create(self.path, self.plan, max_tokens=value, max_nanousd=100)
            self.assertFalse(self.path.exists())
        ledger = self.create()
        before = ledger.snapshot()
        for key in ('tokens', 'nanousd'):
            for value in (True, -1, 1.5, '1', 2**63):
                with self.subTest(key=key, value=value), self.assertRaises(LedgerError):
                    ledger.reserve('bad', 'ep', 'action', **{'tokens': 1, 'nanousd': 1, key: value})
        self.assertEqual(before, ledger.snapshot())

    def test_each_budget_dimension_is_enforced_atomically(self):
        ledger = self.create()
        ledger.reserve('a', 'ep', 'action', tokens=7, nanousd=20)
        for tokens, cost in ((4, 1), (1, 81)):
            with self.subTest(tokens=tokens, cost=cost), self.assertRaises(LedgerError):
                ledger.reserve('b', 'ep', 'fallback', tokens=tokens, nanousd=cost)
        self.assertEqual(ledger.snapshot()['event_count'], 1)
        self.assertTrue(ledger.reserve('b', 'ep', 'fallback', tokens=3, nanousd=80))
        self.assertEqual(ledger.snapshot()['remaining_tokens'], 0)
        self.assertEqual(ledger.snapshot()['remaining_nanousd'], 0)

    def test_conflicting_replays_and_terminal_rewrites_are_rejected(self):
        ledger = self.create()
        ledger.reserve('a', 'ep', 'action', tokens=4, nanousd=40)
        for episode, operation, tokens, cost in (('other', 'action', 4, 40), ('ep', 'fallback', 4, 40),
                                                ('ep', 'action', 5, 40), ('ep', 'action', 4, 41)):
            with self.subTest(episode=episode, operation=operation, tokens=tokens, cost=cost):
                with self.assertRaises(LedgerError):
                    ledger.reserve('a', episode, operation, tokens=tokens, nanousd=cost)
        ledger.settle('a', tokens=3, nanousd=30)
        with self.assertRaises(LedgerError):
            ledger.settle('a', tokens=2, nanousd=30)
        with self.assertRaises(LedgerError):
            ledger.mark_unknown('a')
        with self.assertRaises(LedgerError):
            ledger.settle('absent', tokens=0, nanousd=0)
        self.assertFalse(ledger.reserve('a', 'ep', 'action', tokens=4, nanousd=40))
        self.assertEqual(ledger.snapshot()['event_count'], 2)

    def test_overrun_is_recorded_and_permanently_blocks_new_reservations(self):
        for index, (tokens, cost) in enumerate(((7, 50), (5, 70))):
            ledger = BudgetLedger.create(self.path.with_name(str(index) + '.sqlite3'), self.plan,
                                         max_tokens=10, max_nanousd=100)
            ledger.reserve('a', 'ep', 'action', tokens=6, nanousd=60)
            self.assertTrue(ledger.settle('a', tokens=tokens, nanousd=cost))
            reopened = BudgetLedger(ledger.path, self.plan)
            self.assertTrue(reopened.snapshot()['blocked'])
            self.assertEqual(reopened.snapshot()['used_tokens'], tokens)
            self.assertEqual(reopened.snapshot()['used_nanousd'], cost)
            self.assertEqual(reopened.snapshot()['held_tokens'], 0)
            with self.assertRaises(LedgerError):
                reopened.reserve('b', 'ep', 'action', tokens=0, nanousd=0)

    def test_blocking_does_not_discard_already_inflight_settlement(self):
        ledger = self.create()
        ledger.reserve('a', 'ep', 'action', tokens=4, nanousd=40)
        ledger.reserve('b', 'ep', 'action', tokens=4, nanousd=40)
        ledger.mark_unknown('a')
        ledger.settle('b', tokens=2, nanousd=20)
        self.assertTrue(ledger.snapshot()['blocked'])
        self.assertEqual((ledger.snapshot()['used_tokens'], ledger.snapshot()['held_tokens']), (2, 4))
        with self.assertRaises(LedgerError):
            ledger.settle('a', tokens=0, nanousd=0)

    def test_concurrent_connections_cannot_double_spend_or_reauthorize_same_id(self):
        for shared_id in (False, True):
            path = self.path.with_name(str(shared_id) + '.sqlite3')
            BudgetLedger.create(path, self.plan, max_tokens=10, max_nanousd=100)
            barrier = Barrier(2)
            def reserve(index):
                ledger = BudgetLedger(path, self.plan)
                barrier.wait(timeout=10)
                try:
                    return ledger.reserve('same' if shared_id else str(index), 'ep', 'action', tokens=6, nanousd=60)
                except LedgerError:
                    return 'denied'
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(reserve, (1, 2)))
            self.assertCountEqual(results, [True, False if shared_id else 'denied'])
            state = BudgetLedger(path, self.plan).snapshot()
            self.assertEqual((state['held_tokens'], state['held_nanousd'], state['event_count']), (6, 60, 1))

    def test_process_exit_after_committed_reservation_does_not_reset_budget(self):
        self.create()
        code = ('import os,sys; from pathlib import Path; from pilot_harness.budget_ledger import BudgetLedger; '
                'b=BudgetLedger(Path(sys.argv[1]),sys.argv[2]); '
                "assert b.reserve('a','ep','preflight',tokens=10,nanousd=100); os._exit(9)")
        result = subprocess.run([sys.executable, '-c', code, str(self.path), self.plan],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 9, result.stderr)
        ledger = BudgetLedger(self.path, self.plan)
        self.assertFalse(ledger.reserve('a', 'ep', 'preflight', tokens=10, nanousd=100))
        self.assertEqual(ledger.snapshot()['remaining_tokens'], 0)

    def test_independent_processes_compete_for_one_remaining_reservation(self):
        self.create()
        context = multiprocessing.get_context('spawn')
        barrier, results = context.Barrier(2), context.Queue()
        children = [context.Process(target=reserve_in_process,
                    args=(str(self.path), self.plan, str(index), barrier, results)) for index in (1, 2)]
        started = []
        try:
            for child in children:
                child.start()
                started.append(child)
            for child in started:
                child.join(timeout=20)
                self.assertEqual(child.exitcode, 0)
            self.assertCountEqual([results.get(timeout=5), results.get(timeout=5)], [True, 'denied'])
            state = BudgetLedger(self.path, self.plan).snapshot()
            self.assertEqual((state['held_tokens'], state['held_nanousd'], state['event_count']), (6, 60, 1))
        finally:
            for child in started:
                if child.is_alive():
                    child.terminate()
                child.join(timeout=5)
                child.close()
            results.close()
            results.join_thread()

    def test_missing_wrong_plan_and_existing_file_are_not_recreated(self):
        with self.assertRaises(sqlite3.OperationalError):
            BudgetLedger(self.path, self.plan)
        self.assertFalse(self.path.exists())
        ledger = self.create()
        before = self.path.read_bytes()
        with self.assertRaises(LedgerError):
            BudgetLedger(self.path, 'b' * 64)
        with self.assertRaises(FileExistsError):
            BudgetLedger.create(self.path, self.plan, max_tokens=20, max_nanousd=200)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(ledger.snapshot()['event_count'], 0)

    def test_append_only_constraints_and_invalid_injected_event_fail_closed(self):
        ledger = self.create()
        ledger.reserve('a', 'ep', 'action', tokens=1, nanousd=1)
        with closing(sqlite3.connect(self.path)) as db, db:
            for table in ('events', 'config'):
                for sql in (f'DELETE FROM {table}', f'UPDATE {table} SET record=record'):
                    with self.assertRaises(sqlite3.IntegrityError):
                        db.execute(sql)
            db.execute('INSERT INTO events VALUES (2, ?)', (json.dumps({'kind': 'unknown', 'request_id': 'absent'}),))
        with self.assertRaises(LedgerError):
            ledger.snapshot()
        with self.assertRaises(LedgerError):
            ledger.reserve('new', 'ep', 'action', tokens=1, nanousd=1)

    def test_snapshot_is_readonly_and_does_not_treat_pending_as_spent_zero(self):
        ledger = self.create()
        ledger.reserve('a', 'ep', 'action', tokens=4, nanousd=40)
        before = {path.name: path.read_bytes() for path in self.path.parent.iterdir()}
        state = ledger.snapshot()
        self.assertEqual(state['used_tokens'], 0)
        self.assertEqual(state['held_tokens'], 4)
        self.assertIsNone(state['requests'][0]['actual_tokens'])
        self.assertEqual(state['requests'][0]['status'], 'pending')
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.path.parent.iterdir()})

    def test_reservation_settlement_and_unknown_survive_reopen_without_replay(self):
        ledger = BudgetLedger.create(self.path, self.plan, max_tokens=10, max_nanousd=100)
        self.assertTrue(ledger.reserve('r1', 'episode-1', 'action', tokens=6, nanousd=60))
        ledger = BudgetLedger(self.path, self.plan)
        self.assertFalse(ledger.reserve('r1', 'episode-1', 'action', tokens=6, nanousd=60))
        self.assertEqual(ledger.snapshot()['held_tokens'], 6)
        with self.assertRaises(LedgerError):
            ledger.reserve('r2', 'episode-2', 'action', tokens=5, nanousd=30)
        self.assertTrue(ledger.settle('r1', tokens=4, nanousd=30))
        self.assertFalse(ledger.settle('r1', tokens=4, nanousd=30))
        ledger = BudgetLedger(self.path, self.plan)
        snapshot = ledger.snapshot()
        self.assertEqual((snapshot['used_tokens'], snapshot['used_nanousd']), (4, 30))
        self.assertEqual((snapshot['remaining_tokens'], snapshot['remaining_nanousd']), (6, 70))
        self.assertTrue(ledger.reserve('r2', 'episode-2', 'fallback', tokens=6, nanousd=60))
        self.assertTrue(ledger.mark_unknown('r2'))
        self.assertFalse(ledger.mark_unknown('r2'))
        ledger = BudgetLedger(self.path, self.plan)
        snapshot = ledger.snapshot()
        self.assertTrue(snapshot['blocked'])
        self.assertEqual((snapshot['held_tokens'], snapshot['held_nanousd']), (6, 60))
        self.assertEqual(snapshot['event_count'], 4)
        with self.assertRaises(LedgerError):
            ledger.reserve('r3', 'episode-3', 'preflight', tokens=0, nanousd=0)


if __name__ == '__main__':
    unittest.main()
