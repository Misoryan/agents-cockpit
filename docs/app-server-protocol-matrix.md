# Codex App-Server Protocol Matrix

This file is generated from the installed Codex app-server JSON Schema
plus static Agents Cockpit coverage labels.

- Codex CLI: `codex-cli 0.142.4`

## Server Notifications

- Total: 68; degraded=8, generic_visible=29, supported=31

| Method | Status | Notes |
| --- | --- | --- |
| `account/login/completed` | `generic_visible` | Generic notice/error path only. |
| `account/rateLimits/updated` | `degraded` | Visible in UI, but not full CLI parity yet. |
| `account/updated` | `degraded` | Visible in UI, but not full CLI parity yet. |
| `app/list/updated` | `degraded` | Visible in UI, but not full CLI parity yet. |
| `command/exec/outputDelta` | `supported` | Routed to registered /exec-stream browser cards and command/exec smoke handlers. |
| `configWarning` | `supported` | Implemented in current adapter path. |
| `deprecationNotice` | `supported` | Implemented in current adapter path. |
| `error` | `supported` | Implemented in current adapter path. |
| `externalAgentConfig/import/completed` | `generic_visible` | Generic notice/error path only. |
| `externalAgentConfig/import/progress` | `generic_visible` | Generic notice/error path only. |
| `fs/changed` | `generic_visible` | Generic notice/error path only. |
| `fuzzyFileSearch/sessionCompleted` | `generic_visible` | Generic notice/error path only. |
| `fuzzyFileSearch/sessionUpdated` | `generic_visible` | Generic notice/error path only. |
| `guardianWarning` | `supported` | Implemented in current adapter path. |
| `hook/completed` | `generic_visible` | Generic notice/error path only. |
| `hook/started` | `generic_visible` | Generic notice/error path only. |
| `item/agentMessage/delta` | `supported` | Implemented in current adapter path. |
| `item/autoApprovalReview/completed` | `generic_visible` | Generic notice/error path only. |
| `item/autoApprovalReview/started` | `generic_visible` | Generic notice/error path only. |
| `item/commandExecution/outputDelta` | `supported` | Implemented in current adapter path. |
| `item/commandExecution/terminalInteraction` | `supported` | Implemented in current adapter path. |
| `item/completed` | `supported` | Implemented in current adapter path. |
| `item/fileChange/outputDelta` | `supported` | Implemented in current adapter path. |
| `item/fileChange/patchUpdated` | `supported` | Implemented in current adapter path. |
| `item/mcpToolCall/progress` | `supported` | Implemented in current adapter path. |
| `item/plan/delta` | `supported` | Implemented in current adapter path. |
| `item/reasoning/summaryPartAdded` | `supported` | Implemented in current adapter path. |
| `item/reasoning/summaryTextDelta` | `supported` | Implemented in current adapter path. |
| `item/reasoning/textDelta` | `supported` | Implemented in current adapter path. |
| `item/started` | `supported` | Implemented in current adapter path. |
| `mcpServer/oauthLogin/completed` | `degraded` | Shown as visible OAuth success/failure notice; Web does not own token flows. |
| `mcpServer/startupStatus/updated` | `degraded` | Shown as visible MCP startup/ready/failed notices; resource browser is manual. |
| `model/rerouted` | `supported` | Implemented in current adapter path. |
| `model/safetyBuffering/updated` | `degraded` | Visible in UI, but not full CLI parity yet. |
| `model/verification` | `generic_visible` | Generic notice/error path only. |
| `process/exited` | `generic_visible` | Generic notice/error path only. |
| `process/outputDelta` | `generic_visible` | Generic notice/error path only. |
| `remoteControl/status/changed` | `generic_visible` | Generic notice/error path only. |
| `serverRequest/resolved` | `generic_visible` | Generic notice/error path only. |
| `skills/changed` | `generic_visible` | Generic notice/error path only. |
| `thread/archived` | `generic_visible` | Generic notice/error path only. |
| `thread/closed` | `generic_visible` | Generic notice/error path only. |
| `thread/compacted` | `supported` | Implemented in current adapter path. |
| `thread/deleted` | `generic_visible` | Generic notice/error path only. |
| `thread/goal/cleared` | `supported` | Implemented in current adapter path. |
| `thread/goal/updated` | `supported` | Implemented in current adapter path. |
| `thread/name/updated` | `degraded` | Visible in UI, but not full CLI parity yet. |
| `thread/realtime/closed` | `generic_visible` | Generic notice/error path only. |
| `thread/realtime/error` | `generic_visible` | Generic notice/error path only. |
| `thread/realtime/itemAdded` | `generic_visible` | Generic notice/error path only. |
| `thread/realtime/outputAudio/delta` | `generic_visible` | Generic notice/error path only. |
| `thread/realtime/sdp` | `generic_visible` | Generic notice/error path only. |
| `thread/realtime/started` | `generic_visible` | Generic notice/error path only. |
| `thread/realtime/transcript/delta` | `generic_visible` | Generic notice/error path only. |
| `thread/realtime/transcript/done` | `generic_visible` | Generic notice/error path only. |
| `thread/settings/updated` | `supported` | Implemented in current adapter path. |
| `thread/started` | `supported` | Implemented in current adapter path. |
| `thread/status/changed` | `supported` | Implemented in current adapter path. |
| `thread/tokenUsage/updated` | `supported` | Implemented in current adapter path. |
| `thread/unarchived` | `supported` | Implemented in current adapter path. |
| `turn/completed` | `supported` | Implemented in current adapter path. |
| `turn/diff/updated` | `supported` | Implemented in current adapter path. |
| `turn/moderationMetadata` | `degraded` | Visible in UI, but not full CLI parity yet. |
| `turn/plan/updated` | `supported` | Implemented in current adapter path. |
| `turn/started` | `supported` | Implemented in current adapter path. |
| `warning` | `supported` | Implemented in current adapter path. |
| `windows/worldWritableWarning` | `generic_visible` | Generic notice/error path only. |
| `windowsSandbox/setupCompleted` | `generic_visible` | Generic notice/error path only. |

