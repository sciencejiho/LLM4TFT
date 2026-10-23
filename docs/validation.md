# Workbench validation — 2026-10-23

Validated on Linux with Python 3.9.24 and the frozen uv environment.

## Executed checks

| Check | Result |
| --- | --- |
| `QT_QPA_PLATFORM=offscreen uv run pytest -q` | 94 passed in 4.40 seconds |
| Ruff check on changed/supported modules and tests | Passed |
| Ruff format check | 42 files formatted |
| Mypy with `--follow-imports=silent` on app/server/launcher/recording/research/client/engine | 41 source files, no issues |
| `uv sync --frozen` | Passed |
| `git diff --check` | Passed |
| Independent final integration review | Ready for publication; confirmed findings fixed |

The test run emits seven copies of an upstream Engine.IO/aiohttp deprecation
warning: Engine.IO supplies a float websocket timeout where aiohttp now prefers
`ClientWSTimeout`. The warning is not suppressed. Changed application code has
no Ruff or mypy warnings.

## Real CLI and visual checks

Executed the supported command against an owned subprocess, outside the test
server's accelerated fixtures:

```bash
uv run python research_client.py --policy baseline --seed 7 --games 1 --data-dir <temporary-directory>
```

The complete 34-round match finished in **4.67 seconds**, including process
startup and cleanup. Its JSONL contains one metadata row, 68 decision rows and
one completed outcome, totaling 952,106 bytes. All rows parsed successfully;
decision observations contain no opponent player collection. A second independent
run reproduced the same rounds and seat ranking under distinct output IDs.

Inspected populated preparation and combat renders, both 1440×960. Screenshots
in `docs/images/` show example state rather than an experimental result. The
desktop integration test uses real Qt widgets, a real socket worker and an owned
server process to log in, create a match, start combat and shut down cleanly.

## Regression boundaries

Coverage includes gold interest thresholds, early/streak income, seed isolation,
attack speed in simulation seconds, finite unit supply and upgrade/sale returns,
active filler opponents, role placement, unique player IDs, odd-player ghosts,
round limits, and continuation after a human is eliminated or disconnects.

Lifecycle/data tests cover startup failure, free local ports, process ownership,
unavailable servers, canceled transport tasks, acknowledged navigation, recording
row/byte ceilings, terminal capacity, failed journal startup/writes, malformed and
out-of-phase actions, private policy observations, bounded inference, stale model
responses, and authoritative interrupted/error outcomes. Historical eight-agent
rooms still auto-start when full; their `playing` state is delivered to clients.

OpenAI response parsing and retries were tested with offline SDK-compatible
responses. No paid API request was made. Live credentials, model availability,
and platform-specific desktop packaging were not exercised.

## Reliable Python review

Ran the bundled checker with system Python (its AST implementation requires a
newer interpreter than the project's Python 3.9). The complete changed Python
scope produced **0 errors and 175 advisory warnings**; the checker exits 1 when
warnings are present. These warnings were retained for review, rather than
hidden with blanket suppressions.

| IDs | Evidence, practical scope and rationale |
| --- | --- |
| POT02 / POT03 | Container loops and appends are often bounded outside the current function. Sessions cap players at 8, field/bench/shop at 28/9/5, catalog at 1,000 definitions, games at 8, rounds at 200, model attempts at 3, and journal rows/bytes explicitly. Tests verify exhausted limits. Direct engine callers must preserve these documented container invariants. |
| POT05 | The heuristic averages defensive checks across Qt callbacks, rendering methods, accessors and test fixtures. Validation is concentrated at CLI, socket, model-output and resource boundaries; trivial callbacks do not duplicate those checks or add tautological assertions. |
| POT09 | Qt signal connections, Socket.IO transport ownership and typed widget composition generate three-level attribute chains. Their ownership and event boundaries are explicit; cancellation and cross-thread UI behavior have real integration tests. |
| POT08 | `Status._combine` reflects over a fixed tuple of ten declared numeric fields. No external attribute name, dynamic import, evaluation or generated code is involved. |
| CS02 / CS04 / CS05 | Game/player event facades and the existing ten-field stats constructor retain their public contracts. Startup, recording, rules and presentation concerns were extracted where they have independent behavior; further hierarchy changes would expand this task. |
| CS15 | Recorder/session objects expose bounded lifecycle state and own behavior; they are not abandoned data-only classes. |
| CS20 | Focused failure-path tests call private lifecycle helpers to reproduce cancellation and resource exhaustion. Production consumers use public entry points. |

Small, adjacent suppressions explain the offscreen Qt test import setup and
specific framework/test false positives. No blanket module or rule suppression
was introduced. The simplified game still uses physical basic attacks only;
the research preset is an initial reproducible balance, not a validated claim
that every strategy is equally competitive.
