# Excel financial masking: independent assessment

Scope: read-only review of WIP commit a239ac0 (branch `worktree-agent-a6fd8343b68e0fd43`) and main's xlsx handling. No product code, tests or existing docs were changed. All experiments ran from the worktree with throwaway scripts in the session scratchpad (`exp1`..`exp8`); outputs quoted below are from those runs. Status labels: **[impl]** exists in code, **[tested]** I ran it and saw it work, **[untested]** exists but not exercised, **[proposed]** does not exist. The finance code has no tests of its own (`tests/test_ws_finance.py` and `docs/superpowers/finance-masking.md` do not exist), so "tested" below means my experiments, not the repo.

## 0. Verdict in one paragraph

The WIP is better than "never executed" suggests: it imports, masks and restores all five corpus workbooks, restores unedited cells exactly, and the dimensional formula analysis is a genuinely good idea. But as a *system* it fails the owner's objective in four independent ways: (1) it decides what to mask with Russian/English label regexes and misses or over-fires on real files; (2) a uniform multiplier leaks every ratio, growth rate, sign and equality and falls to one known figure; (3) restoration of AI-modified workbooks is positional and silently wrong for several of the most common AI edits (pasted values, inserted rows, new sheets, unlabeled rows); (4) its safety net (`verify_output`) both misses real leaks and falsely blocks innocent files. The concept "mask numbers so a formula-preserving copy can be computed on" is sound only for a narrow class (pure-linear, single-currency P&L/balance models). The recommended architecture is **patch-the-original with a thin masked view** (section 3), with scaling kept only as a per-block, opt-in transform for blocks the user wants the AI to calculate on.

## 1. Evidence on the current implementation

### 1.1 What works [tested]
- All five generated workbooks (`tools/make_finance_corpus.py`) anonymize and restore; restored cell values equal the originals for pl_model (only the array-formula object compares unequal by identity), simple_model, inconsistent_model, balance_sheet, cap_table (exp1).
- Money vs non-money: shares (4,000,000) and percents left unscaled in cap_table, prices scaled, `=B*D` still dimensionally valid (exp1).
- Formula text untouched; cached results dropped; hidden and veryHidden sheet values scaled (exp1, exp6); restore survives sheet rename (sheetId match) and lost stamp (fallback matching by values, `finance.py:808-830`).
- Dimensional conflict detection works on the obvious case: `IF(B1>B4,...)` with a scaled revenue and an unscaled "Порог" constant excluded the revenue and raised a conflict (exp7).

### 1.2 Failures found [tested]

