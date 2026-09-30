"""Shared fetching plumbing for the sidecar sources.

Browser-like UA, one timeout, and loud failures: a source that errors or
whose structure is not found raises SourceError instead of returning an
empty list (SPEC.md §4 -- a layout change is a warning chip, never "no
rankings this week"). The cache writes to a temp file then renames, so a
crash can't leave a half-written file.

Owned by the Cline session (see COORDINATION.md).
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TIMEOUT = 45


class SourceError(Exception):
    """A source failed: HTTP error, timeout, or structure not found."""


class Client:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def get(self, url, headers=None):
        """GET a public page; raises SourceError on any HTTP/transport error."""
        try:
            resp = self.session.get(url, headers=headers, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise SourceError(f"{url}: {exc}") from exc
        return resp


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def age_seconds(fetched_at):
    """Whole seconds since an ISO timestamp; None when unknown."""
    if not fetched_at:
        return None
    try:
        then = datetime.fromisoformat(fetched_at)
    except ValueError:
        return None
    return max(0, int((datetime.now(timezone.utc) - then).total_seconds()))


def to_int(value):
    """Rank/bye values arrive as strings in some sources; None on garbage."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


class Cache:
    """Per-source JSON files under sidecar/cache/ (gitignored)."""

    def __init__(self, directory):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def load(self, name):
        try:
            return json.loads((self.dir / f"{name}.json")
                              .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def save(self, name, payload):
        target = self.dir / f"{name}.json"
        tmp = self.dir / f"{name}.json.tmp"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, target)


_DECODER = json.JSONDecoder()


def find_projection_array(text):
    """Locate the FFB main projection array in a page.

    The page embeds a JSON array whose rows carry "analyst_name"; the
    variable it is assigned to is not stable, so scan each marker hit,
    back up to the nearest '[', and decode. The first array whose rows look
    like projections (name + analyst_name + a stat field) wins.
    """
    stat_keys = ("passing_yards", "rushing_yards", "receptions",
                 "receiving_yards", "fumbles_lost")
    idx = 0
    for _ in range(64):
        i = text.find('"analyst_name"', idx)
        if i < 0:
            return None
        start = text.rfind("[", 0, i)
        idx = i + 1
        if start < 0:
            continue
        try:
            obj, _end = _DECODER.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if not (isinstance(obj, list) and obj):
            continue
        sample = obj[:5]
        if (all(isinstance(r, dict) and "name" in r and "analyst_name" in r
                for r in sample)
                and any(any(k in r for k in stat_keys) for r in sample)):
            return obj
    return None


def find_data_arrays(text):
    """Every `let/var/const data = <json array>` assignment in a page."""
    out = []
    for m in re.finditer(r"(?:let|var|const)\s+data\s*=\s*", text):
        try:
            obj, _end = _DECODER.raw_decode(text[m.end():])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, list):
            out.append(obj)
    return out


def find_ecr_data(text):
    """The FantasyPros `var ecrData = {...};` blob, or SourceError."""
    m = re.search(r"var\s+ecrData\s*=\s*", text)
    if not m:
        raise SourceError("fantasypros: ecrData not found in page")
    try:
        obj, _end = _DECODER.raw_decode(text[m.end():])
    except json.JSONDecodeError as exc:
        raise SourceError(f"fantasypros: ecrData undecodable: {exc}") from exc
    if not isinstance(obj, dict) or not obj.get("players"):
        raise SourceError("fantasypros: ecrData has no players")
    return obj
