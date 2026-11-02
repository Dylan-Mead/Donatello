import json
import unittest

from donatello.assistant import benchmark
from donatello.providers import FallbackProvider, ModelResponse, ProviderError


class StubProvider:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    def complete(self, messages, json_response=False):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


class FallbackProviderTests(unittest.TestCase):
    def test_uses_fallback_when_primary_fails(self):
        primary = StubProvider(error=ProviderError("offline"))
        fallback = StubProvider(ModelResponse('{"ok":true}', "external", 0.1))
        result = FallbackProvider(primary, fallback).complete([], json_response=True)
        self.assertEqual(json.loads(result.text), {"ok": True})
        self.assertEqual(fallback.calls, 1)

    def test_uses_fallback_for_invalid_json(self):
        primary = StubProvider(ModelResponse("not JSON", "local", 0.1))
        fallback = StubProvider(ModelResponse('{"ok":true}', "external", 0.1))
        result = FallbackProvider(primary, fallback).complete([], json_response=True)
        self.assertEqual(json.loads(result.text), {"ok": True})
        self.assertEqual(fallback.calls, 1)


class BenchmarkTests(unittest.TestCase):
    def test_records_latency_and_json_response_quality(self):
        response = ModelResponse('{"answer":"42"}', "qwen", 0.25, 10, 4)
        results = benchmark(lambda model: StubProvider(response), ["qwen"], "prompt")
        self.assertEqual(results[0]["model"], "qwen")
        self.assertEqual(results[0]["seconds"], 0.25)
        self.assertEqual(results[0]["prompt_tokens"], 10)
        self.assertTrue(results[0]["valid_response"])


if __name__ == "__main__":
    unittest.main()