## Server Requests

- Total: 10; degraded=3, generic_visible=2, supported=5

| Method | Status | Notes |
| --- | --- | --- |
| `account/chatgptAuthTokens/refresh` | `degraded` | Visible in UI, but not full CLI parity yet. |
| `applyPatchApproval` | `generic_visible` | Generic notice/error path only. |
| `attestation/generate` | `degraded` | Visible in UI, but not full CLI parity yet. |
| `execCommandApproval` | `generic_visible` | Generic notice/error path only. |
| `item/commandExecution/requestApproval` | `supported` | Implemented in current adapter path. |
| `item/fileChange/requestApproval` | `supported` | Implemented in current adapter path. |
| `item/permissions/requestApproval` | `supported` | Implemented in current adapter path. |
| `item/tool/call` | `degraded` | Allowlisted MCP passthrough is implemented; unmapped tools fail visibly. |
| `item/tool/requestUserInput` | `supported` | Implemented in current adapter path. |
| `mcpServer/elicitation/request` | `supported` | Implemented in current adapter path. |

## Client Requests

- Total: 87; degraded=2, not_integrated=52, supported=33

| Method | Status | Notes |
| --- | --- | --- |
| `account/login/cancel` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `account/login/start` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `account/logout` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `account/rateLimitResetCredit/consume` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `account/rateLimits/read` | `degraded` | Read-only /account-status attempts this and shows auth-required errors visibly; Web login/token refresh are not integrated. |
| `account/read` | `supported` | Read-only account status is shown in the launch modal and /account-status; login/logout are not integrated. |
| `account/sendAddCreditsNudgeEmail` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `account/usage/read` | `degraded` | Read-only /account-status attempts this and shows auth-required errors visibly; Web login/token refresh are not integrated. |
| `account/workspaceMessages/read` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `app/list` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `command/exec` | `supported` | Buffered /exec and streamed /exec-stream slash workflows are implemented with replayable browser cards. |
| `command/exec/resize` | `supported` | Implemented in current adapter path. |
| `command/exec/terminate` | `supported` | Implemented in current adapter path. |
| `command/exec/write` | `supported` | Implemented in current adapter path. |
| `config/batchWrite` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `config/mcpServer/reload` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `config/read` | `supported` | Implemented in current adapter path. |
| `config/value/write` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `configRequirements/read` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `experimentalFeature/enablement/set` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `experimentalFeature/list` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `externalAgentConfig/detect` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `externalAgentConfig/import` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `externalAgentConfig/import/readHistories` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `feedback/upload` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `fs/copy` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `fs/createDirectory` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `fs/getMetadata` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `fs/readDirectory` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `fs/readFile` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `fs/remove` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `fs/unwatch` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `fs/watch` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `fs/writeFile` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `fuzzyFileSearch` | `supported` | Implemented in current adapter path. |
| `hooks/list` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `initialize` | `supported` | Implemented in current adapter path. |
| `marketplace/add` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `marketplace/remove` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `marketplace/upgrade` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `mcpServer/oauth/login` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `mcpServer/resource/read` | `supported` | Implemented in current adapter path. |
| `mcpServer/tool/call` | `supported` | Implemented in current adapter path. |
| `mcpServerStatus/list` | `supported` | Exposed through /mcp-status and /mcp-resources for manual MCP inventory browsing. |
| `model/list` | `supported` | Implemented in current adapter path. |
| `modelProvider/capabilities/read` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `permissionProfile/list` | `supported` | Implemented in current adapter path. |
| `plugin/install` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `plugin/installed` | `supported` | Exposed read-only through /plugins for installed plugin inventory. |
| `plugin/list` | `supported` | Exposed read-only through /plugins available for marketplace/plugin inventory. |
| `plugin/read` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `plugin/share/checkout` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `plugin/share/delete` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `plugin/share/list` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `plugin/share/save` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `plugin/share/updateTargets` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `plugin/skill/read` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `plugin/uninstall` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `review/start` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `skills/config/write` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `skills/extraRoots/set` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `skills/list` | `supported` | Exposed read-only through /skills for workspace skill inventory. |
| `thread/approveGuardianDeniedAction` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `thread/archive` | `supported` | Implemented in current adapter path. |
| `thread/compact/start` | `supported` | Implemented in current adapter path. |
| `thread/delete` | `supported` | Implemented in current adapter path. |
| `thread/fork` | `supported` | Implemented in current adapter path. |
| `thread/goal/clear` | `supported` | Implemented in current adapter path. |
| `thread/goal/get` | `supported` | Implemented in current adapter path. |
| `thread/goal/set` | `supported` | Implemented in current adapter path. |
| `thread/inject_items` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `thread/list` | `supported` | Implemented in current adapter path. |
| `thread/loaded/list` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `thread/metadata/update` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `thread/name/set` | `supported` | Implemented in current adapter path. |
| `thread/read` | `supported` | Implemented in current adapter path. |
| `thread/resume` | `supported` | Implemented in current adapter path. |
| `thread/rollback` | `supported` | Implemented in current adapter path. |
| `thread/shellCommand` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `thread/start` | `supported` | Implemented in current adapter path. |
| `thread/unarchive` | `supported` | Implemented in current adapter path. |
| `thread/unsubscribe` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `turn/interrupt` | `supported` | Implemented in current adapter path. |
| `turn/start` | `supported` | Implemented in current adapter path. |
| `turn/steer` | `supported` | Implemented in current adapter path. |
| `windowsSandbox/readiness` | `not_integrated` | Not integrated in Agents Cockpit yet. |
| `windowsSandbox/setupStart` | `not_integrated` | Not integrated in Agents Cockpit yet. |
