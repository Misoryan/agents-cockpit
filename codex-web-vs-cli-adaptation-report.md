# codex-web 中 Codex 会话 vs Codex CLI 差距分析与适配计划

生成日期：2026-07-16
项目：`E:\tools\codex-web`
当前代码：`main` / `9f2fc85 refactor codex web structure` + 本轮未提交适配工作树
对照对象：本机 `codex-cli 0.142.4`、`codex app-server --stdio`、本机生成的 app-server JSON Schema
工作树状态：本报告对应的 CLI parity / replay / WebSocket / slash / terminal / MCP 适配改动仍在本地待提交，提交前应重新运行第 9 节验证命令。

## 0. 结论先行

当前项目的 Codex 路线是正确的：它没有把终端 TUI 生硬嵌进浏览器，而是通过 `codex app-server --stdio` 接入 Codex 后端，再把 app-server 的 thread / turn / item / request 事件转换为浏览器可渲染的结构化会话。这条路线天然适合远程、手机、多客户端旁观、通知、登录隔离和后台会话恢复。

但它还不是完整的 Codex CLI 替代品。当前状态可以概括为：

- Remote usable Codex agent session: about **78-82% usable**; core chat, streaming text, reasoning, tool cards, approvals, Plan, replay, history recovery, and image input have working paths.
- Full Codex CLI TUI replacement: about **60-65%**; remaining gaps are mainly profile/add-dir/config depth, full command palette, richer lifecycle UI, account refresh, plugin/skills, and deeper terminal/MCP validation.
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
| Plugin/skills | plugin/list/read/install、skills/list/read | 未接入 | 后续能力 |
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
- This does not replace manual browser/mobile visual QA, but it turns the core multi-access invariant into a repeatable protocol-level smoke test that can be run before each checkpoint.


## 13. 2026-07-17 account recovery and hardened profile checkpoint

- Improved the known unsupported Codex account/security requests: `account/chatgptAuthTokens/refresh` and `attestation/generate` now produce explicit recovery notices with CLI steps instead of showing only a generic unsupported error.
- These notices intentionally pass safe recovery metadata to the UI instead of raw request params, so token material is not exposed in the browser replay/detail panel.
- Added README/config guidance for hardened deployments: HTTPS-only cookies, workspace-root restrictions, per-user Codex/Claude homes, and web approval gates instead of auto-approve.
- The adapter still does not fake success for token refresh or attestation; full Web-native account refresh remains a later low-priority account integration task.
