# codex-web 中 Codex 会话 vs Codex CLI 差距分析与适配计划

生成日期：2026-07-16；最新校准：2026-07-17
项目：`E:\tools\codex-web`
当前代码：`main` (see latest checkpoint at end of this file)
对照对象：本机 `codex-cli 0.142.4`、`codex app-server --stdio`、本机生成的 app-server JSON Schema
当前快照：更完整、可执行的当前版差距分析见 `docs/codex-cli-gap-adaptation-plan.md`；本文件保留早期分析和连续 checkpoint。

## 0. 结论先行

当前项目的 Codex 路线是正确的：它没有把终端 TUI 生硬嵌进浏览器，而是通过 `codex app-server --stdio` 接入 Codex 后端，再把 app-server 的 thread / turn / item / request 事件转换为浏览器可渲染的结构化会话。这条路线天然适合远程、手机、多客户端旁观、通知、登录隔离和后台会话恢复。

但它还不是完整的 Codex CLI 替代品。当前状态可以概括为：

- Remote usable Codex agent session: about **78-82% usable**; core chat, streaming text, reasoning, tool cards, approvals, Plan, replay, history recovery, and image input have working paths.
- Full Codex CLI TUI replacement: about **60-65%** in the early baseline; current checkpoints have moved plugin/skills to read-only inventory, while remaining gaps are mainly profile/config depth, full command palette, richer lifecycle UI, account refresh, plugin/skills write flows, and deeper terminal/MCP validation.
- 代码结构经历了一轮有效拆分：`manager.py`、`common.py`、`native.py`、`codex_native.py` 都已经从巨型单文件向 helper 模块迁移；但 `CodexSession`、`common.py` facade、`web.py`、`index.html` 内联样式和前端全局状态仍是主要复杂度热点。
- 下一阶段不应优先做普通 UI 美化，而应按“协议覆盖 -> CLI 高价值入口 -> Codex-native 工具渲染 -> 安全/结构硬化”推进。

## 1. 当前 Codex 会话链路

```text
Browser / Android WebView
  -> web.py
     - 登录、静态资源、/api/* 代理、/t/<sid>/ws 代理、web/manager 重启控制
  -> manager.py
     - 会话生命周期、HTTP/WebSocket API、session registry、用户隔离
  -> manager_sessions.py / manager_user_api.py / manager_internal_api.py
     - launch/resume/send/approve/answer/interrupt/history/内部 gate 控制
  -> codex_native.py
     - CodexSession 会话对象
     - 启动或复用 per-user CodexAppServerClient
     - 把 Web API 调用映射到 app-server request
     - 把 app-server notification/request 映射到 Web 事件
  -> codex_client.py
     - `codex app-server --stdio` 子进程和 JSON-RPC 通信
     - thread/turn/item 路由、未路由事件短暂缓冲、server request 响应
  -> assets/*.js + index.html
     - 结构化消息、工具卡、审批卡、ask/form、Plan 卡、replay、状态栏、tab/sidebar
```

当前已完成的重要基础能力：

- `CodexSession` 使用 `thread/start`、`thread/resume`、`turn/start`、`turn/interrupt`、`thread/settings/update` 驱动会话。
- Codex 历史已接入 `thread/list`、`thread/read(includeTurns=true)`、`thread/resume`、`thread/delete`。
- Server request 已覆盖命令/文件/权限审批、`item/tool/requestUserInput`、`mcpServer/elicitation/request` 的普通问答和 form/openai form 降级表单。
- `item/tool/call` 不再只有拒绝路径：已支持 `[codex_dynamic_tools]` 显式 allowlist，把安全确认过的动态工具自动透传到 `mcpServer/tool/call`；未映射工具、`attestation/generate`、`account/chatgptAuthTokens/refresh` 仍保持可见失败，不假成功。
- 前端已支持 pending approval / ask / form 的重连重放、`seq/event_id` 去重、`live_codex=1` 历史加载、后端 busy guard、多用户隔离和内部 gate auth。
- 2026-07-16 追加了增量 replay 的流式片段裁剪：当 WebSocket 1006/断线后按 `after=<lastSeq>` 恢复时，已渲染的流式文本不会因为服务端合并 timeline 而整段重复追加；前端重连也不再在已有内容时清空 thinking/turn 状态，减少闪烁。
- 2026-07-16 追加了 `state_snapshot` 收敛逻辑：如果断线期间错过 result/done 事件，重连后服务端快照显示不再 running 时，前端会清掉残留 thinking/turn UI，而不是靠全量重绘修复。
- 2026-07-16 追加了 WebSocket 每 socket 写锁：服务端 keepalive ping 线程与广播线程不会同时向同一个 socket 写入 frame，降低浏览器收到交错 frame 后 1006 断连的概率。
- 2026-07-16 追加了前端 replay 去重收敛：live 与 replay 使用同一稳定 key，poll/reconnect replay 即使拿到重复事件也会跳过已渲染内容，避免重复消息或重复工具卡。
- 2026-07-16 追加了 `tools/app_server_protocol_matrix.py` 和 `docs/app-server-protocol-matrix.md`，将本机 app-server schema 的 method 覆盖状态固化为可重生成的 drift 检查表。
- 旧的自定义 args UI 已移除，避免“用户以为传给 Codex 了但后端没有消费”的误导。
- 2026-07-16 已完成 Codex 启动配置第一刀：新建会话可选择/输入 model，设置 web search、sandbox、approval policy，并通过 `model/list`、`permissionProfile/list`、`config/read` 读取真实 app-server 能力；配置明确进入 `thread/start` / `turn/start`，不再是假 UI。
- 2026-07-16 已完成 slash 命令第一刀：输入框已有轻量 palette；`/model <id>` 可切换后续 Codex turn 使用的模型并同步多端顶栏，`/compact` 调用 `thread/compact/start` 触发 app-server 上下文压缩，`/approval`、`/sandbox` 可设置后续 turn，`/search` 只允许在线程启动前设置，`/rename`、`/archive`、`/unarchive`、`/fork`、`/rollback` 已接入 app-server 线程生命周期，`/goal get/set/status/clear` 已映射到 app-server thread goal，`/steer` 可在运行中对当前 turn 追加引导；这些命令都由后端确认和广播结果，避免单端假状态。
- 2026-07-16 已完成 `fuzzyFileSearch` 第一刀：Web 输入框支持 `@` 文件/目录提及菜单，后端通过 app-server `fuzzyFileSearch` 搜索当前 cwd，并把已选路径作为 `mention` user input 发送给 Codex，而不是只把 `@path` 当普通文本。
- 2026-07-16 已完成 `/fork` 结果入口第一刀：fork 成功后会广播 `thread_forked` 事件，所有连接客户端都能看到“打开 fork”按钮，并通过现有 `/api/resume` 路径打开新线程。
- 2026-07-16 已完成终端交互第一刀：`item/commandExecution/terminalInteraction` 会渲染 Web stdin 卡片，后端 `/api/nterminal` 映射到 `command/exec/write`、`command/exec/resize`、`command/exec/terminate`，不再只能提示回 CLI。
- 2026-07-16 已完成 MCP 手动调用第一刀：slash palette 增加 `/mcp-resource <server> <uri>` 与 `/mcp-tool <server> <tool> <json>`，后端映射到 `mcpServer/resource/read` 和 `mcpServer/tool/call`，结果以可 replay 的 tool_use/tool_result 形式同步到多端。
- 2026-07-16 已完成图片输入第一刀：Codex 输入框支持粘贴/选择图片，后端保存为 per-session `localImage` 并传给 `turn/start`，用户消息以图片卡片形式参与 replay/多端同步。
- 2026-07-16 已将运行中 Codex 会话的 Fork/Rollback/Compact/Archive 快捷入口露出到 sidebar，会调用同一条后端 `/api/nslash` 路径并刷新多端 session/history 状态。
- 2026-07-16 已将 Codex 历史项的 Fork/Archive/Rename/Goal 快捷入口露出到 sidebar，后端通过 `/api/codex_history_action` 直接调用 app-server `thread/fork` / `thread/archive` / `thread/name/set` / `thread/goal/set`，无需先恢复会话再输入 slash。

## 2. Codex CLI 能力面 vs 当前 Web 会话

本机 `codex --help` 暴露的主要交互能力包括：

- 全局启动参数：`--model`、`--profile`、`--sandbox`、`--ask-for-approval`、`--search`、`--image`、`--cd`、`--add-dir`、`--config`、`--enable/--disable`、`--oss`、`--local-provider`。
- 交互式线程生命周期：`resume`、`archive`、`delete`、`unarchive`、`fork`。
- 非会话/辅助能力：`exec`、`review`、`apply`、`cloud`、`doctor`、`mcp`、`plugin`、`features`、`sandbox`。
- TUI 输入体验：slash 命令、`@` 文件/目录提及、图片输入、模型/审批/sandbox 快捷切换、compact/rollback/steer 等。

本机 app-server schema 进一步显示：

- Server notifications：**68** 类，包括 thread/turn/item、account、mcp、model、remote-control、realtime、windows sandbox、skills、fs/watch 等。
- Server requests：**10** 类，包括审批、动态工具调用、用户输入、MCP elicitation、attestation、token refresh。
- Client requests：**87** 类，包括 account、config、model/list、permissionProfile/list、thread/archive/fork/rollback/compact/goal/name、fuzzyFileSearch、mcpServer/tool/resource、plugin/skills、fs、command/exec、windowsSandbox 等。

当前 Web 侧只覆盖其中的高频核心子集。能力差距如下：

