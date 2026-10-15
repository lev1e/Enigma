"""WS images/scans: fail-closed verify must not refuse because of our own placeholders."""
import io
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import fitz
from anonymizer import formats, ocr
from anonymizer.pdftext import PageChars
from tests.helpers import Env

from tests.font_support import system_font

ARIAL = system_font()


def _png(lines, size=26):
    f = ImageFont.truetype(ARIAL, size)
    img = Image.new("RGB", (1000, 40 + len(lines) * 44), "white")
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((24, 20 + i * 44), line, font=f, fill=(20, 20, 20))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


class PlaceholderIsNotResidual(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def test_token_after_password_label_is_not_a_leftover(self):
        d = self.env.service.build_detector(self.env.service.settings_for({}))
        self.assertEqual(formats._residuals(d, "login: Name1 password: Secret2 token Secret3", [], ocr_text=True), [])
        self.assertEqual(formats._residuals(d, "password:Secret2", [], ocr_text=False), [])

    def test_ocr_garbled_email_placeholders_are_not_leftovers(self):
        d = self.env.service.build_detector(self.env.service.settings_for({}))
        for noisy in ("Name4 jPhone1_2lemail@example.com YukiName5", "iNationalld2 temail3@examplecom Name4", "Phone3 email1@exampie.com x",
                      "see @example now"):
            self.assertEqual(formats._residuals(d, noisy, [], ocr_text=True), [], noisy)

    def test_real_email_at_example_com_is_still_a_leftover(self):
        d = self.env.service.build_detector(self.env.service.settings_for({}))
        self.assertIn("john.doe@example.com", formats._residuals(d, "mail john.doe@example.com", [], ocr_text=True))

    def test_real_secret_is_still_a_leftover(self):
        d = self.env.service.build_detector(self.env.service.settings_for({}))
        self.assertIn("Rv070!kd5964Pm", formats._residuals(d, "password: Rv070!kd5964Pm", [], ocr_text=True))

    def test_image_with_password_line_is_redacted_not_refused(self):
        png = _png(["Contact: Yuki E. Whitfield", "password: Rv070!kd5964Pm", "phone +44 20 7423 2235"])
        job = self.env.anonymize(("scan.png", png))
        f = job.files[0]
        self.assertTrue(f.out_path, [m["text"] for m in f.messages])


def _chars_for(lines):
    doc = fitz.open()
    page = doc.new_page(width=600, height=60 + 40 * len(lines))
    words = []
    for i, line in enumerate(lines):
        x = 20.0
        for w in line.split():
            words.append(ocr.Word(w, x, 20 + 40 * i, x + 10 * len(w), 40 + 40 * i, i))
            x += 10 * len(w) + 6
    chars = PageChars(page)
    ocr.add_ocr_chars(chars, words)
    return doc, chars


class PaintAsStrongAsVerify(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)
        self.detector = self.env.service.build_detector(self.env.service.settings_for({}))

    def test_verify_rules_give_paintable_hits_with_char_ids(self):
        doc, chars = _chars_for(["Oliver Kowalczyk, born", "09/01/1960", "passport", "B29513614"])
        self.addCleanup(doc.close)
        hits = formats._verify_hits(self.detector, chars, "x.png", set())
        found = {f.original: ids for f, ids in hits}
        for value in ("09/01/1960", "B29513614"):
            self.assertIn(value, found, list(found))
            text = "".join(chars.chars[i].c for i in sorted(found[value]))
            self.assertEqual(text, value)

    def test_ocr_lookalikes_in_plate_and_date_are_painted(self):
        doc, chars = _chars_for(["госномер O148PЕ 77", "дата рождения 20.10.19/5"])
        self.addCleanup(doc.close)
        found = {f.original for f, _ in formats._verify_hits(self.detector, chars, "x.png", set())}
        self.assertIn("O148PЕ 77", found, found)
        self.assertTrue(any("20.10.19/5" in v for v in found), found)

    def test_already_taken_chars_are_not_repainted_and_own_tokens_skipped(self):
        doc, chars = _chars_for(["password: Secret2", "login: Name1", "mail email3@example.com"])
        self.addCleanup(doc.close)
        self.assertEqual(formats._verify_hits(self.detector, chars, "x.png", set()), [])


class DrawnTokensGarbling(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)
        self.d = self.env.service.build_detector(self.env.service.settings_for({}))
        self.drawn = {"email1@example.com", "email3@example.com", "email4@example.com"}

    def test_garbled_drawn_tokens_are_not_leftovers(self):
        for noisy in ("x @examole comtNationalld", "a eraned4@npe.gile.com b", "адиинетаil3@example.com", "emaig@exampie.com z",
                      "q enmed4@example.com. z"):
            self.assertEqual(formats._residuals(self.d, noisy, [], ocr_text=True, drawn=self.drawn), [], noisy)

    def test_masked_token_rectangles_hide_garbage_but_not_originals(self):
        findings = [formats.Finding("i", "f", "l", "EMAIL", "john.doe@example.com", 0, 20, formats.Decision.AUTO, 1.0)]
        self.assertIn("john.doe@example.com", formats._residuals(self.d, "zz john.doe@example.com", findings, ocr_text=True,
                                                                 drawn=self.drawn, masked_spans=[(0, 2)]))
        # без исходных значений слово на метке (даже настоящий адрес) считается искажением метки, но только внутри её рамки
        self.assertEqual(formats._residuals(self.d, "zz xq@example.com", [], ocr_text=True, drawn=self.drawn,
                                            masked_spans=[(3, 17)]), [])

    def test_real_leaks_stay_leftovers_with_drawn_tokens(self):
        for real in ("john.doe@example.com", "tom.baker@example.com", "j.smith1@example.com"):
            self.assertIn(real, formats._residuals(self.d, "mail " + real, [], ocr_text=True, drawn=self.drawn), real)

    def test_garbled_leftover_containing_an_original_stays_a_leak(self):
        findings = [formats.Finding("i", "f", "l", "EMAIL", "tom.baker@example.com", 0, 20, formats.Decision.AUTO, 1.0)]
        self.assertTrue(formats._residuals(self.d, "a tom.baker@example.com b", findings, ocr_text=True, drawn=self.drawn))


class EmbeddedSurname(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def test_cropped_email_with_known_surname_is_painted(self):
        import fitz
        from anonymizer import ocr
        png = _png(["Signed by Thomas B. Haverford", "reply to thaverford195@corp-dem", "phone +44 20 7423 2235"])
        job = self.env.anonymize(("scan.png", png))
        f = job.files[0]
        self.assertTrue(f.out_path, [m["text"] for m in f.messages])
        doc = fitz.open()
        pg = doc.new_page(width=1000, height=210)
        pg.insert_image(pg.rect, stream=Path(f.out_path).read_bytes())
        seen = " ".join(w.text for layer in ocr.ocr_image_layers(pg, scale=2.0) for w in layer).lower()
        self.assertNotIn("haverford", seen)


class PersonParts(unittest.TestCase):
    def test_surname_of_found_person_becomes_part_but_short_words_do_not(self):
        from anonymizer.models import Finding, Decision
        f = Finding("i", "x", "image", "PERSON", "Thomas B. Haverford", 0, 19, Decision.AUTO, .9, key="p1")
        parts = dict(formats._person_parts([f]))
        self.assertEqual(parts.get("haverford"), "p1")
        self.assertNotIn("b", parts)


class SupplementLabelRule(unittest.TestCase):
    def test_low_confidence_word_kept_only_on_label_line(self):
        from unittest import mock
        W = ocr.Word
        rows = [W("password", 0, 0, 10, 5, 1, conf=.96), W("Rv159!kd", 12, 0, 30, 5, 1, conf=.29),
                W("noise", 0, 9, 10, 14, 2, conf=.1), W("sheet", 12, 9, 30, 14, 2, conf=.9)]
        sup = ocr.TesseractSupplement()
        with mock.patch.object(ocr.TesseractProvider, "words", return_value=rows):
            kept = [w.text for w in sup.words(Path("x.png"))]
        self.assertEqual(kept, ["password", "Rv159!kd", "sheet"])


class FormLabelIsNotSecret(unittest.TestCase):
    """Метки на странице после стёртого значения не секрет: значения стёрты, а метки лежат в конце потока страницы."""
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)
        self.d = self.env.service.build_detector(self.env.service.settings_for({}))

    def test_label_after_erased_value_is_not_residual(self):
        for text in ("token = \nCustomer:\n\u00a0Applicant:\nPhone:\n", "password = \n\u041e\u0442\u0432\u0435\u0442\u0441\u0442\u0432\u0435\u043d\u043d\u044b\u0439:\n",
                     "password\n\u0420\u0430\u0441\u0447\u0451\u0442\u043d\u044b\u0439 \u0441\u0447\u0451\u0442\n"):
            self.assertEqual(formats._residuals(self.d, text, [], ocr_text=False), [], text)

    def test_real_secret_after_label_still_residual(self):
        self.assertIn("Rv070!kd5964Pm", formats._residuals(self.d, "password = Rv070!kd5964Pm\nPhone:", [], ocr_text=False))


class LabelValue(unittest.TestCase):
    def _chars(self, text):
        chars = formats.PageChars.__new__(formats.PageChars)
        chars.chars, chars.lines, chars.blocks, chars.force = [], [], [], set()
        words = []
        x = 0.0
        for w in text.split(" "):
            words.append(ocr.Word(w, x, 0, x + 10 * len(w), 10, 0))
            x += 10 * len(w) + 8
        ocr.add_ocr_chars(chars, words)
        return chars

    def test_garbled_key_after_label_is_taken_but_own_token_is_not(self):
        hit = formats._label_value_hits(self._chars("token = sk live_705871Z081428808XW"), [], "r")
        self.assertEqual([f.original for f, _ in hit], ["sk live_705871Z081428808XW"])
        self.assertEqual(formats._label_value_hits(self._chars("password: Secret2"), [], "r"), [])
        self.assertEqual(formats._label_value_hits(self._chars("Phone: Phone3"), [], "r"), [])
        self.assertEqual([f.original for f, _ in formats._label_value_hits(self._chars("ИНН 391780587105, тел."), [], "r")], ["391780587105"])


class OwnLabelGarbleIsNotResidual(unittest.TestCase):
    """Verify of full-page scans: our drawn labels misread by OCR are masked by position, real values stay."""

    def _layer(self, words):
        page = fitz.open().new_page(width=600, height=200)
        chars = PageChars(page)
        x = 10
        for w in words:
            ocr.add_ocr_chars(chars, [ocr.Word(w, x, 20, x + 8 * len(w), 36, 0)])
            x += 8 * len(w) + 8
        return chars

    def test_mask_by_position_keeps_foreign_text(self):
        chars = self._layer(["Email:", "omal@examgls.com", "tail"])
        email = next(c for c in chars.chars if c.c == "@")
        rect = fitz.Rect(email.x0 - 40, 18, email.x1 + 60, 38)
        masked = formats._mask_drawn_chars([chars], {0: [(rect, "email1@example.com")]})
        text = chars.view("lines").text
        self.assertGreater(masked, 5)
        self.assertNotIn("@", text)
        self.assertIn("Email:", text)
        self.assertIn("tail", text)

    def test_word_level_box_masks_only_the_token_part(self):
        page = fitz.open().new_page(width=600, height=200)
        chars = PageChars(page)
        ocr.add_ocr_chars(chars, [ocr.Word("Свидетел+Name5", 10, 20, 150, 36, 0)])
        for c in chars.chars:                       # layer without per-letter boxes: every letter shares the word box
            c.x0, c.x1 = 10, 150
        formats._mask_drawn_chars([chars], {0: [(fitz.Rect(100, 20, 150, 36), "Name5")]})
        text = chars.view("lines").text.strip()
        self.assertTrue(text.startswith("Свидетел") and "Name" not in text, text)

    def test_label_word_like_needs_a_word_of_the_document(self):
        vocab = {"резервный", "свидетель", "сервер"}
        for ok in ("резервныйр2", "Свидетел+", "розервный(р2", "Серверір1"):
            self.assertTrue(formats._label_word_like(ok, vocab), ok)
        for bad in ("tiger2", "Rv159!kd2556Pm", "резервный12345", "sk_live_5508632q18247646Xw"):
            self.assertFalse(formats._label_word_like(bad, vocab), bad)

    def test_alien_example_email_only_without_similar_original(self):
        originals = ["yuki.whitfield56@demo-mail.example.com"]
        self.assertTrue(formats._alien_example_email("omal@examgls.com", originals))
        self.assertTrue(formats._alien_example_email("Yomaika@oxamja.com", originals))
        self.assertFalse(formats._alien_example_email("yuki.whitfeld56@exampls.com", originals))
        self.assertFalse(formats._alien_example_email("john@corp.org", originals))
        self.assertFalse(formats._alien_example_email("john@example.com", originals))

    def test_public_labels_and_short_values(self):
        self.assertTrue(formats._public_label("ИНH"))
        self.assertTrue(formats._public_label("СНИЛС:"))
        self.assertFalse(formats._public_label("Иванов"))
        self.assertIsNone(formats._PLAIN_LABEL_WORD.fullmatch("Rv159!kd2556Pm"))
        self.assertIsNone(formats._PLAIN_LABEL_WORD.fullmatch("sk_live_550863"))
        self.assertTrue(formats._PLAIN_LABEL_WORD.fullmatch("attn Redwood"))
        self.assertTrue(formats._PLAIN_LABEL_WORD.fullmatch("alt"))
        self.assertIsNone(formats._REAL_IP.search("08::"))
        self.assertTrue(formats._REAL_IP.search("192.168.1.15"))
        self.assertTrue(formats._REAL_IP.search("fe80:0:0:1::5"))


if __name__ == "__main__":
    unittest.main()
