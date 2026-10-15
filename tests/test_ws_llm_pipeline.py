"""W12 slice 3 pieces: outbound guard and streaming restorer."""
import os
import tempfile
import unittest
from pathlib import Path

import json
import random

from anonymizer import chat_pipeline, guard, keystore, llm
from anonymizer.restore import Restorer
from anonymizer.stream_restore import StreamRestorer
from anonymizer.service import Service
from anonymizer.vault import Vault

from .llm_fake import TEST_KEY, FakeProvider

NAME = "Смирнов Алексей Петрович"
MAIL = "smirnov@romashka.ru"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Vault(Path(self.tmp.name) / "v.bin", key=os.urandom(32))
        self.name = self.vault.token_for("PERSON", "k1", NAME)
        self.vault.token_for("EMAIL", "k2", MAIL)
        self.service = Service(self.vault, Path(self.tmp.name) / "work")

    def tearDown(self):
        self.tmp.cleanup()

    def detector(self):
        return self.service.build_detector(self.service.settings_for({}))


class GuardTests(Base):
    def test_clean_payload_passes(self):
        res = guard.check([f"Summarize what {self.name} said."], self.vault, self.detector())
        self.assertFalse(res.blocked, res.kinds)

    def test_blocks_injected_vault_original_without_echoing_it(self):
        res = guard.check([f"Please write to {NAME.upper()} today"], self.vault)
        self.assertTrue(res.blocked)
        self.assertIn("PERSON", res.kinds)
        self.assertNotIn("Смирнов", res.message())

    def test_blocks_detector_hit_not_in_vault(self):
        res = guard.check(["Call +7 913 555-12-34 or write ivanov@firma.ru"], self.vault, self.detector())
        self.assertTrue(res.blocked)
        self.assertTrue(res.kinds)
        self.assertNotIn("913", res.message())

    def test_fails_closed_when_scan_breaks(self):
        class Boom:
            def scan(self, *a):
                raise RuntimeError("x")
        self.assertTrue(guard.check(["hello"], self.vault, Boom()).blocked)

    def test_every_part_is_checked(self):
        res = guard.check(["fine", "", f"file_{MAIL}.txt"], self.vault)
        self.assertTrue(res.blocked)


class StreamTests(Base):
    def stream(self, text, sizes):
        sr = StreamRestorer(self.vault)
        out, i = [], 0
        for n in sizes:
            out.append(sr.feed(text[i:i + n]))
            i += n
        out.append(sr.feed(text[i:]))
        out.append(sr.finish())
        return "".join(out), sr

    def test_split_labels_equal_whole_text_restore(self):
        text = f"Hello {self.name}, write to email1@example.com. Then {self.name}_2 and Name1 again; end {self.name}"
        whole = Restorer(self.vault).substitute(text)
        self.assertIn(NAME, whole)
        for size in (1, 2, 3, 5, 7):
            out, _ = self.stream(text, [size] * 60)
            self.assertEqual(out, whole, size)
        rnd = random.Random(1)
        for _ in range(50):
            out, _ = self.stream(text, [rnd.randint(1, 9) for _ in range(40)])
            self.assertEqual(out, whole)

    def test_partial_label_is_not_shown_early(self):
        sr = StreamRestorer(self.vault)
        shown = sr.feed("See Na")
        self.assertNotIn("Na", shown.split("See")[-1].strip() or "")
        shown += sr.feed("me1 now") + sr.finish()
        self.assertEqual(shown, f"See {NAME} now")

    def test_damaged_labels_restored_and_reported(self):
        for damaged in ("Name 1", "_Name1_", "name1", "**Name1**"):
            out, sr = self.stream(f"Ask {damaged} about it", [2] * 30)
            self.assertIn(NAME, out, damaged)
            self.assertNotIn("Name", out.replace(NAME, ""), damaged)
        out, sr = self.stream("Ask Name 1 about it", [3] * 20)
        self.assertEqual(sr.report()["damaged_but_restored"], 1)

    def test_unknown_label_stays_and_is_reported(self):
        out, sr = self.stream("Ask Name77 and Company5 about it", [4] * 20)
        self.assertEqual(out, "Ask Name77 and Company5 about it")
        report = sr.report()
        self.assertTrue(report["damaged"])
        self.assertEqual(set(report["unknown"]), {"Name77", "Company5"})

    def test_long_text_without_spaces_still_flushes(self):
        sr = StreamRestorer(self.vault)
        text = "x" * 500
        got = sr.feed(text) + sr.finish()
        self.assertEqual(got, text)


CORPORA = ("text_corpus_v1.jsonl", "text_corpus_en.jsonl")
BATCH = 20


def corpus_batches(name):
    path = Path(__file__).parent / "eval" / name
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        yield "\n".join(r["text"] for r in chunk), sorted({sp["text"] for r in chunk for sp in r["spans"]})


