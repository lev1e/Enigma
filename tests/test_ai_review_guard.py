"""Per-span consent must survive the final check without crossing message boundaries."""
import unittest
from types import SimpleNamespace
from unittest import mock

from anonymizer import chat_pipeline, llm


class GuardPartTests(unittest.TestCase):
    def setUp(self):
        def scan(text, *_args):
            return [SimpleNamespace(original="ACME", category="POSSIBLE_ORG",
                                    start=i, end=i + 4, decision="ask")
                    for i in range(len(text)) if text.startswith("ACME", i)]

        self.service = mock.Mock()
        self.service.vault.entities = {}
        self.service.build_detector.return_value = SimpleNamespace(scan=scan)
        self.pipe = chat_pipeline.ChatPipeline(self.service)
        self.pipe.anonymize_text = lambda text, options=None: text
        self.provider = llm.Provider("custom", "http://localhost:9999", model="fake")

    def send(self, prepared):
        with mock.patch.object(llm, "stream_chat", return_value=iter([
                ("usage", {"input": 1, "output": 0}), ("done", "stop")])) as transport:
            events = list(self.pipe.send(prepared, self.provider, ai_on=True))
            transport.assert_called_once()
            self.assertIn(("done", "stop"), events)

    def test_user_allow_survives_final_check_with_system_and_history(self):
        history = [{"role": "assistant", "content": "Earlier answer"}]
        first = self.pipe.prepare("Discuss ACME", "Be brief", history)
        self.assertTrue(first.guard.blocked)
        allowed = self.pipe.prepare("Discuss ACME", "Be brief", history,
                                    resolve={"allow": [first.guard.findings[0]["id"]]})
        self.assertFalse(allowed.guard.blocked)
        self.send(allowed)

    def test_history_allow_survives_final_check(self):
        history = [{"role": "assistant", "content": "Discuss ACME"}]
        first = self.pipe.prepare("Continue", "Be brief", history)
        self.assertEqual(first.guard.findings[0]["part"], 2)
        allowed = self.pipe.prepare("Continue", "Be brief", history,
                                    resolve={"allow": [first.guard.findings[0]["id"]]})
        self.assertFalse(allowed.guard.blocked)
        self.send(allowed)

    def test_user_allow_does_not_authorize_same_value_in_changed_system(self):
        first = self.pipe.prepare("Discuss ACME")
        allowed = self.pipe.prepare("Discuss ACME", resolve={"allow": [first.guard.findings[0]["id"]]})
        allowed.system = "ACME"
        with mock.patch.object(llm, "stream_chat") as transport:
            with self.assertRaises(chat_pipeline.Blocked):
                list(self.pipe.send(allowed, self.provider, ai_on=True))
            transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
