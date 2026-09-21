"""Purpose: Public surface of jev-screen, title/abstract screening for systematic reviews with Jev."""

from .cache import ResultCache
from .client import (
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    FakeJev,
    JevClient,
    JevConfigError,
    JevError,
    JevHTTPError,
    JevResponseError,
    JevResult,
    RateLimiter,
    estimate_cost_usd,
    estimate_tokens,
    request_key,
)
from .criteria import Criteria, CriteriaError, Criterion, build_state, load_criteria, parse_criteria
from .decision import Decision, decide, decide_unjudged, inclusion_score
from .records import Record, load_records, parse_csv, parse_nbib, parse_ris, to_ris, write_csv, write_jsonl, write_ris
from .screening import ScreenResult, screen_records

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_ENDPOINT", "DEFAULT_MODEL", "FakeJev", "JevClient", "JevConfigError", "JevError", "JevHTTPError",
    "JevResponseError", "JevResult", "RateLimiter", "estimate_cost_usd", "estimate_tokens", "request_key",
    "Criteria", "CriteriaError", "Criterion", "build_state", "load_criteria", "parse_criteria",
    "Decision", "decide", "decide_unjudged", "inclusion_score",
    "Record", "load_records", "parse_csv", "parse_nbib", "parse_ris", "to_ris", "write_csv", "write_jsonl", "write_ris",
    "ScreenResult", "screen_records", "ResultCache", "__version__",
]
