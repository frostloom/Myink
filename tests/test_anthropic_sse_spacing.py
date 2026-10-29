"""Anthropic SSE compatibility regressions; also runnable with unittest."""
from __future__ import annotations

from contextlib import ExitStack
import json
import unittest
from unittest.mock import Mock, patch

import httpx

import myink.providers.anthropic as module
from myink.providers.anthropic import AnthropicProvider


class AnthropicSSESpacingTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.permit = Mock()
        self.permit.remaining_seconds.return_value = 120.0
        self.stack.enter_context(patch.object(module, "MAX_RETRIES", 0))
        self.stack.enter_context(patch.object(module, "reserve_attempt", return_value=self.permit))
        self.stack.enter_context(patch.object(module, "budget_stream", side_effect=lambda permit, stream: stream))
        self.stack.enter_context(patch.object(module, "budget_iter", side_effect=lambda permit, items: items))
        self.finish = self.stack.enter_context(patch.object(module, "finish_attempt"))

    def events(self):
        return [
            {"type": "message_start", "message": {"usage": {"input_tokens": 12}}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "first"}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "second"}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 8}},
            {"type": "message_stop"},
        ]

    def generate(self, events, prefixes):
        body = ": keepalive\n\n" + "\n\n".join(
            prefixes[index % len(prefixes)] + json.dumps(event)
            for index, event in enumerate(events)
        ) + "\n\n"
        provider = AnthropicProvider(api_key="offline-test", base_url="https://offline.invalid")
        provider._client.close()
        provider._client = httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)
        ))
        self.addCleanup(provider._client.close)
        deltas = []
        result = provider.generate_stream(
            [{"role": "user", "content": "offline"}], model_id="offline", on_delta=deltas.append,
        )
        return result, deltas

    def assert_success(self, prefixes):
        result, deltas = self.generate(self.events(), prefixes)
        self.assertIsNone(result.error)
        self.assertEqual(deltas, ["first", "second"])
        self.assertEqual(result.content, "firstsecond")
        self.assertEqual((result.input_tokens, result.output_tokens), (12, 8))
        receipt = self.finish.call_args.args[1]
        self.assertTrue(receipt.usage_complete)
        self.assertEqual((receipt.input_tokens, receipt.output_tokens), (12, 8))

    def test_no_space_events_complete_with_budget_and_usage(self):
        self.assert_success(["data:"])

    def test_spaced_events_remain_supported(self):
        self.assert_success(["data: "])

    def test_mixed_spacing_remains_supported(self):
        self.assert_success(["data:", "data: "])

    def test_missing_message_stop_still_fails(self):
        for prefix in ("data:", "data: "):
            with self.subTest(prefix=prefix):
                result, _ = self.generate(self.events()[:-1], [prefix])
                self.assertEqual(result.error, "Anthropic stream ended without message_stop")
                self.assertEqual(result.content, "")
                self.assertEqual(self.finish.call_args.args, (self.permit,))

    def test_no_space_error_event_is_reported(self):
        result, _ = self.generate([
            {"type": "error", "error": {"type": "overloaded_error", "message": "upstream overloaded"}}
        ], ["data:"])
        self.assertEqual(result.error, "upstream overloaded")
        self.assertEqual(self.finish.call_args.args, (self.permit,))

    def test_no_space_tool_arguments_are_preserved(self):
        result, _ = self.generate([
            self.events()[0],
            {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "call-1", "name": "lookup"}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"chapter": 2}'}},
            self.events()[-2], self.events()[-1],
        ], ["data:"])
        self.assertIsNone(result.error)
        self.assertEqual(result.tool_calls, [{"id": "call-1", "name": "lookup", "arguments": {"chapter": 2}}])


if __name__ == "__main__":
    unittest.main()
