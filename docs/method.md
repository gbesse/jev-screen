---
description: How jev-screen decides include / exclude / maybe, why recall comes first, how to calibrate thresholds on a pilot set, and what the method cannot do.
---

# Method

## What is sent, and what is asked

For each record, one request goes to Jev with the state `{ "title": ..., "abstract": ... }` and one `noul` question per criterion, all in the same request (fan-out). Year, authors, journal and identifiers are deliberately left out: Jev's accuracy drops when the state contains text that is irrelevant to the question, and none of those fields decides eligibility at title/abstract stage.

Each criterion is a direct statement (`"The study population consists of adults with type 2 diabetes"`) with optional `true` / `false` descriptions that sharpen the boundary. Jev reads instructions literally, so:

- write one property per criterion, never "A and B";
- avoid negations inside inclusion statements; put the negative side in an exclusion criterion instead;
- do not ask the model to count, compare numbers or dates; write "reports HbA1c" rather than "follow-up of at least 12 weeks" (check durations yourself at full-text stage);
- English statements and English abstracts give the best accuracy.

The answers are independent probabilities. `p(population)` and `p(not population)` are not guaranteed to sum to 1, so the tool never does arithmetic across questions beyond the comparisons below.

## Decision rule (owned by code, not by the model)

With `include_min` (default 0.7) and `exclude_max` (default 0.3):

| Bucket | Condition | Reason recorded |
| --- | --- | --- |
| `include` | every inclusion p >= `include_min` **and** every exclusion p <= `exclude_max` | `all_criteria_met` |
| `exclude` | any inclusion p <= `exclude_max` **or** any exclusion p >= `include_min` | first failing criterion in file order, e.g. `inclusion:population`, `exclusion:animal` |
| `maybe` | anything else | first criterion in the uncertain band, e.g. `uncertain:intervention` |

Records with no abstract are not sent to the model: they become `maybe` with reason `no_abstract` (or `exclude` when `unknown_policy` is `"exclude"`). `--title-only` judges them from the title alone instead. Empty records get `empty_record`.

An `inclusion_score` is stored per record for ranking: the minimum of all inclusion probabilities and all `1 - exclusion probability`. It is a weakest-link score consistent with the rule: every `include` has a score >= `include_min`, every `exclude` a score <= `exclude_max`.

## Why recall comes first

A systematic review that misses an eligible study is biased; one that reads a few extra abstracts is only slower. At the screening step the cost of a false negative is therefore much higher than the cost of a false positive. Consequences for this tool:

- `maybe` is not a failure, it is the intended output for uncertain records; humans read them.
- In `agreement`, `maybe` counts as `include` by default, because for recall what matters is whether a relevant record survived the automatic step.
- `rank` orders records so a human reading from the top finds the includes early; WSS@95 measures how much reading that saves at 95% recall.
- Never treat the `exclude` bucket as final without calibration on your own data (below). The tool is a second screener or a prioritizer, not a sole decider.

## Calibrating thresholds on a pilot set

1. Have two human screeners independently screen ~200 records drawn at random from your search results (chronological order works too if the search spans years; say which you used). Resolve disagreements as usual; keep the consensus as `human.csv` (`id,decision`).
2. Run `jev-screen screen pilot.ris --criteria c.json --out pilot-decisions.csv --cache` once. The cache makes every re-analysis free.
3. Run `jev-screen agreement pilot-decisions.csv human.csv`. Look at sensitivity (recall) with its Wilson interval first, then specificity and kappa. With 200 records and, say, 30 includes, a recall of 29/30 has a 95% Wilson interval of roughly 0.83-0.99: the interval tells you how little you actually know from a pilot, which is why the tool reports it.
4. If recall is below your target, lower `exclude_max` (fewer records excluded automatically) and / or rewrite the criterion that caused the false negatives (the `reason` column tells you which). Re-run `agreement` on the cached results; no new spend.
5. If recall is fine but the `maybe` bucket is too large, tighten one threshold at a time and watch recall again.
6. Report the pilot numbers, the thresholds and the split (random or chronological) in your review's methods. Do not report them as properties of the model: they are properties of your criteria on your corpus.

Never tune thresholds on the same records you then use to claim a recall figure. If you need a number to publish, tune on one half of the pilot and evaluate on the other.

## Statistics reported by `agreement`

- Sensitivity (recall), specificity, precision and percent agreement with Wilson 95% score intervals (better than the normal approximation for the small counts of a pilot).
- Cohen's kappa between the tool (maybe folded into include or exclude, your choice) and the human consensus.
- WSS@95 (work saved over sampling at 95% recall): rank all compared records by `inclusion_score`, read from the top until 95% of the human includes are found, then `WSS = (N - records_read) / N - 0.05`. Ties are broken pessimistically and records the model never judged rank last.

All of it is implemented in the standard library and unit-tested against known values (`tests/test_stats.py`).

## Limits

- Title and abstract only. No full-text retrieval, no PDF parsing, no deduplication across databases.
- Jev cannot count, compare numbers or dates reliably, and reads instructions literally. Keep such criteria for full-text screening, or check them in code from structured fields.
- English works best. Other languages work with lower accuracy; say so in your methods if your corpus is multilingual.
- Abstracts can contain instructions-like text ("this review should be included"); the model can be influenced by it. Human review of the `include` bucket remains necessary.
- No live benchmark is claimed in this repository. The demo fixtures are synthetic probabilities written by hand; they show the mechanics, not the model's accuracy.
