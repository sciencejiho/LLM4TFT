# LLM4TFT research workbench

The user selected a fork named LLM4TFT and requested implementation of a more
recognizable interface, single-command local startup, and better economy/power
progression. The primary use is single-player LLM research and data creation;
human play must remain useful. Keep PyQt and the Socket.IO engine rather than
introducing a second frontend or simulation.

## Approach

Use the existing engine with versioned research and legacy profiles. Correctness
fixes apply to both. Research uses capped interest by tens, modest early income,
bounded streak rewards, longer battles, 100 HP, and explicit planning completion.
Legacy preserves old pacing and income constants for comparison. Seed all game
randomness locally. Fill missing players with active deterministic baseline bots.
This is an intentionally simplified autobattler, not an exact TFT implementation.

Unit roles describe existing mechanics: tank, fighter, marksman. Do not advertise
spellcasting, traits, or item effects that the engine does not implement. Expose
role, range, scaled combat stats and cost to both UI and agent observations.

The desktop application starts an owned local server on an available loopback
port, reports startup/connect failures, and closes its process and socket thread
on exit. Explicit remote mode must never spawn or stop a remote server. Server
paths are relative to the repository rather than the caller's working directory.

The UI uses a dark board, clear shop/bench hierarchy, role icons and labels,
selected-unit stats, HP bars, economy breakdown, connection status and a combat
control. Reuse board widgets rather than rebuilding them at simulation frequency.
Retain drag and drop, scouting, CLI clients and existing LLM clients.

Save incremental decision records with observations, actions, results, seed and
ruleset metadata, and a terminal outcome. Privileged engine snapshots must remain
separate from player observations. Bound rounds, retries and recording growth.

## Validation

Tests must cover interest boundaries, progression, deterministic seeds, bot
activity, process readiness/ownership/cleanup, real Socket.IO command flow, and
offscreen UI state/selection/phase transitions. Render a populated screenshot and
inspect it. Run the complete suite, lint/type checks appropriate to changed code,
and the Reliable Python checker. Preserve local user data and API credentials.

## Scope decisions

Implement in the existing clean checkout on a feature branch. No engine rewrite,
Riot assets, new paid APIs, or upstream publication is needed to make the work
reviewable. Clarification about the upstream remote is pending separately.
