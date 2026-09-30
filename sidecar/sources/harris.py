"""Harris Football weekly ranks, parsed from plain HTML tables.

Harris disallows ?format=json in robots.txt, so the HTML is parsed with the
stdlib html.parser (SPEC.md §1). The RB and WR pages carry two tables,
"Standard Scoring" and PPR; the PPR table is chosen by its heading text,
not by table index (SPEC.md §3). Where only one table exists, it is used.

Rows: rank, player, opponent (e.g. "@ CAR"). The player's own NFL team is
not shown, so rows carry team=None and names.Matcher resolves it.
"""
from html.parser import HTMLParser

from .common import SourceError, now_iso, to_int

# page key -> (config url key, canonical position)
PAGES = {"qb": "QB", "rb": "RB", "wr": "WR", "te": "TE", "def": "D/ST"}

# Section-heading cell text (lowercased) -> which table it introduces.
SECTIONS = {"standard scoring": "standard", "ppr": "ppr"}


class _TableParser(HTMLParser):
    """Collect every <table> as a list of rows of cell texts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(c for c in self._row):
                self.tables[-1].append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _section_rows(tables):
    """Split a page's rows by section heading.

    A section row is one with a single non-empty cell whose text is a known
    heading ("Standard Scoring", "PPR"). Rank rows have an integer first
    cell and a player name in the second. Returns {"standard": [...],
    "ppr": [...], "plain": [...]} of {rank, name, opponent}.
    """
    out = {"standard": [], "ppr": [], "plain": []}
    for table in tables:
        current = "plain"
        for cells in table:
            nonempty = [c for c in cells if c]
            if len(nonempty) == 1 and nonempty[0].lower() in SECTIONS:
                current = SECTIONS[nonempty[0].lower()]
                continue
            rank = to_int(cells[0]) if cells else None
            if rank is not None and len(cells) >= 2 and cells[1]:
                out[current].append({
                    "rank": rank,
                    "name": cells[1],
                    "opponent": cells[2].strip() if len(cells) > 2 else None,
                })
    return out


def parse_page(text, pos):
    """One Harris page -> rank rows for ``pos`` (pure; tested).

    The PPR table wins over Standard; a page with neither heading falls
    back to its only table. No rank rows at all is a source failure, not an
    empty week.
    """
    parser = _TableParser()
    parser.feed(text)
    sections = _section_rows(parser.tables)
    rows = sections["ppr"] or sections["standard"] or sections["plain"]
    if not rows:
        raise SourceError(f"harris: no rank rows found for {pos} "
                          f"(page layout may have changed)")
    return rows


def fetch(client, cfg, season):
    urls = cfg["urls"]["harris"]
    rows = []
    raw = {}
    for page, pos in PAGES.items():
        text = client.get(urls[page]).text
        raw[page] = text
        for row in parse_page(text, pos):
            rows.append({
                "source": "harris",
                "view": "weekly",
                "pos": pos,
                "name": row["name"],
                "team": None,
                "bye": None,
                "injury": None,
                "rank": row["rank"],
                "opponent": row["opponent"],
                "stats": None,
            })
    return {"fetchedAt": now_iso(), "raw": raw, "rows": rows, "notes": []}
