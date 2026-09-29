# ENH-023 — Luck vs. skill index

Status: open · Category: content & features

Luck vs. skill index (owner idea, 2026-09-23). Replace the
current `luckIndex` (h2h − topHalf = "lucky wins − unlucky losses") with a
skill/luck split on the all-play record (`all_play_records`, already
computed): **skill** = all-play win rate (scoring vs. the whole league,
schedule removed); **luck** = actual wins − (all-play rate × games) = net
wins of schedule/matching luck. Verified 2021–24: the luck spread is 3–6
wins and tells real stories (2024: 2nd-best all-play scorer finished 5-9 on
a brutal draw). Flavor stats: close-game win % (<10-pt games) and
home-run-minus-bomb (weekly top scorer minus weekly last).
- Owner's alt data point: scoring vs. **league average** (easy — we have
  `averageScore`). Logged as a candidate "skill" proxy.
- **Caveat (don't over-claim):** with team-level weekly scores we can't
  separate *skill* from *roster luck* — a great waiver-wire haul or drafting
  a breakout RB1 inflates scoring without "skill." So all-play rate and
  league-average scoring are proxies for "underlying scoring," not pure
  skill. The split cleanly separates *schedule* luck, not skill from roster
  luck.
- Pythagorean/margin luck is **degenerate here**: in H2H the higher scorer
  always wins (0 exceptions in 2024), so there's no "outscored but lost."
