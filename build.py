"""Render the FFF static site from templates/ and data/standings-<season>.json.

Reads data/standings-<season>.json (written by compute.py) and renders
templates/ to docs/ per SPEC.md §9 (L4): home.html -> index.html,
playoffs.html -> playoffs.html, graph.html -> graph.html (L5), plus
static/ copied alongside.
Pure: no network, re-runs offline. Output is deterministic (no timestamps)
so L7 can commit only when it changes.

Multi-season (L9): with no --season, every season that has a standings
file is built. The newest season is the site root (docs/); each older
season goes to docs/<season>/. Newest-season-is-root (rather than "the
current calendar year") keeps the root live through the off-season, when
the new year's season does not exist on ESPN yet. layout.html's season
picker links the seasons with relative URLs via the "base" context var;
static/ is copied into every output directory so the templates' relative
asset paths resolve in the subdirectories too.

Pages not rendered (SPEC.md §4 — render only what the data supports, do not
invent data):
- player1.html needs per-team roster data, not in standings.json.
- weeklyupdate.html / welcome.html POST to Flask routes that no longer exist.
- update.html / error.html were admin/Flask concerns and are dropped.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

import compute

# (template, output file) — home is the site root: layout.html's navbar
# links to index.html (de-Flasked in L3).
PAGES = (
    ("home.html", "index.html"),
    ("playoffs.html", "playoffs.html"),
    ("graph.html", "graph.html"),
    ("rivalries.html", "rivalries.html"),
    ("careers.html", "careers.html"),
    ("kickers.html", "kickers.html"),
    ("league.html", "league.html"),
)


def phrase_hash():
    """SHA-256 of the league passphrase, or "" when none is configured.

    The phrase itself is never committed: CI puts it in the environment from
    a GitHub Secret (LEAGUE_PHRASE) and only this digest is baked into the
    page. A local build with no secret set produces no hash, which disables
    the gate entirely -- so `python build.py` on a laptop still renders a
    browsable site.

    Be clear about what this is: the page content ships in the HTML either
    way, so the gate keeps out search engines and casual visitors, not anyone
    willing to open devtools. It is a doorbell, not a lock. The reason that
    is acceptable here is that there is nothing sensitive behind it any
    more -- surnames are stripped from the data at fetch time.
    """
    phrase = os.environ.get("LEAGUE_PHRASE", "").strip()
    if phrase:
        return hashlib.sha256(phrase.encode("utf-8")).hexdigest()
    # LEAGUE_PHRASE_SHA256 lets someone rebuild the site byte-identically
    # without knowing the phrase -- the digest is public in the deployed
    # page anyway, and requiring the secret to reproduce a build would mean
    # every local rebuild silently dropped the gate.
    digest = os.environ.get("LEAGUE_PHRASE_SHA256", "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", digest or ""):
        return digest
    if digest:
        print(f"WARNING: LEAGUE_PHRASE_SHA256 is not a 64-char hex digest; "
              f"ignoring it and building without a gate.", file=sys.stderr)
    return ""


def previous_gate_hash(docs):
    """The gate digest already baked into a built site, or "".

    Read back out of docs/index.html so a rebuild can tell whether it is
    about to remove a gate that is currently live.
    """
    page = docs / "index.html"
    if not page.exists():
        return ""
    match = re.search(r"var HASH = '([0-9a-f]{64})'",
                      page.read_text(encoding="utf-8"))
    return match.group(1) if match else ""


def ordinal(n):
    """1 -> '1st', 2 -> '2nd', 12 -> '12th', 23 -> '23rd'.

    Used for final placements. 11/12/13 are the exceptions that a naive
    last-digit lookup gets wrong ("11st"), so they are special-cased.
    """
    if n is None:
        return ""
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def main():
    parser = argparse.ArgumentParser(description="Render the FFF static site to docs/.")
    parser.add_argument("--season", type=int, default=None,
                        help="Build only this season (default: every season with a standings file)")
    parser.add_argument("--no-gate", action="store_true",
                        help="Allow a build that removes an existing passphrase gate")
    args = parser.parse_args()

    data_dir = Path("data")
    all_seasons = sorted(
        (int(p.stem.split("-")[1]) for p in data_dir.glob("standings-*.json")),
        reverse=True)
    if not all_seasons:
        print("ERROR: no data/standings-<season>.json found. Run compute.py first.",
              file=sys.stderr)
        sys.exit(1)

    if args.season is not None:
        if args.season not in all_seasons:
            print(f"ERROR: data/standings-{args.season}.json not found. "
                  f"Run compute.py --season {args.season} first.", file=sys.stderr)
            sys.exit(1)
        seasons = [args.season]
    else:
        seasons = all_seasons

    # Newest season is the site root; older seasons go to docs/<season>/.
    root_season = all_seasons[0]
    current_season = datetime.now().year

    # Rivalries are all-time, so they're computed once from every season on
    # file (not just the season(s) being (re)built) and reused on every
    # rendered page, regardless of --season.
    all_standings = [json.loads((data_dir / f"standings-{s}.json").read_text(encoding="utf-8"))
                      for s in all_seasons]
    rivalry_owners, rivalry_matrix = compute.build_rivalries(all_standings)
    careers = compute.build_career_stats(all_standings)

    # Prize amounts (the league pot) are a league setting, not ESPN data, so
    # they live in data/prizes.json instead of being hardcoded in the
    # template. The owner edits that file when the pot changes; build.py just
    # reads it. Read once here (not per-season) since the pot is a single
    # league-wide setting shared by every rendered season.
    prizes_path = data_dir / "prizes.json"
    if not prizes_path.exists():
        print("ERROR: data/prizes.json not found.", file=sys.stderr)
        sys.exit(1)
    prize_config = json.loads(prizes_path.read_text(encoding="utf-8"))
    # All-time winnings, computed once over every season on file. Only
    # fully-decided seasons contribute, so an in-progress year doesn't pay
    # out money nobody has won yet.
    career_money = compute.career_payouts(all_standings, prize_config)
    # Only seasons that actually paid out, newest first -- the per-year
    # columns on the all-time winnings table.
    money_seasons = sorted({year for row in career_money for year in row["bySeason"]},
                           reverse=True)

    # Display names: the league refers to each other by first name, and
    # team names change yearly while people don't. Built from every owner
    # across every season at once so a name reads the same on every page.
    all_owners = {row["owner"]
                  for season_data in all_standings
                  for row in season_data["standings"]}
    short = compute.short_names(all_owners)

    # All-time kicker rankings (the Kickers page). Sourced from
    # data/starters-<season>.json, which fetch.py --starters writes -- a
    # separate, deliberately manual fetch (see its docstring), so the files
    # may be absent or cover fewer seasons than standings-*.json do. That is
    # fine: build_kicker_stats returns None when there is nothing to rank and
    # the page is then skipped entirely rather than rendered empty. Owner
    # names are shortened here because the awards bake them into sentences.
    all_starters = [json.loads(path.read_text(encoding="utf-8"))
                    for path in sorted(data_dir.glob("starters-*.json"))]
    kicker_stats = compute.build_kicker_stats(all_starters, all_standings, short)
    if kicker_stats:
        print(f"Kickers: {kicker_stats['distinctKickers']} kickers, "
              f"{kicker_stats['totalStarts']} starts, "
              f"{kicker_stats['totalPoints']} points")
    else:
        print("Kickers: no data/starters-*.json found; skipping the page. "
              "Run `python fetch.py --starters --season <year>` to add it.")
    pages = [entry for entry in PAGES
             if entry[0] != "kickers.html" or kicker_stats]

    env = Environment(loader=FileSystemLoader("templates"),
                      autoescape=select_autoescape())
    env.filters["ordinal"] = ordinal
    gate_hash = phrase_hash()
    if gate_hash:
        print("Passphrase gate: enabled (hash baked in, phrase not stored)")
    else:
        # Refuse to silently un-gate a site that is currently gated. This
        # has already happened once: a rebuild during unrelated work
        # dropped the gate from every page and `git add -A` committed it,
        # publishing the league ungated until someone noticed. A build that
        # removes the gate must now say so out loud, or be told to.
        existing = previous_gate_hash(Path("docs"))
        if existing and not args.no_gate:
            print("\n".join([
                "ERROR: docs/ is currently gated but no passphrase is set, "
                "so this build would strip the gate from every page.",
                "  Set LEAGUE_PHRASE, or pass the existing digest:",
                f"    LEAGUE_PHRASE_SHA256={existing} python build.py",
                "  If removing the gate is intended, re-run with --no-gate.",
            ]), file=sys.stderr)
            sys.exit(1)
        print("Passphrase gate: disabled (set LEAGUE_PHRASE to enable)")
    # `short` on a full owner name; `names` on a list of them, joined as
    # "A", "A & B" or "A, B & C".
    env.filters["short"] = lambda owner: short.get(owner, owner)
    env.filters["names"] = lambda owners: compute.join_names(
        [short.get(o, o) for o in owners])
    docs = Path("docs")

    # Cache-busting versions for the two assets a browser is most likely to
    # hold onto: app.css and the self-hosted fonts. Both ship under stable
    # URLs, so a visitor who loaded the site before a deploy keeps getting
    # the cached copy afterwards -- which is how the header redesign arrived
    # broken on desktop (new HTML + cached old CSS: the logo SVG rendered at
    # its default 300x150 size and the wordmark wrapped and clipped). A
    # content hash in the query string makes every content change a new URL,
    # so the fresh asset is fetched instead of the stale one. The CSS is
    # hashed after normalizing CRLF -> LF so a Windows checkout and CI (LF)
    # produce the same version and the build stays byte-identical.
    css_version = hashlib.sha256(
        Path("static/css/app.css").read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()[:12]
    font_versions = {
        f.name: hashlib.sha256(f.read_bytes()).hexdigest()[:12]
        for f in sorted(Path("static/fonts").glob("*.woff2"))
    }

    for season in seasons:
        data = json.loads((data_dir / f"standings-{season}.json").read_text(encoding="utf-8"))
        out_dir = docs if season == root_season else docs / str(season)
        out_dir.mkdir(parents=True, exist_ok=True)
        context = {
            "standings": data["standings"],
            "weeks": data["weeks"],
            "throughWeek": data["throughWeek"],
            "regularSeasonWeeks": data["regularSeasonWeeks"],
            "season": data["season"],
            # L9 — season picker: every season, newest first; "base" is the
            # relative prefix that makes the picker's links resolve from a
            # subdirectory ("../" for past seasons, "" at the root).
            "seasons": all_seasons,
            "current_season": current_season,
            # The newest season that has data, which is what lives at the
            # site root. Distinct from current_season (the calendar year):
            # in the off-season the new year exists but has no data yet.
            "root_season": root_season,
            "base": "" if season == root_season else "../",
            "rivalry_owners": rivalry_owners,
            "rivalry_matrix": rivalry_matrix,
            "careers": careers,
            # All-time kicker rankings, or None when no starter data is on
            # file -- layout.html hides the nav link in that case.
            "kicker_stats": kicker_stats,
            # Prize lines for this season, each already resolved to a
            # winner, plus the same money re-cut as a ranked payout table.
            # Both come from one resolver in compute.py -- when the macro
            # owned that logic the two views could silently disagree.
            "prizes": compute.resolve_prizes(
                data, compute.prizes_for_season(prize_config, season)),
            "payouts": compute.season_payouts(
                data, compute.prizes_for_season(prize_config, season)),
            "career_money": career_money,
            "money_seasons": money_seasons,
            "entryFee": data.get("entryFee"),
            "phrase_hash": gate_hash,
            # How many teams make the playoffs, per the league's own ESPN
            # settings. home.html used to assume half the field, which is
            # right for this league only by coincidence.
            "playoffTeamCount": data.get("playoffTeamCount"),
            # The league's scoring rules, grouped for the League Info page.
            "scoring": data.get("scoring"),
            # The league's standing rules (roster, draft, keepers, playoffs,
            # trades, FAAB) for the League Info page.
            "rules": data.get("rules"),
            # Championship results (None until a season's final is decided),
            # plus a teamId -> owner lookup so the prize table can name a
            # champion without re-scanning standings in the template.
            "playoffs": data.get("playoffs"),
            "owner_by_team": {s["teamId"]: s["owner"] for s in data["standings"]},
            # Whether this season has finished and ESPN has published final
            # placements. Drives the "Finish" column, which is meaningless
            # (and all em-dashes) mid-season.
            "has_final_ranks": any(s.get("finalRank")
                                   for s in data["standings"]),
            # Final placement order, best first -- the answer to "how did
            # this season actually end", which for a past season matters at
            # least as much as the regular-season table.
            # Advanced stats, records and awards for the Stats page.
            # Derived at render time from the week data already on disk --
            # no extra ESPN call, nothing new stored in the JSON artifact.
            "season_stats": compute.build_season_stats(data),
            "final_standings": sorted(
                (s for s in data["standings"] if s.get("finalRank")),
                key=lambda s: s["finalRank"]),
            "updated": data.get("updated"),
            "leagueName": data.get("leagueName"),
        }
        def emit(template, out, active_page, **extra):
            """Render one template to out and apply the cache-bust swap.

            encoding="utf-8": the locale default (cp1252 on Windows) would
            corrupt non-ASCII text (owner names, dashes) in the HTML.

            root_prefix: pages written one level below the season root
            (team/<id>.html) need the nav links to climb back up one
            directory; flat pages get "". layout.html's season picker does
            not need it -- it builds cross-season URLs off base + active_page.
            """
            root_prefix = "../" if out.parent != out_dir else ""
            html = env.get_template(template).render(
                active_page=active_page, root_prefix=root_prefix,
                **{**context, **extra})
            # layout.html links the stylesheet by stable URL; point it at the
            # content-hashed one (see css_version above). Team pages sit one
            # level below the season root, so their asset URLs carry a ../
            # prefix (root_prefix); accept both spellings.
            html = re.sub(r'href="((?:\.\./)?)static/css/app\.css"',
                          lambda m: f'href="{m.group(1)}'
                                    f'static/css/app.css?v={css_version}"',
                          html)
            if f"app.css?v={css_version}" not in html:
                print(f"WARNING: {out} no longer references "
                      f"static/css/app.css; cache-busting not applied.",
                      file=sys.stderr)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html + "\n", encoding="utf-8")
            print(f"Wrote {out}")

        # active_page drives the sidebar's active nav state (L5).
        for template, out_name in pages:
            emit(template, out_dir / out_name, out_name)

        # Team pages (ENH-025): an index at team.html, then one page per
        # team under team/<teamId>.html. Team IDs are stable per owner
        # across seasons, so the season picker's links from a team page to
        # team/<id> in another year land on the same owner's page.
        emit("team.html", out_dir / "team.html", "team.html")
        for row in sorted(data["standings"], key=lambda s: s["teamId"]):
            team_data = compute.build_team_season(data, row["teamId"])
            if team_data is None:
                continue
            team_page = f"team/{row['teamId']}.html"
            emit("team.html", out_dir / team_page, team_page,
                 team_data=team_data)
        # The templates reference static/ relatively, so every output
        # directory needs its own copy. rmtree first: dirs_exist_ok=True
        # merges instead of mirroring, so a file removed from static/
        # (e.g. dashboard.css, retired for the Tailwind rewrite) would
        # otherwise linger as a stale orphan in docs/ forever.
        static_out = out_dir / "static"
        if static_out.exists():
            shutil.rmtree(static_out)
        shutil.copytree("static", static_out)
        # Same treatment for the fonts: the @font-face rules reference them
        # by stable URL, so a changed woff2 would be masked by the browser's
        # cached copy. Rewrite only the copied CSS -- the source
        # static/css/app.css stays exactly what the Tailwind build emitted.
        app_css = static_out / "css" / "app.css"
        css_text = app_css.read_text(encoding="utf-8")
        for name, version in font_versions.items():
            css_text = css_text.replace(name, f"{name}?v={version}")
        app_css.write_text(css_text, encoding="utf-8")
        print(f"Copied static/ to {static_out}")

    # robots.txt belongs at the root of the built site. Note this is only
    # honoured if the site is served from a domain root -- a crawler looks
    # for https://host/robots.txt and ignores one under a subpath, which is
    # where a GitHub project page lives. The per-page noindex meta tag in
    # layout.html is what actually does the work today; this file is here
    # so the protection holds if a custom domain is ever added.
    # CNAME tells Pages which custom domain serves this site. Setting a
    # custom domain in the repo's Settings makes GitHub commit this file
    # itself, but docs/ is regenerated and re-committed by the daily
    # workflow, so keeping the domain in data/domain.txt makes it explicit
    # and reproducible instead of a file nobody's build knows about.
    #
    # A custom domain also makes robots.txt start working: a crawler only
    # requests it from a domain root, which a project page under
    # user.github.io/repo/ never is.
    domain_path = data_dir / "domain.txt"
    if domain_path.exists():
        domain = domain_path.read_text(encoding="utf-8").strip()
        if domain:
            (docs / "CNAME").write_text(domain + "\n", encoding="utf-8")
            print(f"Wrote {docs / 'CNAME'} ({domain})")
    elif (docs / "CNAME").exists():
        # GitHub created one from the Settings UI. Leave it alone, but say
        # so -- otherwise the domain silently lives outside the build.
        existing = (docs / "CNAME").read_text(encoding="utf-8").strip()
        print(f"NOTE: docs/CNAME exists ({existing}) but data/domain.txt does "
              f"not. Create it with that domain so rebuilds stay reproducible.")

    (docs / "robots.txt").write_text(
        "\n".join(["# This is a private league page.",
                   "User-agent: *",
                   "Disallow: /",
                   ""]), encoding="utf-8")
    print(f"Wrote {docs / 'robots.txt'}")


if __name__ == "__main__":
    main()
