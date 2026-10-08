# jev-screen

## Human review CSV · CSV de revue humaine · CSV de revisión humana

Run `PYTHONPATH=src python3 -m examples.csv_review_queue` to export the `maybe` records from the synthetic three-record pilot. The CSV is a review queue, never an automatic exclusion list. / La commande exporte les dossiers `maybe` pour une revue humaine, jamais une liste d'exclusion automatique. / El comando exporta los registros `maybe` para revisión humana, nunca una lista de exclusión automática.

**Title/abstract screening for systematic reviews: screen thousands of bibliographic records against explicit inclusion and exclusion criteria with Jev, get include / exclude / maybe buckets with a reason per criterion, PRISMA counts, RIS exports, and agreement plus recall against your human screeners.**

[![Tests](https://github.com/gbesse/jev-screen/actions/workflows/test.yml/badge.svg)](https://github.com/gbesse/jev-screen/actions/workflows/test.yml) ![MIT](https://img.shields.io/badge/license-MIT-blue) ![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue) ![Public alpha](https://img.shields.io/badge/status-public%20alpha-orange)

jev-screen is a **second screener or a prioritizer, never a sole decider**. Recall is the metric that matters at this stage of a review; the tool routes uncertain records to a human and reports recall with confidence intervals so you can see how little a pilot actually proves. Standard library only; nothing to install besides Python 3.11+.

## 30-second offline quick start (no key, no network)

```sh
git clone https://github.com/gbesse/jev-screen.git
cd jev-screen
PYTHONPATH=src python -m examples.offline_demo
```

The demo screens 30 synthetic, fictional records with fixture probabilities (hand-written, **not measured Jev output**), then prints PRISMA counts, a ranked reading order and agreement statistics against a synthetic human file. Optional editable install: `python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`, after which `jev-screen` is on the venv path and `PYTHONPATH` is not needed.

For a smaller CSV pilot, run `PYTHONPATH=src python -m examples.csv_pilot`. Three fictional records show one `include`, one `exclude` and one `maybe` decision with their first reason. The script writes its output to a temporary directory, uses synthetic fixture probabilities and makes no API call.

## Call real Jev

```sh
export TYPESAFE_API_KEY=...            # requests are paid and go to https://api.typesafe.ai
jev-screen estimate records.ris --criteria criteria.json          # tokens, requests, cost; no call
jev-screen screen records.ris --criteria criteria.json --out decisions.csv --export-dir out/ --cache
jev-screen prisma decisions.csv
jev-screen rank decisions.csv --top 50
jev-screen agreement decisions.csv human.csv
```

Only the title and abstract of each record are sent. `--cache` stores validated answers in `.jev-cache.json` keyed by the exact request, so re-runs with the same criteria are free; `screen` resumes from the ids already in `--out`. Cost order of magnitude: 5,000 abstracts with 6 criteria is roughly 3 million input tokens, about USD 0.13 at the published USD 0.042 per million input tokens (an estimate from the price list, not a quote). Official SDKs exist (`typesafe-sdk` on PyPI, `@typesafe-ai/sdk` on npm); this repository ships its own minimal client so users install nothing.

Inputs: RIS (`.ris`), PubMed MEDLINE (`.nbib`), CSV (`id,title,abstract,year,doi[,authors]`). `.txt` files are sniffed. Outputs: `decisions.csv` (one row per record with decision, reason, `inclusion_score`, one `p_<criterion>` column per criterion, tokens, cache flag) and, with `--export-dir`, `included` / `excluded` / `maybe` as `.ris` (decision in an `N1` note), `.csv` and `.jsonl`.

## Criteria file

```json
{
  "review": "Digital self-management programs and glycaemic control in adults with type 2 diabetes",
  "inclusion": [
    { "id": "population", "statement": "The study population consists of adults with type 2 diabetes",
      "true": "Adults diagnosed with type 2 diabetes ...", "false": "Children, animals, type 1 only ..." }
  ],
  "exclusion": [
    { "id": "animal", "statement": "The study is conducted in animals or in vitro only" }
  ],
  "thresholds": { "include_min": 0.7, "exclude_max": 0.3 },
  "unknown_policy": "maybe"
}
```

`true` / `false` are optional criteria descriptions passed to Jev. `unknown_policy` (`maybe` or `exclude`) applies to records the model never sees (no abstract). See `examples/criteria.json` for a full file.

## Library use

```python
from jev_screen import JevClient, FakeJev, load_criteria, load_records, screen_records, ResultCache

criteria = load_criteria("criteria.json")
records = load_records("records.ris")
provider = JevClient()                       # reads TYPESAFE_API_KEY; or FakeJev.load("fixtures.json")
results = screen_records(records, criteria, provider, cache=ResultCache(".jev-cache.json"), concurrency=8)
for r in results:
    print(r.record.id, r.decision.label, r.decision.reason, r.probabilities)
```

`screen_records` raises on any provider error; nothing is swallowed.

## How it decides

- One request per record: state `{ "title", "abstract" }` and one `noul` question per criterion, evaluated in parallel by Jev (fan-out). Authors, year and identifiers are never sent: irrelevant state lowers accuracy and they do not decide eligibility here.
- Each question's `instructions` is the criterion `statement`; `criteria: { true, false }` is added when you provide descriptions. Model pinned to `jev-1.13.0`; the response is validated (model, every answer present and typed `noul`, probabilities in [0, 1]) or rejected.
- Rule (code, not model): **include** when every inclusion p >= `include_min` and every exclusion p <= `exclude_max`; **exclude** when any inclusion p <= `exclude_max` or any exclusion p >= `include_min`, recording the first failing criterion in file order (`inclusion:population`, `exclusion:animal`); otherwise **maybe**, recording the first uncertain criterion (`uncertain:intervention`). No abstract: `maybe` with reason `no_abstract` unless `--title-only`.
- `inclusion_score` = minimum of inclusion probabilities and `1 - exclusion probability`: a weakest-link score used by `rank` and by WSS@95.
- Thresholds 0.7 / 0.3 are illustrative defaults, not calibrated guarantees. `docs/method.md` explains how to calibrate them on a pilot of ~200 human-screened records, and why recall comes first.

## Boundaries

- Not a sole screener. It is meant to be the second screener of a pair, or to order the reading list for humans. Read the `maybe` bucket; audit the `exclude` bucket on your pilot before trusting it.
- Title and abstract only: no full-text retrieval, no deduplication, no data extraction.
- Jev weaknesses that matter here (docs.typesafe.ai/model-jaggedness/jev-1.13): literal reading of statements, unreliable counting and numeric/date comparison (keep "at least 12 weeks" for full-text), lower accuracy on non-English text and on large irrelevant state, and susceptibility to instruction-like text inside abstracts. Probabilities from separate questions are independent and are not combined arithmetically.
- No live benchmark is claimed. The demo's probabilities are synthetic, and the demo deliberately contains a human include the fixtures miss (`S20`) and a human include with no abstract (`S24`) so the WSS@95 line shows what a false negative and a missing abstract cost.
- `agreement` uses the ids present in both files; human labels other than include/exclude are counted and ignored.

## Validation

```sh
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src python -m unittest discover -s tests
PYTHONPATH=src python -m examples.offline_demo
```

CI (`.github/workflows/test.yml`) runs exactly these on Python 3.11 and 3.13 after `pip install -r requirements-dev.txt`. Tests cover the three parsers (multi-line abstracts, alternative tags, missing fields), RIS round trip, the decision table with first-reason ordering, PRISMA counts, kappa / Wilson / WSS against known values, cache and resume, client retries and validation on a loopback fake server, and the fake provider path. No test or CI step calls Jev. `scripts/live_smoke.py` makes at most two real requests when `TYPESAFE_API_KEY` is set; it is opt-in and manual.

## Related projects

- [DecisionPacks](https://github.com/gbesse/decisionpacks): versioned decision rules over Jev answers, if you want the include/exclude policy as a shareable pack.
- [Question Forge](https://github.com/gbesse/question-forge): help writing criteria statements that survive Jev's literal reading.
- [Autonomy Meter](https://github.com/gbesse/autonomy-meter): measuring how much of a workflow can be left to automated decisions, which is the question behind "second screener vs sole decider".

Independent project; not affiliated with TypeSafe AI. API reference: https://docs.typesafe.ai/api. Model limits: https://docs.typesafe.ai/model-jaggedness/jev-1.13.

## October 2026 improvement · Amélioration d’octobre 2026 · Mejora de octubre de 2026

Run `PYTHONPATH=src python3 -m examples.csv_review_queue` to export only `maybe` records with title and inclusion score, ordered for human review. The fixture is synthetic.

Exécutez `PYTHONPATH=src python3 -m examples.csv_review_queue` pour exporter seulement les dossiers `maybe` avec titre et score d’inclusion, classés pour la revue humaine. La fixture est synthétique.

Ejecute `PYTHONPATH=src python3 -m examples.csv_review_queue` para exportar solo los registros `maybe` con título y puntuación de inclusión, ordenados para revisión humana. La muestra es sintética.
