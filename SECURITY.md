# Security and operational boundaries

`jev-screen` sends the title and abstract of each bibliographic record to `api.typesafe.ai` when a real API key is configured. Nothing else leaves your machine: no telemetry, no automatic emails, no cache upload. The API key is read from `TYPESAFE_API_KEY`, never written to disk, never printed, and redacted from error messages.

Model probabilities are not calibrated guarantees. The tool is a second screener or a prioritizer; keep a human screener in the loop and calibrate thresholds on your own pilot set before relying on the `exclude` bucket. See `docs/method.md`.

Do not include credentials, private manuscripts or unpublished records in public issues. Report a vulnerability through GitHub private vulnerability reporting when enabled; otherwise open a minimal issue asking for a private contact channel, without exploit details. This alpha has no security audit and no support SLA.
