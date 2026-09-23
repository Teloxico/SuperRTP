# Known Issues

## Resolved: intermittent live RM2000/RM2003 CharSet capture (EasyRPG Player 0.8.1.1)

**Status:** resolved in the verifier on 2026-09-23. The engine behaviour behind it is
still unexplained, but it no longer affects verification.

**What happened.** The positive control starts with the hero facing down and sends
Left, Up and Right as X11 key presses (`tools/verify_runtime.py`). In most sessions each
press turns the hero and moves it one tile. In about a third of sessions the hero only
turns, for that press and every later one. The capture check required the hero's
centroid inside a window that assumed the one-tile step, so the turn-only sessions
failed even though every facing row rendered correctly.

**Established facts:**
- Screenshots from failing sessions showed the correct left and right arrows at the
  start tile. The CharSet rows were right; only the step differed.
- X keyboard focus was on the EasyRPG window in passing and failing sessions alike.
  Session logs were identical apart from timestamps.
- The fixture map is 20×15 with every tile passable. `Game_Player::UpdateNextMovementAction`
  (0.8.1.1) has no time-dependent branch between turning and moving.
- Waiting for a pixel-stable frame before the first press, which rules out the new-game
  fade-in, did not change the failure rate.

**Fix.** The facing is established by the arrow shape (tip versus wings), which never
depended on position. The centroid window was removed. The centroid is still recorded,
and the sprite must still be found near the screen centre. The recorded evidence fields
did not change, so the committed evidence verifies as before. Measured: 10 of 10 live
captures passed (five runs each for RM2000 and RM2003), against about 1 in 3 failing
before. The tests run as a required CI step again.

**Still unknown:** why a direction key sometimes turns without stepping. It matters to
anyone who wants to verify movement itself.

## Open: one intermittent RMXP live capture on CI

On one CI run (2026-09-23), `test_rmxp` found no stable frame in which the scene was
drawn ("observed runs: []"). It has passed on every run since, locally and on CI.
When a live capture fails, CI now uploads the recordings (`live-captures` artifact),
including mkxp's recording as `<screenshot>.failed.mkv`, so the next occurrence can be
inspected.
