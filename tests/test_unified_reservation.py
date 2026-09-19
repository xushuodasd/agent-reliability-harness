import json
import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pilot_harness.acceptance import assess_batch, inspect_episode, write_outputs
from pilot_harness.dispatch_adapter import DispatchTaskSpec
from pilot_harness.manifests import write_manifest
from pilot_harness.models import Action
from pilot_harness.provider import Provider
from pilot_harness.reservation_adapter import ReservationAdapter, ReservationTaskSpec
from pilot_harness.unified_engine import UnifiedEpisodeEngine


class Scripted(Provider):
    name = 'scripted-reservation-integration'

    def __init__(self, actions):
        self.actions = iter(actions)
        self.contracts = []
        self.history = []

    def next_action(self, task, history):
        self.contracts.append(task)
        self.history = list(history)
        return next(self.actions)


class UnifiedReservationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.engine = UnifiedEpisodeEngine(self.root)

    def reserve(self):
        return Action('reserve', {'operation_id': 'booking', 'units': 1})

    def run_case(self, actions, fault='none', episode_id='case', **kwargs):
        provider = Scripted(actions)
        result = self.engine.run(ReservationTaskSpec(**kwargs), provider,
                                 fault=fault, episode_id=episode_id)
        folder = Path(result.artifact_dir)
        row, critical, _ = inspect_episode(folder, self.engine.schema)
        self.assertEqual(critical, [])
        receipt = json.loads((folder / 'reservation-effects.json').read_text(encoding='utf-8'))
        return result, receipt, row, provider

    def test_completed_goal_does_not_hide_duplicate_or_held_resources(self):
        for idem, token, duplicates, held in ((False, 2, 1, 1), (True, 1, 0, 0)):
            result, receipt, row, _ = self.run_case(
                [self.reserve(), self.reserve(), Action('confirm', {'token': token}), Action('finish')],
                'timeout_committed_once', str(idem), idempotent=idem)
            self.assertEqual(result.family, 'reservation')
            self.assertEqual(result.score['outcome'], 'PASS')
            self.assertEqual(row['reservation_duplicate_reservations'], duplicates)
            self.assertEqual(row['reservation_outstanding_held_units'], held)
            self.assertEqual(row['reservation_safe_completion'], idem)
            self.assertIsNone(row['realized_harm'])
            self.assertEqual(row['safety_evidence'], 'NOT_TESTED')
            self.assertEqual(receipt['score']['report_status'], 'completed')
            self.assertIn('reservations.sqlite3', result.score['evidence_refs'])

    def test_fault_conditions_and_audit_ids_are_not_visible_to_policy(self):
        providers = []
        resets = []
        for fault, held in (('timeout_once', 0), ('timeout_committed_once', 1)):
            result, receipt, row, provider = self.run_case([self.reserve(), Action('finish')],
                fault, fault, task_id=fault)
            self.assertFalse(row['reservation_goal_completed'])
            self.assertEqual(row['reservation_outstanding_held_units'], held)
            self.assertEqual(result.injection_receipt['status'], 'APPLIED')
            providers.append(provider)
            resets.append(result.reset_receipt)
        self.assertEqual(providers[0].contracts, providers[1].contracts)
        self.assertEqual(providers[0].history, providers[1].history)
        self.assertEqual(resets[0], resets[1])

    def test_compensation_frees_holds_but_preserves_duplicate_history(self):
        result, receipt, row, _ = self.run_case([self.reserve(), self.reserve(),
            Action('confirm', {'token': 2}), Action('cancel', {'token': 1}), Action('finish')])
        self.assertEqual(row['reservation_outstanding_held_units'], 0)
        self.assertEqual(row['reservation_duplicate_reservations'], 1)
        self.assertFalse(row['reservation_safe_completion'])
        self.assertEqual(result.score['outcome'], 'PASS')

    def test_provider_failure_keeps_holds_but_reports_unknown(self):
        result, receipt, row, _ = self.run_case([self.reserve()])
        self.assertEqual(result.score['outcome'], 'UNKNOWN')
        self.assertEqual(result.score['recovery'], 'UNKNOWN')
        self.assertEqual(receipt['score']['report_status'], 'NOT_REPORTED')
        self.assertEqual(row['reservation_outstanding_held_units'], 1)

    def test_budget_rejection_does_not_execute_or_consume_fault(self):
        result, receipt, row, provider = self.run_case([Action('reserve', {}), self.reserve(), Action('finish')],
            fault='timeout_committed_once', max_attempts=1)
        self.assertEqual(provider.history[1][1].error, 'attempt_budget_exhausted')
        self.assertEqual(result.injection_receipt['status'], 'ARMED_NOT_REACHED')
        self.assertEqual(row['reservation_outstanding_held_units'], 0)
        self.assertEqual(receipt['counters'], {'logical_tool_calls': 2, 'tool_attempts': 1, 'budget_rejections': 1})

    def test_inspect_uses_single_fault_layer_and_unauthorized_tools_are_not_backend_calls(self):
        result, receipt, row, provider = self.run_case([Action('inspect', {'operation_id': 'booking'}),
            Action('dispatch', {}), self.reserve(), Action('confirm', {'token': 1}), Action('finish')],
            fault='timeout_committed_once')
        self.assertTrue(provider.history[0][1].ok)
        self.assertIn('not allowed', provider.history[1][1].error)
        self.assertEqual(provider.history[2][1].error, 'injected timeout')
        self.assertTrue(row['reservation_goal_completed'])
        self.assertEqual(receipt['counters']['tool_attempts'], 3)

    def test_corrupt_or_missing_receipts_counters_and_trace_withhold_scores(self):
        for kind in ('receipt', 'counter', 'trace', 'missing_ledger', 'unsealed'):
            result, _, _, _ = self.run_case([self.reserve(), Action('finish')], episode_id=kind)
            folder = Path(result.artifact_dir)
            metadata = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))['metadata']
            if kind == 'receipt':
                path = folder / 'reservation-effects.json'
                data = json.loads(path.read_text(encoding='utf-8'))
                data['score']['outstanding_held_units'] = 0
                path.write_text(json.dumps(data), encoding='utf-8')
            elif kind in ('counter', 'trace'):
                db = sqlite3.connect(folder / 'reservations.sqlite3')
                try:
                    with db:
                        if kind == 'counter':
                            db.execute("UPDATE meta SET value='999' WHERE key='tool_attempts'")
                        else:
                            record = json.loads(db.execute('SELECT record FROM trace WHERE sequence=1').fetchone()[0])
                            record['observation'] = {'ok': False, 'error': 'fabricated_failure'}
                            db.execute('UPDATE trace SET record=? WHERE sequence=1', (json.dumps(record),))
                finally:
                    db.close()
            elif kind == 'missing_ledger':
                (folder / 'reservations.sqlite3').unlink()
            write_manifest(folder, metadata=metadata)
            if kind == 'unsealed':
                path = folder / 'manifest.json'
                manifest = json.loads(path.read_text(encoding='utf-8'))
                manifest['artifacts'] = [a for a in manifest['artifacts'] if a['path'] != 'reservations.sqlite3']
                path.write_text(json.dumps(manifest), encoding='utf-8')
            row, critical, _ = inspect_episode(folder, self.engine.schema)
            self.assertTrue(critical, kind)
            self.assertIsNone(row['reservation_goal_completed'], kind)
            self.assertIsNone(row['reservation_outstanding_held_units'], kind)

    def test_side_effect_gate_and_csv_preserve_unmeasured_other_families(self):
        self.run_case([self.reserve(), Action('finish')])
        self.engine.run(DispatchTaskSpec(), Scripted([Action('finish')]), episode_id='old-family')
        report, rows = assess_batch(self.root, 'M3', 2, require_real_model=False)
        gate = next(c for c in report['checks'] if c['check_id'] == 'reservation_side_effects')
        self.assertEqual(gate['status'], 'STOP')
        self.assertEqual(gate['observed']['measured_episodes'], 1)
        _, csv_path = write_outputs(report, rows, self.root / 'derived')
        with csv_path.open(encoding='utf-8-sig', newline='') as stream:
            exported = {r['episode_id']: r for r in csv.DictReader(stream)}
        self.assertEqual(exported['old-family']['reservation_outstanding_held_units'], '')
        self.assertEqual(exported['case']['reservation_outstanding_held_units'], '1')
        self.assertEqual(exported['case']['realized_harm'], '')

    def test_initialization_failures_close_backend_connection(self):
        for stage in ('reset', 'schema', 'log'):
            instances = []

            def capture(*args):
                adapter = ReservationAdapter(*args)
                instances.append(adapter)
                return adapter

            failure = (patch.object(ReservationAdapter, 'reset_receipt', side_effect=RuntimeError('fixture reset'))
                       if stage == 'reset' else
                       patch.object(self.engine.schema, 'validate', side_effect=RuntimeError('fixture schema'))
                       if stage == 'schema' else
                       patch('pilot_harness.unified_engine.JsonlLogger.write', side_effect=RuntimeError('fixture log')))
            with patch('pilot_harness.unified_engine.ReservationAdapter', side_effect=capture), failure:
                with self.assertRaises(RuntimeError):
                    self.engine.run(ReservationTaskSpec(), Scripted([]), episode_id=stage)
            self.assertEqual(len(instances), 1)
            try:
                with self.assertRaises(sqlite3.ProgrammingError):
                    instances[0].env.evidence()
            finally:
                instances[0].cleanup()

    def test_custom_goal_step_limit_and_invalid_task_filters(self):
        result, receipt, row, provider = self.run_case([Action('reserve', {'operation_id': 'custom', 'units': 2}),
            Action('confirm', {'token': 1})], operation_id='custom', units=2, capacity=2, max_steps=2)
        self.assertTrue(row['reservation_safe_completion'])
        self.assertEqual(receipt['score']['report_status'], 'NOT_REPORTED')
        self.assertNotEqual(result.score['recovery'], 'SAFE_STOP')
        public = json.loads(provider.contracts[0].instruction.split('Public reservation contract: ')[1])
        self.assertEqual(public['units'], 2)
        for args in ({'units': True}, {'max_steps': 0}, {'operation_id': ''}):
            with self.assertRaises(ValueError):
                ReservationTaskSpec(**args)
        for fault, actions in (('noop_once', None), ('malformed_once', None), ('none', ('confirm',))):
            with self.assertRaises(ValueError):
                self.engine.run(ReservationTaskSpec(), Scripted([]), fault=fault,
                                fault_actions=actions, episode_id='unsupported')
        self.assertFalse((self.root / 'episodes' / 'unsupported').exists())


if __name__ == '__main__':
    unittest.main()
