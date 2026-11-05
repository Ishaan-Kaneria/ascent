"""LeetCode public GraphQL + zerotrac problem ratings.

Limits worth knowing (so nothing here over-promises):
* Publicly, LeetCode only exposes your ~20 most recent accepted submissions.
  ascent journals every AC it sees, so syncing regularly (or the daily GitHub
  Action) accumulates your full history from the day you start.
* Problem difficulty uses zerotrac's contest-based ratings
  (github.com/zerotrac/leetcode_problem_rating). Those exist only for problems
  that appeared in weekly/biweekly contests; others fall back to LeetCode's
  Easy/Medium/Hard label, shown as such and never converted into a fake number.
"""
from __future__ import annotations

import json

from .http import get_json, request

GRAPHQL = "https://leetcode.com/graphql"
ZEROTRAC = "https://raw.githubusercontent.com/zerotrac/leetcode_problem_rating/main/ratings.txt"


def _gql(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    res = get_json(GRAPHQL, data=body, headers={
        "Content-Type": "application/json", "Accept": "application/json",
        "Origin": "https://leetcode.com", "Referer": "https://leetcode.com/"})
    if res.get("errors"):
        raise RuntimeError(f"LeetCode GraphQL error: {res['errors']}")
    return res["data"]


def profile_summary(username: str) -> dict:
    """Solved counts by difficulty + contest standing (public profile data)."""
    d = profile(username)
    user = d.get("matchedUser")
    if not user:
        raise RuntimeError(f"LeetCode user '{username}' not found (check the handle)")
    solved = {x["difficulty"]: x["count"] for x in user["submitStatsGlobal"]["acSubmissionNum"]}
    cr = d.get("userContestRanking") or {}
    return {"solved": solved, "contest_rating": cr.get("rating"), "attended": cr.get("attendedContestsCount") or 0,
            "top_percentage": cr.get("topPercentage")}


def profile(username: str) -> dict:
    q = """query($u: String!) {
      matchedUser(username: $u) { username
        submitStatsGlobal { acSubmissionNum { difficulty count } } }
      userContestRanking(username: $u) { rating attendedContestsCount topPercentage }
    }"""
    return _gql(q, {"u": username})


def contest_history(username: str) -> list[dict]:
    q = """query($u: String!) {
      userContestRankingHistory(username: $u) {
        attended rating ranking contest { title startTime } } }"""
    return [h for h in (_gql(q, {"u": username})["userContestRankingHistory"] or []) if h["attended"]]


def recent_accepted(username: str, limit: int = 20) -> list[dict]:
    q = """query($u: String!, $n: Int!) {
      recentAcSubmissionList(username: $u, limit: $n) { id title titleSlug timestamp } }"""
    return _gql(q, {"u": username, "n": limit})["recentAcSubmissionList"] or []


def zerotrac_ratings() -> list[dict]:
    """Rows: rating (float), id, title, slug, contest_slug, index."""
    text = request(ZEROTRAC).decode("utf-8")
    rows = []
    lines = text.splitlines()
    header = lines[0].split("\t")
    col = {name: i for i, name in enumerate(header)}
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < len(header):
            continue
        rows.append({
            "rating": float(parts[col["Rating"]]),
            "id": parts[col["ID"]],
            "title": parts[col["Title"]],
            "slug": parts[col["Title Slug"]],
            "contest_slug": parts[col["Contest Slug"]],
            "index": parts[col["Problem Index"]],
        })
    return rows
