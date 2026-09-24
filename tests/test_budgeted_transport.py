import json
import io
import os
import sqlite3
import tempfile
import traceback
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from contextlib import closing
from decimal import Inexact, localcontext
from unittest.mock import patch

from pilot_harness.budget_ledger import BudgetLedger
from pilot_harness.budgeted_transport import AttemptBudget, BudgetedTransportError, send_budgeted
from pilot_harness.models import Task
from pilot_harness.provider_http import HttpResponse, OpenAICompatibleProvider


class BudgetedTransportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = BudgetLedger.create(Path(self.directory.name) / 'budget.db', 'a' * 64,
                                          max_tokens=100, max_nanousd=1000000)
        self.request = urllib.request.Request('https://offline.invalid/chat/completions',
                                              data=b'{}', method='POST')

    def send(self, transport, **overrides):
        options = dict(ledger=self.ledger, request_id='attempt-1', episode_id='episode-1',
                       operation='action', budget=AttemptBudget(10, '0.0001', '0.0002'),
                       transport=transport)
        options.update(overrides)
        return send_budgeted(self.request, 2.0, **options)

    def test_reserves_before_send_settles_exact_ceiling_and_never_replays(self):
        response = HttpResponse(json.dumps({'usage': {'prompt_tokens': 2,
                                                      'completion_tokens': 3}}).encode())
        calls = []

        def transport(request, timeout):
            snapshot = BudgetLedger(self.ledger.path, 'a' * 64).snapshot()
            self.assertEqual((snapshot['held_tokens'], snapshot['held_nanousd']), (10, 2))
            self.assertEqual(snapshot['requests'][0]['status'], 'pending')
            self.assertIs(request, self.request)
            self.assertEqual(timeout, 2.0)
            calls.append(request)
            return response

        self.assertIs(self.send(transport), response)
        snapshot = self.ledger.snapshot()
        self.assertEqual((snapshot['used_tokens'], snapshot['used_nanousd']), (5, 1))
        self.assertEqual((snapshot['held_tokens'], snapshot['held_nanousd']), (0, 0))
        with self.assertRaises(BudgetedTransportError):
            self.send(transport)
        self.assertEqual(len(calls), 1)

    def test_interrupt_preserves_unknown_hold_and_original_exit_signal(self):
        def transport(*_):
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            self.send(transport)
        snapshot = BudgetLedger(self.ledger.path, 'a' * 64).snapshot()
        self.assertEqual(snapshot['requests'][0]['status'], 'unknown')
        self.assertTrue(snapshot['blocked'])
        self.assertEqual(snapshot['held_tokens'], 10)

    def test_uncertain_attempt_holds_budget_blocks_next_send_and_redacts_errors(self):
        valid = b'{"usage":{"prompt_tokens":2,"completion_tokens":3}}'
        cases = [TimeoutError('private-provider-error'),
                 urllib.error.HTTPError('https://private.invalid', 422,
                                        'private-provider-error', {}, io.BytesIO(b'private-body')),
                 b'private-provider-error', b'[]', b'{}', b'{"usage":{"total_tokens":5}}',
                 b'{"usage":{"prompt_tokens":true,"completion_tokens":3}}',
                 b'{"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":1}}',
                 HttpResponse(valid, 500), HttpResponse(valid, True)]
        for index, outcome in enumerate(cases):
            ledger = BudgetLedger.create(Path(self.directory.name) / f'case-{index}.db', 'a' * 64,
                                          max_tokens=100, max_nanousd=1000000)
            calls = []

            def transport(*_):
                calls.append(1)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

            with self.subTest(index=index):
                with self.assertRaises(BudgetedTransportError) as raised:
                    self.send(transport, ledger=ledger)
                rendered = ''.join(traceback.format_exception(raised.exception))
                self.assertNotIn('private-provider-error', rendered)
                self.assertNotIn('private.invalid', rendered)
                snapshot = BudgetLedger(ledger.path, 'a' * 64).snapshot()
                self.assertTrue(snapshot['blocked'])
                self.assertEqual((snapshot['held_tokens'], snapshot['held_nanousd']), (10, 2))
                self.assertEqual(snapshot['requests'][0]['status'], 'unknown')
                with self.assertRaises(BudgetedTransportError):
                    self.send(transport, ledger=ledger, request_id='attempt-2')
                self.assertEqual(len(calls), 1)

    def test_invalid_admission_configuration_never_creates_a_reservation(self):
        for ceiling in (True, 0, -1, 1.5, '10', 2**63):
            with self.subTest(ceiling=ceiling), self.assertRaises(ValueError):
                AttemptBudget(ceiling, '1', '1')
        for rate in (None, True, 1, 0.5, '-1', 'NaN', 'inf', '1e2', '1/3', '', ' 1', '1' * 65):
            for field in (0, 1):
                rates = ['1', '1']
                rates[field] = rate
                with self.subTest(rate=rate, field=field), self.assertRaises(ValueError):
                    AttemptBudget(10, *rates)
        with self.assertRaises(ValueError):
            AttemptBudget(2**63 - 1, '1', '1')
        calls = []
        for timeout in (True, 0, -1, '2', float('nan'), float('inf'), 10**400):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                send_budgeted(self.request, timeout, ledger=self.ledger, request_id='bad',
                              episode_id='e', operation='action', budget=AttemptBudget(10, '0', '0'),
                              transport=lambda *_: calls.append(1))
        self.assertEqual(calls, [])
        self.assertEqual(self.ledger.snapshot()['event_count'], 0)

    def test_overrun_is_recorded_but_response_not_delivered_and_new_send_denied(self):
        calls = []

        def transport(*_):
            calls.append(1)
            return b'{"usage":{"prompt_tokens":0,"completion_tokens":11}}'

        with self.assertRaises(BudgetedTransportError):
            self.send(transport)
        snapshot = self.ledger.snapshot()
        self.assertTrue(snapshot['blocked'])
        self.assertEqual((snapshot['used_tokens'], snapshot['used_nanousd']), (11, 3))
        self.assertEqual(snapshot['requests'][0]['status'], 'settled')
        with self.assertRaises(BudgetedTransportError):
            self.send(transport, request_id='attempt-2')
        self.assertEqual(len(calls), 1)

    def test_insufficient_budget_denies_transport_in_both_dimensions(self):
        calls = []
        for budget in (AttemptBudget(101, '0', '0'), AttemptBudget(10, '101', '101')):
            with self.subTest(budget=budget), self.assertRaises(BudgetedTransportError):
                self.send(lambda *_: calls.append(1), budget=budget)
        self.assertEqual(calls, [])
        self.assertEqual(self.ledger.snapshot()['event_count'], 0)

    def test_operation_labels_and_zero_rates_are_explicit_and_cumulative(self):
        response = b'{"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}'
        for operation in ('preflight', 'action', 'fallback'):
            self.assertIs(self.send(lambda *_: response, request_id=operation, operation=operation,
                                    budget=AttemptBudget(10, '0', '0')), response)
        snapshot = self.ledger.snapshot()
        self.assertEqual((snapshot['used_tokens'], snapshot['used_nanousd']), (15, 0))
        self.assertEqual([r['operation'] for r in snapshot['requests']], ['preflight', 'action', 'fallback'])

    def test_exact_fraction_cost_does_not_depend_on_decimal_context(self):
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            response = b'{"usage":{"prompt_tokens":3,"completion_tokens":2}}'
            self.send(lambda *_: response, budget=AttemptBudget(10, '0.1234567', '0.7654321'))
        # 3 * 0.1234567 * 1000 + 2 * 0.7654321 * 1000 = 1901.2343 nano-USD.
        self.assertEqual(self.ledger.snapshot()['used_nanousd'], 1902)

    def test_http_error_cannot_trigger_provider_automatic_fallback(self):
        calls = []
        stream = io.BytesIO(b'private-response')

        def transport(*_):
            calls.append(1)
            raise urllib.error.HTTPError('https://offline.invalid', 422, 'private-response', {}, stream)

        provider = OpenAICompatibleProvider('https://offline.invalid', 'fixture-model', json_mode='auto',
            transport=lambda request, timeout: send_budgeted(request, timeout, ledger=self.ledger,
                request_id='attempt-1', episode_id='episode-1', operation='action',
                budget=AttemptBudget(10, '1', '1'), transport=transport))
        with patch.dict(os.environ, {'AGENT_PILOT_API_KEY': 'offline-fixture'}):
            with self.assertRaises(BudgetedTransportError):
                provider.next_action(Task('t', 'write', 'answer.txt', 'ok'), [])
        self.assertEqual(len(calls), 1)
        self.assertTrue(stream.closed)
        self.assertEqual(self.ledger.snapshot()['requests'][0]['status'], 'unknown')

    def test_http_error_cleanup_failure_cannot_override_safe_error(self):
        class FailingClose(io.BytesIO):
            def close(self):
                super().close()
                raise OSError('private-close-error')

        stream = FailingClose(b'private-response')

        def transport(*_):
            raise urllib.error.HTTPError('https://private.invalid', 422, 'private-error', {}, stream)

        with self.assertRaises(BudgetedTransportError) as raised:
            self.send(transport)
        rendered = ''.join(traceback.format_exception(raised.exception))
        self.assertNotIn('private-', rendered)
        self.assertNotIn('private.invalid', rendered)
        self.assertTrue(stream.closed)
        self.assertEqual(self.ledger.snapshot()['requests'][0]['status'], 'unknown')

    def test_storage_write_failure_never_delivers_response_or_releases_hold(self):
        # A storage-boundary fault fixture; the public snapshot remains readable.
        for unknown_also_fails in (False, True):
            ledger = BudgetLedger.create(Path(self.directory.name) / f'write-{unknown_also_fails}.db',
                                          'a' * 64, max_tokens=100, max_nanousd=1000000)

            def transport(*_):
                with closing(sqlite3.connect(ledger.path)) as db:
                    kinds = ('settle', 'unknown') if unknown_also_fails else ('settle',)
                    for kind in kinds:
                        db.execute(f'''CREATE TRIGGER reject_{kind} BEFORE INSERT ON events
                            WHEN NEW.record LIKE '%"kind": "{kind}"%'
                            BEGIN SELECT RAISE(ABORT, 'offline storage failure'); END''')
                    db.commit()
                return b'{"usage":{"prompt_tokens":2,"completion_tokens":3}}'

            with self.subTest(unknown_also_fails=unknown_also_fails):
                with self.assertRaises(BudgetedTransportError):
                    self.send(transport, ledger=ledger)
                snapshot = BudgetLedger(ledger.path, 'a' * 64).snapshot()
                self.assertEqual((snapshot['held_tokens'], snapshot['held_nanousd']), (10, 2))
                self.assertEqual(snapshot['used_tokens'], 0)
                self.assertEqual(snapshot['requests'][0]['status'],
                                 'pending' if unknown_also_fails else 'unknown')
                calls = []
                with self.assertRaises(BudgetedTransportError):
                    self.send(lambda *_: calls.append(1), ledger=ledger)
                self.assertEqual(calls, [])
