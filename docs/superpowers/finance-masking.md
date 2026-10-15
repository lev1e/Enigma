# Finance masking (xlsx)

Off by default (`finance_numbers`). When on, money amounts in a workbook are multiplied by one secret factor k = p/10000
(per sheet with `finance_scale_per_sheet` when sheets do not reference each other's amounts). The factor lives only in the vault.

## What the owner must know

- **The restored file is value-identical, not byte-identical.** Every cell value is restored in original units (numbers compared as
  Decimal, rounded to kopecks above 100), formulas are kept as text, cached formula results are cleared and Excel recalculates on open.
  XML ordering, shared-string layout and style ids may differ from the input.
- **Ratios stay visible.** Scaling hides magnitudes, not proportions: margins, growth rates, shares of total, and the relative size of
  any two amounts are identical in the masked file. Someone who knows one real figure can recover k. Percent cells, years, counts,
  dates and rates are intentionally not scaled.
- Precision: Excel keeps 15 significant digits. Masked values are capped at 15 digits (`_cap_sig`); sums of masked values equal the masked
  sum up to that cap, and `_tie_out` moves the rounding difference into the largest row of a `SUM` range so totals still tie.
- Conflicts: formulas that multiply two amounts, look up by amount, compare an amount with a literal, or turn an amount into text cannot be
  scaled consistently. Their inputs stay **visible** and the file is marked "attention" with a named warning per cell
  ("Sheet X, cell B14: ..."). In `kpi_dashboard` and `consolidated_multisheet` this leaves all amounts visible: treat such files as not masked.

## Surfaces covered outside cells

conditional formatting and data-validation formulas, DV error/prompt text, number-format literals, comments (legacy and threaded), drawing and
chart text, chart axis limits (when the series is scaled, including formula series), chart caches (dropped/rewritten), pivot cache values that equal a
masked amount, defined-name constants (hidden ones too, any value from 100000), text amounts in cells (`finance_text_amounts`, e.g. "4,2 млн",
"USD 6,250,000"), numbers stored as text in money rows. Every replacement is recorded in the vault for restore.

## Output check and warnings

`verify_output` scans every XML part (theme/styles and DrawingML colour attributes excluded) for the masked originals; round amounts from
100000 count as secrets. A leak blocks the file. Unrecognised numbers >= 1000 are reported as named warnings (cell addresses, not values).

## Restore of an AI-edited file

`finance_restore.restore_by_patch` aligns the returned file with the snapshot of the issued file (rows by content/labels, columns by
signature) and converts edits back. Contract (tests/test_ws_finance_restore.py, 53 scenarios): a wrong number is never silent; it is flagged and
status is not "ok". Known flagged cases: unlabeled new numbers, constants inside formulas, numbers typed as text, new sheets without labels.

## Tools

`python tools/finance_probe.py --synthetic --real DIR` masks and restores, greps every part for masked amounts and diffs restored cell values.
