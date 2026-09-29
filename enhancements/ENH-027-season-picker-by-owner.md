# ENH-027 — Season picker should match teams by owner

Status: open · Category: content & features

Season picker should match teams by owner, not ESPN team
ID (follow-up to BUG-010, 2026-09-28). Team IDs are mostly, not always,
stable per owner: teamId 9 was Maxwell in 2019–20 and Daniel Sharp from
2021 on, so the ID-based picker links can land on a different owner's
page when switching seasons. Needs a cross-season owner→teamId map passed
into the template.
