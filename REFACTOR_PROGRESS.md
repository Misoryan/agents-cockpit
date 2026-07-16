# codex-web refactor progress

This note records the current refactor state for the local Agents Cockpit
checkout. It is intentionally concise so future changes can stay incremental.

## Current Structure

- `app.py` selects web mode, manager mode, or stop/help commands.
- `web.py` owns browser login, restart/stop endpoints, static assets, and proxying to the manager.
- `manager.py` is now a thin HTTP/WebSocket shell; session lifecycle lives in `manager_sessions.py`, internal gate/control endpoints in `manager_internal_api.py`, and browser APIs in `manager_user_api.py`.
- `common.py` is now mostly a compatibility facade over focused helpers such as `common_auth.py`, `common_process.py`, `common_history.py`, `common_registry.py`, and `common_http.py`.
- `native.py` keeps the Claude session class while delegating CLI argv/process/replay/gate helpers to `native_*.py` modules.
- `codex_native.py` keeps the Codex session class while delegating app-server client, routing, requests, replay, text/form/history, thread-history conversion, and notification lifecycle helpers to `codex_*.py` modules.
- `index.html` is now mostly markup. Frontend assets live under `assets/`, split into app shell/sidebar/state/native/replay/socket/action/auth/icon files.

## Completed Items

- Multi-user gate calls carry internal auth and user context through `gate_mcp.py` and per-session MCP config.
- Manager internal routes are separated from browser routes and covered by boundary tests.
- `/api/nsend` has a backend busy guard.
- Claude replay/polling has stable `seq`/dedupe support.
- Codex replay recovery avoids startup app-server I/O and drops recovery-only noise.
- Frontend history loading requests live Codex history with `live_codex=1`.
- Unused launch/settings `args` UI was removed because the backend does not consume it.
- Static frontend CSS/JS is served through `/assets/*` with traversal protection.
- Codex incremental replay trims merged stream chunks after the browser's last
  rendered `seq`, so reconnect/poll recovery does not duplicate already visible
  text or force a full conversation repaint.
- The frontend preserves existing turn/thinking DOM when reconnecting a session
  that already has content, reducing visible flicker during WebSocket 1006-style
  disconnect/reconnect loops.
- Codex Plan external notifications now use stable readable text instead of
  mojibake strings.
- Markdown sanitizing and syntax highlighting libraries are vendored under
  `assets/vendor/`, so the chat UI no longer waits on CDN access.
- `tools/app_server_protocol_matrix.py` regenerates
  `docs/app-server-protocol-matrix.md` from the installed Codex app-server
  schema, giving future CLI upgrades a clear protocol drift checklist.
- Codex launch config has its first CLI-parity slice: the launch modal can set
  model, web search, sandbox, and approval policy; backend normalization lives
  in `codex_config.py`, and the values are passed to `thread/start` and
  `turn/start` instead of being cosmetic UI only.
- Codex launch config now also passes reasoning effort, reasoning summary,
  service tier, and extra workspace-write writable directories through
  schema-shaped `thread/start` config and `turn/start` overrides, with user
  workspace boundary checks before launch.
- The launch modal reads `model/list`, `permissionProfile/list`, and
  `config/read` asynchronously from app-server so opening a session still stays
  non-blocking when capability discovery is slow or unavailable.
- Codex slash commands have a first backend-driven palette: `/model <id>`
  updates the session model for subsequent turns and broadcasts the badge to all
  connected clients, `/compact` calls `thread/compact/start` and relies on the
  app-server `thread/compacted` notification to clear busy state, and
  `/approval`, `/sandbox`, `/search` update only when the app-server can really
  consume the setting.
- The slash palette now also exposes `/reasoning`, `/summary`,
  `/service-tier`, and `/add-dir` for Codex turns, so common CLI-style model
  tuning and workspace-write changes can be applied without restarting the web
  session.
- Thread lifecycle slash commands now cover `/rename`, `/archive`, and `/fork`
  through app-server `thread/name/set`, `thread/archive`, and `thread/fork`;
  the web UI reports the confirmed backend action to every connected client.
- Thread lifecycle and goal slash commands now also cover `/unarchive` and
  `/goal get|set|status|clear` through app-server `thread/unarchive` and
  `thread/goal/*`; goal/unarchive notifications are surfaced as Codex notices
  so all connected clients see the same confirmed state.
- The sidebar now exposes common running Codex thread actions (`Rename`,
  `Goal`, `Fork`, `Rollback`, `Compact`, `Archive`) by calling the same `/api/nslash` backend
  path, so long-running sessions no longer require remembering slash commands
  for these lifecycle controls.
- Codex history rows now expose `Rename`, `Goal`, `Fork`, and `Archive`
  shortcuts through `/api/codex_history_action`; the manager calls app-server
  `thread/name/set`, `thread/goal/set`, `thread/fork`, or `thread/archive`
  directly under the current user's Codex home, so history
  entries can use common CLI lifecycle actions without first resuming a thread.
- The sidebar now has an Active/Archived history filter for Codex threads.
  Archived view calls live app-server `thread/list` with `archived=true` and
  archived rows expose `Unarchive` through the same `/api/codex_history_action`
  path, closing the first lifecycle UI gap left after archive support.
- The slash palette supports keyboard up/down selection, keeping CLI-style
  command discovery usable without requiring mouse interaction.
- Codex `@` file mentions have a first app-server-backed path: the input box
  queries `/api/nfiles`, the backend calls `fuzzyFileSearch` scoped to the
  session cwd, and selected paths are sent as Codex `mention` user input items
  instead of plain decorative text.