class PipelineTests(Base):
    def provider(self, fake):
        return llm.Provider("custom", fake.url, TEST_KEY, "m-one")

    def test_ai_off_by_default_and_nothing_sent(self):
        with FakeProvider() as fake:
            pipe = chat_pipeline.ChatPipeline(self.service)
            prep = pipe.prepare("Hello there")
            with self.assertRaises(chat_pipeline.AiOff):
                list(pipe.send(prep, self.provider(fake)))
            self.assertEqual(fake.requests, [])

    def test_dry_run_matches_sent_payload_and_conversation_roundtrip(self):
        with FakeProvider(chunks=["Reply about ", "Name1 ", "done"]) as fake:
            pipe = chat_pipeline.ChatPipeline(self.service)
            prep = pipe.prepare(f"Tell me about {NAME}, phone +7 913 555-12-34", system="Be brief.")
            dry = pipe.dry_run(prep, self.provider(fake))
            shown = "".join(v for k, v in pipe.send(prep, self.provider(fake), ai_on=True) if k == "delta")
            self.assertEqual(dry["body"], fake.requests[0]["body"] | {})
            self.assertEqual(len(fake.requests), 1)
            self.assertIn(NAME, shown)
            self.assertNotIn(NAME, json.dumps(fake.requests[0]["body"], ensure_ascii=False))
            self.assertEqual(pipe.outgoing_log[0]["labels"], prep.labels)
            self.assertNotIn(NAME, json.dumps(pipe.outgoing_log, ensure_ascii=False))
            self.assertNotIn(TEST_KEY, json.dumps(pipe.outgoing_log))

    def test_injected_clear_text_in_history_is_blocked_before_any_request(self):
        with FakeProvider() as fake:
            pipe = chat_pipeline.ChatPipeline(self.service)
            prep = pipe.prepare("Hi", history=[{"role": "assistant", "content": f"Call {NAME}"}])
            self.assertTrue(prep.guard.blocked)
            with self.assertRaises(chat_pipeline.Blocked):
                list(pipe.send(prep, self.provider(fake), ai_on=True))
            self.assertEqual(fake.requests, [])

    def test_stop_aborts_and_no_resend(self):
        with FakeProvider(chunks=["word "] * 200) as fake:
            pipe = chat_pipeline.ChatPipeline(self.service)
            prep = pipe.prepare("Count please")
            got = 0
            with self.assertRaises(llm.LLMError):
                for kind, _ in pipe.send(prep, self.provider(fake), ai_on=True):
                    got += 1
                    if got == 3:
                        pipe.stop()
            self.assertEqual(len(fake.requests), 1)
            self.assertEqual(pipe.outgoing_log[0]["status"], "cancelled")

    def test_key_not_in_profile_dir(self):
        with FakeProvider() as fake:
            store = keystore.Keystore(Path(self.tmp.name) / "ai", os.urandom(32), None)
            store.configure("p", "custom", fake.url, "m-one")
            store.set_secret("p", TEST_KEY)
            pipe = chat_pipeline.ChatPipeline(self.service)
            prep = pipe.prepare(f"About {NAME}")
            list(pipe.send(prep, store.provider("p"), ai_on=True))
            blob = b"".join(f.read_bytes() for f in Path(self.tmp.name).rglob("*") if f.is_file())
            self.assertNotIn(TEST_KEY.encode(), blob)


class OutboundLeakTests(Base):
    """End to end over the gold corpora: captured request bodies must contain zero gold values and zero vault originals."""

    def test_corpora(self):
        report = {}
        for name in CORPORA:
            sent = blocked = leaks = 0
            kinds = {}
            vault_leaks = 0
            with FakeProvider(chunks=["ok"]) as fake:
                pipe = chat_pipeline.ChatPipeline(self.service)
                provider = llm.Provider("custom", fake.url, TEST_KEY, "m")
                for text, gold in corpus_batches(name):
                    prep = pipe.prepare(text)
                    if prep.guard.blocked:
                        blocked += 1
                        for k, n in prep.guard.kinds.items():
                            kinds[k] = kinds.get(k, 0) + n
                        continue
                    list(pipe.send(prep, provider, ai_on=True))
                    sent += 1
                bodies = [b.decode("utf-8") for b in fake.bodies()]
            body_text = "\n".join(bodies).casefold()
            for _, gold in corpus_batches(name):
                for value in gold:
                    if len(value) >= 3 and value.casefold() in body_text:
                        leaks += 1
            originals = {o for o, _ in guard.vault_originals(self.vault)}
            vault_leaks = sum(1 for o in originals if len(o) >= guard.WORD_LEN and o in body_text)
            report[name] = {"batches": sent + blocked, "sent": sent, "blocked": blocked, "blocked_kinds": kinds, "gold_leaks_in_sent": leaks,
                            "vault_original_leaks_in_sent": vault_leaks}
            print("OUTBOUND", name, report[name])
            self.assertEqual(leaks, 0, report[name])
            self.assertEqual(vault_leaks, 0, report[name])


if __name__ == "__main__":
    unittest.main()
