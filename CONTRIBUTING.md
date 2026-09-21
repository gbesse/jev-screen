# Contributing

`jev-screen` is an independent, experimental tool. Open an issue with the Python version, the command you ran and a redacted, synthetic reproduction (never real manuscripts or unpublished records).

Before proposing a change run, from the repository root with `PYTHONPATH=src`:

```sh
python -m compileall -q src tests
python -m unittest discover -s tests
python -m examples.offline_demo
```

Rules of the house:

- Runtime code is standard library only; do not add dependencies.
- Every file starts with a `Purpose:` header; docstrings explain why nontrivial logic exists.
- Errors are never swallowed. Library code raises; the CLI prints to stderr and exits non-zero.
- Fixtures are small, readable and synthetic; fixture probabilities are invented, not measured Jev output.
- Add focused tests when changing parsers, the decision rule, statistics or the client contract.
- Record the purpose and key technical decisions of your change in `ai/CHANGELOG.md`.
- Never run live Jev calls in tests or CI.
