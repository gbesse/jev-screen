# AI change log

This file records the purpose and technical decisions of agent-authored changes.

## 2026-09-21 — v0.1.0, initial release

**Purpose.** Title/abstract screening for systematic reviews with Jev (TypeSafe AI System One): RIS / MEDLINE `.nbib` / CSV in, include / exclude / maybe buckets with a per-criterion reason out, PRISMA counts, RIS/CSV/JSONL exports, ranking for human screeners and agreement/recall statistics against human labels. Built as one of the wave-3 repositories from the shared spec.

**Key technical decisions.**
- Standard library only at runtime (`urllib.request` with explicit timeout, `csv`, `json`, `hashlib`, `concurrent.futures`). Package under `src/jev_screen`, console script `jev-screen`, also `python -m jev_screen`.
- One request per record with state `{title, abstract}` only and one `noul` per criterion (fan-out). Authors, year and identifiers are never sent: irrelevant state hurts Jev's accuracy and they do not decide eligibility.
- The decision rule lives in code (`decision.py`): include when every inclusion p >= `include_min` and every exclusion p <= `exclude_max`; exclude on the first hard failure in criteria order (reason `inclusion:<id>` / `exclusion:<id>`); otherwise maybe with the first uncertain criterion. Records without abstract are never sent (`no_abstract`, policy `maybe` or `exclude`), unless `--title-only`.
- `inclusion_score` = min(inclusion p, 1 - exclusion p): a weakest-link score consistent with the rule, used by `rank` and by WSS@95.
- Client: pinned `jev-1.13.0`, HTTPS required except loopback, redirects refused, retries only on 429/529 and network errors with exponential backoff + jitter honouring `Retry-After`, strict response validation (model, answer types, probabilities in [0,1]), key redacted from errors, chars/4 token estimate with a 24k state budget, in-process sliding-window rate limiter (1,000/min), bounded `ThreadPoolExecutor` (8).
- Exact-input cache keyed by sha256 of canonical `{model, state, questions}`, written atomically (temp + rename), errors never cached. Resume reads ids already in `--out` and checks the header matches the criteria columns.
- Results and CSV rows are emitted in input order through a reorder buffer so decision files are deterministic while still being flushed during the run.
- Statistics in `stats.py`: Wilson score interval, Cohen's kappa, confusion-derived sensitivity/specificity/precision, WSS@R with pessimistic tie-breaking; all tested against hand-computed or textbook values (kappa 0.4 on the classic 2x2 table, Wilson 5/10 -> 0.2366-0.7634).
- `FakeJev` fixture provider implements the same `ask` contract; fixtures are keyed by title with hand-written synthetic probabilities. A missing fixture value raises rather than defaulting silently.

**Verified.** `python -m compileall -q src tests`, `python -m unittest discover -s tests` (61 tests) and `python -m examples.offline_demo` pass on Python 3.11.3 locally (`PYTHONPATH=src`). The CI workflow runs the same three commands on 3.11 and 3.13 after `pip install -r requirements-dev.txt`.

**Not verified.** No live Jev request was made; `scripts/live_smoke.py` (2 requests max, opt-in on `TYPESAFE_API_KEY`) is for the maintainer. No screening benchmark on real corpora: the demo probabilities are synthetic. The 3.13 matrix entry was not run locally. Parsers were tested on hand-written RIS/MEDLINE samples, not on exports from every reference manager.
