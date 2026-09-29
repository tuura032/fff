# ENH-022 — League feed

Status: shelved 2026-09-29 · Category: content & features

League feed (owner idea, 2026-09-23): a feed of league
chatter — user comments, plus the ability to create polls (e.g. "should we
switch to 2QB or superflex?") that members can vote on. Open question,
unsolved: this is user-generated content and the static-site + daily-git-
commit strategy has no way to persist comments or votes. If it can't be
done cleanly, the fallback is the existing Facebook group and this item
stays open/closed as "not here."

## Why shelved

Declined. User comments and polls need somewhere to store what people write, and the static-site + daily-commit design has none (NOT-BUILDING.md rules out a database and accounts). The league's Facebook group already does this. This was the fallback the item itself named.
