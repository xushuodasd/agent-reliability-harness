import json
import os
import unittest
import urllib.error
from decimal import Inexact, localcontext
from unittest.mock import patch

from pilot_harness.models import Task
from pilot_harness.provider_http import (
    EpisodeBudgetExceeded, HttpResponse, OpenAICompatibleProvider, _parse_action_content,
)


class ProviderHttpTests(unittest.TestCase):
    task = Task("t", "write", "answer.txt", "ok")

    def test_malformed_usage_cannot_bypass_token_budget(self):
        usages = [
            {'total_tokens': '6'}, {'total_tokens': 6.0}, {'total_tokens': True},
            {'total_tokens': -1}, {'prompt_tokens': True, 'completion_tokens': 2},
            {'prompt_tokens': -1, 'completion_tokens': 2, 'total_tokens': 1},
            {'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 1},
            {'prompt_tokens': 3, 'total_tokens': 2},
        ]
        for usage in usages:
            response = {'choices': [{'message': {'content': '{"kind":"finish"}'}}], 'usage': usage}
            provider = OpenAICompatibleProvider('http://example.invalid/v1', 'm', max_episode_tokens=5,
                transport=lambda *_, value=response: json.dumps(value).encode())
            with self.subTest(usage=usage), patch.dict(os.environ, {'AGENT_PILOT_API_KEY': 'fixture'}):
                with self.assertRaises(EpisodeBudgetExceeded):
                    provider.next_action(self.task, [])
                self.assertIsNone(provider.call_metadata[-1].total_tokens)

    def test_unknown_usage_preserves_subtotal_and_blocks_further_episode_requests(self):
        calls = []
        usages = iter([{'prompt_tokens': 1, 'completion_tokens': 1},
                       {'total_tokens': 'unknown'}, {'prompt_tokens': 1, 'completion_tokens': 1}])
        def transport(*_):
            calls.append(1)
            return json.dumps({'choices': [{'message': {'content': '{"kind":"finish"}'}}],
                               'usage': next(usages)}).encode()
        provider = OpenAICompatibleProvider('http://example.invalid/v1', 'm', transport=transport,
            max_episode_tokens=10, input_cost_per_million_usd=1, output_cost_per_million_usd=1)
        with patch.dict(os.environ, {'AGENT_PILOT_API_KEY': 'fixture'}):
            provider.next_action(self.task, [])
            with self.assertRaises(EpisodeBudgetExceeded):
                provider.next_action(self.task, [])
            usage = provider.episode_usage()
            self.assertIsNone(usage['total_tokens'])
            self.assertIsNone(usage['cost_usd'])
            self.assertEqual(usage['known_tokens'], 2)
            self.assertEqual(usage['known_cost_usd'], 0.000002)
            self.assertFalse(usage['tokens_complete'])
            self.assertFalse(usage['cost_complete'])
            with self.assertRaises(EpisodeBudgetExceeded):
                provider.next_action(self.task, [])
            self.assertEqual(len(calls), 2)
            provider.begin_episode()
            provider.next_action(self.task, [])
            self.assertEqual(provider.episode_usage()['total_tokens'], 2)
            self.assertEqual(provider.episode_usage()['calls'], 1)

    def test_nonfinite_and_noninteger_budget_configuration_is_rejected(self):
        for name in ('max_output_tokens', 'max_episode_tokens', 'max_episode_cost_usd',
                     'input_cost_per_million_usd', 'output_cost_per_million_usd'):
            bad = [True, '5', float('nan'), float('inf'), -1]
            if name in ('max_output_tokens', 'max_episode_tokens'):
                bad.extend([1.5, 0])
            elif name == 'max_episode_cost_usd':
                bad.append(0)
            for value in bad:
                config = {'input_cost_per_million_usd': 1, 'output_cost_per_million_usd': 1, name: value}
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ValueError):
                        OpenAICompatibleProvider('http://example.invalid/v1', 'm', **config)

    def test_cost_overflow_is_unknown_and_latched_not_infinite_or_free(self):
        for tokens, requests in ((2_000_000, 1), (1_000_000, 2), (10**309, 1)):
            calls = []
            def transport(*_):
                calls.append(1)
                return json.dumps({'choices': [{'message': {'content': '{"kind":"finish"}'}}],
                                   'usage': {'prompt_tokens': tokens, 'completion_tokens': 0}}).encode()
            provider = OpenAICompatibleProvider('http://example.invalid/v1', 'm', transport=transport,
                max_episode_cost_usd=1e308, input_cost_per_million_usd=1e308, output_cost_per_million_usd=0)
            with self.subTest(tokens=tokens, requests=requests), patch.dict(os.environ, {'AGENT_PILOT_API_KEY': 'fixture'}):
                for _ in range(requests - 1):
                    provider.next_action(self.task, [])
                    self.assertEqual(provider.call_metadata[-1].cost_usd, 1e308)
                with self.assertRaises(EpisodeBudgetExceeded):
                    provider.next_action(self.task, [])
                usage = provider.episode_usage()
                self.assertIsNone(usage['cost_usd'])
                self.assertFalse(usage['cost_complete'])
                self.assertEqual(usage['total_tokens'], tokens * requests)
                json.dumps(usage, allow_nan=False)
                with self.assertRaises(EpisodeBudgetExceeded):
                    provider.next_action(self.task, [])
                self.assertEqual(len(calls), requests)

    def test_cost_budget_is_independent_of_callers_decimal_context(self):
        response = {'choices': [{'message': {'content': '{"kind":"finish"}'}}],
                    'usage': {'prompt_tokens': 123, 'completion_tokens': 0}}
        for trap in (False, True):
            provider = OpenAICompatibleProvider('http://example.invalid/v1', 'm',
                transport=lambda *_: json.dumps(response).encode(), max_episode_cost_usd=0.000122,
                input_cost_per_million_usd=1, output_cost_per_million_usd=1)
            with self.subTest(trap=trap), localcontext() as context, patch.dict(os.environ, {'AGENT_PILOT_API_KEY': 'fixture'}):
                context.prec = 2
                context.traps[Inexact] = trap
                with self.assertRaises(EpisodeBudgetExceeded):
                    provider.next_action(self.task, [])
                self.assertEqual(provider.episode_usage()['cost_usd'], 0.000123)

    def test_minimax_think_wrapper_is_removed_before_action_parse(self):
        item = _parse_action_content(
            '<think>private reasoning with {braces}</think>\n'
            '{"kind":"write_file","arguments":{"path":"a.txt","content":"ok"}}'
        )
        self.assertEqual(item["kind"], "write_file")

    def test_incomplete_action_json_is_rejected(self):
        with self.assertRaises(json.JSONDecodeError):
            _parse_action_content('<think>x</think>{"kind":')

    def test_key_is_sent_but_not_retained_or_exposed_in_name(self):
        captured = {}

        def transport(request, timeout):
            captured["authorization"] = request.headers["Authorization"]
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return json.dumps({"choices": [{"message": {"content": '{"kind":"finish","arguments":{}}'}}]}).encode()

        provider = OpenAICompatibleProvider("http://example.invalid/v1", "model-x", transport=transport)
        with patch.dict(os.environ, {"AGENT_PILOT_API_KEY": "secret-value"}):
            action = provider.next_action(self.task, [])
        self.assertEqual(action.kind, "finish")
        self.assertEqual(captured["authorization"], "Bearer secret-value")
        self.assertNotIn("secret-value", provider.name)
        self.assertNotIn("secret-value", repr(provider.__dict__))

    def test_missing_key_fails_before_transport(self):
        provider = OpenAICompatibleProvider(
            "http://example.invalid/v1", "model-x", transport=lambda *_: self.fail("called")
        )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "missing API key"):
                provider.next_action(self.task, [])

    def test_disallowed_action_is_rejected(self):
        response = json.dumps({"choices": [{"message": {"content": '{"kind":"shell","arguments":{}}'}}]}).encode()
        provider = OpenAICompatibleProvider("http://example.invalid/v1", "model-x", transport=lambda *_: response)
        with patch.dict(os.environ, {"AGENT_PILOT_API_KEY": "x"}):
            with self.assertRaisesRegex(RuntimeError, "disallowed"):
                provider.next_action(self.task, [])

    def test_scaffold_is_named_and_included_in_request(self):
        captured = {}

        def transport(request, _timeout):
            captured.update(json.loads(request.data.decode("utf-8")))
            return json.dumps({"choices": [{"message": {"content": '{"kind":"finish","arguments":{}}'}}]}).encode()

        provider = OpenAICompatibleProvider(
            "http://example.invalid/v1", "model-x", scaffold="verified", transport=transport
        )
        with patch.dict(os.environ, {"AGENT_PILOT_API_KEY": "x"}):
            provider.next_action(self.task, [])
        self.assertTrue(provider.name.endswith(":verified"))
        self.assertIn('"scaffold": "verified"', captured["messages"][1]["content"])

    def test_unknown_scaffold_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "scaffold"):
            OpenAICompatibleProvider("http://example.invalid/v1", "model-x", scaffold="unknown")

    def test_auto_json_mode_falls_back_only_for_compatibility_error(self):
        bodies = []
        def transport(request, _timeout):
            body = json.loads(request.data.decode("utf-8"))
            bodies.append(body)
            if len(bodies) == 1:
                raise urllib.error.HTTPError(request.full_url, 400, "unsupported", {}, None)
            return json.dumps({"choices": [{"message": {"content": '{"kind":"finish"}'}}],
                               "usage": {"prompt_tokens": 3, "completion_tokens": 2}}).encode()
        provider = OpenAICompatibleProvider("http://example.invalid/v1", "m", transport=transport)
        with patch.dict(os.environ, {"AGENT_PILOT_API_KEY": "x"}):
            provider.next_action(self.task, [])
        self.assertIn("response_format", bodies[0])
        self.assertNotIn("response_format", bodies[1])
        self.assertEqual(provider.call_metadata[-1].total_tokens, 5)
        self.assertFalse(provider.call_metadata[-1].json_mode)

    def test_auto_json_mode_does_not_mask_auth_error(self):
        calls = []
        def transport(request, _timeout):
            calls.append(request)
            raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, None)
        provider = OpenAICompatibleProvider("http://example.invalid/v1", "m", transport=transport)
        with patch.dict(os.environ, {"AGENT_PILOT_API_KEY": "x"}):
            with self.assertRaises(urllib.error.HTTPError): provider.next_action(self.task, [])
        self.assertEqual(len(calls), 1)

    def test_usage_request_id_latency_and_cost_are_metered_without_secret(self):
        response = {"choices": [{"message": {"content": '{"kind":"finish"}'}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
        provider = OpenAICompatibleProvider("http://example.invalid/v1", "m",
            input_cost_per_million_usd=2, output_cost_per_million_usd=5,
            transport=lambda *_: HttpResponse(json.dumps(response).encode(), headers={"X-Request-ID": "req-7"}))
        provider.begin_episode()
        with patch.dict(os.environ, {"AGENT_PILOT_API_KEY": "do-not-record"}): provider.next_action(self.task, [])
        meta = provider.call_metadata[-1]
        self.assertEqual((meta.request_id, meta.total_tokens, meta.cost_usd), ("req-7", 120, 0.0003))
        self.assertGreaterEqual(meta.latency_ms, 0)
        self.assertNotIn("do-not-record", repr(meta))
        self.assertEqual(provider.episode_usage()["calls"], 1)

    def test_episode_token_budget_fails_closed_when_exceeded_or_usage_missing(self):
        responses = [
            {"choices": [{"message": {"content": '{"kind":"finish"}'}}], "usage": {"total_tokens": 6}},
            {"choices": [{"message": {"content": '{"kind":"finish"}'}}]},
        ]
        for response in responses:
            provider = OpenAICompatibleProvider("http://example.invalid/v1", "m", max_episode_tokens=5,
                transport=lambda *_, value=response: json.dumps(value).encode())
            provider.begin_episode()
            with self.subTest(response=response), patch.dict(os.environ, {"AGENT_PILOT_API_KEY": "x"}):
                with self.assertRaises(EpisodeBudgetExceeded): provider.next_action(self.task, [])

    def test_episode_cost_budget_requires_pricing_and_stops_overrun(self):
        with self.assertRaisesRegex(ValueError, "requires both"):
            OpenAICompatibleProvider("http://example.invalid/v1", "m", max_episode_cost_usd=.01)
        response = {"choices": [{"message": {"content": '{"kind":"finish"}'}}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 1000}}
        provider = OpenAICompatibleProvider("http://example.invalid/v1", "m",
            max_episode_cost_usd=.001, input_cost_per_million_usd=1,
            output_cost_per_million_usd=1, transport=lambda *_: json.dumps(response).encode())
        provider.begin_episode()
        with patch.dict(os.environ, {"AGENT_PILOT_API_KEY": "x"}):
            with self.assertRaisesRegex(EpisodeBudgetExceeded, "cost"):
                provider.next_action(self.task, [])

    def test_models_and_minimal_chat_preflight_use_expected_methods(self):
        requests = []
        def transport(request, _timeout):
            requests.append(request)
            if request.get_method() == "GET":
                return HttpResponse(b'{"data":[{"id":"model-x"}]}', headers={"request-id": "models-1"})
            return b'{"choices":[{"message":{"content":"OK"}}],"usage":{"total_tokens":2}}'
        provider = OpenAICompatibleProvider("http://example.invalid/v1", "model-x", transport=transport)
        with patch.dict(os.environ, {"AGENT_PILOT_API_KEY": "x"}):
            models = provider.preflight("models")
            chat = provider.preflight("chat")
        self.assertTrue(models["model_visible"])
        self.assertIsNone(chat["model_visible"])
        self.assertEqual([r.get_method() for r in requests], ["GET", "POST"])
        self.assertEqual(json.loads(requests[1].data)["max_tokens"], 2)

    def test_provider_echoing_credential_in_request_id_is_redacted(self):
        response = b'{"choices":[{"message":{"content":"{\\"kind\\":\\"finish\\"}"}}]}'
        provider = OpenAICompatibleProvider("http://example.invalid/v1", "m",
            transport=lambda *_: HttpResponse(response, headers={"x-request-id": "prefix-secret-x"}))
        provider.begin_episode()
        with patch.dict(os.environ, {"AGENT_PILOT_API_KEY": "secret"}): provider.next_action(self.task, [])
        self.assertEqual(provider.episode_usage()["requests"][0]["request_id"], "[redacted]")


if __name__ == "__main__":
    unittest.main()