| 能力维度 | Codex CLI / app-server 能力 | 当前 Web 状态 | 差距判断 |
| --- | --- | --- | --- |
| 后端同源 | CLI 与 app-server 共用 Codex 后端 | 使用 `codex app-server --stdio` | 路线正确 |
| 基础对话 | thread/start、turn/start、流式输出 | 已打通 | 接近 |
| Reasoning / thinking | reasoning delta、summary | 已转为 thinking 卡 | 接近，但结构化摘要不足 |
| 工具执行展示 | command/file/mcp/web/search 等 item | 高价值 item 已有基础卡片 | 可用但不够 Codex-native |
| 审批 | command/file/permissions approval | Web 卡片 + always for session | 优于 CLI 的移动端体验 |
| 用户输入 | requestUserInput / elicitation | ask/form 卡片 | 基础可用 |
| Plan | collaborationMode + plan item/delta | 已支持 Plan 卡与退出 | 基础可用 |
| 历史 | list/read/resume/delete/archive/unarchive/fork/rollback/goal/name/compact | list/read/resume/delete + slash archive/unarchive/fork/rollback/goal/name/compact + 运行中会话 sidebar 快捷动作 + 历史项 Fork/Archive/Rename/Goal | archived view / unarchive 入口仍需补齐 |
| 启动配置 | model/profile/sandbox/approval/search/image/add-dir/config | cwd/backend/yolo/plan/task + model/search/sandbox/approval 第一刀；图片作为 turn input 已接 | 仍有 profile/add-dir/config 长尾缺口 |
| 输入增强 | slash、@、图片、compact、rollback、goal、steer | 轻量 slash palette + `@` 文件提及 + 图片粘贴/选择 + plan/task 按钮 | 完整 palette 仍缺 |
| 动态工具 | `item/tool/call` / MCP passthrough | 手动 MCP tool/resource 已接；自动 dynamic tool 支持 `[codex_dynamic_tools]` allowlist 透传 | 仍需真实 MCP server 验证和更完整结果卡 |
| 终端交互 | command exec stdin/resize/terminate/write | terminalInteraction stdin/terminate/resize 第一刀 | 仍需真实复杂命令验证 |
| Codex 账号 | login/token refresh/rate limits/usage | 依赖外部 CLI 登录；refresh unsupported | 关键差距 |
| Plugin/skills | plugin/list/read/install、skills/list/read | `/skills`、`/plugins [installed\|available]` 已只读接入；read/install/write 未接 | 只读可见，写入仍后续 |
| Realtime/audio | realtime notifications | 未接入 | 暂不必要 |
| 远程/多端 | CLI 单终端 | Web 多端、通知、Android WebView | Web 优势 |

## 3. 当前代码中的主要问题

### P0 / 需要尽快修的小问题

1. `codex_session_events.py` 中 Plan 外部通知标题/正文出现实际 mojibake 字符串。（已修复）
   - 位置：`on_item_completed()` 处理 `agentMessage`、`plan`，以及 `flush_pending_plan_items()`。
   - 修复：外部通知统一为 `Codex Plan needs review - <dir>` / `tap to review the plan`，并由 `tests/check_codex_session_events_helpers.py` 覆盖。

2. `item/tool/call` 已有 allowlist passthrough 第一刀。
   - 当前 `[codex_dynamic_tools]` 可配置 `namespace.tool`、`namespace.*` 或无 namespace 的 `tool` 到 `mcp:<server>/<tool>`，命中后自动调用 `mcpServer/tool/call` 并把 MCP 结果转换成 `DynamicToolCallResponse`。
   - 未配置映射的动态工具仍结构化拒绝并提示配置方式，避免把未知 client tool 假装执行成功。下一步需要用真实 MCP server 做端到端验证，并补更细的结果卡。

3. `attestation/generate` 与 `account/chatgptAuthTokens/refresh` 仍是 unsupported。
   - 影响：当 Codex 账号凭据过期或某些认证/设备证明流程触发时，Web 会话无法自愈，只能提示回 CLI 处理。
   - 短期应把提示做成清晰的恢复步骤；长期再评估是否接入 app-server account/login 系列。

4. 前端运行依赖外部 CDN：`marked`、`DOMPurify`、`highlight.js`。（已修复）
   - 对局域网/隧道/离线场景不稳，也增加供应链风险。
   - 修复：`marked`、`DOMPurify`、`highlight.js` 与 highlight theme 已 vendor 到 `assets/vendor/`，`index.html` 不再引用 jsDelivr。

### P1 / CLI 体验差距导致的产品问题

5. 新建会话配置仍未完全追平 CLI。
   - 已有第一刀：model、web search、sandbox、approval policy 可从 Web 进入 Codex app-server；yolo 仍作为快捷开关覆盖为 `never + danger-full-access`。
   - 仍缺 profile、add-dir、image、config override、reasoning/service tier 等 CLI 高频项。

6. 输入框仍接近普通 textarea。
   - 已支持轻量 slash palette，覆盖 `/model`、`/compact`、`/approval`、`/sandbox`、`/search`、`/rename`、`/archive`、`/unarchive`、`/fork`、`/rollback`、`/goal`、`/steer`，并支持键盘上下选择；`@` 文件/目录提及已接入 app-server `fuzzyFileSearch` 和 mention input。仍缺图片粘贴/上传，以及更完整的 command palette 体验。
   - 这会让熟悉 CLI 的用户在 Web 中明显降级。

7. Codex thread 生命周期入口仍需继续产品化。
   - app-server 已有 `thread/archive`、`thread/unarchive`、`thread/fork`、`thread/rollback`、`thread/compact/start`、`thread/name/set`、`thread/goal/*`、`turn/steer`。
   - 当前 slash 路径已覆盖 archive/unarchive/fork/rollback/compact/name/goal/steer，sidebar 对运行中 Codex 会话已露出 Fork/Rollback/Compact/Archive/Rename/Goal，历史项已露出 Fork/Archive/Rename/Goal；archived view / unarchive 入口还需补齐。

8. 终端交互已有 Web stdin 第一刀。
   - 当前 `item/commandExecution/terminalInteraction` 会渲染输入卡片，支持发送 stdin、关闭 stdin、终止进程，并提供 resize 后端入口。
   - 仍需要用真实交互式命令验证长时间 PTY、重复 stdin 和移动端输入体验。

9. Codex-native 工具 UI 还不够细。
   - `commandExecution`、`fileChange`、`mcpToolCall`、`dynamicToolCall`、`webSearch`、`imageGeneration`、`imageView`、`sleep`、`contextCompaction` 都被压成通用 tool/result 形状。
   - `turn/diff/updated` 目前挂到固定 `turn-diff` 结果，未必能归属到正确的工具卡。

### P2 / 架构和维护性问题

10. `codex_native.py` 仍然过重。
    - 现有拆分已经把很多 helper 挪走，但 `CodexSession` 仍同时负责状态、turn lifecycle、持久化、通知、pending request、WebSocket replay、push notify 和 app-server client 协调。
    - 后续新增 CLI parity 时，如果继续塞进这个类，会再次膨胀。

11. `codex_client.py` 的路由 fallback 仍是经验性策略。
    - 对缺少 threadId/turnId/itemId 的通知，会用“single busy session”兜底；单用户单会话很好，多会话并发时仍可能无法路由或需要等待后续事件。
    - 应增加 trace fixture 和 schema-based routing tests，明确哪些 notification 必须 buffer、哪些允许全局 notice。

12. `common.py` 仍有较强 import side effects。
    - 它在 import 时读取 config、解析 auth、发现二进制、可能 `sys.exit`。
    - 当前通过 `--stop/--help` 特判绕开了一些问题，但长期看配置加载、运行时服务、测试 helper 应继续解耦。

13. `web.py` 混合了登录、代理、manager watchdog、重启控制、HTTPS 启动。
    - 现在 448 行还能接受，但这是后续安全/部署变更的风险点。
    - 最好拆成 `web_auth.py`、`web_proxy.py`、`web_lifecycle.py` 或至少把纯函数下沉。

14. `index.html` 仍包含大量会话样式。
    - 虽然 JS/CSS 已拆到 `assets/`，但 `#nativestage` 的大段 `<style>` 仍在 HTML 中，`index.html` 还不是纯 markup。
    - 前端 JS 也依赖大量全局变量，没有模块边界/类型约束。

15. 测试体系是脚本式 check，缺少 app-server 协议契约测试。
    - 当前 helper tests 很有价值，但没有固定记录“本版本 app-server schema 中哪些 method 是 supported/degraded/unsupported”。
    - 每次 Codex CLI 升级后，协议 drift 只能靠人工发现。
    - 已新增 `tools/app_server_protocol_matrix.py` 与 `docs/app-server-protocol-matrix.md` 作为第一版协议矩阵；后续还需要把矩阵里的 `planned_high_value` 项逐步转成实现和更强的契约测试。
    - 本次验证中 `tests/check_common_process_helpers.py` 曾在 `wait_port(timeout=0.2)` 上偶发失败，单测重跑和全量重跑通过；这类 Windows 端口等待测试应放宽超时或改成更稳定的同步方式。

### P3 / 安全与发布问题

16. 默认配置偏局域网便利，不适合直接公网暴露。
    - `[server] host = 0.0.0.0`、`cookie_secure = 0`、`allow_unconfigured_paths = 1` 都是兼容/便利默认。
    - README 已提示要强密码和 HTTPS/VPN，但发布版应提供 hardened profile。

17. 缺少 CSRF/Origin 防护。
    - 登录 cookie + JSON POST 在内网工具里通常可接受，但如果经隧道暴露，仍建议为状态变更接口加 Origin/CSRF token。

18. 多用户隔离策略有兼容折中。
    - 第一用户可使用默认 Codex/Claude homes，其他用户使用 per-user homes。这便于无痛迁移，但也意味着主账号和本机 CLI 仍共享状态。
    - 对多人场景，应提供强隔离模式文档与默认建议。

## 4. 适配原则

1. **以 app-server 为事实源**：不要再造 CLI 文本解析；优先用 schema、thread/read、thread/list、client request。
2. **不假成功**：暂不支持的 request 必须可见、结构化失败，不能返回 `{}` 误导 app-server。
3. **小步行为保持**：每个适配点都配 py_compile、node --check、目标 tests 和必要的 stub/live smoke。
4. **先高价值入口，再覆盖长尾**：启动参数、历史动作、slash/@/image、动态工具，比 realtime/audio/plugin marketplace 更优先。
5. **安全默认要可切换**：继续保留本机/局域网便利模式，但增加 hardened profile 和文档。

## 5. 分阶段适配计划

### 阶段 A：当前问题收敛与协议基线（优先）

目标：先把当前明显 bug 和 drift 风险压住。

