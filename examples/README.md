Purpose: describe the example files used by the offline demo; all content is synthetic and fictional.

- `records.ris`: 30 fictional bibliographic records (RIS). Two (`S24`, `S25`) have no abstract on purpose. No real study, author or DOI is referenced.
- `criteria.json`: three inclusion and three exclusion criteria for a fictional review on digital self-management in adults with type 2 diabetes; thresholds are illustrative defaults.
- `fixtures.json`: probabilities for `FakeJev`, keyed by record title. Written by hand to exercise every bucket and reason; not measured Jev output.
- `human.csv`: synthetic "human screener" labels (`id,decision`) with a few deliberate disagreements so the agreement report is not trivial.
- `offline_demo.py`: runs estimate, screen (twice, to show cache hits), prisma, rank and agreement in a temporary directory.
- `csv_pilot.csv` and `csv_pilot.py`: a three-record fictional CSV example showing all three decision buckets and their first reasons, using the existing synthetic fixtures. Run `PYTHONPATH=src python -m examples.csv_pilot`.
