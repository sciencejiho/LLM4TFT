# LLM4TFT Research Workbench Implementation Plan

> **For agentic workers:** Use the parallel-agent workflow for the disjoint UI and engine domains; the controller integrates server/startup. Track completed steps here.

**Goal:** Deliver an approachable single-player research client with automatic server lifecycle, interpretable units and corrected, reproducible progression.

**Architecture:** Preserve PyQt and Socket.IO. Separate engine rules, presentation, local-process ownership and recording at existing boundaries.

**Tech Stack:** Python >=3.9, PyQt6, aiohttp, python-socketio, uv, unittest/pytest.

**Spec:** `docs/superpowers/specs/2026-10-23-research-workbench-design.md`

## Global Constraints

- Preserve existing agent command event names and unit IDs.
- Use NumPy-style documentation and typed new public boundaries, bounded loops and explicit failures.
- No secrets or existing DB/replay data in commits. No upstream PR without resolving user's destination.
- Disjoint ownership: engine owns pyautobattle/** and tests/test_engine.py; UI owns client/** except socket.py and tests/test_ui.py; controller owns app.py, client/socket.py, server.py, launcher/recording, project configuration and docs.

## Review Focus

- Child server exits early, unavailable ports, shutdown while connecting: launcher integration tests.
- Empty battle state, changing selected/scouted player, elimination and new game: offscreen UI tests.
- Seed interleaving across games and empty unit pools: engine regression tests.
- Late/rejected actions and untimed preparation: real Socket.IO tests.
- Interrupted session: flush incremental recording and check game-ended cleanup.

### Task 1: Engine rules and reproducibility

- [x] Write and run failing regressions for interest at 0/9/10/19/20/50/99 gold, seed determinism, active fillers and decision-based planning.
- [x] Implement `AutoBattlerGame(..., seed=0, ruleset="research", decision_mode=False)` and `Player(..., rules=None)` without breaking existing callers. `game.advance()` starts combat when READY. `game.to_json()["state"]` includes decision_mode and ruleset; `Player.to_json()` adds economy and role-rich units. Use `research` and `legacy` ruleset identifiers.
- [x] Expose `role` (tank/fighter/marksman), `role_description`, `name`, `cost`, `status` in unit JSON; preserve id and level. Existing util functions resolve these or CSV defaults.
- [x] Run engine tests and audit changed engine code; report actual limitations.

### Task 2: Recognizable UI

- [x] Write and run failing offscreen tests for unit roles, selected-unit details, phase control, and widget reuse.
- [x] Replace crowded grey controls with a responsive dark board/shop/bench hierarchy and explanatory inspector. Render real role metadata; fall back honestly for old servers.
- [x] Preserve GameScreen(parent), update_state(data), send_command(action,*args), refresh_style(), set_view_player(index), quit() interfaces. Send `advance_round` to start combat. Parent still exposes run_async and socket_thread. Never call nonexistent trait/spell/item functionality.
- [x] Run UI tests and produce a populated screenshot for inspection.

### Task 3: Integrated startup, recording and documentation

- [x] Write and run failing launcher and real server tests, then implement owned subprocess lifecycle and explicit remote CLI mode.
- [x] Add /health and server CLI paths/options; create runtime directories, use command/event validation, integrate decision-mode advance and bounded JSONL recording with seed/ruleset.
- [x] Add project test/lint tooling, rename project metadata/README to LLM4TFT and document startup, research controls, profile differences and data schema.
- [x] Run full tests, formatting/lint/type checks and Python audit; inspect final diff and UI screenshot, fix confirmed findings and report caveats.

### Task 4: Supported headless data generation

- [x] Add a bounded baseline/OpenAI policy client, private observation filtering and strict action validation with failing regressions first.
- [x] Add owned fast simulation and per-preparation wakeups, retaining identical simulation steps and explicit planning.
- [x] Distinguish completed, failed and interrupted outcomes; reject stale model actions after inference.
- [x] Complete an actual CLI match, inspect JSONL data, and verify independent integration review findings are fixed.