- 修复 `codex_session_events.py` Plan 通知乱码，增加回归检查。（已完成）
- 补强 WebSocket 断线后的增量 replay：避免已渲染流式文本被合并 timeline 重放造成重复和闪烁。（已完成）
- 把 CDN 依赖 vendor 到本地，前端默认不依赖外网。（已完成）
- 增加 `docs/app-server-protocol-matrix.md` 或测试 fixture，记录本机 schema 的 68/10/87 method 覆盖状态：`supported`、`degraded`、`visible unsupported`、`not applicable`。（已完成第一版）
- 为未映射 `item/tool/call`、attestation、token refresh 的降级路径补充更明确的 UI 文案和恢复步骤；`item/tool/call` allowlist passthrough 第一刀已完成。
- 验证：`python -m py_compile ...`、`node --check assets/*.js`、`tests/check_*.py`、`git diff --check`。

### 阶段 B：启动配置与会话生命周期追平 CLI 高频项

目标：让 Web 新建/历史管理不再明显弱于 CLI。

- 新建会话 modal 增加结构化 Codex 配置：model、profile、sandbox、approval policy、web search、additional writable dirs。（已完成 model/search/sandbox/approval 第一刀）
- 后端将配置明确写入 `thread/start` / `turn/start` / `thread/settings/update` 或 config override；不能生效的字段不展示。（第一刀已进入 `thread/start` / `turn/start`）
- 接入只读能力发现：`model/list`、`permissionProfile/list`、`config/read`，给 UI 选项提供真实数据。（已完成）
- slash 路径已增加 archive/unarchive、fork、rename、compact、rollback、goal 的第一批动作；sidebar 已露出运行中 Codex 会话的 Fork/Rollback/Compact/Archive/Rename/Goal 以及历史项 Fork/Archive/Rename/Goal，下一步补 archived view / unarchive 入口。
- 增加 `turn/steer` 或等价操作，用于“不中断会话地追加引导”。
- 验收：用真实 Codex session 验证不同 model/profile/sandbox/search 真的生效；历史动作与 CLI 可互认。

### 阶段 C：输入体验追平 CLI

目标：减少 Web textarea 与 TUI 的落差。

- Slash command palette：先做 `/compact`、`/model`、`/approval`、`/sandbox`、`/search`、`/fork`、`/rollback`、`/archive`、`/rename`。（已完成轻量 palette 和上述首批命令，并额外接入 `/steer`）
- `@` 文件/目录提及：已优先使用 `fuzzyFileSearch` 并遵守当前 cwd / per-user workspace roots；后续可补本地降级搜索和更细的 mention 展示。
- 图片输入：已支持粘贴/选择图片，后端保存到 per-session upload 目录并以 `localImage` 输入传给 app-server；后续补更完整历史缩略图和清理策略。
- `#`/goal 类能力：slash 已映射到 `thread/goal/set/get/clear`；后续可加更自然的 `#`/goal UI，但不要混同本地 memory。
- 验收：移动端和桌面输入都可用，快捷命令有可见执行反馈，错误不吞。

### 阶段 D：工具/终端/动态 MCP 深水区

目标：处理 CLI agentic 工作流中最容易卡住的交互。

- `item/tool/call` allowlist passthrough：明确 `namespace/tool -> mcpServer/tool/call` 或本地 handler 的映射。（MCP 映射第一刀已完成，仍需真实 server 验证和更多 handler）
- MCP resource/read、tool call、elicitation schema 做更完整的 renderer 和结果卡。（手动 resource/tool slash 第一刀已完成）
- `commandExecution/terminalInteraction` 接入 Web stdin/terminate/resize；无法接入的命令保持可见阻断，不假装完成。
- `fileChange` / `turn/diff/updated` 做行级 diff、文件组、复制 patch、打开文件路径。
- 为 imageGeneration/imageView/sleep/contextCompaction 做专属卡片，而不是裸 JSON。
- 验收：复杂任务中动态工具、长命令输出、需要输入的命令、diff review 都不会迫使用户回 CLI，除非明确标注为 unsupported。

### 阶段 E：结构硬化与发布模式

目标：在功能继续增加前降低维护风险。

- 将 `CodexSession` 拆为更清晰的组件：`CodexSessionState`、`CodexTurnRunner`、`CodexNotificationAdapter`、`CodexRequestHandler`、`CodexReplayStore`。
- 将 `web.py` 拆出 auth/proxy/lifecycle；把 `index.html` 中的 stage style 移到 `assets/app.css` 或更细 CSS 文件。
- 把前端全局状态收束成少数 namespace，至少增加 DOM fixture tests；中期可考虑 TypeScript/ES modules。
- 增加 hardened config 示例：HTTPS、secure cookie、workspace path restriction、禁用默认 homes、强密码 hash。
- 增加 Origin/CSRF token 检查，避免隧道暴露时被跨站 POST。
- 验收：默认开发体验不破坏；hardened profile 能在局域网/隧道下明确启动并通过登录/launch/replay/approve smoke。

### 阶段 F：低优先级高级能力

这些能力可以排在核心 parity 后：

- Web 内 Codex account login / logout / token refresh。
- plugin / skills 浏览、安装、读取。
- Codex Cloud task 浏览与 apply。
- remote-control websocket app-server 模式。
- realtime/audio 相关通知。
- windows sandbox readiness/setup UI。

## 6. 推荐推进顺序

1. **先做阶段 A**：修乱码、vendor 前端依赖、建立协议覆盖矩阵。这一步风险最低，能立刻降低误判。
2. **再做阶段 B 的启动配置**：model/profile/sandbox/search 是 CLI 用户最常感知的差距。
3. **随后做历史生命周期**：archive/fork/rollback/compact/name 会显著改善长期会话管理。
4. **再做 slash 与 @**：这是输入体验的最大提升，但要依赖前面配置/文件边界清晰。
5. **最后进入动态工具和终端交互**：这部分价值高但风险也最高，需要 schema fixture 和真实任务验证。

## 7. 当前进度估算

