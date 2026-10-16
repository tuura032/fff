# Sidecar source modules. Each module implements fetch(client, cfg, season)
# and returns {"fetchedAt", "raw", "rows", "notes"}. Adding a source is one
# module here plus one line in SOURCES (SPEC.md §3).

from . import drafts, espn, fantasypros, ffballers, harris

SOURCES = {
    "espn": {"module": espn, "label": "ESPN (FFF)"},
    "drafts": {"module": drafts, "label": "ESPN drafts"},
    "ffballers": {"module": ffballers, "label": "Fantasy Footballers"},
    "harris": {"module": harris, "label": "Harris Football"},
    "fantasypros": {"module": fantasypros, "label": "FantasyPros"},
}

# Fetch order: ESPN first (the match target), then the ranking sources.
ORDER = ["espn", "drafts", "ffballers", "harris", "fantasypros"]
