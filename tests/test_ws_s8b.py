"""S8B: NER inference side (chunking with overlap, no size skip, exact Viterbi, fail-soft notes)."""
import unittest
from unittest import mock

import numpy as np

from anonymizer import ner

HAVE = ner.available()
NAME = "Андрей Петрович Тарнов"


class ChunkOwnership(unittest.TestCase):
    def _check(self, text):
        owned = []
        for a, b, oa, ob in ner._chunks(text):
            self.assertTrue(a <= oa <= ob <= b or ob == len(text) or oa >= a, (a, b, oa, ob))
            owned.append((oa, ob))
        self.assertEqual(owned[0][0], 0)
        self.assertEqual(owned[-1][1], len(text))
        for (_, e1), (s2, _) in zip(owned, owned[1:]):
            self.assertEqual(e1, s2)                       # каждая позиция принадлежит ровно одному окну

    def test_ownership_partitions_text(self):
        self._check("слово " * 12_000)                     # без точек и переводов строк: жёсткие разрезы с перекрытием
        self._check("Это предложение. " * 9_000)
        self._check("строка\n" * 30_000)
        self._check("а" * 70_000)                          # даже без пробелов

    def test_hard_cut_windows_overlap(self):
        ws = list(ner._chunks("слово " * 12_000))
        self.assertGreater(len(ws), 2)
        for (a1, b1, _, _), (a2, b2, _, _) in zip(ws, ws[1:]):
            self.assertLess(a2, b1)


@unittest.skipUnless(HAVE, "natasha is not installed")
class Inference(unittest.TestCase):
    def test_name_on_chunk_border(self):
        for shift in range(-12, 13, 4):
            filler = "слово " * ((ner.CHUNK + shift) // 6)
            text = filler + NAME + " подписал договор " + "слово " * 3000
            spans = ner.person_spans(text)
            start = text.index(NAME)
            self.assertIn((start, start + len(NAME)), [(s, e) for s, e, _ in spans], f"shift={shift}")

    def test_large_text_is_not_skipped(self):
        unit = "Договор подписал директор Мерцов в присутствии свидетелей.\n"
        text = (unit * 7000) + "Свидетель " + NAME + " подтвердил показания.\n" + unit * 1000
        self.assertGreater(len(text), 400_000)
        spans = ner.person_spans(text)
        self.assertTrue(spans)
        self.assertTrue(all(text[s:e].strip() for s, e, _ in spans))
        i = text.index(NAME)
        self.assertTrue(any(s <= i and e >= i + len(NAME) for s, e, _ in spans))

    def test_offsets_absolute_in_late_chunks(self):
        text = "Погода стояла хорошая.\n" * 5000 + "Заявитель: " + NAME + "\n" + "Конец документа.\n" * 100
        for s, e, c in ner.person_spans(text):
            self.assertEqual(text[s:e].split()[0][0].isupper(), True)
        i = text.index(NAME)
        self.assertTrue(any(s <= i < e for s, e, _ in ner.person_spans(text)))

    def test_viterbi_matches_slovnet(self):
        tagger, _ = ner._load()
        crf = tagger.infer.model.head.crf
        rnd = np.random.default_rng(3)
        for n in (1, 2, 17, 300):
            em = rnd.normal(size=(1, n, 8)) * 2
            mask = np.ones((1, n), dtype=bool)
            ref = crf.decode(em, mask)
            got = ner._decode(crf.transitions.array, em, mask)
            self.assertEqual(list(ref[0]), list(got[0]))

    def test_identical_windows_use_cache(self):
        text = ("Договор подписал " + NAME + " в Москве.\n") * 40
        a = ner._raw_spans(text)
        with mock.patch.object(ner, "_run_piece", side_effect=AssertionError("must hit cache")):
            self.assertEqual(ner._raw_spans(text), a)


class FailSoft(unittest.TestCase):
    def setUp(self):
        ner.take_notes()

    def test_hard_cap_emits_note(self):
        with mock.patch.object(ner, "MAX_TEXT", 100):
            self.assertEqual(ner.person_spans("Привет мир. " * 50), [])
        notes = ner.take_notes()
        self.assertEqual(len(notes), 1)
        self.assertIn("NER", notes[0])

    def test_missing_model_emits_note_and_no_spans(self):
        with mock.patch.object(ner, "_model", False):
            self.assertEqual(ner.person_spans("Договор подписал " + NAME + " в Москве."), [])
        self.assertTrue(ner.take_notes())

    def test_load_is_lazy(self):
        import subprocess, sys
        code = "from anonymizer import ner; assert ner._model is None; ner.installed(); assert ner._model is None; from anonymizer.util import peak_memory_mb; print(peak_memory_mb())"
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent))
        self.assertEqual(out.returncode, 0, out.stderr[-300:])


if __name__ == "__main__":
    unittest.main()