| 方向 | 当前进度 | 说明 |
| --- | ---: | --- |
| 结构化 Codex 基础会话 | 80% | 核心对话、replay、审批、history 已可用 |
| Codex CLI 高频交互追平 | 80% | Plan/approval、启动配置第一刀、轻量 slash palette、`@` 文件提及、图片粘贴/选择、terminal stdin、MCP 手动调用、dynamic tool allowlist passthrough、sidebar history actions、goal 和更多 history/steer actions 已可用，完整 palette 缺口仍大 |
| app-server 协议覆盖 | 60% | 核心 method + item/tool/call allowlist passthrough + model/list/permissionProfile/list/config/read/fuzzyFileSearch/command/exec/write/resize/terminate/mcpServer/tool/call/mcpServer/resource/read/thread/compact/start/thread/archive/thread/unarchive/thread/fork/thread/name/set/thread/rollback/thread/goal/*/turn/steer 有，长尾 client requests 和部分 server requests 未接 |
| 前端结构拆分 | 65% | JS/CSS 已拆，但 HTML 内仍有大段 stage CSS，全局变量仍多 |
| 后端结构拆分 | 70% | manager/common/native/codex 已拆，但 `CodexSession` 和 `common.py` 仍重 |
| 安全发布硬化 | 50% | 有 auth/multi-user，但默认仍偏本机/局域网便利模式 |

## 8. 最小下一步任务清单

建议从这 6 个小 PR/commit 开始：

1. 在 README/config 中补充 Codex 登录/token refresh 降级说明和 hardened profile 建议。
2. 继续实测 1006 断线场景：如果网络层无法完全避免断联，至少保证 `after=<lastSeq>` 增量恢复、轮询兜底和 pending 卡重放不闪烁。
3. 将 `index.html` 中的大段 native stage CSS 继续下沉到 `assets/app.css`。
4. 用真实 MCP server 验证 `item/tool/call` allowlist passthrough，并补充更完整的 MCP/dynamic tool 结果卡。
5. 继续扩展输入体验：补 archived view / unarchive 入口，并完善图片预览/历史缩略图体验。
6. 补齐 profile、add-dir 和更细的 model/service tier/reasoning 配置。

## 9. 本轮产物与验证状态

本轮分析已经落到可维护的项目文件中：

- `codex-web-vs-cli-adaptation-report.md`：完整差距分析、代码问题清单和分阶段适配计划。
- `docs/app-server-protocol-matrix.md`：由本机 `codex-cli 0.142.4` 的 app-server JSON Schema 生成的协议覆盖矩阵。
- `tools/app_server_protocol_matrix.py`：协议矩阵生成脚本，Codex CLI 升级后可重跑以发现 drift。
- `tools/codex_ws_smoke.py`：非破坏性 WebSocket 重连探针，用于验证 `after=<lastSeq>` 不会重放已渲染事件。
- `REFACTOR_PROGRESS.md`：当前结构、已完成拆分、验证命令和后续拆分方向。
- `codex_config.py`：Codex 启动配置规范化、sandbox 映射和 live option 读取 helper。

当前已通过的验证：

```powershell
python -m py_compile app.py web.py common.py manager.py native.py codex_native.py codex_config.py gate_mcp.py codex_client.py codex_events.py codex_forms.py codex_history.py codex_replay.py codex_requests.py codex_routing.py codex_session_events.py codex_text.py codex_thread_history.py common_auth.py common_binaries.py common_browse.py common_ccswitch.py common_history.py common_http.py common_notify.py common_process.py common_registry.py common_users.py common_ws.py manager_internal_api.py manager_sessions.py manager_user_api.py native_cli.py native_config.py native_gate.py native_replay.py tools\app_server_protocol_matrix.py tools\codex_ws_smoke.py
Get-ChildItem assets -Recurse -Filter *.js | Sort-Object FullName | ForEach-Object { node --check $_.FullName }
Get-ChildItem tests\check_*.py | Sort-Object Name | ForEach-Object { python $_.FullName }
python tools\app_server_protocol_matrix.py --out docs\app-server-protocol-matrix.md
python tools\codex_ws_smoke.py --seconds 2
git diff --check
```

`git diff --check` 只有 Windows 换行提示，没有 whitespace error。`tools/codex_ws_smoke.py` 已对当前运行中的 Codex 历史恢复会话完成一次非破坏性重连探针：首次连接收到 `replay_batch` + `state_snapshot`，历史 replay 被规范化到 `last_seq=200`，按 `after=200` 重连后只收到 `state_snapshot`，`after_replay_events=0`。尚未完成真实浏览器/手机端可视化长连接 smoke；1006 断线问题目前主要通过增量 replay、pending 卡重放和重连不清空 DOM 来降低可见闪烁，仍建议在下一轮做一次浏览器双端场景验证。


## 10. 2026-07-17 progress checkpoint

- Added an Active/Archived sidebar filter for Codex thread history. The archived view requests `/api/history?live_codex=1&archived=1`, which flows to app-server `thread/list` with `archived=true` instead of relying on stale local cache.
- Added a visible `Unarchive` action for archived Codex history rows through `/api/codex_history_action` -> `thread/unarchive`, completing the first UI entry point for archived thread lifecycle parity.
- Kept the active view non-disruptive: running sessions are only attached to the normal history view, so switching to archived history does not mix live sessions into archived results or force active conversation DOM reloads.


## 11. 2026-07-17 launch config parity checkpoint

- Extended Codex launch config beyond model/search/sandbox/approval: the modal now captures reasoning effort, reasoning summary, service tier, and extra writable directories.
- Backend normalization in `codex_config.py` keeps these values schema-shaped: `serviceTier`, `effort`, `summary`, and workspace-write `writableRoots` are sent on `turn/start`, while `thread/start` receives matching config overrides such as `model_reasoning_effort`, `model_reasoning_summary`, `service_tier`, and `sandbox_workspace_write.writable_roots`.
- Extra writable roots are normalized relative to the launch cwd and checked against the logged-in user's allowed workspace roots before launch or slash updates, preserving multi-user path boundaries.
- Slash parity also gained `/reasoning`, `/summary`, `/service-tier`, and `/add-dir`, so subsequent Codex turns can be tuned without restarting the web session.
- Remaining launch-config gap: CLI `--profile` still has no direct, safe app-server thread/start field in the current schema, so it remains documented as a gap rather than shown as a fake UI option.


## 12. 2026-07-17 multi-client replay smoke checkpoint

- Extended `tools/codex_ws_smoke.py` with `--clients 2` so the live validation can open two simultaneous WebSocket clients for the same Codex session.
- Added `--launch-temp` so the same smoke can create and stop a temporary idle Codex session when no running Codex session is available, keeping the multi-client reconnect check repeatable after restarts.
- The two-client probe verifies both clients receive a `state_snapshot`, agree on the latest replay `seq`, and can reconnect with their own `after=<lastSeq>` cursor without receiving duplicate replay batches.
- The probe now also exercises a safe live `mode_state` broadcast on temporary sessions, proving two connected clients see the same live event before reconnect recovery.
- This does not replace manual browser/mobile visual QA, but it turns the core multi-access invariant into a repeatable protocol-level smoke test that can be run before each checkpoint.


## 13. 2026-07-17 account recovery and hardened profile checkpoint

- Improved the known unsupported Codex account/security requests: `account/chatgptAuthTokens/refresh` and `attestation/generate` now produce explicit recovery notices with CLI steps instead of showing only a generic unsupported error.
- These notices intentionally pass safe recovery metadata to the UI instead of raw request params, so token material is not exposed in the browser replay/detail panel.
- Added README/config guidance for hardened deployments: HTTPS-only cookies, workspace-root restrictions, per-user Codex/Claude homes, and web approval gates instead of auto-approve.
- The adapter still does not fake success for token refresh or attestation; full Web-native account refresh remains a later low-priority account integration task.


## 14. 2026-07-17 current reassessment and adaptation plan

Current verified baseline:

- Branch/worktree: `main...origin/main`, clean before this documentation update.
- Latest pushed checkpoint: `d6e7f68 Exercise live broadcast in Codex WS smoke`.
- Local CLI baseline: `codex-cli 0.142.4`.
- Protocol matrix baseline: app-server schema currently records 68 server notifications, 10 server requests, and 87 client requests. The web adapter labels 30 notifications as supported, 9 as degraded, 29 as generic visible, 5 server requests as supported, 3 as degraded, 2 as generic visible, and 32 client requests as supported.

### 14.1 Current product position

The project is now a credible remote Codex session host, not just a web terminal wrapper. Its strongest areas are:

- Structured app-server integration instead of TUI scraping.
- Multi-client replay with stable `seq` / `event_id` and `after=<lastSeq>` reconnect.
- Sidebar/history lifecycle controls, including active/archived Codex history.
- Launch config parity for model, search, sandbox, approval, reasoning effort/summary, service tier, and workspace-write writable roots.
- Input parity first slice: slash palette, `@` file mention via `fuzzyFileSearch`, image upload/paste, Plan/task switches, and backend-confirmed lifecycle actions.
- Approval/ask/form/pending-card recovery across reconnects.
- Manual MCP resource/tool slash calls, dynamic tool allowlist passthrough, and web stdin cards for terminal interaction.
- Multi-user state/home/workspace isolation with documented hardened deployment guidance.

It is still not a full Codex CLI replacement. The remaining gap is less about basic chat and more about tail behavior: stale-open WebSocket reconciliation, real-world browser/mobile visual QA, richer Codex-native tool cards, deep MCP/terminal validation, Web-native account recovery, plugin/skills write/install/read-detail coverage, and security hardening for tunneled/shared exposure.

Updated rough progress estimate:

| Area | Current estimate | Notes |
| --- | ---: | --- |
| Remote usable Codex agent session | 85% | Core chat, approvals, Plan, history, replay, image input, and multi-client protocol smoke are usable. |
| Full Codex CLI TUI replacement | 66-71% | High-frequency session operations are covered; plugin/skills inventory is read-only; account/doctor/cloud/exec/review/apply-style workflows remain mostly outside the web UI. |
| Multi-access and sync | 75% | Incremental reconnect and two-client smoke are strong; open-but-stale WS catch-up and real browser/mobile visual tests are still needed. |
| app-server protocol coverage | 62% | 32/87 client requests are supported; plugin/skills inventory is read-only, while many long-tail account/config/fs/plugin-write/skills-write/windows sandbox methods remain intentionally not integrated. |
| Frontend maintainability | 65% | JS/CSS are split, but `index.html` still holds large native-stage style blocks and the JS state model remains global. |
| Backend maintainability | 70% | Manager/common/native modules are split; `CodexSession`, `common.py`, and some app-server routing fallbacks remain complexity hotspots. |
| Security/release hardening | 55% | Auth/multi-user/hardened docs exist; CSRF/Origin checks and stricter default deployment profiles still need implementation. |

### 14.2 Current CLI vs Web gaps

1. Session transport and replay:
   - Reconnect after a closed WebSocket is much better now because both WS URL and `/api/nreplay` can use `after=<lastSeq>`.
   - Remaining gap: if the browser WebSocket remains `readyState === 1` but stops receiving useful events, `pollSessionSignals()` currently only refreshes session state and does not perform a low-frequency `after=<lastSeq>` catch-up. This can still leave the UI waiting until a close/reconnect happens.
   - Required adaptation: add throttled visible-session catch-up polling that runs even when WS is open, uses the current replay cursor, and applies only unseen events silently.

2. Launch/config parity:
   - Covered: model, web search, sandbox, approval, reasoning effort, reasoning summary, service tier, and writable roots.
   - Remaining gap: CLI `--profile`, arbitrary `-c key=value`, `--enable/--disable`, local provider / OSS mode, and some account/config methods do not have safe Web UI equivalents yet.
   - Required adaptation: keep unsupported config hidden unless the app-server schema has a clear target field; add read-only profile/config visibility before allowing writes.

3. Input parity:
   - Covered: common slash commands, keyboard selection, `@` mention, and image input.
   - Remaining gap: the palette is still a small command list rather than a CLI-grade command surface; image history thumbnails and cleanup policy are basic; file mentions are first-slice UX.
   - Required adaptation: expand command discovery in small batches and keep each command backend-confirmed so the UI never displays fake state.

4. Tool/terminal parity:
   - Covered: generic command/file/MCP/dynamic tool cards, manual MCP slash calls, allowlisted dynamic tool passthrough, and terminal stdin/resize/terminate endpoints.
   - Remaining gap: real MCP server E2E has not become a repeatable smoke; terminal interaction needs long-running/interactive command validation; file diffs and `turn/diff/updated` still need Codex-native cards.
   - Required adaptation: validate one real MCP server and one real interactive command path first, then improve renderer fidelity.

5. Account and non-session CLI capabilities:
   - Covered: account refresh and attestation now fail visibly with safe CLI recovery steps.
   - Remaining gap: Web-native account login/logout/token refresh, usage/rate-limit details, `doctor`, plugin/skills write/install/read-detail, `cloud`, `review`, `apply`, and noninteractive `exec` are mostly not integrated.
   - Required adaptation: treat these as lower priority than session stability unless the user workflow depends on them; start with read-only account/status/plugin/skills views before write/install actions.

6. Security and deployment:
   - Covered: auth, multi-user isolation, README/config hardened guidance, per-user homes, workspace-root checks for writable dirs.
   - Remaining gap: state-changing JSON APIs still need Origin/CSRF protection for tunneled/shared exposure; default config remains local/LAN-friendly; manager/internal control boundaries need continued audit.
   - Required adaptation: add an opt-in hardened mode first, then consider making safer defaults the recommended public profile.

### 14.3 Current code issues to keep visible

- `assets/app_sidebar.js` / `assets/native_replay.js`: polling and pending-card resync are still mostly close-triggered. Add open-WS catch-up polling to avoid stale-but-open sockets causing delayed UI.
- `assets/native_events.js`: the event renderer has grown large and handles many item types in one file. New Codex-native cards should be split before adding many more special cases.
- `index.html`: native-stage CSS is still inline, so markup, layout policy, and component styling remain coupled.
- `codex_native.py`: `CodexSession` is still the largest backend hotspot. It owns session state, turn lifecycle, persistence, replay, app-server calls, request handling, notifications, and push state.
- `codex_client.py`: notification routing still needs trace fixtures for methods that lack complete thread/turn/item IDs; the "single busy session" fallback is useful but should not be the only multi-session safety net.
- `common.py`: still acts as a compatibility facade with import-time config/auth/binary discovery. This is manageable now, but it complicates isolated tests and future service boundaries.
- `web.py`: still mixes login, static serving, manager proxying, restart/stop, and manager watchdog concerns.
- `docs/app-server-protocol-matrix.md`: useful as a snapshot, but future Codex CLI upgrades must regenerate it and compare drift before assuming parity still holds.

### 14.4 Recommended adaptation roadmap from here

Phase 1 - Stability before feature depth:

- Add throttled foreground catch-up polling using `/api/nreplay?sid=<sid>&after=<lastSeq>` even when WS is open.
- Extend frontend static checks to assert the catch-up path uses `after`, `silent:true`, in-flight guards, and does not clear DOM.
- Run protocol smoke with two clients and one temporary session after every replay/socket change.
- Add at least one manual browser/mobile visual checklist for reconnect, pending approval, Plan, image, and sidebar history.

Phase 2 - Tool and terminal realism:

- Pick one real MCP server and make dynamic-tool passthrough a repeatable end-to-end test.
- Validate terminal stdin with at least one interactive command requiring multiple writes and termination.
- Improve renderer cards for command execution, file changes, MCP results, context compaction, and diffs before adding more raw JSON output.

Phase 3 - CLI command/config parity:

- Add read-only profile/config/account status visibility first.
- Only expose writable config/profile controls when the target app-server request and schema fields are known.
- Expand slash palette in small confirmed batches: delete/unsubscribe/metadata where useful, account/status reads, plugin/skills reads, and richer goal/profile shortcuts.

Phase 4 - Structure hardening:

- Split `CodexSession` along state, turn runner, notification adapter, request handler, and replay store seams.
- Move remaining native-stage CSS out of `index.html`.
- Group frontend globals into a small `window.AC` namespace or ES-module-like boundaries before the next large UI feature.
- Add trace fixtures for app-server routing and replay edge cases.

Phase 5 - Deployment hardening:

- Add Origin/CSRF checks for state-changing browser APIs.
- Make hardened profile easy to enable and verify: HTTPS cookies, path restrictions, non-default homes, no auto-approve, and private manager port.
- Keep localhost/internal manager endpoints explicitly authenticated and covered by boundary tests.

Immediate next commit candidate:

- Implement Phase 1 catch-up polling first. It directly addresses the current user-facing risk: WebSocket 1006 or stale-open connections should not cause duplicate replay, missing pending cards, or visible conversation flicker. This is small enough to validate with `node --check`, frontend static tests, replay helper tests, `tools/codex_ws_smoke.py --clients 2 --launch-temp`, and `git diff --check`.


## 15. 2026-07-17 foreground catch-up polling checkpoint

- Implemented a throttled visible-session catch-up path in `assets/native_replay.js`. When `/api/sessions` says the current visible session is running, waiting for confirmation, in Plan mode, or has just settled from an active state, the browser can call `/api/nreplay?sid=<sid>&after=<lastSeq>` even if the WebSocket still reports `readyState === 1`.
- The catch-up path is intentionally silent: it uses existing replay de-duplication and `nReplayBatchAsync(..., {silent:true})`, handles `state_snapshot` and pending cards, and does not clear the existing DOM. This targets stale-open WS cases separately from normal closed-socket polling.
- Added per-stage `lastCatchupPoll` and `catchupInFlight` guards so the regular 4s `/api/sessions` signal loop cannot flood replay requests while a session is actively streaming.
- Added frontend contract coverage in `tests/check_replay_loading_frontend.py` and a Node-level behavior check in `tests/check_native_replay_frontend_logic.py` to lock the `after=<lastSeq>` URL, silent replay behavior, open-WS trigger, and throttling.


## 16. 2026-07-17 diff card checkpoint

- Improved the `turn/diff/updated` display path on the frontend. Standalone tool results with `tool_use_id = "turn-diff"` now render as a dedicated unified diff card with file/add/delete/line summary instead of a generic `Result (...)` text blob.
- Repeated `turn/diff/updated` snapshots now update the same standalone result card via `data-tuid`, reducing duplicate diff cards during long coding turns and keeping replay/live rendering less noisy across clients.
- The generic tool-result renderer now detects diff-like content and uses the same diff card; non-diff output keeps the existing collapsed result block.
- Added frontend static and Node helper checks for `nDiffResultHtml`, `nToolResultMarkup`, and `nRenderToolResult`, covering summary stats, add/delete line classes, and the special `turn-diff` path.


## 17. 2026-07-17 JSON tool result card checkpoint

- Improved the generic tool-result renderer again: JSON-shaped result content now becomes a structured result card with a concise summary, optional content preview, and pretty-printed JSON body.
- Tool cards now keep the originating tool name in `data-tname`, so MCP/manual tool results can display summaries such as `JSON · server.tool` rather than an anonymous `Result (...)` blob.
- The renderer still preserves the same replay contract (`tool_result` events with `tool_use_id`); this is a frontend-only display improvement that works for live events, replay, reconnect, and catch-up polling.
- Added static and Node-level checks for `nJsonResultHtml`, JSON previews, and the JSON branch in `nToolResultMarkup`.


## 18. 2026-07-17 special tool start card checkpoint

- Added dedicated compact start cards for Codex `sleep`, `contextCompaction`, `imageGeneration`, and `imageView` tool-use events. These no longer fall back to a raw JSON input dump in the conversation.
- The cards expose the most useful fields directly: sleep duration/reason, compaction status/summary/tokens, image prompt/size/model, and viewed image path or URL.
- This is display-only and keeps the same replay event shape, so multi-client live rendering, history replay, reconnect, and catch-up polling continue to use the same event stream.
- Added frontend contract and Node helper checks for `nSpecialToolBody` and the new tool-use branches.


## 19. 2026-07-17 MCP/dynamic tool-use card checkpoint

- Added a structured start-card path for dotted or slash-style MCP/dynamic tool names, such as `server.tool` and `mcpServer.resource/read`.
- These tool-use cards now show server/tool labels, a short argument preview, and collapsed pretty arguments instead of defaulting directly to a raw JSON input block.
- The renderer keeps the same `tool_use` replay event shape and only changes frontend presentation, so live clients, replay, reconnect, and catch-up polling remain protocol-compatible.
- Added frontend contract and Node helper checks for `nStructuredToolBody`, argument previews, and the non-interference case where normal shell tools still use their existing renderers.


## 20. 2026-07-17 MCP end-to-end smoke checkpoint

- Added `tools/codex_mcp_smoke.py`, a repeatable live smoke that creates a temporary `CODEX_HOME`, writes a local stdio MCP echo server into it, starts `codex app-server --stdio`, opens a temporary Codex thread, and calls `mcpServer/tool/call` against the real MCP server.
- The same smoke also exercises the Agents Cockpit dynamic-tool passthrough handler with an explicit `smoke.echo -> mcp:codex_smoke/echo` mapping, verifying that it records matching `tool_use` / `tool_result` events and returns `DynamicToolCallResponse` content from the MCP result.
- This closes the first real MCP E2E validation gap without depending on external services or the user's permanent Codex config.
- Added `tests/check_codex_mcp_smoke_helpers.py` so the smoke helper structure is covered by the normal fast `tests/check_*.py` bundle, while the live E2E is run explicitly with `python tools\codex_mcp_smoke.py --cwd .`.


## 21. 2026-07-17 visual smoke gate checkpoint

- Added `docs/codex-visual-smoke-checklist.md` as the repeatable browser/mobile visual QA gate for Codex multi-client sync. It covers dual-client open, streaming sync, Plan/pending cards, tool card replay, image input, WebSocket disconnect recovery, stale-open catch-up, lifecycle actions, narrow mobile input, and long-history loading.
- Added `tools/codex_visual_smoke_report.py` to generate a per-run Markdown evidence template with git status, Codex CLI version, protocol-smoke commands, V01-V10 scenario rows, and failure fields for close code / last seq / catch-up URL.
- Expanded `window.NATIVE_DEBUG` logs for WebSocket close and replay catch-up paths so visual smoke runs can capture close code, retry delay, replay cursor, content presence, visibility state, catch-up URL, event count, snapshot state, and pending count without exposing raw conversation data.
- Added `tests/check_codex_visual_smoke_report.py` so the checklist and template stay aligned with the current Phase A stability requirements.
- This still does not claim that a real browser/mobile smoke has been executed in this checkpoint; it makes that user-visible gate explicit and repeatable before the next browser automation or manual QA pass.


## 22. 2026-07-17 headless browser smoke checkpoint

- Added `tools/codex_browser_smoke.py`, which starts two real headless Chromium/Edge tabs through the Chrome DevTools Protocol, logs in to the web UI, attaches both tabs to one temporary Codex session, and verifies a backend-confirmed `/rename` notice reaches both rendered DOMs.
- The same smoke deliberately closes the mirror tab's WebSocket, sends another backend-confirmed notice while that tab is disconnected, and verifies the mirror tab recovers the missed notice through replay/catch-up without clearing the existing DOM content.
- This upgrades Phase A evidence from protocol-only to rendered-browser evidence for the most important user-visible invariant: multi-client content stays synchronized and reconnect recovery appends missing content instead of repainting the whole conversation.
- Added `tests/check_codex_browser_smoke_helpers.py` to keep the smoke's login, `showNativeSession`, forced `ws.close()`, `/api/nslash`, and DOM-preservation assertions present in the fast test bundle.

## 22.1. 2026-07-17 narrow browser smoke checkpoint

- Extended `tools/codex_browser_smoke.py` so the mirror tab defaults to a phone-like 390x844 viewport through Chrome DevTools `Emulation.setDeviceMetricsOverride` while the primary tab stays desktop-sized.
- The rendered smoke now records viewport/layout evidence and fails if the narrow mirror cannot see the native composer, input, submit button, message stage, or expected mobile sidebar drawer positioning.
- This does not replace real phone/manual background-foreground QA, but it closes the first repeatable headless narrow-screen evidence gap for reconnect-without-flicker and multi-client content sync.
- Updated `tests/check_codex_browser_smoke_helpers.py`, `REFACTOR_PROGRESS.md`, and `docs/codex-cli-gap-adaptation-plan.md` so the narrow-layout contract remains visible in the fast checks and current plan.

## 22.2. 2026-07-17 forced reconnect browser smoke checkpoint

- Extended the same browser smoke to distinguish disconnected catch-up from an actual WebSocket reconnect: after the mirror tab silently catches up a missed notice, it calls `nativeConnect(sid, {force:true})`, waits for an open socket, and sends another backend-confirmed `/rename`.
- The smoke now records both `after_catchup` and `after_reconnect` summaries, and fails unless the pre-existing marked DOM node plus prior text survive both phases.
- This turns the reconnect anti-flicker claim into stronger rendered-browser evidence: the UI can recover missed events while disconnected and then reconnect without clearing/rebuilding the conversation DOM.


## 23. 2026-07-17 terminal interaction smoke checkpoint

- Added `tools/codex_terminal_smoke.py` to validate the Web adapter side of Codex terminal interaction without waiting for a nondeterministic model-triggered interactive command. It simulates two `item/commandExecution/terminalInteraction` notifications, tracks their process ids, and drives the same `terminal_write`, `terminal_resize`, and `terminal_terminate` methods used by `/api/nterminal`.
- The smoke verifies multiple stdin writes are base64-encoded into `command/exec/write`, resize maps to `command/exec/resize`, close-stdin emits a replayable `terminal_closed`, terminate maps to `command/exec/terminate`, and closed/terminated processes reject later actions.
- Added `tests/check_codex_terminal_smoke_helpers.py` so this long-path contract is covered by the fast test bundle while the standalone smoke remains runnable with `python tools\codex_terminal_smoke.py --cwd .`.
- This closes the first repeatable terminalInteraction validation gap; a later smoke can still add a real app-server `command/exec` launch once that method is productized instead of only supporting write/resize/terminate for existing Codex-owned processes.


## 24. 2026-07-17 Origin/CSRF hardening checkpoint

- Added browser-facing Origin/Referer validation for state-changing POST requests and Codex/Claude WebSocket handshakes in `web.py`. Internal local requests with the existing `Authorization` secret still bypass this check, so local restart/manager control tooling remains usable.
- Added `[security] csrf_origin_check`, `csrf_allow_missing_origin`, and `allowed_origins` config knobs. Defaults keep compatibility for clients that omit Origin/Referer while still rejecting explicit cross-origin browser requests; hardened deployments should set `csrf_allow_missing_origin = 0`.
- The check accepts same Host or `X-Forwarded-Host`, plus configured extra origins for reverse proxy/tunnel deployments.
- Added helper coverage in `tests/check_common_auth_helpers.py` and `tests/check_web_security_helpers.py`, and updated README/config guidance so the hardened profile is now executable rather than only conceptual.


## 25. 2026-07-17 hardened profile verifier checkpoint

- Added `tools/check_hardened_profile.py`, a standalone verifier for the recommended shared/tunnel deployment profile. It checks localhost binding or explicit override, HTTPS or trusted proxy termination, no extra HTTP listener, web approval gates, workspace-root restrictions, per-user Codex/Claude homes, Secure cookies, Origin checks, missing-Origin rejection, and bounded session TTL.
- The verifier supports text output for humans and `--json` for scripts, plus `--behind-https-proxy` for reverse-proxy deployments where Agents Cockpit itself receives local HTTP behind TLS.
- Added `tests/check_hardened_profile_tool.py` with passing, proxy, and weak-config fixtures so the hardened profile no longer exists only as README prose.
- Updated README, `REFACTOR_PROGRESS.md`, and the CLI adaptation plan validation bundle to include the hardened-profile check.


## 26. 2026-07-17 terminal adapter extraction checkpoint

- Added `codex_terminal.py` and moved the terminalInteraction process tracking plus `command/exec/write`, `command/exec/resize`, and `command/exec/terminate` mapping logic out of `codex_native.py`.
- `CodexSession.terminal_interaction_event`, `_terminal_known`, `terminal_write`, `terminal_resize`, and `terminal_terminate` remain as compatibility wrappers, so `/api/nterminal`, replay, browser cards, and existing tests keep the same public behavior.
- This is the first Phase D structure-hardening step after the terminal smoke: it reduces the session class responsibility without changing the validated terminalInteraction contract.


## 27. 2026-07-17 pending request adapter extraction checkpoint

- Added `codex_pending.py` and moved Codex pending approval/ask/form helper logic out of `codex_native.py`: pending detection, approval decisions, ask/form answers, state snapshot pending lists, replayable pending-card snapshots, and pending waiter cleanup.
- `CodexSession.approve`, `CodexSession.answer`, `_state_snapshot`, `_pending_events_snapshot`, `state`, `close`, and `on_client_exit` still expose the same behavior through wrappers or direct helper calls, preserving `/api/napprove`, `/api/nanswer`, replay recovery, and app-server-exit cleanup.
- Added `tests/check_codex_pending_helpers.py` so pending approval, ask, form, terminal snapshot mixing, event wakeups, and broadcasts are covered in the fast test bundle.

## 28. 2026-07-17 comprehensive Codex CLI parity reassessment

- Re-read the current baseline on `main` / `a02753a` against local `codex-cli 0.142.4` and refreshed the protocol matrix from the installed app-server schema.
- Rewrote `docs/codex-cli-gap-adaptation-plan.md` as the current source-of-truth plan: 68 server notifications, 10 server requests, and 87 client requests are now called out with the current support mix.
- Current conclusion: the Web session is a strong remote/multi-client Codex agent host, not yet a full CLI replacement. High-frequency chat/approval/Plan/replay/history/image/MCP/terminalInteraction paths are usable; profile/config layers, account/login closure, plugin/skills, doctor/update/features, exec/review/apply/cloud, and richer tool UI remain gaps.
- Current code hotspots: `codex_native.py` is still the main backend concentration point at about 1473 lines; `common.py`, `web.py`, `manager_user_api.py`, `codex_client.py`, and the native frontend renderer files remain the next maintenance and hardening seams.
- Recommended next implementation step: extract a behavior-preserving `CodexReplayFacade` before adding more CLI parity features. The first slice should wrap timeline identity/merge/events/replay payload while keeping public `CodexSession` methods and WebSocket behavior stable.
- No runtime behavior was changed in this checkpoint; this is a documentation/planning update to align the next refactor steps with the current code state.

## 29. 2026-07-17 replay facade extraction checkpoint

- Added `codex_replay_facade.py` and routed Codex replay/timeline compatibility wrappers through `CodexReplayFacade`.
- The first slice is behavior-preserving: `CodexSession` still exposes `_is_dangerous`, `_record_timeline_locked`, `_merge_timeline_event_locked`, `_adopt_history_replay`, `_events_after_seq`, and `replay_payload`, but event identity, timeline recording/merging, history replay adoption, incremental event lookup, and replay payload generation now sit behind the facade.
- Added `tests/check_codex_replay_facade_helpers.py` so the new facade has direct coverage for dangerous command detection, event identity, broadcast decoration, incremental replay payloads, history replay adoption, scoring, and recovery-noise filtering.
- Updated `REFACTOR_PROGRESS.md` and `docs/codex-cli-gap-adaptation-plan.md` to record the facade as Phase 1's first completed structural slice and to include `codex_replay_facade.py` in the validation bundle.

## 30. 2026-07-17 replay facade poll/persist checkpoint

- Moved the next replay/broadcast seam into `CodexReplayFacade`: broadcast preparation now decorates timeline events and records trimmed `poll_events` in one place.
- Persistence throttling also moved behind the facade. `CodexSession._persist_if_due()` remains as a compatibility wrapper, but important-event detection and the 1.5s non-important-event throttle now live with replay/broadcast coordination.
- Extended `tests/check_codex_replay_facade_helpers.py` to cover poll-event exclusion for snapshots/usage-style events, incremental replay after polled broadcasts, important-event persistence, and throttled non-important persistence.

## 31. 2026-07-17 replay facade client attach checkpoint

- Moved `CodexSession.add_client()` internals behind `CodexReplayFacade.add_client()` while keeping the public `CodexSession.add_client(sock, after_seq=0)` entrypoint unchanged for manager/WebSocket callers.
- The facade now owns the client attach replay sequence: optional `replay_batch`, `state_snapshot`, pending approval/ask/form events, client registration, keepalive ping loop, WebSocket recv loop, client discard, and socket close cleanup.
- Extended `tests/check_codex_replay_facade_helpers.py` with a fake socket/thread path so initial replay ordering, pending-card replay on attach, close/discard cleanup, and keepalive thread startup are covered without opening a real socket.

## 32. 2026-07-17 turn runner extraction checkpoint

- Added `codex_turn.py` with `CodexTurnRunner`, starting Phase 2 by moving Codex thread/turn lifecycle coordination out of the main `CodexSession` body.
- `CodexSession` still exposes `_thread_params`, `_turn_params`, `_collaboration_mode`, `_sync_collaboration_mode`, `_apply_thread_response`, `_ensure_thread`, and `_run_turn`, but those compatibility wrappers now delegate to the runner.
- The runner now owns thread/start params, turn/start params, task-mode prompt prefixing, collaboration mode sync, thread response adoption, thread resume, turn/start request handling, turn registration, and turn-start failure cleanup.
- Added `tests/check_codex_turn_helpers.py` to cover thread params, task-mode turn params, collaboration settings, thread resume adoption, successful turn start registration, and failed turn cleanup.

## 33. 2026-07-17 notification adapter extraction checkpoint

- Added `codex_notifications.py` with `CodexNotificationAdapter`, starting the notification-adapter slice without changing the existing `codex_session_events.py` helper implementation.
- `CodexSession` still exposes `_remember_codex_debug_notice`, `_remember_route_debug`, `_codex_notice`, `_handle_updated_event`, `handle_notification`, `_on_turn_completed`, `_on_item_started`, `_on_item_completed`, `_flush_pending_plan_items`, `_on_plan_updated`, `_on_thread_settings_updated`, and `_usage_for_meta`; those wrappers now delegate through the adapter.
- Added `tests/check_codex_notifications_helpers.py` to cover visible/silent notices, updated-event message extraction, compacted-thread notification handling, and usage meta passthrough through the adapter.

## 34. 2026-07-17 notification implementation migration checkpoint

- Moved the Codex notification helper implementation into `codex_notifications.py` so `CodexNotificationAdapter` now owns the notification/notice behavior rather than only wrapping `codex_session_events.py`.
- Kept `codex_session_events.py` as a compatibility import layer for existing helper tests and any older imports, preserving the public helper function names while making the adapter module the implementation home.
- Re-ran targeted notification/session-event tests to confirm visible notices, silent debug notices, compacted-thread handling, pending plan flushing, goal notifications, terminal interaction events, and usage metadata still behave the same.

## 35. 2026-07-17 state persistence extraction checkpoint

- Added `codex_state.py` with `CodexSessionState`, moving Codex state path construction, persisted JSON payload construction, state writes, recovered thread/model/timeline application, and startup recovery into a focused helper.
- `CodexSession._state_path()`, `_persist()`, and `recover()` remain as compatibility wrappers, so manager/session callers and replay recovery behavior keep the same public entrypoints.
- Added `tests/check_codex_state_helpers.py` to cover state path/payload persistence, recovery field application, recovery-noise filtering, next-sequence restoration, and local-only client registration during startup recovery.
- Updated `REFACTOR_PROGRESS.md` and `docs/codex-cli-gap-adaptation-plan.md` so the current structure plan records the state helper slice and includes `codex_state.py` in the validation bundle.

## 36. 2026-07-17 input adapter extraction checkpoint

- Added `codex_input.py` with `CodexInputAdapter`, moving cwd-bounded `@` mention resolution, app-server `fuzzyFileSearch` result shaping, per-session image upload storage, `localImage` turn input creation, and user-message image replay blocks out of `codex_native.py`.
- `CodexSession._path_within_cwd()`, `_resolve_mention_path()`, `_image_upload_dir()`, `image_file()`, `prepare_image_inputs()`, `_display_user_content()`, `_user_input_items()`, `_search_file_result()`, and `search_files()` remain as compatibility wrappers, preserving manager API and turn runner behavior.
- Added `tests/check_codex_input_helpers.py` to cover mention de-duplication, cwd boundary filtering, image validation/storage/detail fallback, replay block creation, and filtered fuzzy-file results.
- Updated `REFACTOR_PROGRESS.md` and `docs/codex-cli-gap-adaptation-plan.md` so the current structure plan records the input adapter slice and includes `codex_input.py` in the validation bundle.

## 37. 2026-07-17 slash adapter extraction checkpoint

- Added `codex_slash.py` with `CodexSlashAdapter`, moving slash dispatch, session config tuning, thread lifecycle actions, goal commands, steer, and manual MCP resource/tool helpers out of `codex_native.py`.
- `CodexSession.handle_slash_command()`, config setters, lifecycle methods, goal helpers, and manual MCP helpers remain as compatibility wrappers, preserving `/api/nslash`, sidebar/history actions, and existing helper tests.
- Added `tests/check_codex_slash_helpers.py` to cover direct slash adapter dispatch, delegated session-state mutation, compaction request state, goal read notices, steer input mapping, and invalid MCP JSON handling.
- Updated `REFACTOR_PROGRESS.md` and `docs/codex-cli-gap-adaptation-plan.md` so the current structure plan records the slash adapter slice and includes `codex_slash.py` in the validation bundle.

## 38. 2026-07-17 server request adapter checkpoint

- Added `CodexRequestAdapter` inside `codex_requests.py`, moving the active `CodexSession` delegation point for app-server requests behind a request-focused adapter.
- The adapter now owns tool event/result conversion, incremental tool output append, approval/ask/form waits, dynamic MCP passthrough/rejection, `currentTime/read`, unsupported account/attestation recovery notices, and approve/answer decisions.
- `CodexSession.handle_server_request()`, `_await_approval()`, `_await_user_input()`, `_await_form_input()`, `_handle_dynamic_tool_call()`, `_call_mcp_tool_for_dynamic()`, `approve()`, and `answer()` remain as compatibility wrappers, preserving app-server routing and browser APIs.
- Extended `tests/check_codex_requests_helpers.py` to cover the adapter path directly, including tool output accumulation, direct `currentTime/read`, dynamic MCP mapping, and existing recovery/error behavior.

## 39. 2026-07-17 native tool-card renderer extraction checkpoint

- Added `assets/native_tool_cards.js` and moved the Codex assistant `tool_use` card renderer out of `assets/native_events.js`.
- `nHandle()` now dispatches assistant tool-use blocks to `nRenderToolUseBlock(sid, st, b)`, keeping replay/live event flow unchanged while isolating shell/edit/todo/web/MCP/special tool-card markup for future CLI-parity upgrades.
- Updated `index.html` to load the new renderer between shared native stage helpers and the event dispatcher, preserving dependency order.
- Updated `tests/check_replay_loading_frontend.py` so the static frontend contract verifies the new script order and `nRenderToolUseBlock` entrypoint.

## 40. 2026-07-17 Codex config status visibility checkpoint

- Added a read-only Codex `config/read` status line to the launch modal via `#lm-codex-status`.
- `assets/app_launch.js` now summarizes high-frequency inherited fields from app-server config (`model`, approval, sandbox, web search, reasoning effort/summary, and service tier) plus available model/profile counts.
- This does not add unsafe profile/config writes; it only makes the current inherited Codex defaults more visible before launch, aligning with the plan's read-only-first config strategy.
- Updated `tests/check_replay_loading_frontend.py` to lock the new DOM id and status-rendering helper entrypoints.

## 41. 2026-07-17 native tool-result renderer extraction checkpoint

- Added `assets/native_tool_results.js` and moved result/diff/JSON tool-result rendering out of `assets/native_stage.js`.
- `nRenderToolResult()` keeps the same public entrypoint for replay/live tool results, but diff stats, JSON previews, generic result markup, and standalone result host lookup now live in the dedicated result renderer.
- Improved command readability: shell command cards show `cwd` when present, and Bash/PowerShell results now summarize exit code and output line count instead of only showing a generic line count.
- Updated `index.html`, `tests/check_native_replay_frontend_logic.py`, and `tests/check_replay_loading_frontend.py` to load and validate the new result renderer.

## 42. 2026-07-17 native pending-card renderer extraction checkpoint

- Added `assets/native_pending_cards.js` and moved pending approval, Plan review, ask, form, and resolved-card cleanup handling out of `assets/native_events.js`.
- `nHandle()` now dispatches pending events to `nHandlePendingApproval`, `nHandlePendingAsk`, `nHandlePendingForm`, and `nHandlePendingResolved`, keeping live/replay event flow unchanged while isolating confirmation-card markup.
- Updated `index.html`, `REFACTOR_PROGRESS.md`, and `tests/check_replay_loading_frontend.py` so script order and static frontend contracts include the new renderer.
- Refreshed the CLI gap plan to mark pending/form renderer extraction complete and make terminalInteraction/stage/sidebar renderer seams the next structure candidates.

## 43. 2026-07-17 native terminal-card renderer extraction checkpoint

- Added `assets/native_terminal_cards.js` and moved terminalInteraction card rendering, `/api/nterminal` posting, input-sent cleanup, and close/terminate summaries out of `assets/native_events.js`.
- `nHandle()` now dispatches `terminal_interaction`, `terminal_input_sent`, and `terminal_closed` to dedicated terminal-card helpers, keeping replay/live event routing unchanged while isolating terminal UI behavior.
- Updated `index.html`, `REFACTOR_PROGRESS.md`, `docs/codex-cli-gap-adaptation-plan.md`, and `tests/check_replay_loading_frontend.py` so the current structure map and static frontend contracts include the new renderer.
- This leaves `assets/native_events.js` more focused on event routing; the next frontend seams are stage text/thinking helpers, sidebar lifecycle action rendering, or push/notification boundaries.

## 44. 2026-07-17 native text/thinking renderer extraction checkpoint

- Added `assets/native_text_cards.js` and moved assistant text bubbles, stream text/thinking handling, replayed thinking blocks, and proposed-plan text rendering out of `assets/native_stage.js` / `assets/native_events.js`.
- `nHandle()` now delegates `stream_event` to `nHandleStreamEvent()` and assistant thinking blocks to `nRenderAssistantThinkingBlock()`, keeping live/replay routing unchanged while isolating text/thinking UI behavior.
- Updated `index.html`, `REFACTOR_PROGRESS.md`, `docs/codex-cli-gap-adaptation-plan.md`, and `tests/check_replay_loading_frontend.py` so the current structure map and static frontend contracts include the new text renderer.
- This leaves the next low-risk frontend seams as sidebar lifecycle actions, tool-body helper placement, or push/notification boundaries rather than adding more markup to the central event dispatcher.

## 45. 2026-07-17 sidebar Codex action extraction checkpoint

- Added `assets/app_sidebar_codex_actions.js` and moved running/history Codex lifecycle action helpers out of `assets/app_sidebar.js`.
- The sidebar still calls `appendCodexRunActions()` and `appendCodexHistoryActions()` from conversation rows, but `/api/nslash` and `/api/codex_history_action` posting plus action-button construction now live in the dedicated Codex action module.
- Updated `index.html`, `REFACTOR_PROGRESS.md`, `docs/codex-cli-gap-adaptation-plan.md`, and `tests/check_replay_loading_frontend.py` so script order and static contracts include the new sidebar action module.
- This keeps sidebar list rendering separate from CLI-parity lifecycle actions, making future Fork/Rollback/Goal/Archive UX work safer for multi-client session list refreshes.

## 46. 2026-07-17 native tool-helper extraction checkpoint

- Added `assets/native_tool_helpers.js` and moved special tool body rendering, structured MCP/dynamic tool previews, and shell tool grouping helpers out of `assets/native_stage.js`.
- `assets/native_stage.js` now stays focused on session stage containers plus shared row/meta helpers, while `assets/native_tool_cards.js` consumes the dedicated helper module for tool-specific markup.
- Updated `index.html`, `tests/check_replay_loading_frontend.py`, `tests/check_native_replay_frontend_logic.py`, `REFACTOR_PROGRESS.md`, and `docs/codex-cli-gap-adaptation-plan.md` so script order and helper coverage include the new module.
- This reduces the risk that future CLI-parity tool card work touches session/replay stage lifecycle code.

## 47. 2026-07-17 sidebar row renderer extraction checkpoint

- Added `assets/app_sidebar_rows.js` and moved sidebar directory rows, directory bodies, conversation rows, resume/delete/close row actions, and history row rendering out of `assets/app_sidebar.js`.
- `assets/app_sidebar.js` now stays focused on session/history model loading, polling, filters, tab state, and pending visibility; row layout lives in the dedicated sidebar row module.
- Updated `index.html`, `tests/check_replay_loading_frontend.py`, `REFACTOR_PROGRESS.md`, and `docs/codex-cli-gap-adaptation-plan.md` so script order and static contracts include the new row renderer.
- This makes future sidebar UX work safer for multi-client refresh and long-history loading because list model updates and row markup are no longer mixed in one file.

## 48. 2026-07-17 Codex broadcast adapter extraction checkpoint

- Added `codex_broadcast.py` with `CodexBroadcastAdapter`, moving WebSocket broadcast, transient replay pushes, one-shot socket sends, dead-client pruning, and push-notification throttling out of `codex_native.py`.
- `CodexSession._broadcast()`, `_broadcast_transient()`, `_send_one()`, and `_push()` remain as compatibility wrappers, preserving replay facade, manager WebSocket, and notification caller behavior.
- Added `tests/check_codex_broadcast_helpers.py` to cover broadcast persistence, dead-client pruning, transient sends, one-shot send failure cleanup, notification throttling, and disabled notification events.
- Updated `REFACTOR_PROGRESS.md` and `docs/codex-cli-gap-adaptation-plan.md` so validation bundles include `codex_broadcast.py`.

## 49. 2026-07-17 Codex thread history action facade checkpoint

- Moved the Codex history-row lifecycle action implementation from `CodexSession.history_action()` into `codex_thread_history.history_action()`.
- `CodexSession.history_action()` remains as the compatibility wrapper used by `/api/codex_history_action`, preserving sidebar/history behavior while reducing session-core logic.
- Extended `tests/check_codex_history_helpers.py` to cover direct fork/archive/unarchive/rename/goal history actions, missing-input errors, unsupported actions, and app-server request mapping.
- Re-ran targeted history/config checks so the existing launch/slash/lifecycle behavior remains unchanged before wider validation.

## 50. 2026-07-17 Codex launch account status checkpoint

- Extended `codex_config.load_launch_options()` to call app-server `account/read` with `refreshToken=false` and return a sanitized, non-token account summary for the launch modal.
- Updated `assets/app_launch.js` so the Codex launch status line combines inherited `config/read` defaults, model/profile counts, and masked account/plan/auth status instead of only showing config fields.
- Marked `account/read` as supported in `docs/app-server-protocol-matrix.md` with a read-only note; login/logout/token refresh remain intentionally outside this slice.
- Added config/frontend/protocol tests covering account status shaping, UI helper entrypoints, and matrix classification.

## 51. 2026-07-17 Codex command result card checkpoint

- Added command-result metadata to Codex `commandExecution` tool results: `exit_code`, `duration_ms`, and aggregated output now travel with replayed tool-result blocks.
- Enhanced `assets/native_tool_results.js` so Bash/PowerShell results show CLI-like summaries with exit status, duration, output line count, section labels, future stdout/stderr split support, and large-output auto-collapse.
- Updated the native event dispatcher to pass the whole tool-result block to the result renderer without changing the replay event shape for other tools.
- Added frontend and conversion tests for command duration parsing, split stdout/stderr rendering, metadata preservation, and updated static script contracts.

## 52. 2026-07-17 Codex diff file summary checkpoint

- Enhanced `assets/native_tool_results.js` diff result cards with parsed file lists, file chips, `+N more` overflow summaries, and large-diff auto-collapse while keeping the replay event shape unchanged.
- Added shared CSS for diff file chips and unified diff bodies in `index.html` so standalone result cards and tool-embedded results render the same summary affordance.
- Updated frontend logic and static-contract tests to lock the new `fileList`, `diff-file-list`, `diff-file-chip`, and `diff-large` behavior.
- This is the first Phase 4 file-change slice after command-result cards; deeper per-file navigation and richer patch summaries can build on this parser without touching replay semantics.

## 53. 2026-07-17 Codex per-file diff section checkpoint

- Extended diff parsing in `assets/native_tool_results.js` from a flat file list into per-file sections with per-file `+/-` counts and simple status labels for added/deleted/renamed/binary patches.
- Diff result cards now show a patch summary row, file chips with per-file stats, and nested per-file sections; large multi-file diffs keep the outer card closed and also keep file sections collapsed until opened.
- Updated `index.html` styling plus frontend logic/static tests so `diff-patch-summary`, `diff-file-sections`, and `diff-file-section` stay covered.
- This advances the Phase 4 file-change work from "large blob with chips" toward CLI-like file-level navigation without changing backend replay events.

## 54. 2026-07-17 Codex terminal interaction card UX checkpoint

- Rebuilt `assets/native_terminal_cards.js` terminalInteraction markup around a pure `nTerminalCardHtml()` helper, replacing mojibake/broken labels with clear stdin, send, close-stdin, terminate, status, and resize controls.
- Added terminal card CSS in `index.html` so replayed/live terminalInteraction events render as first-class cards instead of unstyled blocks.
- Extended frontend logic/static tests to cover the terminal card helper, resize button, and status element while preserving the existing `/api/nterminal` backend contract.
- This improves the Phase 4 terminalInteraction UX; a future slice still needs real app-server `command/exec` launch coverage once that workflow is productized.

## 55. 2026-07-17 Codex launch diagnostics checkpoint

- Extended `/api/codex_options` with a read-only `diagnostics` block that summarizes cwd, user, Codex home, state dir, workspace roots, inherited high-frequency config, model/profile counts, config layer count, and capability-read errors.
- Changed `config/read` discovery to request `includeLayers=true` and preserve returned layer metadata when available, without adding any profile/config write UI.
- Added a collapsible `Codex diagnostics` section in the launch modal and cleaned the status rendering path so inherited defaults, account state, and local path boundaries are visible before launch.
- Added backend and static frontend tests for the diagnostics payload and UI contracts, keeping the read-only-first CLI parity strategy intact.

## 56. 2026-07-17 Codex command/exec live smoke checkpoint

- Added connection-scoped `command/exec/outputDelta` handlers to `CodexAppServerClient`, so standalone streamed `command/exec` output can be routed without relying on thread/turn ids.
- Added `tools/codex_command_exec_smoke.py`, a real app-server smoke covering buffered `command/exec`, streamed stdout/stderr, streamed stdin via `command/exec/write`, and termination via `command/exec/terminate`.
- Updated the protocol matrix so `command/exec` is no longer `not_integrated`; it is marked `degraded` because live smoke and output routing exist, but no browser/admin workflow is productized yet.
- This advances the Phase 4 terminalInteraction E2E requirement while keeping the user-facing session path unchanged until a safe product surface is designed.

## 57. 2026-07-17 Codex MCP status visibility checkpoint

- Added `codex_mcp_status.py` so MCP status/resource browsing is kept out of the main `CodexSession` body while still using the existing slash adapter wrapper pattern.
- Added `/mcp-status [full|tools]` and `/mcp-resources <server>`; both call app-server `mcpServerStatus/list` and surface visible replayable notices with auth status, tool counts, resources, templates, and detail JSON.
- `mcpServer/startupStatus/updated` and `mcpServer/oauthLogin/completed` now produce explicit visible notices instead of generic status updates; OAuth remains a degraded notice path, not a Web-owned token/login flow.
- Updated the slash palette, protocol matrix, helper tests, frontend static contract, `REFACTOR_PROGRESS.md`, and `docs/codex-cli-gap-adaptation-plan.md` so Phase 4 MCP gaps are tracked as first-slice complete with richer UI/admin work still open.

## 58. 2026-07-17 MCP status result-card checkpoint

- Updated `codex_mcp_status.py` so `/mcp-status` and `/mcp-resources` emit replayable `tool_use` / `tool_result` pairs in addition to concise Codex notices.
- MCP inventory now shows up as the same structured JSON result cards used for other Codex tool outputs, so reconnecting or second clients do not depend on a transient notice detail panel to inspect resources/tools.
- Extended MCP status helper tests to verify the emitted result-card payloads while keeping the existing `mcpServerStatus/list` request shape and slash command results unchanged.
- Extended the live MCP smoke to call `mcpServerStatus/list` against the temporary stdio server, so the status path is verified alongside direct MCP tool calls and dynamic-tool passthrough.

## 59. 2026-07-17 MCP resource browser card checkpoint

- Added a dedicated frontend renderer for `mcpServerStatus.list` and `mcpServerStatus.resources` JSON results in `assets/native_tool_results.js`.
- MCP inventory now renders as server/resource/template/tool sections instead of a raw JSON block, and resource rows include `Read` actions wired to the existing `/mcp-resource <server> <uri>` slash/backend path.
- Added delegated click handling in `assets/native_actions.js`, plus CSS and frontend tests, so the resource browser remains replay-safe and usable from reconnected or second clients.

## 60. 2026-07-17 browser reconnect DOM-preservation checkpoint

- Strengthened `tools/codex_browser_smoke.py` so the reconnect test marks an existing rendered message node before forcibly closing one browser tab's WebSocket.
- After reconnect/catch-up, the smoke now requires both old text preservation and the same DOM node marker to remain, proving the session was not fully cleared/repainted during recovery.
- This gives the multi-access anti-flicker requirement a stronger repeatable browser-level gate than checking final text content alone.


## 59. 2026-07-17 Codex plugin/skills read-only inventory checkpoint

- Added `codex_inventory.py` and slash commands `/skills`, `/plugins`, and `/plugins available`, backed by app-server `skills/list`, `plugin/installed`, and `plugin/list`.
- The payload intentionally strips local skill/plugin paths and icon paths before replay, keeping the browser card focused on name, scope, enabled/installed state, version, and descriptions.
- Added dedicated `codex.skills` and `codex.plugins` result-card rendering in `assets/native_tool_results.js`, so plugin/skills inventory is replayable across clients without falling back to raw JSON.
- Updated the protocol matrix to mark `skills/list`, `plugin/installed`, and `plugin/list` as supported read-only client requests; write/install/read-detail plugin and skills flows remain documented gaps.
