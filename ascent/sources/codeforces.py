"""Codeforces public API client (https://codeforces.com/apiHelp).

Only public, unauthenticated methods are used. Codeforces asks clients to keep
to roughly one request every two seconds; the client enforces that.
"""
from __future__ import annotations

import re
import time
import urllib.parse
from html.parser import HTMLParser

from .http import FetchError, get_json, request

API = "https://codeforces.com/api/"
_last_call = [0.0]
MIN_GAP = 2.1  # seconds between calls


def _call(method: str, **params) -> object:
    wait = _last_call[0] + MIN_GAP - time.time()
    if wait > 0:
        time.sleep(wait)
    url = API + method + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        payload = get_json(url)
    finally:
        _last_call[0] = time.time()
    if not isinstance(payload, dict) or payload.get("status") != "OK":
        comment = payload.get("comment") if isinstance(payload, dict) else payload
        raise FetchError(f"Codeforces API {method} failed: {comment}")
    return payload["result"]


def problemset() -> tuple[list[dict], list[dict]]:
    res = _call("problemset.problems")
    return res["problems"], res["problemStatistics"]


def contests() -> list[dict]:
    return _call("contest.list", gym="false")


def user_info(handle: str) -> dict:
    return _call("user.info", handles=handle)[0]


def user_rating(handle: str) -> list[dict]:
    return _call("user.rating", handle=handle)


def user_status(handle: str, known_ids: set[int] | None = None, page: int = 1000) -> list[dict]:
    """All submissions, newest first. Stops early once a page is fully known."""
    out: list[dict] = []
    start = 1
    while True:
        batch = _call("user.status", handle=handle, **{"from": start, "count": page})
        out.extend(batch)
        if len(batch) < page:
            break
        if known_ids and all(s["id"] in known_ids for s in batch):
            break
        start += page
    return out


def contest_kind(name: str) -> str:
    n = name.lower()
    if "educational" in n:
        return "edu"
    if "global round" in n:
        return "global"
    if "div. 1 + div. 2" in n or "div. 1 + 2" in n or "div.1+div.2" in n:
        return "div12"
    for d in ("4", "3", "2", "1"):
        if f"div. {d}" in n or f"div.{d}" in n or f"division {d}" in n:
            return f"div{d}"
    return "other"


# ----------------------------------------------------------------------------
# Statement fetching for the analyzer. Codeforces renders statements as HTML:
#   div.problem-statement > div.header, div (legend), div.input-specification,
#   div.output-specification, div.sample-tests, div.note
# ----------------------------------------------------------------------------

VOID = {"br", "img", "hr", "input", "meta", "link", "source", "wbr", "col", "area",
        "base", "embed", "param", "track"}


class _StatementParser(HTMLParser):
    SECTION_CLASSES = {
        "input-specification": "input",
        "output-specification": "output",
        "interaction-specification": "output",
        "sample-tests": "samples",
        "note": "note",
        "header": "header",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.root_depth: int | None = None
        self.stack: list[str | None] = []
        self.sections: dict[str, list[str]] = {}
        self.current = "legend"

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            if self.root_depth is not None and tag == "br":
                self._add("\n")
            return
        self.depth += 1
        cls = dict(attrs).get("class", "") or ""
        section = None
        if self.root_depth is None and "problem-statement" in cls.split():
            self.root_depth = self.depth
        elif self.root_depth is not None and self.depth == self.root_depth + 1:
            section = "legend"
            for c, name in self.SECTION_CLASSES.items():
                if c in cls.split():
                    section = name
        self.stack.append(section)
        if section:
            self.current = section
        if self.root_depth is not None and tag in ("p", "li", "div", "pre"):
            self._add("\n")

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.stack:
            self.stack.pop()
        if self.root_depth is not None and self.depth == self.root_depth:
            self.root_depth = None
        self.depth -= 1

    def handle_data(self, data):
        if self.root_depth is not None:
            self._add(data)

    def _add(self, text):
        self.sections.setdefault(self.current, []).append(text)


def parse_statement_html(html: str) -> dict[str, str]:
    p = _StatementParser()
    p.feed(html)
    out = {}
    for k, parts in p.sections.items():
        txt = re.sub(r"[ \t]+", " ", "".join(parts))
        txt = re.sub(r"\n\s*\n+", "\n", txt).strip()
        # Drop the leading section title ("Input", "Output", "Note").
        txt = re.sub(r"^(Input|Output|Note|Interaction|Examples?)\s*\n?", "", txt)
        out[k] = txt
    return out


def fetch_statement(contest_id: int, index: str) -> dict[str, str]:
    url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}"
    wait = _last_call[0] + MIN_GAP - time.time()
    if wait > 0:
        time.sleep(wait)
    try:
        html = request(url).decode("utf-8", "replace")
    finally:
        _last_call[0] = time.time()
    sections = parse_statement_html(html)
    if not sections.get("legend") and not sections.get("input"):
        raise FetchError(f"could not find a statement at {url} (blocked or layout changed); "
                         "save the statement text to a file and use --file")
    return sections
