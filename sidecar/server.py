"""Local-only board server for the sidecar (SPEC.md §5).

Binds 127.0.0.1 only, serves web/, and a small JSON API:

  GET  /api/status    per-source freshness (fresh/stale/failed/never)
  GET  /api/board     assembled board from cache (incl. the "Look back"
                      block from analysis.py); stale sources get a
                      background re-fetch (stale-while-revalidate, §6)
  POST /api/refresh   {"source": name} or {} to force-refresh one/all

Data lives in sidecar/cache/*.json, written by the source modules. The
board pipeline follows COORDINATION.md: names.Matcher -> names.match_rows
-> model.positional_ranks -> per-source positional ranks returned to the
browser, which re-runs consensus on source toggle.

python server.py [--port N] [--check]
"""
import argparse
import json
import threading
from datetime import date
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import analysis
import model
import names
import sources.espn as espn
import sources.ffballers as ffb
import sources.harris as harris
import sources.fantasypros as fp
import sources.history as history
from sources.common import Cache, Client, age_seconds

HERE = Path(__file__).resolve().parent
SOURCES = {"espn": espn, "ffballers": ffb, "harris": harris,
           "fantasypros": fp, "history": history}
# The five rank sources the board can toggle (model.py source keys).
RANK_SOURCES = ("ffb-andy", "ffb-jason", "ffb-mike", "harris", "fp")
VIEWS = ("weekly", "ros", "dynasty")


class State:
    """Cache-backed source state with background refresh threads."""

    def __init__(self, cfg, cache):
        self.cfg = cfg
        self.cache = cache
        self.lock = threading.Lock()
        self.error = {}
        self.refreshing = set()

    def status(self):
        ttl = self.cfg.get("cacheTtlMinutes", 60) * 60
        out = {}
        with self.lock:
            for name in SOURCES:
                payload = self.cache.load(name)
                fetched_at = (payload or {}).get("fetchedAt")
                age = age_seconds(fetched_at)
                if name in self.refreshing:
                    state = "refreshing"
                elif payload is None:
                    state = "failed" if name in self.error else "never"
                elif name in self.error:
                    # Last refresh failed; we're serving cached data, but
                    # the chip must say so.
                    state = "failed"
                elif age is not None and age <= ttl:
                    state = "fresh"
                else:
                    state = "stale"
                out[name] = {
                    "state": state,
                    "fetchedAt": fetched_at,
                    "ageSec": age,
                    "lastError": self.error.get(name),
                }
        return out

    def refresh(self, name):
        """Start a background fetch for one source; False if already running."""
        with self.lock:
            if name in self.refreshing:
                return False
            self.refreshing.add(name)

        def run():
            try:
                payload = SOURCES[name].fetch(Client(), self.cfg,
                                              self.cfg["season"])
                self.cache.save(name, payload)
                with self.lock:
                    self.error.pop(name, None)
            except Exception as exc:  # noqa: BLE001 - surfaced in the UI
                with self.lock:
                    self.error[name] = str(exc)
            finally:
                with self.lock:
                    self.refreshing.discard(name)

        threading.Thread(target=run, daemon=True).start()
        return True



def _player_view(p):
    d = {"name": p["name"], "pos": p["pos"], "team": p.get("team"),
         "injury": p.get("injury"), "bye": p.get("bye"),
         "pctOwned": p.get("pctOwned"), "status": p["status"]}
    if p.get("ownerTeamId") is not None:
        d["ownerTeamId"] = p["ownerTeamId"]
        d["lineupSlotId"] = p.get("lineupSlotId")
    return d


_SNAP_LOCK = threading.Lock()


def iso_week(day):
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def snapshot_movers(cache, season, cur, today=None):
    """Weekly movers vs last week's snapshot (SPEC.md §5).

    One snapshot per ISO week (cache/snapshot-weekly-<season>-<YYYY-Www>),
    rewritten through the week so it ends as that week's last board. The
    comparison is against the newest snapshot from an *earlier* week, so
    reloading the page doesn't reset it. Returns (movers, that week or None);
    movers is {} until a previous week exists.
    """
    prefix = f"snapshot-weekly-{season}-"
    this = prefix + iso_week(today or date.today())
    with _SNAP_LOCK:
        earlier = [n for n in cache.names(prefix) if n < this]
        movers, since = {}, None
        if earlier:
            prev = {int(k): v
                    for k, v in (cache.load(earlier[-1]) or {}).items()}
            movers = model.movers(cur, prev)
            since = earlier[-1][len(prefix):]
        snap = {str(pid): round(v, 3) for pid, v in cur.items()}
        if cache.load(this) != snap:
            cache.save(this, snap)
    return movers, since


