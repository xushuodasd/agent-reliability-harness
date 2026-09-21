import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pilot_harness.dispatch_adapter import DispatchTaskSpec
from pilot_harness.reservation_adapter import ReservationTaskSpec
from pilot_harness.manifests import write_manifest
from pilot_harness.models import Action, Observation
from pilot_harness.audit import RESERVED_FIELDS, verify_chain
from pilot_harness.logging import JsonlLogger
from pilot_harness.scripted_comparison import RecoveryPolicy
from pilot_harness import scripted_comparison as comparison
from pilot_harness.unified_engine import UnifiedEpisodeEngine


class RecoveryPolicyTests(unittest.TestCase):
    def test_errors_stop_without_false_completion_or_unbounded_retries(self):
        task = SimpleNamespace(family='dispatch', instruction=DispatchTaskSpec().public_instruction())
        for policy in ('retry_once', 'query_then_retry'):
            for history in (
                [(Action('dispatch'), Observation(False, None, 'authentication_error'))],
                [(Action('dispatch'), Observation(False, None, 'injected timeout'))] * 2,
                [(Action('dispatch'), Observation(True, {'status': 'unexpected'}))],
                [(Action('lookup'), Observation(True, {'found': True, 'payload': 'wrong'}))],
            ):
                with self.subTest(policy=policy, history=history):
                    with self.assertRaises(RuntimeError):
                        RecoveryPolicy(policy).next_action(task, history)

    def test_complete_presaved_plan_and_readonly_sealed_comparison(self):
        original = UnifiedEpisodeEngine.run
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'comparison'
            def checked_run(engine, task, provider, **kwargs):
                plan = json.loads((output / 'plan.json').read_text())
                self.assertEqual(len(plan['cells']), 36)
                self.assertEqual((task.max_attempts, task.max_steps), (4, 6))
                return original(engine, task, provider, **kwargs)
            with patch.object(UnifiedEpisodeEngine, 'run', checked_run):
                summary = comparison.run_comparison(output)
            self.assertEqual(len(summary['rows']), 36)
            self.assertEqual(summary['independent_task_structures'], 2)
            self.assertTrue(all(row['outcome'] == 'PASS' for row in summary['rows']))
            self.assertEqual(sum(row['local_score']['duplicate_effects'] for row in summary['rows'][:24]), 3)
            self.assertEqual(sum(row['local_score']['outstanding_held_units'] for row in summary['rows'][24:]), 1)
            before = {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob('*') if p.is_file()}
            verified = comparison.verify_comparison(output)
            self.assertTrue(verified['valid'], verified['errors'])
            self.assertEqual(verified['summary'], summary)
            after = {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            with self.assertRaises(FileExistsError):
                comparison.run_comparison(output)

    def test_matched_after_commit_recovery(self):
        cases = [
            (DispatchTaskSpec(), 'retry_once', 'duplicate_effects', 1, 2),
            (DispatchTaskSpec(), 'query_then_retry', 'duplicate_effects', 0, 2),
            (DispatchTaskSpec(visibility='lagged_once'), 'query_then_retry', 'duplicate_effects', 1, 3),
            (ReservationTaskSpec(max_attempts=4, max_steps=6), 'retry_once', 'duplicate_reservations', 1, 3),
            (ReservationTaskSpec(max_attempts=4, max_steps=6), 'query_then_retry', 'duplicate_reservations', 0, 3),
        ]
        with tempfile.TemporaryDirectory() as directory:
            engine = UnifiedEpisodeEngine(Path(directory))
            for index, (task, policy, field, expected, attempts) in enumerate(cases):
                with self.subTest(index=index):
                    result = engine.run(task, RecoveryPolicy(policy), fault='timeout_committed_once', episode_id=str(index))
                    receipt = json.loads((Path(result.artifact_dir) / (result.family + '-effects.json')).read_text())
                    self.assertEqual(result.score['outcome'], 'PASS')
                    self.assertTrue(receipt['score']['goal_completed'])
                    self.assertEqual(receipt['score'][field], expected)
                    self.assertEqual(receipt['counters']['tool_attempts'], attempts)


class ComparisonBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.fixture = Path(cls.temporary.name) / 'sealed'
        comparison.run_comparison(cls.fixture)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / 'copy'
        shutil.copytree(self.fixture, self.output)

    def assert_rejected(self):
        result = comparison.verify_comparison(self.output)
        self.assertFalse(result['valid'])
        self.assertIsNone(result['summary'])
        self.assertTrue(result['errors'])

    def test_changed_summary_is_rejected_even_after_resealing(self):
        path = self.output / 'summary.json'
        summary = json.loads(path.read_text())
        summary['rows'][0]['local_score']['goal_completed'] = 1  # bool != int in canonical evidence
        path.write_text(json.dumps(summary))
        write_manifest(self.output)
        self.assert_rejected()

    def test_changed_budget_plan_is_rejected_even_after_resealing(self):
        path = self.output / 'plan.json'
        plan = json.loads(path.read_text())
        plan['cells'][0]['task']['max_attempts'] = 5
        path.write_text(json.dumps(plan))
        write_manifest(self.output)
        self.assert_rejected()

    def test_omitted_cell_is_not_removed_from_denominator_by_resealing(self):
        shutil.rmtree(self.output / 'episodes' / 'cell-000')
        write_manifest(self.output)
        self.assert_rejected()

    def test_missing_receipt_and_unexpected_episode_are_rejected(self):
        (self.output / 'episodes' / 'cell-000' / 'dispatch-effects.json').unlink()
        (self.output / 'episodes' / 'extra-cell').mkdir()
        write_manifest(self.output)
        self.assert_rejected()

    def test_changed_planned_fault_is_rejected(self):
        path = self.output / 'plan.json'
        plan = json.loads(path.read_text())
        plan['cells'][0]['condition'] = 'timeout_once'
        path.write_text(json.dumps(plan))
        write_manifest(self.output)
        self.assert_rejected()

    def test_nonobject_plan_fails_closed_without_raising(self):
        for value in ([], None):
            with self.subTest(value=value):
                (self.output / 'plan.json').write_text(json.dumps(value))
                self.assert_rejected()

    def test_nonobject_event_and_checkpoint_fail_closed_after_resealing(self):
        folder = self.output / 'episodes' / 'cell-000'
        for name in ('events.jsonl', 'events.jsonl.head.json', 'chain.json'):
            path = folder / name
            original = path.read_bytes()
            with self.subTest(name=name):
                path.write_text('[]\n')
                write_manifest(folder, metadata=json.loads((self.fixture / 'episodes' / 'cell-000' / 'manifest.json').read_text())['metadata'])
                write_manifest(self.output)
                self.assert_rejected()
            path.write_bytes(original)

    def test_nested_null_contract_is_rejected_even_with_valid_rebuilt_chain(self):
        folder = self.output / 'episodes' / 'cell-000'
        path = folder / 'events.jsonl'
        events = [json.loads(line) for line in path.read_text().splitlines()]
        next(event for event in events if event['event'] == 'episode_start')['contract'] = None
        path.unlink()
        path.with_name(path.name + '.head.json').unlink()
        logger = JsonlLogger(path)
        for event in events:
            logger.write({key: value for key, value in event.items() if key not in RESERVED_FIELDS})
        chain = verify_chain(path)
        self.assertTrue(chain.valid)
        (folder / 'chain.json').write_text(json.dumps(chain.__dict__))
        metadata = json.loads((folder / 'manifest.json').read_text())['metadata']
        write_manifest(folder, metadata=metadata)
        write_manifest(self.output)
        self.assert_rejected()

    def test_nonobject_chain_summary_fails_closed_after_resealing(self):
        folder = self.output / 'episodes' / 'cell-000'
        (folder / 'chain.json').write_text('[]')
        metadata = json.loads((folder / 'manifest.json').read_text())['metadata']
        write_manifest(folder, metadata=metadata)
        write_manifest(self.output)
        self.assert_rejected()

    def test_runtime_failure_is_retained_and_does_not_skip_later_cells(self):
        original = UnifiedEpisodeEngine.run
        output = self.output.parent / 'failed-run'
        def failed_run(engine, task, provider, **kwargs):
            if kwargs['episode_id'] == 'cell-000':
                raise OSError('synthetic fixture infrastructure failure')
            return original(engine, task, provider, **kwargs)
        with patch.object(UnifiedEpisodeEngine, 'run', failed_run):
            summary = comparison.run_comparison(output)
        self.assertEqual(len(summary['rows']), 36)
        self.assertIsNone(summary['rows'][0]['local_score'])
        self.assertTrue(summary['rows'][0]['errors'])
        self.assertEqual(summary['rows'][35]['outcome'], 'PASS')
        self.assertEqual(json.loads((output / 'execution-errors.json').read_text()), {'cell-000': 'OSError'})
        self.assertIsNone(comparison.verify_comparison(output)['summary'])

    def test_valid_unknown_is_retained_in_verified_summary(self):
        original = RecoveryPolicy.next_action
        output = self.output.parent / 'unknown-run'
        def stopped(policy, task, history):
            if task.family == 'reservation' and len(history) == 1:
                raise RuntimeError('synthetic fixture policy failure')
            return original(policy, task, history)
        with patch.object(RecoveryPolicy, 'next_action', stopped):
            summary = comparison.run_comparison(output)
        self.assertEqual(len(summary['rows']), 36)
        self.assertEqual(sum(row['outcome'] == 'UNKNOWN' for row in summary['rows']), 12)
        self.assertEqual(summary['rows'][24]['local_score']['outstanding_held_units'], 1)
        self.assertEqual(summary['rows'][24]['local_score']['report_status'], 'NOT_REPORTED')
        result = comparison.verify_comparison(output)
        self.assertTrue(result['valid'], result['errors'])
        self.assertEqual(result['summary'], summary)


if __name__ == '__main__':
    unittest.main()
