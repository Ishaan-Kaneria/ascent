"""Import any problem sheet (CP31, Striver A2Z, your own) and track it.

ascent does not ship anyone's curated sheet. You paste the links (CSV or one
URL per line) and it tracks progress against your real submissions. Supported
links: Codeforces problemset/contest URLs or bare IDs like 1903C, LeetCode
problem URLs, and anything else (GfG, CSES, AtCoder ...) as an external item you
tick off with `ascent mark`.
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3

CF_URL = re.compile(r"codeforces\.com/(?:problemset/problem|contest)/(\d+)/(?:problem/)?([A-Z]\d?)", re.I)
CF_BARE = re.compile(r"^\s*(\d{1,5})\s*([A-Z]\d?)\s*$", re.I)
LC_URL = re.compile(r"leetcode\.com/problems/([a-z0-9-]+)", re.I)


def to_pid(ref: str) -> tuple[str, str | None]:
    ref = ref.strip()
    if m := CF_URL.search(ref):
        cid, idx = m.group(1), m.group(2).upper()
        return f"CF:{cid}{idx}", f"https://codeforces.com/problemset/problem/{cid}/{idx}"
    if m := CF_BARE.match(ref):
        cid, idx = m.group(1), m.group(2).upper()
        return f"CF:{cid}{idx}", f"https://codeforces.com/problemset/problem/{cid}/{idx}"
    if m := LC_URL.search(ref):
        return f"LC:{m.group(1).lower()}", f"https://leetcode.com/problems/{m.group(1).lower()}/"
    if ref.lower().startswith(("lc:", "cf:")):
        return ref[:2].upper() + ref[2:], None
    if ref.startswith("http"):
        return f"EXT:{ref}", ref
    raise ValueError(f"not a recognisable problem reference: {ref!r}")


def parse(text: str) -> list[dict]:
    """CSV with a header containing 'url' (optional 'title', 'section'),
    or one reference per line ('# Section name' lines set the section)."""
    lines = [l for l in text.splitlines() if l.strip()]
    items: list[dict] = []
    if lines and "url" in [h.strip().lower() for h in lines[0].split(",")]:
        for row in csv.DictReader(io.StringIO("\n".join(lines))):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            pid, url = to_pid(row["url"])
            items.append({"pid": pid, "url": url, "title": row.get("title") or None,
                          "section": row.get("section") or None})
        return items
    section = None
    for l in lines:
        if l.lstrip().startswith("#"):
            section = l.lstrip("# ").strip() or None
            continue
        pid, url = to_pid(l)
        items.append({"pid": pid, "url": url, "title": None, "section": section})
    return items


def progress(conn: sqlite3.Connection, name: str, solved: set[str]) -> dict:
    rows = conn.execute("""SELECT s.*, p.rating, p.name AS pname FROM sheets s
                           LEFT JOIN problems p ON p.pid = s.pid WHERE s.name=? ORDER BY position""",
                        (name,)).fetchall()
    sections: dict = {}
    for r in rows:
        sec = sections.setdefault(r["section"] or "-", [0, 0])
        sec[1] += 1
        sec[0] += r["pid"] in solved
    return {"total": len(rows), "solved": sum(r["pid"] in solved for r in rows), "sections": sections,
            "rows": [dict(r) for r in rows]}


def next_items(conn: sqlite3.Connection, name: str, solved: set[str], level: int, n: int = 5,
               include_easy: bool = False) -> tuple[list[dict], int]:
    """Next unsolved items in sheet order. Codeforces items rated below your
    level are skipped (and counted) unless include_easy."""
    rows = progress(conn, name, solved)["rows"]
    out, skipped = [], 0
    for r in rows:
        if r["pid"] in solved:
            continue
        if not include_easy and r["rating"] and r["pid"].startswith("CF:") and r["rating"] < level:
            skipped += 1
            continue
        out.append(r)
        if len(out) >= n:
            break
    return out, skipped
