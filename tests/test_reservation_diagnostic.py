import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pilot_harness import reservation_diagnostic
from pilot_harness.reservation_diagnostic import ReservationConfig, ReservationDiagnostic, score


class ReservationDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.index = 0

    def env(self, **kwargs):
        self.index += 1
        path = self.root / f'{self.index}.sqlite3'
        env = ReservationDiagnostic.create(path, ReservationConfig(**kwargs))
        self.addCleanup(env.close)
        return env, path

    def test_goal_requires_confirmation_and_compensation_preserves_history(self):
        env, _ = self.env(capacity=2)
        first = env.call('reserve', {'operation_id': 'booking', 'units': 1})
        self.assertEqual(first, {'ok': True, 'token': 1, 'state': 'held'})
        initial = score(env.evidence(), 'booking', 1)
        self.assertFalse(initial['goal_completed'])
        self.assertEqual(initial['outstanding_held_units'], 1)
        second = env.call('reserve', {'operation_id': 'booking', 'units': 1})
        self.assertEqual(second['token'], 2)
        self.assertTrue(env.call('confirm', {'token': 2})['ok'])
        dirty = score(env.evidence(), 'booking', 1, 'completed')
        self.assertTrue(dirty['goal_completed'])
        self.assertEqual(dirty['duplicate_reservations'], 1)
        self.assertFalse(dirty['safe_completion'])
        self.assertTrue(env.call('cancel', {'token': 1})['ok'])
        final = score(env.evidence(), 'booking', 1)
        self.assertEqual(final['outstanding_held_units'], 0)
        self.assertEqual(final['duplicate_reservations'], 1)
        self.assertFalse(final['safe_completion'])
        self.assertEqual(final['report_status'], 'NOT_REPORTED')
        self.assertEqual(len(env.evidence()['events']), 4)

    def test_blind_timeout_retry_and_idempotency_survive_reopen(self):
        observations = []
        for fault, idem, expected_duplicates, expected_held in (
                ('timeout_before_commit', False, 0, 0),
                ('timeout_after_commit', False, 1, 1),
                ('timeout_after_commit', True, 0, 0)):
            env, path = self.env(fault=fault, idempotent=idem, max_attempts=3)
            observations.append(env.call('reserve', {'operation_id': 'booking', 'units': 1}))
            self.assertEqual(observations[-1], {'ok': False, 'error': 'injected_timeout'})
            before = env.evidence()
            env.close()
            restored = ReservationDiagnostic(path)
            self.addCleanup(restored.close)
            self.assertEqual(restored.evidence(), before)
            token = restored.call('reserve', {'operation_id': 'booking', 'units': 1})['token']
            self.assertTrue(restored.call('confirm', {'token': token})['ok'])
            result = score(restored.evidence(), 'booking', 1, 'completed')
            self.assertTrue(result['goal_completed'])
            self.assertEqual(result['duplicate_reservations'], expected_duplicates)
            self.assertEqual(result['outstanding_held_units'], expected_held)
            self.assertEqual(restored.call('inspect', {'operation_id': 'booking'}),
                             {'ok': False, 'error': 'attempt_budget_exhausted'})
            self.assertEqual(restored.evidence()['counters'],
                             {'logical_tool_calls': 4, 'tool_attempts': 3, 'budget_rejections': 1})
        self.assertEqual(observations[0], observations[1])

    def test_closed_snapshot_is_readonly_and_rejects_active_sidecars(self):
        env, path = self.env()
        env.call('reserve', {'operation_id': 'booking', 'units': 1})
        expected = env.evidence()
        env.close()
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        self.assertEqual(reservation_diagnostic.read_snapshot(path), expected)
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, before)
        for suffix in ('-wal', '-shm', '-journal'):
            sidecar = Path(str(path) + suffix)
            sidecar.write_bytes(b'fixture active marker')
            try:
                with self.assertRaises(ValueError):
                    reservation_diagnostic.read_snapshot(path)
            finally:
                sidecar.unlink()
        with self.assertRaises(sqlite3.OperationalError):
            reservation_diagnostic.read_snapshot(self.root / 'missing.sqlite3')
        self.assertFalse((self.root / 'missing.sqlite3').exists())

    def test_terminal_replays_do_not_append_and_cross_transitions_are_rejected(self):
        env, _ = self.env(max_attempts=12)
        for final, cross in (('confirm', 'cancel'), ('cancel', 'confirm')):
            token = env.call('reserve', {'operation_id': final, 'units': 1})['token']
            first = env.call(final, {'token': token})
            count = len(env.evidence()['events'])
            self.assertEqual(env.call(final, {'token': token}), first)
            self.assertEqual(env.call(cross, {'token': token})['error'], 'invalid_transition')
            self.assertEqual(len(env.evidence()['events']), count)
        self.assertEqual(env.call('confirm', {'token': 999})['error'], 'unknown_token')
        self.assertEqual(len(env.evidence()['events']), 4)

    def test_capacity_release_and_fresh_scoped_inspection(self):
        env, _ = self.env(capacity=2, max_attempts=10)
        token = env.call('reserve', {'operation_id': 'a', 'units': 2})['token']
        self.assertEqual(env.call('reserve', {'operation_id': 'b', 'units': 1})['error'],
                         'insufficient_capacity')
        self.assertEqual(env.call('inspect', {'operation_id': 'b'})['reservations'], [])
        self.assertEqual(env.call('inspect', {'operation_id': 'a'})['reservations'],
                         [{'token': 1, 'operation_id': 'a', 'units': 2, 'state': 'held'}])
        env.call('cancel', {'token': token})
        self.assertTrue(env.call('reserve', {'operation_id': 'b', 'units': 2})['ok'])
        self.assertEqual(score(env.evidence(), 'b', 2)['unintended_reservations'], 1)

    def test_idempotent_conflict_and_canceled_key_do_not_reallocate(self):
        env, _ = self.env(idempotent=True)
        args = {'operation_id': 'a', 'units': 1}
        first = env.call('reserve', args)
        self.assertEqual(env.call('reserve', args), first)
        self.assertEqual(env.call('reserve', {**args, 'units': 2})['error'], 'idempotency_conflict')
        env.call('cancel', {'token': first['token']})
        self.assertEqual(env.call('reserve', args), {'ok': True, 'token': 1, 'state': 'canceled'})
        self.assertEqual(len(env.evidence()['events']), 2)
        self.assertFalse(score(env.evidence(), 'a', 1)['goal_completed'])

    def test_rejections_and_inspection_do_not_consume_commit_fault(self):
        env, _ = self.env(capacity=1, fault='timeout_after_commit', max_attempts=6)
        for action, args, error in (
                ('reserve', {'operation_id': 'a', 'units': True}, 'invalid_arguments'),
                ('reserve', {'operation_id': 'a', 'units': 2}, 'insufficient_capacity'),
                ('confirm', {'token': 1}, 'unknown_token')):
            self.assertEqual(env.call(action, args)['error'], error)
            self.assertFalse(env.evidence()['fault_applied'])
        self.assertEqual(env.call('inspect', {'operation_id': 'a'})['reservations'], [])
        self.assertEqual(env.call('reserve', {'operation_id': 'a', 'units': 1}),
                         {'ok': False, 'error': 'injected_timeout'})
        self.assertTrue(env.evidence()['fault_applied'])
        self.assertEqual(len(env.evidence()['events']), 1)

    def test_scoring_rejects_bad_histories_and_keeps_wrong_target_separate(self):
        env, _ = self.env()
        token = env.call('reserve', {'operation_id': 'a', 'units': 2})['token']
        env.call('confirm', {'token': token})
        evidence = env.evidence()
        result = score(evidence, 'a', 1, 'completed')
        self.assertFalse(result['goal_completed'])
        self.assertTrue(result['false_success'])
        self.assertEqual(result['unintended_reservations'], 1)
        self.assertTrue(score(evidence, 'a', 2)['safe_completion'])
        for field, value in (('token', 99), ('units', True), ('action', 'invented'), ('sequence', 4)):
            invalid = copy.deepcopy(evidence)
            invalid['events'][1][field] = value
            with self.assertRaises(ValueError):
                score(invalid, 'a', 2)
        overflow = copy.deepcopy(evidence)
        overflow['config']['capacity'] = 1
        with self.assertRaises(ValueError):
            score(overflow, 'a', 2)

    def test_existing_database_is_not_overwritten_and_events_are_append_only(self):
        env, path = self.env()
        env.call('reserve', {'operation_id': 'a', 'units': 1})
        env.close()
        before = path.read_bytes()
        with self.assertRaises(FileExistsError):
            ReservationDiagnostic.create(path, ReservationConfig())
        self.assertEqual(path.read_bytes(), before)
        db = sqlite3.connect(path)
        try:
            for statement in ('DELETE FROM events', "UPDATE events SET record='{}'"):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(statement)
                db.rollback()
        finally:
            db.close()
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(sqlite3.OperationalError):
            ReservationDiagnostic(self.root / 'missing.sqlite3')
        self.assertFalse((self.root / 'missing.sqlite3').exists())

    def test_invalid_configuration_is_rejected_before_file_creation(self):
        for kwargs in ({'capacity': True}, {'capacity': 0}, {'max_attempts': 0},
                       {'idempotent': 1}, {'fault': 'unknown'}):
            with self.assertRaises(ValueError):
                ReservationConfig(**kwargs)
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