def build_board(state):
    """Assemble the /api/board payload from whatever is in cache."""
    cfg = state.cfg
    cache = state.cache
    espn_p = cache.load("espn") or {}
    players = espn_p.get("players") or []
    league = espn_p.get("league") or {}
    pts = model.points_by_stat(league.get("scoringItems"))

    ranks = {view: {} for view in VIEWS}
    unmatched = {}
    week_info = {}
    notes = []
    if players:
        matcher = names.Matcher(players, cfg.get("aliases"))
        for name in ("ffballers", "harris", "fantasypros", "history"):
            payload = cache.load(name)
            if not payload:
                continue
            notes.extend(payload.get("notes") or [])
            matched, un = names.match_rows(payload.get("rows") or [],
                                           matcher)
            if un:
                unmatched[name] = un
            for r in matched:
                if r.get("view") == "weekly" and r.get("opponent"):
                    week_info.setdefault(r["espnId"],
                                         {"opponent": r["opponent"]})
            for view, srcs in model.positional_ranks(matched,
                                                     pts).items():
                ranks.setdefault(view, {}).update(srcs)

    my_team_id = cfg.get("myTeamId")
    mine = [p for p in players
            if p.get("status") == "OWNED"
            and p.get("ownerTeamId") == my_team_id]
    free_agents = [p for p in players
                   if p.get("status") in ("FA", "WAIVERS")]

    ros = ranks.get("ros") or {}
    cons_ros = (model.consensus(ros, [s for s in RANK_SOURCES if s in ros])
                if ros else {})
    upgrades = (model.upgrades(mine, free_agents, cons_ros,
                               league.get("lineupSlotCounts"),
                               cfg.get("upgradeMargin", 5))
                if cons_ros else [])
    drops = (model.drop_candidates(mine, free_agents, cons_ros)
             if cons_ros else [])
    byes = (model.bye_conflicts(mine, league.get("currentWeek") or 0)
            if mine else {})

    movers, movers_since = {}, None
    weekly = ranks.get("weekly") or {}
    if weekly:
        cons_w = model.consensus(
            weekly, [s for s in RANK_SOURCES if s in weekly])
        cur = {pid: c["avg"] for pid, c in cons_w.items()}
        movers, movers_since = snapshot_movers(cache, cfg["season"], cur)

    return {
        "meta": {
            "season": league.get("season") or cfg.get("season"),
            "currentWeek": league.get("currentWeek"),
            "myTeamId": my_team_id,
            "scoringItems": league.get("scoringItems"),
            "lineupSlotCounts": league.get("lineupSlotCounts"),
            "upgradeMargin": cfg.get("upgradeMargin", 5),
            "moversSince": movers_since,
        },
        "status": state.status(),
        "players": {str(p["espnId"]): _player_view(p) for p in players},
        "teams": espn_p.get("teams") or [],
        "ranks": ranks,
        "weekInfo": {str(k): v for k, v in week_info.items()},
        "unmatched": unmatched,
        "recommendations": {"upgrades": upgrades, "drops": drops,
                            "byes": byes},
        "movers": {str(k): v for k, v in movers.items()},
        "lookback": analysis.lookback(ranks, cache.load("history")),
        "notes": notes,
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, state=None, directory=None, **kwargs):
        self.state = state
        super().__init__(*args,
                         directory=directory or str(HERE / "web"),
                         **kwargs)

    def log_message(self, *args):
        pass  # local tool; keep the console quiet

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/status":
            self._json({"status": self.state.status()})
        elif path == "/api/board":
            board = build_board(self.state)
            for name, st in board["status"].items():
                if st["state"] == "stale":
                    self.state.refresh(name)  # stale-while-revalidate
            self._json(board)
        else:
            super().do_GET()

    def do_POST(self):
        if self.path != "/api/refresh":
            self._json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json({"error": "bad json"}, 400)
            return
        target = body.get("source")
        targets = [target] if target in SOURCES else list(SOURCES)
        started = [s for s in targets if self.state.refresh(s)]
        self._json({"started": started, "status": self.state.status()})


def main():
    ap = argparse.ArgumentParser(description="sidecar board server")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--check", action="store_true",
                    help="fetch every source once, print results, exit")
    args = ap.parse_args()
    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    cache = Cache(HERE / "cache")
    state = State(cfg, cache)

    if args.check:
        ok = True
        for name in SOURCES:
            try:
                payload = SOURCES[name].fetch(Client(), cfg, cfg["season"])
                cache.save(name, payload)
                state.error.pop(name, None)
                what = (len(payload.get("players") or []) or
                        len(payload["rows"]))
                print(f"OK   {name}: {what} players/rows, "
                      f"notes={payload['notes']}")
            except Exception as exc:  # noqa: BLE001
                ok = False
                state.error[name] = str(exc)
                print(f"FAIL {name}: {exc}")
        raise SystemExit(0 if ok else 1)

    port = args.port or cfg.get("port", 8765)
    handler = partial(Handler, state=state)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"sidecar board: http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

