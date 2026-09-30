"""Match player names from ranking sources to ESPN players.

Every source spells players its own way ("Kenneth Walker III", "Ken Walker",
"Minnesota Vikings", "Vikings D/ST"). This normalizes names, maps defenses
to NFL team abbreviations, and matches each source row to one ESPN player.
Rows it can't match are returned, never dropped, so the UI can list them
and the alias table can grow.

Pure: no I/O. Owned by the Claude session (see COORDINATION.md).
"""
import re
import unicodedata

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# Source abbreviations that differ from ESPN's (model.PRO_TEAMS).
TEAM_ABBR_ALIASES = {
    "WAS": "WSH", "JAC": "JAX", "LA": "LAR", "OAK": "LV", "SD": "LAC",
    "ARZ": "ARI", "GNB": "GB", "KAN": "KC", "NWE": "NE", "NOR": "NO",
    "SFO": "SF", "TAM": "TB", "BLT": "BAL", "CLV": "CLE", "HST": "HOU",
}

# ESPN abbr -> (city/region, nickname). Used to resolve defenses named by
# city, nickname or both.
NFL_TEAMS = {
    "ARI": ("Arizona", "Cardinals"), "ATL": ("Atlanta", "Falcons"),
    "BAL": ("Baltimore", "Ravens"), "BUF": ("Buffalo", "Bills"),
    "CAR": ("Carolina", "Panthers"), "CHI": ("Chicago", "Bears"),
    "CIN": ("Cincinnati", "Bengals"), "CLE": ("Cleveland", "Browns"),
    "DAL": ("Dallas", "Cowboys"), "DEN": ("Denver", "Broncos"),
    "DET": ("Detroit", "Lions"), "GB": ("Green Bay", "Packers"),
    "HOU": ("Houston", "Texans"), "IND": ("Indianapolis", "Colts"),
    "JAX": ("Jacksonville", "Jaguars"), "KC": ("Kansas City", "Chiefs"),
    "LV": ("Las Vegas", "Raiders"), "LAC": ("Los Angeles", "Chargers"),
    "LAR": ("Los Angeles", "Rams"), "MIA": ("Miami", "Dolphins"),
    "MIN": ("Minnesota", "Vikings"), "NE": ("New England", "Patriots"),
    "NO": ("New Orleans", "Saints"), "NYG": ("New York", "Giants"),
    "NYJ": ("New York", "Jets"), "PHI": ("Philadelphia", "Eagles"),
    "PIT": ("Pittsburgh", "Steelers"), "SF": ("San Francisco", "49ers"),
    "SEA": ("Seattle", "Seahawks"), "TB": ("Tampa Bay", "Buccaneers"),
    "TEN": ("Tennessee", "Titans"), "WSH": ("Washington", "Commanders"),
}

# Known source spelling -> ESPN spelling, found live on 2026-09-29 (Harris vs
# ESPN). config.json "aliases" adds to these; it doesn't replace them.
DEFAULT_ALIASES = {
    "Kenneth Gainwell": "Kenny Gainwell",
    "A.D. Mitchell": "Adonai Mitchell",
}

DST_POS = "D/ST"
_DST_WORDS = {"d", "st", "dst", "def", "defense", "d/st"}


def team_abbr(value):
    """Normalize a team abbreviation to ESPN's. None/'' -> None."""
    if not value:
        return None
    v = str(value).strip().upper()
    return TEAM_ABBR_ALIASES.get(v, v)


def normalize(name):
    """Canonical key for a player name.

    Lowercase, accents stripped, punctuation removed (so "D.J." == "DJ" and
    "Ja'Marr" == "Jamarr"), and generational suffixes dropped.
    """
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[.'’`]", "", s)          # joiners vanish: D.J. -> dj
    s = re.sub(r"[^a-z0-9]+", " ", s)      # other punctuation splits
    tokens = [t for t in s.split() if t not in SUFFIXES]
    return " ".join(tokens)


def dst_team(raw):
    """Resolve a defense name in any source's format to an ESPN abbr.

    Handles "MIN", "Minnesota Vikings", "Vikings", "Vikings D/ST",
    "Minnesota Defense". Returns None when ambiguous ("New York" alone) or
    unknown.
    """
    if not raw:
        return None
    text = str(raw).strip()
    if team_abbr(text) in NFL_TEAMS:
        return team_abbr(text)
    words = [w for w in normalize(text.replace("/", " ")).split()
             if w not in _DST_WORDS]
    key = " ".join(words)
    if not key:
        return None
    hits = set()
    for abbr, (city, nick) in NFL_TEAMS.items():
        c, n = normalize(city), normalize(nick)
        if key in (n, f"{c} {n}"):
            return abbr                     # a nickname is unique
        if key == c:
            hits.add(abbr)
    return hits.pop() if len(hits) == 1 else None


def _is_dst(pos):
    return str(pos or "").upper().replace(" ", "") in {"D", "DST", "D/ST", "DEF"}


class Matcher:
    """Index of ESPN players for matching source rows.

    players: ESPN player dicts (see COORDINATION.md) with espnId, name, pos,
    team. aliases: {"source spelling": "ESPN spelling"}, compared after
    normalize().
    """

    def __init__(self, players, aliases=None):
        self.by_name = {}
        self.dst_by_team = {}
        for p in players:
            if p.get("pos") == DST_POS:
                self.dst_by_team[team_abbr(p.get("team"))] = p
            else:
                self.by_name.setdefault(normalize(p["name"]), []).append(p)
        merged = {**DEFAULT_ALIASES, **(aliases or {})}
        self.aliases = {normalize(k): normalize(v) for k, v in merged.items()}

    def match(self, name, pos=None, team=None):
        """Return the one ESPN player for this row, or None."""
        if _is_dst(pos):
            return self.dst_by_team.get(dst_team(team) or dst_team(name))
        key = normalize(name)
        key = self.aliases.get(key, key)
        cands = self.by_name.get(key, [])
        if len(cands) > 1 and pos:
            cands = [p for p in cands if p.get("pos") == pos] or cands
        if len(cands) > 1 and team:
            t = team_abbr(team)
            cands = [p for p in cands if team_abbr(p.get("team")) == t] or cands
        return cands[0] if len(cands) == 1 else None


def match_rows(rows, matcher):
    """Attach espnId to each source row.

    Returns (matched, unmatched). Matched rows are copies with "espnId" and
    "pos" set from ESPN. Unmatched rows are copies with a "reason" for the
    UI's "Unmatched (N)" panel.
    """
    matched, unmatched = [], []
    for r in rows:
        p = matcher.match(r.get("name"), r.get("pos"), r.get("team"))
        if p is None:
            unmatched.append({**r, "reason": "no unique ESPN player"})
        else:
            matched.append({**r, "espnId": p["espnId"], "pos": p["pos"]})
    return matched, unmatched
