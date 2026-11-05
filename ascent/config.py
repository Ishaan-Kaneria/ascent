"""Configuration and data-directory handling.

All state lives in one directory (default ``~/.ascent``, override with the
``ASCENT_HOME`` environment variable):

* ``config.json``   - handles, targets, tuning knobs
* ``journal.jsonl`` - append-only log of everything *you* did by hand
                      (timers, editorial flags, sheet imports, LeetCode ACs).
                      Plain text, git-friendly, the source of truth for
                      anything an API cannot give back.
* ``ascent.db``     - SQLite cache. Can always be rebuilt from the APIs plus
                      the journal (``ascent sync --rebuild``).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def home() -> Path:
    p = Path(os.environ.get("ASCENT_HOME", Path.home() / ".ascent")).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class Config:
    cf_handle: str = ""
    lc_handle: str = ""
    # The rating you are training towards (1600 = Codeforces Expert).
    target_rating: int = 1600
    # Minutes you can realistically train per day; sizes `ascent today`.
    daily_minutes: int = 120
    # Ignore very old problems by default: style and difficulty calibration of
    # early rounds differ from modern ones. Contest 1000 is from mid-2018.
    min_contest_id: int = 1000
    # Practice (no clock, no pressure) is easier than a live contest. A practice
    # solve of a D-rated problem is treated as contest-equivalent evidence at
    # D - practice_discount when estimating skill. Conservative on purpose.
    practice_discount: int = 250
    # Half-life (days) for weighting old evidence when estimating skill.
    recency_half_life_days: int = 90
    # Extra readiness thresholds for the quant/OA profile (LeetCode side).
    oa_lc_contest_rating: int = 1850
    oa_lc_hard_rated_min: int = 1900
    oa_lc_hard_rated_count: int = 30
    extra: dict = field(default_factory=dict)

    @classmethod
    def path(cls) -> Path:
        return home() / "config.json"

    @classmethod
    def load(cls) -> "Config":
        p = cls.path()
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text())
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self) -> None:
        self.path().write_text(json.dumps(asdict(self), indent=2) + "\n")


def db_path() -> Path:
    return home() / "ascent.db"


def journal_path() -> Path:
    return home() / "journal.jsonl"
