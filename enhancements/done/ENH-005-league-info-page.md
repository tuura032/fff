# ENH-005 — League Info page

Status: done

League Info page — done 2026-09-23. New "League Info" tab
answers the recurring questions (roster, scoring, draft, keepers, playoffs,
tiebreakers, trades/FAAB, dues). The scoring table and standing rules are
read straight from `mSettings` (`compute.build_scoring_table` /
`build_league_rules`), so they track any commissioner change; keeper pricing
(not in the ESPN API) is owner-confirmed config in the template.
