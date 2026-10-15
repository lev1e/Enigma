# S9G: NER on markup documents (branch ws/s9g)
Labels: [M] measured. natasha 1.6.0, Python 3.12. Corpus: tests/eval/real (not case/), service path (Env.anonymize, ner_candidates on), md/txt first 150k chars, html first 400k raw chars. Script in /tmp, not committed.

## Change (anonymizer/ner.py)
Old: `eligible()` rejected the whole document if `_MARKUP` matched in the first 4000 chars. New: when the head has markup, the document is masked in place (same length, markup replaced by spaces, so offsets stay valid) and the veto applies only if the masked share of non-space chars exceeds `MARKUP_MAX_SHARE = 0.75`. Masked: fenced code, `{{...}}` templates (nesting-aware, up to 30k chars), `[[Файл:/Категория:...`, `[[target|` (display text stays), stray `[[ ]] {{ }}`, URLs, html tags, `|param =`, `\cmd{`. NER literals are matched on the masked text and a match is dropped if the original slice differs (name split by markup). Documents with no markup in the head: untouched (`working_text` returns the same object).
Measured share masked [M]: md_ru_putin 0.69, md_ru_gazprom 0.60 (now eligible); raw html cheb 0.85, pushkin 0.80, tver 0.84 (stay vetoed).

Texts shorter than `MARKUP_MIN_TEXT = 2000` chars with markup in the head keep the old whole veto (tag fragments in cells; caught by test_ws_ner).

## Finding that corrects the request [M]
html_ru_* never hit the veto in the product path: `transform_text_file` feeds `Structure(...).masked` (tags blanked) to the detector, `eligible()` is already True there and NER already runs (700 spans on cheb). Before/after output for all 6 html docs is identical. The S9C "review 100 -> 209" was measured on text that still had markup. Only md was really vetoed.

## Numbers (before -> after) [M]
| doc | AUTO person strings | extra AUTO names | wrong (read) | review items |
|---|---|---|---|---|
| md_ru_putin | 334 -> 346 | +12 (Тони Блэра, Роя Медведева, Марина/Мариной/Марины Салье, Саддама Хусейна, Дэвида Клиланда, Блэр Тони, Голдман Маршалл, Салье, Гэдди, Нормана, Хорстом); -1 (Медведева, now inside "Роя Медведева") | 2 partial (Нормана, Хорстом: first names only) | 215 -> 217 (+0.9%) |
| md_ru_gazprom | 114 -> 114 (Елена Касьян AUTO, "Helen" -> review) | +1 | 0 | 135 -> 136 (+0.7%) |
| html_ru_cheb, gazprom, moscow, pushkin, sber, tver | unchanged | 0 | - | unchanged (107/118/156/228/101/129) |
| controls txt_ru_putin / sber / moscow | unchanged | 0 | - | unchanged |
Review growth stays far below +20% (max +0.9%).

## Gates
- Leaked: `tools/eval_real.py run --only md_ru_putin,md_ru_gazprom,html_ru_cheb,html_ru_tver --jobs 2`: gold 44 each, leaked 0, opens True, restore True on all 4. real_results.json restored.
- Still-vetoed documents behave as before: test `test_vetoed_document_output_identical_with_ner_on_and_off` (findings and review list equal with ner_candidates on/off), `test_mostly_markup_keeps_whole_document_veto`, `test_no_markup_text_untouched` (same object, no mask).
- Tests: tests/test_ws_s9g.py 8 OK; s9g + s9c + s8a + w7b + s7c + s7d + s6c + s8b = 100 OK; + test_ws_ner OK.

## Speed [M]
Masking costs 0.1 s per 619k chars (process time; 2 % of the NER time). Running natasha on a markup md now costs about 5 s per 619k chars (person_spans 5.0 s, three runs), which is the normal NER cost already paid for txt; whole pipeline md 619k: about 14.1-15.1 s old -> 17.6 s new with NER on, 13-16 s with NER off (machine shared, noisy). So the +10% limit is NOT met for md docs that previously got no NER at all; it is met for the filter itself (<1 %) and for every document that was already eligible (no change). Nothing to trade without dropping the accuracy layer for md.

## Unverified
Wikipedia md only; no real LaTeX/RST documents in the corpus; the threshold 0.75 is tuned on the 8 documents above plus a synthetic code/html case.
