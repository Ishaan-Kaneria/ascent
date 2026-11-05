"""SQLite storage + the append-only journal of manual events."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS problems (
    pid           TEXT PRIMARY KEY,      -- CF:1903C, LC:two-sum, EXT:<url>
    platform      TEXT NOT NULL,         -- CF | LC | EXT
    contest_id    INTEGER,
    idx           TEXT,
    name          TEXT,
    rating        INTEGER,
    rating_source TEXT,                  -- official | estimated | zerotrac | lc-difficulty
    tags          TEXT DEFAULT '[]',     -- JSON list
    solved_count  INTEGER,
    lc_difficulty TEXT,
    url           TEXT,
    trick         REAL                   -- 0..1, see difficulty.trickiness
);
CREATE INDEX IF NOT EXISTS ix_problems_rating ON problems(platform, rating);

CREATE TABLE IF NOT EXISTS contests (
    id         INTEGER PRIMARY KEY,
    name       TEXT,
    kind       TEXT,                     -- div1 | div2 | div3 | div4 | edu | global | div12 | other
    start_time INTEGER,
    duration   INTEGER
);

CREATE TABLE IF NOT EXISTS submissions (
    sid              TEXT PRIMARY KEY,   -- CF:123456 / LC:987
    platform         TEXT NOT NULL,
    pid              TEXT NOT NULL,
    time             INTEGER NOT NULL,   -- unix seconds
    verdict          TEXT,               -- OK, WRONG_ANSWER, ... (LC ACs are OK)
    participant_type TEXT,               -- CONTESTANT, VIRTUAL, PRACTICE, OUT_OF_COMPETITION
    relative_time    INTEGER,            -- seconds since contest start (contest/virtual only)
    language         TEXT
);
CREATE INDEX IF NOT EXISTS ix_sub_pid ON submissions(pid);

CREATE TABLE IF NOT EXISTS rating_history (
    platform    TEXT NOT NULL,
    contest_id  TEXT NOT NULL,
    contest_name TEXT,
    time        INTEGER,
    old_rating  INTEGER,
    new_rating  INTEGER,
    rank        INTEGER,
    PRIMARY KEY (platform, contest_id)
);

CREATE TABLE IF NOT EXISTS attempts (     -- manual / timer data per problem
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pid         TEXT NOT NULL,
    started_at  INTEGER,
    finished_at INTEGER,
    minutes     REAL,
    editorial   INTEGER DEFAULT 0,
    solved      INTEGER DEFAULT 1,
    notes       TEXT
);
CREATE INDEX IF NOT EXISTS ix_attempts_pid ON attempts(pid);

CREATE TABLE IF NOT EXISTS timers (pid TEXT PRIMARY KEY, started_at INTEGER);

CREATE TABLE IF NOT EXISTS reviews (
    pid      TEXT PRIMARY KEY,
    stage    INTEGER DEFAULT 0,          -- 0: 7d, 1: 21d, 2: 60d, 3: done
    due_at   INTEGER,
    reason   TEXT
);

CREATE TABLE IF NOT EXISTS sheets (
    name     TEXT NOT NULL,
    position INTEGER NOT NULL,
    pid      TEXT NOT NULL,
    title    TEXT,
    url      TEXT,
    section  TEXT,
    PRIMARY KEY (name, position)
);

CREATE TABLE IF NOT EXISTS manual_solved (pid TEXT PRIMARY KEY, time INTEGER);

CREATE TABLE IF NOT EXISTS statements (    -- cached statements for the analyzer
    pid        TEXT PRIMARY KEY,
    fetched_at INTEGER,
    sections   TEXT                         -- JSON {legend,input,output,note,...}
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or config.db_path()))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, str(value)))


def upsert_many(conn: sqlite3.Connection, table: str, rows: Iterable[dict]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    cols = list(rows[0].keys())
    sql = (f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) "
           f"VALUES ({', '.join('?' for _ in cols)})")
    conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
    return len(rows)


# --------------------------------------------------------------------------
# Journal: every manual event is appended here AND applied to the DB, so the
# DB can be thrown away and rebuilt (`ascent sync --rebuild`).
# --------------------------------------------------------------------------

def journal(conn: sqlite3.Connection, event: dict, path: Path | None = None) -> None:
    event = {"ts": int(time.time()), **event}
    with open(path or config.journal_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")
    apply_event(conn, event)


def replay_journal(conn: sqlite3.Connection, path: Path | None = None) -> int:
    p = path or config.journal_path()
    if not p.exists():
        return 0
    n = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            apply_event(conn, json.loads(line))
            n += 1
    return n


def apply_event(conn: sqlite3.Connection, ev: dict) -> None:
    kind = ev["type"]
    if kind == "timer_start":
        conn.execute("INSERT OR REPLACE INTO timers(pid, started_at) VALUES (?, ?)",
                     (ev["pid"], ev["at"]))
    elif kind == "timer_cancel":
        conn.execute("DELETE FROM timers WHERE pid=?", (ev["pid"],))
    elif kind == "attempt":
        conn.execute("DELETE FROM timers WHERE pid=?", (ev["pid"],))
        conn.execute(
            "INSERT INTO attempts(pid, started_at, finished_at, minutes, editorial, solved, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ev["pid"], ev.get("started_at"), ev.get("finished_at"), ev.get("minutes"),
             int(bool(ev.get("editorial"))), int(bool(ev.get("solved", True))), ev.get("notes")))
    elif kind == "mark_solved":
        conn.execute("INSERT OR REPLACE INTO manual_solved(pid, time) VALUES (?, ?)",
                     (ev["pid"], ev.get("at", ev["ts"])))
    elif kind == "lc_ac":
        # LeetCode only exposes the last ~20 public ACs, so every AC we ever
        # see is journaled to build up full history over time.
        conn.execute(
            "INSERT OR REPLACE INTO submissions(sid, platform, pid, time, verdict, participant_type,"
            " relative_time, language) VALUES (?, 'LC', ?, ?, 'OK', 'PRACTICE', NULL, NULL)",
            (f"LC:{ev['sid']}", ev["pid"], ev["at"]))
        conn.execute("INSERT OR IGNORE INTO problems(pid, platform, name, url) VALUES (?, 'LC', ?, ?)",
                     (ev["pid"], ev.get("title"), f"https://leetcode.com/problems/{ev['pid'][3:]}/"))
    elif kind == "sheet_import":
        conn.execute("DELETE FROM sheets WHERE name=?", (ev["name"],))
        for i, item in enumerate(ev["items"]):
            conn.execute(
                "INSERT INTO sheets(name, position, pid, title, url, section) VALUES (?, ?, ?, ?, ?, ?)",
                (ev["name"], i, item["pid"], item.get("title"), item.get("url"), item.get("section")))
    elif kind == "review_done":
        row = conn.execute("SELECT stage FROM reviews WHERE pid=?", (ev["pid"],)).fetchone()
        stage = (row["stage"] if row else 0)
        if ev.get("clean"):
            stage += 1
        intervals = [7, 21, 60]
        if stage >= len(intervals):
            conn.execute("UPDATE reviews SET stage=?, due_at=NULL WHERE pid=?", (stage, ev["pid"]))
        else:
            due = ev["ts"] + intervals[stage] * 86400
            conn.execute("INSERT OR REPLACE INTO reviews(pid, stage, due_at, reason) VALUES (?, ?, ?,"
                         " COALESCE((SELECT reason FROM reviews WHERE pid=?), 'manual'))",
                         (ev["pid"], stage, due, ev["pid"]))
    else:
        raise ValueError(f"unknown journal event type: {kind}")
