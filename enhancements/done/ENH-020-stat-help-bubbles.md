# ENH-020 — Stat help bubbles + mobile column visibility

Status: done

Stat help bubbles + mobile column visibility — done
2026-09-23. "?" bubbles beside Home/Playoffs stat headers explain each
stat (hover on desktop, tap/keyboard on mobile); H2H Wins and Top Six
Finishes no longer hidden on small screens; Playoffs "Week N" renamed
"Most Recent". The tip is a JS-positioned floating div clamped to the
viewport — a pure-CSS ::after tip clipped at the table's overflow
container edge on phones.