- Codex image input has a first web path: users can paste or choose image
  files, `/api/nsend` stores them in the per-session upload directory, and
  `turn/start` receives schema-shaped `localImage` user input while replayed
  user messages show synchronized image cards.
- `/fork` now emits a replayable `thread_forked` event with an "open fork"
  action, so every connected client can resume the forked Codex thread through
  the existing history resume path instead of copying the thread id manually.
- `tools/codex_ws_smoke.py` provides a non-destructive live reconnect probe:
  it connects to a running Codex session, reconnects with `after=<lastSeq>`,
  and fails if already rendered replay events are sent again.
- The same smoke probe now supports `--clients 2`, opening two simultaneous
  WebSocket clients against one Codex session and verifying both receive the
  same replay seq before reconnecting each client with its own `after` cursor.
- When no Codex session is already open, the probe can run with
  `--launch-temp` to create and stop a temporary idle Codex session for the
  same two-client reconnect invariant.
- The two-client probe also exercises a safe live `mode_state` broadcast for
  temporary sessions, proving that two access sources see the same live event
  before both reconnect without duplicate replay.
- Codex history resume now normalizes replay events with stable `seq` values
  via `_adopt_history_replay`, so old thread history loaded from app-server can
  still participate in incremental reconnect instead of forcing a full replay.
- Codex terminal-interaction requests now have a first web path: app-server
  `item/commandExecution/terminalInteraction` renders a stdin card, and
  `/api/nterminal` maps write/close/resize/terminate actions to
  `command/exec/write`, `command/exec/resize`, and
  `command/exec/terminate`.
- MCP manual parity has a first slice: `/mcp-resource <server> <uri>` and
  `/mcp-tool <server> <tool> <json>` call app-server
  `mcpServer/resource/read` and `mcpServer/tool/call`, then broadcast replayable
  tool_use/tool_result events to every connected client.
- Codex dynamic tool calls now have a safe first passthrough slice:
  `[codex_dynamic_tools]` maps explicit `namespace.tool`, `namespace.*`, or
  bare `tool` keys to `mcp:<server>/<tool>` targets; mapped `item/tool/call`
  requests call `mcpServer/tool/call` and return `DynamicToolCallResponse`,
  while unmapped tools still fail visibly instead of pretending success.
- Unsupported Codex account/security requests now have safer recovery UX:
  `account/chatgptAuthTokens/refresh` and `attestation/generate` show concrete
  CLI recovery steps without exposing token material or returning fake success.
- README/config now document a hardened profile for tunneled/shared use:
  HTTPS-only cookies, workspace-root restrictions, per-user Codex/Claude homes,
  and web approval gates instead of auto-approve.
- Frontend `state_snapshot` handling now also clears stale thinking/turn UI
  when the server says the session is no longer running, covering missed result
  events during WebSocket 1006-style reconnects without repainting the whole
  conversation.
- WebSocket frame writes are serialized per socket in `common_ws.py`, so the
  keepalive ping thread cannot interleave protocol frames with live broadcast
  messages; this targets one plausible source of browser 1006 disconnects.
- Frontend replay de-duplication now uses one stable key path for live and
  replayed events, filters duplicate events inside replay batches, and skips
  already-rendered replay events during polling or reconnect recovery.
- The visible Codex/native session now has a throttled catch-up replay poll:
  session status polling can call `/api/nreplay?after=<lastSeq>` even while the
  WebSocket is still open, so stale-open sockets can recover missed events
  silently without clearing or repainting the conversation.
- Standalone Codex diff results now render as update-in-place diff cards instead
  of generic result blobs, so repeated `turn/diff/updated` snapshots replace the
  same card and keep long coding turns closer to the CLI diff experience.
- JSON-shaped tool results now render as structured result cards with a short
  preview and pretty JSON body, improving MCP/dynamic/tool result readability
  without changing the replay event contract.
- Codex sleep, context-compaction, image-generation, and image-view tool starts
  now use dedicated compact cards instead of raw JSON input dumps.

## Optional Follow-ups

- Reduce `codex_native.py` further only if the remaining session core grows again; thread-history conversion is now in `codex_thread_history.py`.
- Decide whether `web.py` should be split into auth, proxy, and lifecycle helpers; current size is acceptable but still mixed.
- For release hardening, restart web/manager and manually exercise login, launch, replay, ask/approve, and reconnect flows.

## Validation Bundle

Run this bundle after behavior changes:

```powershell
python -m py_compile app.py web.py common.py manager.py native.py codex_native.py codex_config.py gate_mcp.py codex_client.py codex_events.py codex_forms.py codex_history.py codex_replay.py codex_requests.py codex_routing.py codex_session_events.py codex_text.py codex_thread_history.py common_auth.py common_binaries.py common_browse.py common_ccswitch.py common_history.py common_http.py common_notify.py common_process.py common_registry.py common_users.py common_ws.py manager_internal_api.py manager_sessions.py manager_user_api.py native_cli.py native_config.py native_gate.py native_replay.py tools\app_server_protocol_matrix.py tools\codex_ws_smoke.py
Get-ChildItem assets -Recurse -Filter *.js | Sort-Object FullName | ForEach-Object { node --check $_.FullName }
Get-ChildItem tests\check_*.py | Sort-Object Name | ForEach-Object { python $_.FullName }
git diff --check
```

Regenerate the protocol matrix after Codex CLI upgrades:

```powershell
python tools\app_server_protocol_matrix.py --out docs\app-server-protocol-matrix.md
```

Run this optional live smoke when the local manager has at least one Codex
session open:

```powershell
python tools\codex_ws_smoke.py --seconds 2
python tools\codex_ws_smoke.py --clients 2 --seconds 2 --launch-temp --cwd .
```
