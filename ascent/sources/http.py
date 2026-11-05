"""Tiny stdlib HTTP helper with retries (no third-party dependencies)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

USER_AGENT = "ascent-cp-trainer/1.0 (+https://github.com)"


class FetchError(RuntimeError):
    pass


def request(url: str, *, data: bytes | None = None, headers: dict | None = None,
            retries: int = 4, timeout: float = 30.0) -> bytes:
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    delay = 2.0
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last = e
            # 4xx other than 429 will not get better by retrying.
            if 400 <= e.code < 500 and e.code != 429:
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        if attempt < retries - 1:
            time.sleep(delay)
            delay *= 2
    raise FetchError(f"GET {url} failed: {last}")


def get_json(url: str, **kw) -> object:
    return json.loads(request(url, **kw).decode("utf-8"))
