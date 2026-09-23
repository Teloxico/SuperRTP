# Known Issues

## Intermittent live RM2000/RM2003 CharSet capture (EasyRPG Player 0.8.1.1)

**Status:** open. The committed evidence in `artifacts/runtime/rm2000/charset/` and
`artifacts/runtime/rm2003/charset/` verifies. A *fresh* live capture
(`tests/test_runtime_evidence.py`, `test_rm2000_charset` / `test_rm2003_charset`)
fails in about a third of runs. In CI it runs in its own step with
`continue-on-error: true`, so failures stay visible without blocking the build.

**What happens.** The positive control starts with the hero facing down and sends
Left, Up and Right as X11 key presses (`tools/verify_runtime.py`). In passing sessions,
each press turns the hero and moves it one tile. `EXPECTED_CENTROIDS` encodes those
moved positions. In failing sessions, the hero turns to the new facing but does not
move, in that session and for every later press. The facing check therefore fails on
position: it reports the down-facing centroid, (337.0, 219.5), for the left capture.

**Established facts (2026-09-23):**
- The failing screenshots show the correct left-facing and right-facing arrows at the
  start tile. The CharSet rows render correctly, so the fault is in the step, not the
  asset.
- X keyboard focus is on the EasyRPG window in both passing and failing sessions
  (`xdotool getwindowfocus`).
- Session logs of passing and failing runs are identical apart from timestamps.
- The fixture map (`tools/generate_fixture.cpp`) is 20×15, and every tile is passable
  in all four directions.
- `Game_Player::UpdateNextMovementAction` (0.8.1.1 `src/game_player.cpp`) has no
  time-dependent branch between turning and moving.
- Waiting for a pixel-stable frame before the first key press, which rules out the
  new-game fade-in (`src/scene.cpp`), did **not** change the failure rate.
- Waiting a further 2 s before the first press passed 8 of 8 runs. This is not
  treated as a fix: the mechanism is unknown, and a sleep would only hide it.

**Next steps for whoever picks this up:**
1. Record the failing session and check whether the hero starts a step and is pulled
   back, or never starts one.
2. Compare `Game_Character::Move` / `MakeWay` state (e.g. through EasyRPG's debug
   overlay) between passing and failing sessions.
3. Alternatively, make the facing check independent of position: locate the sprite
   and classify it by arrow shape only. This verifies what the CharSet slice is about
   and is robust to whether the hero steps. It changes the recorded
   `directional_evidence`, so the committed evidence would have to be re-captured.