| # | Finding | Evidence |
|---|---|---|
| F1 | **Integer drift breaks ties.** Scaled values are rounded to the original decimal places (`scale_value`, finance.py:65). A balance sheet that balances to 0 shows residual +1/-1 in 2 of 5 runs; total of 30 expense lines differs from k*sum by mean 11, max 96 units. Balance checks and reconciliations fail in the masked file the AI works on. | exp2 |
| F2 | **Small prices lose precision.** Price 1.5 becomes 0.7 (true 0.645) and 0.0125 becomes 0.0054 because rounding uses the original number of places. `E=B*D` totals are off 1-8%. | exp1 cap_table |
| F3 | **Pasted values are not un-scaled.** If the AI replaces a formula cell with a computed constant (gross profit B6), restore leaves it in masked units: 1,422,284 instead of 1,680,000, status `ok`. The code skips cells listed in the record's `f` list (finance.py:880). | exp4 H |
| F4 | **Inserted row shifts constants onto former-formula cells and they stay masked.** After `insert_rows(3)` the "Управленческие расходы" row restored to 175,244 instead of 250,000 (and C-E likewise), no warning. | exp4 C |
| F5 | **New rows with unrecognised labels are not restored.** Labels "Прогноз выручки" and "Бонус"-less rows work; "Фонд Альфа" (2,222,222) and "Итого прогноз" (9,999,999) were left in masked units. Whether a new number is divided depends on a regex over the row label (`classify_cell`), so correctness depends on the AI's wording. Status `ok`. | exp3 B |
| F6 | **New sheets are never restored.** Restore loops only over sheets in the vault record (finance.py:840). A sheet "AI_Forecast" with `Выручка прогноз 1,000,000` stays 1,000,000 (masked scale). Status `ok`. | exp3 D |
| F7 | **Edit path rounding.** Edited/shifted cells go through `unscale_value`, which rounds to the original decimals; with k<1 error reaches 1.16 units (mean 0.39) on integers. Minor but means "exact restore" is only exact for untouched cells. | exp4 |
| F8 | **Leaks outside cells.** In a workbook with conditional formats, data validation, defined-name constants, number-format literals, comments and text labels, the masked file still contained: CF thresholds 10,000,000 / 1,234,567 / 9,876,543; DV bounds 1,500,000 / 25,000,000 and list "3100000,3200000"; defined name `Limit` 3,750,000 and `Tax_Threshold` 8,888,888 (name not in the money dictionary); comment "17 850 000 руб"; text "Порог сделки 15 000 000 руб"; format literal `"из 2 900 000"`. Status `attention`, nothing blocked, nothing named in warnings. | exp6 |
| F9 | **`finance_text_amounts` is a no-op for abbreviated amounts.** The comment "4,2 млн ₽ плановая выручка" survives with the option ON because `_scale_text` returns early when the digits are `< 100` (finance.py `if value < 100`), ignoring the "млн" multiplier. | exp5 |
| F10 | **`verify_output` misses (F8, F9) and false-blocks.** It builds its secret set only from scaled *cells* and ignores values with fewer than 3 significant digits (4,200,000 is skipped), so non-cell sources are invisible. Conversely it searches every part for any scaled original value as a bare number token, so an unscaled number elsewhere equal to a scaled original blocks the file. With finance ON, 3 of the 5 real-corpus xlsx that contain numbers returned status `error` "остались настоящие суммы" (syn_invoice_ru, poi_xlsx_7 with 4,310 numbers, poi_xlsx_5), while the same files with finance OFF were `ok`/`attention`. | exp8 |
| F11 | **Contradictory notices.** The legacy message "Числа в таблицах не обезличены (значений: 22)" is shown next to "Числа: 20 ячеек замаскировано". | exp5/6 |
| F12 | **Formulas are treated as text-safe via `_safe_formula`** and skipped from the prose detector, which is correct; but formulas containing sheet names or string literals still reach the prose detector. This is the pre-existing audit item (audit-0810 #15), not new. | audit-0810-formats.md:296 |

### 1.3 Structural limits [impl, by reading code]
- Classification is label/format regex (`NONMONEY`, `MONEY`, `CURRENCY_*`, finance.py:93-103; `classify_cell`:320). It reads the row label as the text in the first and last text cell left of the cell, the column header as the nearest text above. English/Russian only. Labels that are numbers, merged headers, multi-row headers, labels in other sheets or right-to-left layouts degrade to `unknown` which is *not masked* (confidential-by-default is reversed: unknown means exposed). Fallback "thousands format on financial sheet" is the only recall booster.
- Single factor per workbook (`make_factor`, k in [0.37, 2.9], excluding a handful of "round" ratios). `per_sheet` option falls back to the shared k whenever any cross-sheet reference exists (`build_plan`, ~lines 570-595) and is conservative (any unparsable formula counts as cross).
- `MAX_ITER = 40` exclusion loop: when a conflict is found, *all precedents* are un-masked (`excluded |= deps`). One `price*quantity*rate` formula can expose a whole block with the user told only "N warnings".
- Formula support is a custom parser (`finance_formula.py`, 551 lines). Functions beyond the hard-coded set, INDIRECT/OFFSET, LET/LAMBDA, dynamic arrays, structured table refs with edge cases, data tables, external links: [untested]. Unparsable formula = `BAD` = treated as unknown/conflict.
- Vault record stores original values in plaintext inside the encrypted vault `finance` dict. Size scales with cell count (no streaming) [untested at 100k+ cells].
- Charts: numCache points are rewritten from scaled cell values or removed; pivot caches set to zero with refreshOnLoad [impl, untested with a real pivot; no real pivot in corpus]. External-link caches zeroed [untested].

### 1.4 Information-theoretic leakage of one multiplier [reasoned, partly tested]
- Every ratio is exact: margins (B8, F8), growth `C2/B2`, mix, balance-sheet leverage, covenant ratios. The tool's own notice admits it. For a P&L the ratios are usually *the* confidential content (margin, growth, cost structure); the absolute scale is the least sensitive part.
- Equalities, ordering, signs, zeros and repeated values survive (B5=C5=542,869 in exp1). Time-series shape survives. Benford-type digit statistics approximately survive.
- Known-value attack: any single publicly known or guessable figure (a disclosed revenue, a round contract price, a share count x price) gives k, and then all values. The WIP's k range [0.37, 2.9] with p/q up to ~10^4 does not matter once k is estimated from one pair; per-sheet factors are disabled whenever sheets reference each other, which is exactly the models where they matter.
- Because shares/percent/dates/years are left clear and money is scaled, the *composition* "shares x price = amount" lets k be solved from the visible quantity if price is guessable.
- Label text (row names, sheet names) stays and tells the AI exactly what each number is, which is what makes the file useful; it is also what pins values to public benchmarks.

Threat-model conclusion: scaling protects against *casual disclosure to a third-party AI provider* (someone reading the file cannot see the amounts). It does not protect against an adversary with any side information, and it does nothing for ratios. If the owner's threat is "the provider trains on or leaks our figures", scaling is adequate for absolute magnitudes only. If the threat is "competitor reads our margins", scaling is not a protection at all. This must be stated in the UI, and the product should pick a threat model rather than imply both.

## 2. The proposed workflow vs the actual architecture

| Step | Owner's vision | Actual (WIP) | Status |
|---|---|---|---|
| 1 Analyze | Scan structure, financial context, formulas, dependencies, sensitive info | `Model` parses cells, formats, defined names, tables; `Analysis` does degree propagation over formulas. No inventory of hidden rows/cols, CF, DV, comments, external links, pivots, connections, VBA, docProps, named ranges as a report | partial [impl], inventory [proposed] |
| 2 Classify | Only what needs masking | Binary money/dimless/unknown by regex; unknown = not masked; no sensitivity notion, no "public/immaterial" class, no document-type notion | weak [impl] |
| 3 Customize | Profiles, review, overrides at workbook/sheet/column/range/cell | 4 settings (on/off, per-sheet, text amounts, conflict policy). No overrides, no preview, no per-range anything | missing [proposed] |
| 4 Mask | Reversible, preserves meaning, formulas, formatting | Uniform scale; formulas untouched; formats untouched | [impl/tested on 5 files] |
| 5 Validate | Functional, consistent, no disclosure | Leak scan on cell values only; no recalculation, no comparison of before/after ratios, no tie-out check | weak, wrong in both directions (F10) |
| 6 AI processing | External AI edits / creates | Out of scope in the module; chat/add-in paths exist elsewhere | n/a |
| 7 Restore | Detect modifications, restore originals, transform NEW data, keep legitimate AI changes | Positional per-cell: exact if equal to masked value, else divide by k; "new" heuristic by label | fails on F3-F6 |
| 8 Verify | Compare restored vs original and intended modifications | Counter stats (exact/divided/new/missing) only. No diff report, no formula-error detection, no unresolved-masked-value detection | missing |

Two gaps are architectural rather than incremental: there is no *change detection* between what Enigma emitted and what comes back, and no *per-item decision record* the user can see and correct.

## 3. Architecture options

### A. Scaling with a vault (current)
- Security: absolute magnitudes only; ratios, signs, equalities exposed; one known value breaks it. Leaks outside cells (F8) need a separate sweep.
- Correctness: formulas keep working only where dimensional analysis succeeds; integer drift breaks tie-outs (F1); precision loss for small values (F2).
- Restore: positional; fails or silently errs for pasted values, inserted rows, new sheets, new rows (F3-F6). Division path inexact.
- UX: zero configuration, which is its strength; but no way to correct a wrong classification.
- Complexity: already ~1,500 lines; every new Excel feature (dynamic arrays, structured refs) needs formula-parser upkeep.

### B. Patch-the-original (diff and apply) [proposed]
Keep the original workbook sealed locally. Produce a *masked view* for the AI (any reversible masking, even trivial). When the modified file returns, **diff modified-masked against emitted-masked** at the cell/formula/structure level, translate each *change* back into original units (or reject it), and **apply the changes as a patch to the original workbook**, never reverse-transforming the whole file.
- Security: independent of the masking transform; can use stronger masking (below). Original never leaves.
- Correctness: unchanged cells are byte-identical by construction (no restore error is possible there). Changes are explicit, enumerable and reportable.
- Restore: handles pasted values, inserted rows, new sheets because changes are *relative to the emitted snapshot*, using row/column alignment by anchors (sheet id + header/key columns + content hash), not cell refs. Ambiguity (cannot align) becomes a flagged item instead of a silent error.
- UX: users review a change list ("12 cells edited, 1 sheet added, 3 pasted values replaced formulas") and accept or reject. Natural fit for the owner's steps 7-8.
- Complexity: higher than A for the diff, lower than A for formula semantics (it does not need to understand every function; it only needs to know which new constants are in masked units).
- Key unsolved sub-problem (shared with A): a *new constant* written by the AI is in masked units only if derived from masked values; a typed assumption ("growth 8%") is not. Neither architecture can know. Resolve by (i) AI-side prompt contract "put new inputs on an Assumptions sheet", (ii) provenance heuristics: new constant equals a formula combination of masked cells (detectable by comparing with the emitted workbook's computed values), (iii) ask the user for the rest.

### C. Hybrid: per-block factors + pseudonymization + structure-aware rules [proposed]
- Partition cells into *dependency blocks* (connected components of the formula graph over money cells, cut at "free" boundaries such as a link cell the user marks as an interface). Independent blocks get independent factors; chain-coupled blocks share one.
- Some blocks need not preserve arithmetic at all (a transaction list of customer payments, a salary register): pseudonymize or randomize with sum-preserving noise only if a total is shown; else replace with surrogates (already exists as `numbers` option).
- Rules by semantic role: keep (years, headcount, FX, tax rate that is public), scale (amounts), pseudonymize (IDs, account numbers, INN), remove (notes with amounts).
- Security: strictly better than A (ratios *across* blocks hidden; one known value opens one block). Within a block ratios still leak, deliberately, because that is what makes the block calculable. Adding affine offsets or non-linear transforms breaks formulas (SUM of scaled values is no longer the scaled SUM), so the only formula-safe transform is a linear scale per dependency-closed block.
- Complexity: needs the block graph and a clearer boundary UX; per-block k only helps when blocks are really independent (multi-sheet models with cross-sheet links are usually one block).

### Comparison

| Criterion | A scaling+vault | B patch-original | C hybrid blocks |
|---|---|---|---|
| Security vs casual disclosure | ok | depends on mask | good |
| Security vs ratios/known value | poor | depends on mask | partial |
| Formula integrity in masked view | good where parseable, drift | independent of mask | good within a block |
| Restore of untouched content | exact (cell values) | exact (byte-level) | exact |
| Restore of edits/inserts/new sheets | poor (F3-F6) | good, flagged | same as A unless combined with B |
| UX / configurability | none | change review | needs block/override UI |
| New-value unit ambiguity | unsolved | contained by review | unsolved |
| Implementation cost | sunk, ~60% more to harden | moderate | highest |
| Regression risk to existing paths | low | low (new module) | medium |

**Recommendation: B as the restoration core, with C's classification/override model and a *conservative* A as the masking transform.** Concretely: keep the scaled masked view (it is cheap and makes the AI's numbers meaningful), but stop treating "reverse the scale over the whole returned file" as the restoration mechanism. Restoration becomes "diff what the AI changed, translate, apply to original". Per-block factors are an upgrade within the same transform, and are worth doing only after the diff exists. This fits the owner's own steps 7-8 better than any variant of A.

## 4. Recommended end-to-end algorithm [proposed]

1. **Inventory (Analyze).** Enumerate every part of the package that can hold a number: sheet cells (typed, shared strings, inline), formulas and constants inside formulas, cached values, defined names, tables, CF rules, DV rules, number-format literals, comments/threaded comments, drawings/text boxes, charts (series caches and titles), pivot caches and tables, external links, connections/query tables, VBA, docProps, sheet and name labels, hidden/veryHidden sheets, hidden rows/columns, grouped/collapsed ranges. Produce a machine inventory; each item is a *candidate with a location*, not just a cell.
2. **Classify.** Give each numeric candidate: `role` (amount, price, rate, quantity, id, date, year, count, code, flag, threshold, unknown), `sensitivity` (confidential, internal, public) and `confidence`. Evidence stack, in order: user overrides; workbook structure (numeric type of neighbours, formula role such as input vs output, being referenced as a rate in `*`, a divisor, a lookup key, a SUMIF criterion); formats; labels/headers (multilingual dictionaries); optional local LLM/embedding for ambiguous labels; "uncertain" bucket. Deterministic rules decide most; the LLM never sees values, only labels and structure. Default for unknown: **mask** if the number is >= some size and sits in a financial region, otherwise keep; but surface unknown items in a short review list (see section 5), not one-by-one prompts.
3. **Dependency analysis.** Build the formula graph. Compute dimensional degree as the WIP does, but report conflicts *per block* with a plain-language cause and a one-click choice (exclude only the minimal conflicting input, keep block scaled, or accept breakage). Do not exclude all precedents by default.
4. **Mask.** Per dependency block, one rational factor; amounts that appear as *interface constants* (rate x amount) keep a block-local factor. Replace rounding-to-original-decimals with: scale to full precision, then round to at most the original *significant digits* but never fewer than 6, and run a **tie-out repair pass** (adjust the largest line in each SUM so that masked totals equal the rounded exact total; check before/after for `A-B=0` style checks). Also mask in non-cell locations: CF/DV thresholds, defined-name constants, comments, text amounts (fix the `<100` bug), format literals. Save a *mask map*: cell → role, block, factor, original-hash, emitted value.
5. **Validate (before emit).** Recompute with a formula engine over original and masked workbooks (e.g. `formulas`/`pycel`, or LibreOffice headless where available) and require: all results scale by the block factor within tolerance; no error values introduced; zero checks stay zero; sign and IF branches unchanged. Run a leak sweep over *all parts* using the inventory (not just scaled cell values), with a whitelist of values that are intentionally clear, so identical-valued clear cells do not block (fixes F10 false positives). Emit a one-page report.
6. **AI step.** Provide the AI a prompt contract: keep structure, put new inputs on a sheet named `Assumptions`, write formulas not constants where possible.
7. **Restore by patch.** Compare returned file against the emitted snapshot: per sheet, align rows by row keys (key column or hash of labels) and columns by header; classify changes: edited input, formula changed, formula replaced by constant, new row, deleted row, new sheet, renamed sheet, format-only. For each change: translate numeric constants into original units if provenance says "derived from masked values" (equal to a combination of masked cells, or entered in a cell whose neighbours are masked amounts), flag if uncertain; apply to a copy of the original workbook using an OOXML-preserving writer (edit XML in place, as `formats.py` already does, not openpyxl, which drops charts and pivots). Untouched content stays byte-for-byte.
8. **Verify.** Recompute the restored workbook; check no remaining value equals an emitted masked value that is not intended; formula errors; unresolved flagged items; checks that were zero are zero. Present a diff the user can accept or reject.

Guarantee statement: restore is *exact* for all content the AI did not touch (patch semantics), *exact* for AI edits whose provenance is unambiguous (one block factor, integer-rational division with remainder check), and *flagged* for the rest.

## 5. Customization and UX [proposed]

- **Default (zero-click):** auto-detect and show a one-screen summary: "34 amounts masked, 6 left visible (years, headcount, tax rate), 3 uncertain". No configuration required.
- **Profiles:** `Share with AI, magnitudes only` (current behaviour), `Share with AI, ratios also protected` (per-block factors + pseudonymized transaction lists), `Maximum` (labels masked too, values surrogate), `Internal / compliance` (only identifiers masked). Profiles are bundles of the rules below.
- **Review without hundreds of clicks:** present *groups*, not cells: "Column C 'Сумма' (1,204 cells) mask / keep", "Row 'Ставка НДС' keep", "Named range Limit mask". Sort by (confidence ascending, impact descending). Only uncertain groups need a decision. A heat-map preview of the sheet colours masked/kept cells.
- **Override levels:** workbook default > sheet > column/row > range > cell, each rule `mask | keep | pseudonymize | remove` plus optional `block` tag. Express as a rules list (`Sheet!C:C mask`, `*!Ставка* keep`), saved with the workbook fingerprint in the vault and reusable by name for recurring reports (monthly P&L).
- **Warnings that matter:** (1) block can't stay formula-safe, with cause and minimal fix; (2) clear numbers that could pin k (round figures, public share counts); (3) numbers in text/comments/CF/DV; (4) ratio exposure notice phrased as consequence ("margins and growth rates remain visible").
- **Feedback loop:** user corrections feed the project-level rule list; never retrain silently.
- **Do not interrupt for each uncertainty.** Single batched review, decisions remembered per label-pattern.

## 6. Mechanism choice: is a single factor optimal? [reasoned]

No. It is the *simplest formula-safe* transform, not the best. Better options in order of value:
1. **Per-dependency-block factors** (C). Cheap once blocks are known; hides cross-block ratios (e.g. revenue-to-payroll across sheets) when blocks are truly independent. Most corporate models are one block, so benefit is modest. Worth doing after the diff restore, not before.
2. **Role-based treatment.** Keep (public: statutory rates, years, FX of the day), scale (amounts), pseudonymize (IDs, transaction rows where totals are not needed), remove (free-text amounts). This is a bigger confidentiality win than varying factors.
3. **Sum-preserving noise** (jitter line items, keep totals exact) only for lists whose individual values are not analytically needed. It hides line items but not totals; use for payroll/transaction registers.
4. **Rounding/bucketing** reduces precision leakage but conflicts with tie-out; avoid in calculable blocks.
5. **Affine or non-linear transforms** break SUM/SUMIF/compare semantics; reject.

Truthful claim: nothing formula-preserving hides ratios within a block. If ratios are the secret, the honest options are (i) do not send the block, (ii) send aggregates only, (iii) send structure with surrogate values and let the AI write formulas, then apply the formulas to the original (patch-the-original shines here: the AI's *formulas* transfer, its *numbers* do not matter).

## 7. Datasets and coverage [tested]

- The finance corpus is 5 openpyxl-generated workbooks authored by the same agent as the code (`tools/make_finance_corpus.py`): one 20-cell P&L, a 3-row linear model, a deliberately conflicting model, a 10-row balance sheet, a 3-row cap table. Authored with the assumptions of the code (Russian labels in the regex dictionary), no cached values, no pivots, no real charts caches, no CF/DV/threshold names, 4 quarters, a single currency. They show the code runs, not that it generalizes.
- The real corpus (`tests/eval/real`, gitignored) contains 14 distinct xlsx: POI test files (poi_xlsx_5..9, bug files with no financial meaning, one is not a valid zip), synthetic invoices/resumes/contracts, adv_hugecell (20,000 numeric cells without formulas), a nested zip. **None is a financial model.** Only 3 of 14 contain formulas-free numbers that matter, and 3 of those were wrongly blocked by `verify_output` when finance is ON (F10).
- Main's xlsx suite (tests/test_service.py:173-278, test_llm_edits.py:176, test_extended.py:125) covers text anonymization, the older surrogate-number option, row reversal and a model sorting rows, but not money semantics.
- Measured success rate: on the 5 synthetic books 5/5 unedited round-trips exact; on 7 edit scenarios (A-H) correct in 3 (value edit, delete row, sheet rename), silently wrong in 4 (pasted value, insert-row onto formula positions, new unlabeled row, new sheet); on the real corpus, 3/5 numeric files blocked by a false positive; on the hidden-content kitchen sink, 8 categories of leak.
- Never tested: real Excel-authored files (cached values, shared formulas, `t="shared"`, array and dynamic-array formulas, `_xlfn.` functions), pivots and slicers, structured table references in practice, multi-currency models, XIRR/NPV/data tables, LibreOffice or Excel opening the output, Excel's "repair" prompts, VBA, protected sheets, large files (>100k cells), mixed-language labels, cash-flow and forecasting models with scenarios, loan schedules, the add-in (Office.js) path that returns structure.
- Needed datasets: 30-50 real or realistic anonymized models by type: P&L, balance sheet, cash flow, 13-week cash forecast, budget vs actual, scenario/sensitivity (data tables), DCF, loan amortization, cap table, payroll register, transaction ledger, KPI dashboard with pivots/charts, multi-sheet consolidations, multi-currency, English/Russian/mixed. Authored by someone other than the code author; include Excel-saved versions with cached values and hostile structures (merged headers, labels in column Z, numbers stored as text, hidden rows, grouped rows). Ground truth for each: list of cells that *should* be masked (labelled by a finance reviewer), measured by precision and recall.

## 8. Evaluation of the proposed improvements

| Proposal | What exists | Missing | Benefit | Cost | Regression risk | Verdict |
|---|---|---|---|---|---|---|
| Comprehensive XLSX component and hidden-data inspection | cells, names (partial), charts caches, pivot/ext caches zeroed | CF, DV, number-format literals, comments amounts, text labels with amounts, connections, VBA, docProps, hidden row/col report | Closes F8 which is the most direct disclosure | Medium | Low | **Worth it, first** |
| More accurate semantic classification | Regex labels/format/year/small-int | Structural evidence (formula role), multilingual, confidence, uncertain bucket, overrides, public-vs-confidential | Directly addresses "mask exactly what needs it" | Medium-High | Medium (changes what is masked) | **Worth it**, deterministic first; LLM on labels only, optional |
| Dependency-aware transformation and validation | Dimensional analysis, exclusion loop | Block partitioning, minimal exclusion, recalculation check, tie-out repair | Prevents F1/F2 and unexplained exposure | Medium-High | Medium | **Worth it** (validation via formula engine is the big win) |
| AI modification detection and restoration | Positional restore | Snapshot, alignment, change classification, patch onto original, review UI | Fixes F3-F6 and the whole class | High | Low if a new module | **Worth it, highest value** |
| Configurable rules and profiles | 4 toggles | Rule model, groups, preview, reuse | Required by owner step 3 | Medium | Low | **Worth it**, small first (workbook/sheet/column/name keep-mask) |
| Automated math integrity checks | none | engine-based recompute, ratio/zero preservation, IF-branch preservation | Catches silent breakage | Medium | Low | **Worth it** (also testing harness) |
| Stronger protection against re-identification | one factor | Per-block factors, role-based pseudonymization, public-value guard, ratio disclosure notice | Real but limited | Medium | Medium | **Defer** per-block factors; **do now** the honest notice and public-value guard; **reject** non-linear transforms and noise inside calculable blocks |

Reject: label-based "LLM decides masking of numbers with values in the prompt" (leaks the thing being protected); a universal formula interpreter inside Enigma (use an off-the-shelf engine only as a validator, never as a gate to produce output).

## 9. Prioritised roadmap with acceptance criteria [proposed]

**P0 correctness/safety (1-2 weeks).** Keep `finance_numbers` off by default, mark experimental until done.
- Fix F10: verify against an *inventory* of intended-clear values; zero false blocks on the 14-file real corpus; zero missed leaks in a synthetic leak set of at least 40 planted values in CF/DV/names/comments/formats/text.
- Fix F9 (multiplier-aware text amounts) and extend masking to CF/DV/name constants/format literals (F8): the kitchen-sink workbook (exp6) yields no original amount in any part.
- Remove silent `ok`: restore must report counts of unrestored candidates (new sheets, constants over former formula cells, unlabeled rows). Acceptance: each of exp3/exp4 scenarios B, C, D, H returns status `attention` with the cells named.
- Tie-out repair or integer-safe rounding: balance sheet residual 0 in 1,000 randomized runs.

**P1 restore architecture (3-4 weeks).**
- Snapshot of emitted masked workbook in the vault; diff by alignment; apply patch to the original through the existing XML-in-place path. Acceptance: on a scenario suite of 25 AI edits (value edit, formula edit, pasted value, insert/delete/sort rows, new sheet, renamed sheet/column, added column with formulas, deleted formula), restored workbook equals the intended result in at least 22 and flags the other 3; untouched parts byte-identical in 100%.
- Change report UI (accept/reject).

**P2 classification and customization (3-4 weeks).**
- Inventory report; role/sensitivity/confidence; override rules at workbook/sheet/column/range/cell/name; group-level review; reusable rule sets. Acceptance: on the labelled dataset (section 7) recall of confidential amounts >= 98%, precision (non-secret numbers wrongly masked) >= 90%; median user interactions <= 3 for typical files; RU/EN/mixed.

**P3 validation engine (2-3 weeks, can overlap).** Recompute original and masked via an engine: every block scales by its factor within 1e-9 relative; checks that are zero stay zero; no new errors. Run in CI over the dataset.

**P4 protection upgrades (optional).** Block-local factors, pseudonymized registers, public-value guard (warn when a clear value is a likely public anchor), ratio-exposure notice. Acceptance: with one known value per block, other blocks' absolute values are not derivable; documented residual risk.

**P5 dataset.** 30-50 workbooks per section 7 before any claim of reliability; publish measured numbers (leak rate, restore exactness, flagged-ambiguity rate).

## 10. Answers to the specific questions (short)

- *Which numbers to mask:* decide by role and sensitivity, not "number"; identifiers, amounts, salaries, prices, budgets, balances are masked; years, headcount, public rates, FX, percentages of public origin, month numbers, row indices are kept. Percentages that reveal margins or growth are as sensitive as amounts; keep them *only* if the threat model is magnitudes-only, and say so. Formula constants: keep if dimensionless (`*1.2` VAT), mask if they embed an amount (`+500000`), and when a threshold in a formula compares to an amount, mask both.
- *Context dependence:* yes, on document type, dimension and relationships; profile selects the stance.
- *Uncertainty:* batch review of groups, default by the profile, remembered rules.
- *Real threat model:* third-party AI provider and its retention, plus leakage via file transit; not an adversary with side information.
- *Restore guarantee:* exact for untouched content (patch), exact for unambiguous edits, flagged for ambiguous ones; never silent.
- *Is current algorithm sufficient for edited/new content:* no (F3-F7).
- *Do not confuse unit tests with reliability:* there are none for finance; the evidence above is from my 8 experiment scripts plus a 5-file synthetic corpus written by the code's author. Real-world reliability is unmeasured.

## 11. Residual risks of this assessment
- Not run in Excel or LibreOffice (soffice absent; Excel.app present but not driven), so recalculation, repair prompts and visual results are inferred. openpyxl was used to produce edits, which mimics common AI tools but is not the only path.
- Experiments seeded random factors; counts like "2 of 5" for drift are samples, not rates.
- Real-file coverage is the repo's gitignored corpus (14 xlsx, none financial).
