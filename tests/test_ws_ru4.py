"""W3 residuals: bare surname after cue words (invented surnames, not from any case file)."""
import unittest

from tests.helpers import Env

_E = Env()


def _scan(text):
    d = _E.service.build_detector(_E.service.settings_for({}))
    d.harvest(text, "x.txt")
    return d.scan(text, "x.txt", "text")


def _flagged(text, word):
    pos = text.index(word)
    return [f for f in _scan(text) if f.start <= pos < f.end]


class CueSurnameTests(unittest.TestCase):
    def test_ru_judicial_cue(self):
        for w in ("Брундель", "Шалтыров", "Мельтуш", "Пстыга", "Рыкунец"):
            for t in ("Свидетель {} подтвердил показания.", "Заявитель {} обратился в суд.", "Ответчик {} возражает."):
                self.assertTrue(_flagged(t.format(w), w), t.format(w))

    def test_en_cue(self):
        for w in ("Brindlecott", "Varnholt", "Quelmar", "Zandt"):
            for t in ("Witness {} confirmed the statement.", "Director {} approved the budget.", "Signed by {} on Monday."):
                self.assertTrue(_flagged(t.format(w), w), t.format(w))

    def test_generic_words_stay_quiet(self):
        for t, w in (("Director General approved the budget.", "General"), ("Manager Operations met the Board.", "Operations"),
                     ("Signed by Monday the contract starts.", "Monday"), ("Witness Statement attached.", "Statement")):
            self.assertFalse([f for f in _flagged(t, w)], t)


class OcrTextTests(unittest.TestCase):
    def test_initial_without_period_after_cue(self):
        self.assertTrue(_flagged("attn Marcus R Haverford", "Haverford"))
        self.assertFalse(_scan("See Appendix A Contract and Plan B Strategy."))

    def test_ocr_damaged_provider_key_after_label(self):
        for t, k in (("token = sk live_705871Z081428808XW", "705871"), ("API key: sk live 550863Zq18247646X", "550863")):
            self.assertTrue(any(f.category == "SECRET" and f.decision.value == "AUTO" for f in _flagged(t, k)), t)


if __name__ == "__main__":
    unittest.main()
