"""W12 slice 1: provider adapters against a fake local server."""
import unittest
import urllib.error
from unittest.mock import patch

from anonymizer import llm

from .llm_fake import TEST_KEY, FakeProvider

MSGS = [{"role": "user", "content": "Summarize Name1 and Company2"}]


def provider(kind, fake, model="m-one"):
    return llm.Provider(kind, fake.url, TEST_KEY, model)


class AdapterTests(unittest.TestCase):
    def run_kind(self, kind, stream=True):
        with FakeProvider(chunks=["Hel", "lo ", "Name1"]) as fake:
            text, usage = llm.complete(provider(kind, fake), MSGS, "be brief", 100, 5, stream=stream)
            return text, usage, fake.requests

    def test_streaming_all_kinds(self):
        for kind in llm.KINDS:
            text, usage, requests = self.run_kind(kind)
            self.assertEqual(text, "Hello Name1", kind)
            self.assertEqual(usage, {"input": 7, "output": 3}, kind)
            self.assertEqual(len(requests), 1, "exactly one request, no retry")

    def test_non_streaming_all_kinds(self):
        for kind in llm.KINDS:
            text, usage, _ = self.run_kind(kind, stream=False)
            self.assertEqual(text, "Hello Name1", kind)
            self.assertEqual(usage, {"input": 7, "output": 3}, kind)

    def test_key_only_in_header_never_in_url_or_body(self):
        for kind in ("anthropic", "openai", "gemini", "openrouter"):
            _, _, requests = self.run_kind(kind)
            req = requests[0]
            self.assertNotIn(TEST_KEY, req["path"])
            self.assertNotIn(TEST_KEY.encode(), req["raw"])
            self.assertIn(TEST_KEY, "".join(req["headers"].values()))

    def test_system_prompt_and_model_in_payload(self):
        _, _, requests = self.run_kind("anthropic")
        self.assertEqual(requests[0]["body"]["system"], "be brief")
        self.assertEqual(requests[0]["body"]["model"], "m-one")
        _, _, requests = self.run_kind("openai")
        self.assertEqual(requests[0]["body"]["messages"][0], {"role": "system", "content": "be brief"})

    def test_errors_are_plain_and_never_contain_the_key(self):
        cases = {401: "auth", 403: "auth", 429: "rate_limit", 400: "bad_request", 500: "server", 503: "server"}
        for status, code in cases.items():
            for kind in llm.KINDS:
                with FakeProvider(status=status) as fake:
                    with self.assertRaises(llm.LLMError) as caught:
                        llm.complete(provider(kind, fake), MSGS, "", 10, 5)
                    self.assertEqual(caught.exception.code, code, (kind, status))
                    self.assertNotIn(TEST_KEY, caught.exception.message)
                    self.assertEqual(len(fake.requests), 1, "no automatic retry on error")

    def test_network_error_and_timeout(self):
        bad = llm.Provider("custom", "http://127.0.0.1:9", "", "m")
        # Closed TCP ports can refuse immediately or time out depending on the
        # host firewall. Exercise both transports deterministically, including
        # urllib's wrapped socket error, without relying on a reserved port.
        for error, expected in ((urllib.error.URLError(ConnectionRefusedError()), "network"),
                                (urllib.error.URLError(TimeoutError()), "timeout"),
                                (TimeoutError(), "timeout")):
            with self.subTest(expected=expected), patch.object(llm, "_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(llm.LLMError) as caught:
                    llm.complete(bad, MSGS, "", 10, 2)
                self.assertEqual(caught.exception.code, expected)
                opener.return_value.open.assert_called_once()

    def test_refusal_finish_reason(self):
        with FakeProvider(finish="content_filter") as fake:
            with self.assertRaises(llm.LLMError) as caught:
                llm.complete(provider("openai", fake), MSGS)
            self.assertEqual(caught.exception.code, "refused")

    def test_error_event_in_stream(self):
        with FakeProvider(tail_error=True) as fake:
            with self.assertRaises(llm.LLMError) as caught:
                llm.complete(provider("anthropic", fake), MSGS)
            self.assertEqual(caught.exception.code, "server")

    def test_stop_cancels_stream(self):
        with FakeProvider(chunks=["a"] * 50) as fake:
            seen = []
            with self.assertRaises(llm.LLMError) as caught:
                for kind, value in llm.stream_chat(provider("openai", fake), MSGS, cancel=lambda: len(seen) >= 3):
                    seen.append(value)
            self.assertEqual(caught.exception.code, "cancelled")

    def test_list_models_and_test_connection(self):
        for kind in llm.KINDS:
            with FakeProvider() as fake:
                self.assertEqual(llm.list_models(provider(kind, fake)), ["m-one", "m-two"], kind)
                result = llm.test_connection(provider(kind, fake))
                self.assertTrue(result["ok"])
        with FakeProvider(status=401) as fake:
            result = llm.test_connection(provider("openai", fake))
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "auth")
            self.assertNotIn(TEST_KEY, str(result))

    def test_remote_http_and_credentials_in_url_refused(self):
        with self.assertRaises(llm.LLMError):
            llm.validate(llm.Provider("custom", "http://example.org", "k", "m"))
        with self.assertRaises(llm.LLMError):
            llm.validate(llm.Provider("custom", "https://user:pw@example.org", "k", "m"))
        with self.assertRaises(llm.LLMError):
            llm.validate(llm.Provider("openai", "", "", "m"))          # no key
        llm.validate(llm.Provider("custom", "http://localhost:11434", "", "m"))   # local Ollama, no key

    def test_redirect_is_refused(self):
        import http.server
        import threading

        class Redirect(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                self.send_response(307)
                self.send_header("Location", "http://127.0.0.1:1/steal")
                self.end_headers()

        server = http.server.HTTPServer(("127.0.0.1", 0), Redirect)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            prov = llm.Provider("openai", f"http://127.0.0.1:{server.server_address[1]}", TEST_KEY, "m")
            with self.assertRaises(llm.LLMError) as caught:
                llm.complete(prov, MSGS)
            self.assertEqual(caught.exception.code, "config")
        finally:
            server.shutdown()
            server.server_close()

    def test_repr_hides_key(self):
        self.assertNotIn(TEST_KEY, repr(llm.Provider("openai", "", TEST_KEY, "m")))

    def test_last_message_must_be_user(self):
        with FakeProvider() as fake:
            with self.assertRaises(llm.LLMError):
                llm.complete(provider("openai", fake), [{"role": "assistant", "content": "x"}])


if __name__ == "__main__":
    unittest.main()
