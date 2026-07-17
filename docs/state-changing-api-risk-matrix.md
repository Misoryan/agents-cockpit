# State-changing API Risk Matrix

Updated: 2026-07-17

This matrix records the browser-visible and internal POST routes that can mutate
sessions, history, command I/O, uploads, approval state, or process lifecycle.
It is intentionally paired with `tools/check_state_changing_api_risks.py` so new
routes cannot be added without an explicit risk classification.

## Shared Guards

- Browser routes enter through `web.py`, which enforces browser auth and, when enabled, Origin/Referer checks before proxying to the manager.
- Manager user routes require a resolved user context, then re-check session ownership, history ownership, or workspace roots at the handler boundary.
- Internal gate/control routes are separated from browser routes and are expected to require internal Authorization.
- Image upload is currently part of `/api/nsend`; `CodexSession.prepare_image_inputs()` owns MIME, magic-byte signature, size, count, and storage validation for Codex image payloads.

## Browser/Manager User POST Routes

| Route | Risk | Area | Required guards |
| --- | --- | --- | --- |
| `/api/launch` | high | session_lifecycle | auth, user_context, workspace_root, writable_roots |
| `/api/resume` | high | session_lifecycle | auth, user_context, history_owner, workspace_root |
| `/api/nresume` | high | session_lifecycle | auth, user_context, history_owner, workspace_root |
| `/api/stop` | medium | session_lifecycle | auth, user_context, session_owner |
| `/api/stop_all` | high | session_lifecycle | auth, user_context, owned_sessions_only |
| `/api/ninterrupt` | medium | turn_control | auth, user_context, session_owner |
| `/api/nsend` | high | codex_turn_and_upload | auth, user_context, session_owner, busy_guard, image_validation |
| `/api/nslash` | high | codex_control | auth, user_context, session_owner, busy_guard, slash_allowlist |
| `/api/nterminal` | high | command_io | auth, user_context, session_owner, process_owner, terminal_action_allowlist, input_size_limit, resize_bounds |
| `/api/nmode` | low | ui_mode | auth, user_context, session_owner |
| `/api/napprove` | high | approval_gate | auth, user_context, session_owner, pending_request |
| `/api/nanswer` | high | answer_gate | auth, user_context, session_owner, pending_request |
| `/api/history_delete` | high | history_mutation | auth, user_context, history_owner |
| `/api/codex_history_action` | high | history_mutation | auth, user_context, history_owner, codex_backend_only, action_allowlist |

## Web Lifecycle POST Routes

| Route | Risk | Area | Required guards |
| --- | --- | --- | --- |
| `/api/restart_web` | high | web_lifecycle | browser_auth, origin_check |
| `/api/restart_manager` | high | manager_lifecycle | browser_auth, origin_check, internal_soft_exit |
| `/api/restart` | critical | full_lifecycle | browser_auth, origin_check, internal_exit |
| `/api/_stop` | critical | full_lifecycle | browser_auth, origin_check, internal_exit |

## Internal Manager POST Routes

| Route | Risk | Area | Required guards |
| --- | --- | --- | --- |
| `/api/_perm_gate` | critical | internal_approval_gate | internal_auth, optional_user_context, session_owner |
| `/api/_ask_gate` | critical | internal_answer_gate | internal_auth, optional_user_context, session_owner |
| `/api/_exit` | critical | internal_control | internal_auth, control_route_only |
| `/api/_soft_exit` | critical | internal_control | internal_auth, control_route_only |

## Validation

Run the route coverage check after adding or changing POST routes:

```powershell
python tools\check_state_changing_api_risks.py
```

Run it with `--json` when a CI-style machine-readable summary is useful:

```powershell
python tools\check_state_changing_api_risks.py --json
```

`tests/check_web_security_helpers.py` also exercises the web lifecycle control
routes through `WebHandler.do_POST`, proving rejected browser origins do not
reach auth or restart/stop side effects.
