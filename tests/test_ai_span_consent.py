"""Consent is bound to individual spans and exact payload parts."""
import re
import unittest
from types import SimpleNamespace
from unittest import mock

from anonymizer import chat_pipeline, guard, llm
from .helpers import Env


class SpanConsentTests(unittest.TestCase):
    def setUp(self):
        self.vault = SimpleNamespace(entities={})

        def token_for(kind, key, original):
            number = len(self.vault.entities) + 1
            self.vault.entities[key] = {"kind": kind, "spellings": [original]}
            return f"Term{number}"

        self.vault.token_for = token_for

        def scan(text, *_args):
            return [SimpleNamespace(original=m.group(), category="POSSIBLE_ORG", start=m.start(),
                                    end=m.end(), decision="ask") for m in re.finditer(r"ACME|BETA", text)]

        self.detector = SimpleNamespace(scan=scan)
        service = mock.Mock(vault=self.vault)
        service.build_detector.return_value = self.detector
        self.pipe = chat_pipeline.ChatPipeline(service)
        self.pipe.anonymize_text = lambda text, options=None: text
        self.provider = llm.Provider("custom", "http://localhost:9999", model="fake")

    def send(self, prepared):
        with mock.patch.object(llm, "stream_chat", return_value=iter([("done", "stop")])) as transport:
            events = list(self.pipe.send(prepared, self.provider, ai_on=True))
            transport.assert_called_once()
            self.assertIn(("done", "stop"), events)

    def test_duplicate_occurrences_have_distinct_ids_without_values(self):
        findings = self.pipe.prepare("ACME then ACME").guard.findings
        self.assertEqual(len(findings), 2)
        self.assertNotEqual(findings[0]["id"], findings[1]["id"])
        self.assertTrue(all("ACME" not in f["id"] for f in findings))

    def test_allowing_first_occurrence_keeps_second_blocked(self):
        first = self.pipe.prepare("ACME then ACME")
        allowed = self.pipe.prepare("ACME then ACME", resolve={"allow": [first.guard.findings[0]["id"]]})
        self.assertTrue(allowed.guard.blocked)
        self.assertEqual([f["start"] for f in allowed.guard.findings], [10])

    def test_masking_first_occurrence_keeps_second_visible_and_blocked(self):
        first = self.pipe.prepare("ACME then ACME")
        masked = self.pipe.prepare("ACME then ACME", resolve={"anonymize": [first.guard.findings[0]["id"]]})
        self.assertEqual(masked.text, "ACME then ACME")
        self.assertTrue(masked.guard.blocked)
        self.assertEqual([f["start"] for f in masked.guard.findings], [10])
        self.assertEqual(self.vault.entities, {})

    def test_mask_and_allow_same_value_still_blocks_vault_original(self):
        first = self.pipe.prepare("ACME then ACME")
        resolved = self.pipe.prepare("ACME then ACME", resolve={
            "anonymize": [first.guard.findings[0]["id"]], "allow": [first.guard.findings[1]["id"]]})
        self.assertTrue(resolved.guard.blocked)
        self.assertTrue(resolved.guard.kinds)

    def test_masking_earlier_value_remaps_later_allowed_span_for_send(self):
        first = self.pipe.prepare("BETA then ACME")
        original_allow = first.guard.findings[1]["id"]
        resolved = self.pipe.prepare("BETA then ACME", resolve={
            "anonymize": [first.guard.findings[0]["id"]], "allow": [original_allow]})
        self.assertEqual(resolved.text, "Term1 then ACME")
        self.assertFalse(resolved.guard.blocked)
        self.assertNotEqual(resolved.allow, [original_allow])
        self.send(resolved)

    def test_changed_part_invalidates_previous_consent_even_without_offset_change(self):
        first = self.pipe.prepare("ACME then")
        allowed = self.pipe.prepare("ACME then", resolve={"allow": [first.guard.findings[0]["id"]]})
        allowed.text = "ACME else"
        with mock.patch.object(llm, "stream_chat") as transport:
            with self.assertRaises(chat_pipeline.Blocked):
                list(self.pipe.send(allowed, self.provider, ai_on=True))
            transport.assert_not_called()
        changed = self.pipe.prepare("prefix ACME then", resolve={"allow": [first.guard.findings[0]["id"]]})
        self.assertTrue(changed.guard.blocked)

    def test_incremental_mask_then_allow_uses_original_composer_span_ids(self):
        first = self.pipe.prepare("BETA then ACME")
        mask = [first.guard.findings[0]["id"]]
        masked = self.pipe.prepare("BETA then ACME", resolve={"anonymize": mask})
        self.assertTrue(masked.guard.blocked)
        self.assertEqual(masked.guard.findings[0]["id"], first.guard.findings[1]["id"])
        resolved = self.pipe.prepare("BETA then ACME", resolve={
            "anonymize": mask, "allow": [masked.guard.findings[0]["id"]]})
        self.assertFalse(resolved.guard.blocked)
        self.send(resolved)

    def test_definite_finding_cannot_be_allowed(self):
        detector = SimpleNamespace(scan=lambda text, *_args: [SimpleNamespace(
            original=text, category="PHONE", start=0, end=len(text), decision="auto")])
        first = guard.check(["123456789"], self.vault, detector)
        allowed = guard.check(["123456789"], self.vault, detector, allow=[first.findings[0]["id"]])
        self.assertTrue(allowed.blocked)

    def test_system_and_history_consent_survive_user_mask(self):
        history = [{"role": "assistant", "content": "ACME"}]
        first = self.pipe.prepare("BETA", "ACME", history)
        resolved = self.pipe.prepare("BETA", "ACME", history, resolve={
            "anonymize": [first.guard.findings[0]["id"]],
            "allow": [f["id"] for f in first.guard.findings if f["part"] != 0]})
        self.assertFalse(resolved.guard.blocked)
        self.send(resolved)

    def test_anonymize_does_not_modify_system_or_history(self):
        history = [{"role": "assistant", "content": "ACME"}]
        first = self.pipe.prepare("hello", "BETA", history)
        resolved = self.pipe.prepare("hello", "BETA", history,
                                     resolve={"anonymize": [f["id"] for f in first.guard.findings]})
        self.assertEqual(resolved.system, "BETA")
        self.assertEqual(resolved.history, history)
        self.assertTrue(resolved.guard.blocked)

    def test_overlapping_mask_requests_fail_before_vault_changes(self):
        findings = [dict(id="one", part=0, start=0, end=4, category="POSSIBLE_ORG", possible=True),
                    dict(id="two", part=0, start=2, end=6, category="POSSIBLE_ORG", possible=True)]
        with self.assertRaises(chat_pipeline.Blocked):
            self.pipe._mask_spans("ABCDEF", findings, {"one", "two"}, [])
        self.assertEqual(self.vault.entities, {})

    def test_real_service_incremental_choices_defer_vault_writes_until_complete(self):
        env = Env(ner_candidates=False)
        self.addCleanup(env.close)
        pipe = chat_pipeline.ChatPipeline(env.service)
        text = "Напиши SQL-запрос и сравни результат с QZVX."
        first = pipe.prepare(text)
        self.assertGreaterEqual(len(first.guard.findings), 2)
        self.assertTrue(all(f["possible"] for f in first.guard.findings))
        mask = [first.guard.findings[0]["id"]]
        before = dict(env.vault.entities)
        partial = pipe.prepare(text, resolve={"anonymize": mask})
        self.assertTrue(partial.guard.blocked)
        self.assertEqual(env.vault.entities, before)
        self.assertNotIn(mask[0], [f["id"] for f in partial.guard.findings])
        choices = {"anonymize": mask, "allow": [f["id"] for f in partial.guard.findings]}
        complete = pipe.prepare(text, resolve=choices)
        self.assertFalse(complete.guard.blocked, complete.guard.kinds)
        # /send prepares the original composer again after the preview call.
        replayed = pipe.prepare(text, resolve=choices)
        self.assertFalse(replayed.guard.blocked, replayed.guard.kinds)
        with mock.patch.object(llm, "stream_chat", return_value=iter([("done", "stop")])) as transport:
            self.assertIn(("done", "stop"), list(pipe.send(replayed, self.provider, ai_on=True)))
            transport.assert_called_once()


if __name__ == "__main__":
    unittest.main()
