"""Purpose: Client contract tests on a loopback fake server: key handling, https rule, retries, validation, redaction, budget, fake provider."""

import json
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

from jev_screen.client import (
    FakeJev,
    JevClient,
    JevConfigError,
    JevError,
    JevHTTPError,
    JevResponseError,
    RateLimiter,
    estimate_cost_usd,
    estimate_tokens,
    request_key,
)
from tests.helpers import ScriptedJevServer, noul_payload

QUESTIONS = {"population": {"type": "noul", "instructions": "The study population consists of adults"}}
STATE = {"title": "A study", "abstract": "Adults were studied."}


def make_client(server, **kwargs):
    kwargs.setdefault("sleep", lambda s: None)
    return JevClient("test-key-abc", endpoint=server.endpoint, **kwargs)


class ConfigTest(unittest.TestCase):
    def test_requires_key(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            with self.assertRaises(JevConfigError) as ctx:
                JevClient()
        self.assertIn("Set TYPESAFE_API_KEY", str(ctx.exception))

    def test_https_only_except_loopback(self):
        JevClient("k", endpoint="http://127.0.0.1:1/x")
        JevClient("k", endpoint="http://localhost:1/x")
        JevClient("k", endpoint="https://api.typesafe.ai/v1/systemone")
        with self.assertRaises(JevConfigError):
            JevClient("k", endpoint="http://example.com/v1/systemone")

    def test_repr_hides_key(self):
        self.assertNotIn("secret", repr(JevClient("secret", endpoint="https://api.typesafe.ai/v1/systemone")))


class HttpTest(unittest.TestCase):
    def test_success_sends_bearer_and_pinned_model(self):
        with ScriptedJevServer() as server:
            server.responses.append((200, {}, noul_payload("jev-1.13.0", QUESTIONS, 0.42, tokens=1000)))
            result = make_client(server).ask(STATE, QUESTIONS)
        self.assertEqual(result.answers["population"]["noul"], 0.42)
        self.assertEqual(result.input_tokens, 1000)
        self.assertAlmostEqual(result.estimated_cost_usd, 1000 * 0.042 / 1e6)
        sent = server.requests[0]
        self.assertEqual(sent["authorization"], "Bearer test-key-abc")
        self.assertEqual(sent["body"]["model"], "jev-1.13.0")
        self.assertEqual(sent["body"]["state"], STATE)

    def test_retries_on_429_and_529_then_succeeds(self):
        with ScriptedJevServer() as server:
            server.responses.append((429, {"Retry-After": "0"}, {"error": "slow down"}))
            server.responses.append((529, {}, {"error": "overloaded"}))
            server.responses.append((200, {}, noul_payload("jev-1.13.0", QUESTIONS)))
            client = make_client(server, max_retries=2)
            result = client.ask(STATE, QUESTIONS)
        self.assertEqual(result.answers["population"]["noul"], 0.9)
        self.assertEqual(len(server.requests), 3)

    def test_retries_are_bounded(self):
        with ScriptedJevServer() as server:
            server.responses.extend([(429, {}, {}), (429, {}, {})])
            with self.assertRaises(JevHTTPError) as ctx:
                make_client(server, max_retries=1).ask(STATE, QUESTIONS)
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(len(server.requests), 2)

    def test_other_4xx_and_500_are_not_retried(self):
        for status in (400, 401, 422, 500):
            with self.subTest(status=status), ScriptedJevServer() as server:
                server.responses.append((status, {}, {"error": f"status {status}"}))
                with self.assertRaises(JevHTTPError) as ctx:
                    make_client(server).ask(STATE, QUESTIONS)
                self.assertEqual(ctx.exception.status, status)
                self.assertEqual(len(server.requests), 1)

    def test_network_error_retried_then_raised_with_redaction(self):
        calls = []

        def opener(request, timeout):
            calls.append(request.get_header("Authorization"))
            raise urllib.error.URLError("boom with test-key-abc inside")

        client = JevClient("test-key-abc", endpoint="https://api.typesafe.ai/v1/systemone", opener=opener, max_retries=1, sleep=lambda s: None)
        with self.assertRaises(JevError) as ctx:
            client.ask(STATE, QUESTIONS)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("test-key-abc", str(ctx.exception))
        self.assertIn("[redacted]", str(ctx.exception))

    def test_error_body_is_redacted(self):
        with ScriptedJevServer() as server:
            server.responses.append((401, {}, {"error": "bad key test-key-abc"}))
            with self.assertRaises(JevHTTPError) as ctx:
                make_client(server).ask(STATE, QUESTIONS)
        self.assertNotIn("test-key-abc", str(ctx.exception))

    def test_validation_rejects_bad_payloads(self):
        good = noul_payload("jev-1.13.0", QUESTIONS)
        bad_cases = {
            "model mismatch": {**good, "model": "jev-latest"},
            "missing answer": {**good, "answers": {}},
            "wrong type": {**good, "answers": {"population": {"type": "choice", "choice": "x"}}},
            "probability > 1": {**good, "answers": {"population": {"type": "noul", "noul": 1.2}}},
            "probability string": {**good, "answers": {"population": {"type": "noul", "noul": "0.5"}}},
            "no usage": {"model": "jev-1.13.0", "answers": good["answers"]},
            "not json": b"<html>oops</html>",
            "not an object": [1, 2, 3],
        }
        for name, payload in bad_cases.items():
            with self.subTest(case=name), ScriptedJevServer() as server:
                server.responses.append((200, {}, payload))
                with self.assertRaises(JevResponseError):
                    make_client(server).ask(STATE, QUESTIONS)

    def test_state_budget_refuses_before_sending(self):
        with ScriptedJevServer() as server:
            client = make_client(server, state_token_budget=10)
            with self.assertRaises(JevError):
                client.ask({"title": "x" * 200}, QUESTIONS)
        self.assertEqual(server.requests, [])

    def test_redirects_are_refused(self):
        with ScriptedJevServer() as server:
            server.responses.append((302, {"Location": "http://127.0.0.1:1/elsewhere"}, {}))
            with self.assertRaises(JevHTTPError) as ctx:
                make_client(server).ask(STATE, QUESTIONS)
        self.assertEqual(ctx.exception.status, 302)


class HelpersTest(unittest.TestCase):
    def test_token_and_cost_estimates(self):
        self.assertEqual(estimate_tokens("abcd" * 10), 10)
        self.assertEqual(estimate_tokens(""), 1)
        self.assertAlmostEqual(estimate_cost_usd(1_000_000), 0.042)

    def test_request_key_is_canonical(self):
        a = request_key("m", {"b": 1, "a": 2}, {"q": {"type": "noul"}})
        b = request_key("m", {"a": 2, "b": 1}, {"q": {"type": "noul"}})
        c = request_key("m", {"a": 2, "b": 1}, {"q": {"type": "noul", "instructions": "x"}})
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(len(a), 64)

    def test_rate_limiter_waits_when_window_full(self):
        clock = [0.0]
        slept = []
        limiter = RateLimiter(2, clock=lambda: clock[0], sleep=lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s)))
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()  # third call must wait for the 60 s window
        self.assertTrue(slept and slept[0] >= 59.0)


class FakeJevTest(unittest.TestCase):
    def test_answers_from_fixture_and_records_calls(self):
        fake = FakeJev({"records": {"A study": {"population": 0.8}}})
        result = fake.ask(STATE, QUESTIONS)
        self.assertEqual(result.answers["population"]["noul"], 0.8)
        self.assertEqual(result.model, "jev-1.13.0")
        self.assertGreater(result.input_tokens, 0)
        self.assertEqual(len(fake.calls), 1)

    def test_default_and_missing(self):
        fake = FakeJev({"records": {}, "default": {"population": 0.5}})
        self.assertEqual(fake.ask(STATE, QUESTIONS).answers["population"]["noul"], 0.5)
        with self.assertRaises(JevError):
            FakeJev({"records": {}}).ask(STATE, QUESTIONS)
        with self.assertRaises(JevError):
            FakeJev({"records": {}}).ask(STATE, {"q": {"type": "choice", "criteria": {"a": None}}})

    def test_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"records": {}}, handle)
            self.assertIsInstance(FakeJev.load(path), FakeJev)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump([], handle)
            with self.assertRaises(JevError):
                FakeJev.load(path)


if __name__ == "__main__":
    unittest.main()
