# Codex Web vs Codex CLI 差距分析与适配计划

更新时间：2026-07-17
项目：`E:\tools\codex-web`
当前基线：`main` / `ad8f4bb`（截至 2026-07-17 stale-open browser catch-up checkpoint）
Codex CLI：`codex-cli 0.142.4`
协议快照：`docs/app-server-protocol-matrix.md` 基于本机 app-server schema，记录 68 个 server notifications、10 个 server requests、87 个 client requests。当前标注为：server notifications supported=31/degraded=8/generic_visible=29；server requests supported=5/degraded=3/generic_visible=2；client requests supported=33/degraded=2/not_integrated=52。

## 0. 本轮复核摘要

- 本轮基于已推送的 `ad8f4bb` 重新校准：`codex --version` 仍为 `codex-cli 0.142.4`，协议矩阵重生成后无代码差异。
- 结论没有变：Web 路线应继续以 `codex app-server --stdio` 为事实源，不回退到 ttyd/TUI iframe；当前适合做远程、多端、移动端可用的 Codex agent 会话，但还不是完整 CLI 替代品。
- 当前最核心的适配目标是：多访问源同步不丢事件、不重复、不闪烁；用户能在 Web 中看清当前 Codex 配置、账号状态、工具执行结果和生命周期动作；安全边界在隧道/共享部署下可审计。
- 下一步不应盲目补控件，而应按“同步稳定与安全兜底 -> CLI 高频可见性/discovery -> 工具/历史/lifecycle 产品化 -> 非会话 CLI 能力单独建模 -> 继续拆热点代码”的顺序推进。

## 1. 总体判断

当前项目已经从“把 Codex CLI 终端塞进网页”转成了“通过 `codex app-server --stdio` 驱动结构化 Web 会话”的路线。这个方向比 ttyd/TUI iframe 更适合多端旁观、移动端、登录隔离、结构化工具卡、通知、replay 和历史恢复。

但它仍不能被当成完整 Codex CLI 替代品。更准确的定位是：高频交互式 agent 会话已经可用，CLI 的完整配置层、账号/插件/skills/doctor/update/exec/review/apply/cloud 等长尾能力仍未产品化，且 Web 多端同步需要继续用真实浏览器和手机场景守住体验。

| 维度 | 当前估算 | 依据 |
| --- | ---: | --- |
| 远程可用 Codex agent 会话 | 88-90% | 对话、流式、Plan、审批/ask/form、历史恢复、图片、`@` 文件、MCP、terminalInteraction、双端 smoke 已有真实路径。 |
| Codex CLI TUI 高频替代 | 72-78% | 高频会话能力覆盖较好；profile/config layer、插件/skills、账号闭环、非交互命令仍明显缺失。 |
| 多访问源同步与重连体验 | 82-86% | `seq/event_id`、`after=<lastSeq>`、去重、state snapshot、open-WS catch-up、headless 双页 smoke 已完成；手机/窄屏/长会话手工记录仍缺。 |
| app-server 协议高价值覆盖 | 66-72% | 会话核心 request/notification 覆盖较好；完整 schema 数量上仍有大量 account/config/plugin/windows sandbox/remote-control 能力未集成；MCP status/resource 浏览已有第一刀。 |
| 代码可维护性 | 75-77% | manager/common/native/frontend 已多轮拆分；工具卡、结果卡、pending 卡、terminalInteraction 卡、text/thinking、tool helper、sidebar renderers 和 Codex broadcast/push helper + thread history action facade 已拆出；`CodexSession`、web 入口和协议路由仍是复杂热点。 |
| 共享/公网暴露硬化 | 65-70% | 多用户、workspace root、Origin/Referer、内部 gate auth、hardened verifier 已有；默认配置仍偏本地兼容，public profile 需要继续收紧和验收。 |

## 2. 当前 Codex 会话链路

```text
Browser / Android WebView
  -> web.py
     - 登录、静态资源、Origin/Referer 检查、restart/stop、HTTP/WS 代理
  -> manager.py
     - manager HTTP/WS shell、鉴权、会话所有权检查、路由分发
  -> manager_sessions.py / manager_user_api.py / manager_internal_api.py
     - launch/resume/send/slash/terminal/history/gate/control API
  -> codex_native.py
     - CodexSession：会话状态、turn 生命周期、配置/slash、输入、通知、replay、持久化和 push 协调
  -> codex_client.py
     - codex app-server --stdio 子进程、JSON-RPC、notification/request 路由
  -> codex_config.py / codex_input.py / codex_slash.py / codex_requests.py / codex_replay.py / codex_replay_facade.py / codex_notifications.py / codex_session_events.py / codex_pending.py / codex_state.py / codex_terminal.py / codex_turn.py
     - 配置归一化、输入/图片/文件提及、slash/lifecycle/manual MCP、server request、replay/timeline facade、notification 转换、pending 状态、state 持久化/恢复、turn 生命周期、terminalInteraction 映射
  -> assets/*.js + index.html
     - 消息渲染、工具卡、结果卡、pending/Plan 卡、ask/form 表单、socket/replay、sidebar/history、launch modal
```

已形成优势：

- 不再依赖终端 scraping；Web 使用 app-server 协议和结构化事件。
- 多用户路径已有：web login、per-user state/workspace/Codex home、session ownership、内部 gate auth。
- Codex replay 已有稳定 `seq/event_id`、`after=<lastSeq>`、前端 live/replay 统一去重、state snapshot 收敛、open-WS catch-up。
- Codex 启动/turn 配置覆盖 model、approval、sandbox、web search、reasoning effort/summary、service tier、workspace-write extra writable roots。
- Slash 和 UI 覆盖 `/model`、`/compact`、`/approval`、`/sandbox`、`/search`、`/reasoning`、`/summary`、`/service-tier`、`/add-dir`、`/rename`、`/archive`、`/unarchive`、`/fork`、`/rollback`、`/goal`、`/steer`、`/mcp-status`、`/mcp-resources`、`/mcp-resource`、`/mcp-tool`、`/skills`、`/plugins`、`/account-status`、`/exec`、`/exec-stream`。
- `@` 文件提及走 app-server `fuzzyFileSearch`；图片输入发送为 `localImage`；terminalInteraction 走 `command/exec/write|resize|terminate`。
- 动态 MCP 只通过 `[codex_dynamic_tools]` allowlist 透传，未映射工具显式失败，不伪造成功。

## 3. 与 Codex CLI 的主要差距

### 3.1 启动配置、profile 与 config layer

已覆盖：

- `--model`、`--sandbox`、`--ask-for-approval`、`--search`、`--add-dir` 的高频等价项。
- reasoning effort、reasoning summary、service tier 的 turn/thread 参数。
- launch modal 从 app-server 读取 `model/list`、`permissionProfile/list`、`config/read`，失败时降级显示错误。

仍缺：

- `--profile` 没有安全的一键等价 UI；Web 还没有展示“当前配置来自哪个 profile/layer”的解释。
- `-c key=value`、`--enable/--disable`、`--strict-config` 没有通用映射；不能做看似可写但 app-server 不消费的假控件。
- `--oss`、`--local-provider`、remote app-server (`--remote`) 没有产品化入口。
- Web 的配置面板还缺“只读诊断优先、写入严格按 schema 放开”的分层策略。

适配原则：先做只读 profile/config/account status 面板；只有当 schema 字段明确、后端确实消费、测试能证明生效时，再开放写入。

### 3.2 输入体验、slash 命令与命令发现

已覆盖：

- 高频 slash 命令和 sidebar/history 的部分同等入口。
- `@` 文件搜索、图片粘贴/选择、Plan/pending ask/form 卡。
- 多端看到后端确认后的状态，而不是纯前端假状态。

仍缺：

- Slash palette 缺完整 discovery、参数提示、历史参数复用、错误纠正和移动端键盘优化。
- `@` 文件提及仍是第一版，长列表、同名文件 disambiguation、移动端选择体验需要打磨。
- 图片输入缺上传清理策略、错误细节、缩略图一致性和大图限制策略。

### 3.3 工具、diff、MCP 与 terminalInteraction

已覆盖：

- command/file/MCP/dynamic/webSearch 等 item 可见；diff-like 结果有 unified diff card；JSON-shaped result 有结构化 card。
- sleep/contextCompaction/imageGeneration/imageView 有专用 compact card。
- MCP 手动调用、status/resource 浏览、plugin/skills 只读 inventory、account status 只读卡片和 dynamic allowlist passthrough 有真实或 helper 级验证路径。
- terminalInteraction 有 Web stdin/resize/terminate 路径、adapter smoke，standalone `command/exec` 已有 buffered/stream stdin/terminate 真实 app-server smoke；浏览器侧已有显式 `/exec <command>` buffered workflow 和 `/exec-stream <command>` streaming/stdin/terminate workflow 第一刀，并已进入双页 browser smoke。
- `mcpServer/startupStatus/updated` 和 `mcpServer/oauthLogin/completed` 已变成可见 notice；`/mcp-status [full|tools]` 和 `/mcp-resources <server>` 可用 `mcpServerStatus/list` 浏览服务器、auth、tools、resources 和 templates，并同步成 replayable 专用 MCP result card，资源行可直接触发 `/mcp-resource`。

仍缺：

- command execution card 已有 cwd、duration、stdout/stderr 分区、exit code 和长输出折叠；仍缺失败聚合摘要、复制/重跑入口、流式状态细节和移动端长输出体验。
- 多文件/大 diff 已有文件 chip、patch summary、按文件分段和大 diff 折叠；仍缺文件级锚点导航、搜索/定位、与真实工作区文件打开动作的联动。
- terminalInteraction 与 `/exec-stream` 已有真实 app-server 和浏览器双页路径；仍缺真实 Codex 长时间命令、多轮 stdin 后台恢复、移动端输入的完整 E2E。
- MCP 已有 status/resource browser、结构化结果卡和资源读取按钮第一刀；仍缺真正的 OAuth/login 闭环、分页/搜索和 richer MCP admin 面板。

### 3.4 会话生命周期与历史

已覆盖：

- `thread/list/read/resume/delete` 基础历史能力。
- active/archived filter、Archive/Unarchive、Rename、Goal、Fork、Rollback、Compact、Steer 的 slash 或 UI 入口。
- History loading 使用 `live_codex=1`，不再默认只看本地陈旧缓存。

仍缺：

- CLI resume picker 的完整语义、搜索/过滤/批量管理、metadata 展示仍不足。
- Fork/Rollback/Compact 的结果链路还可更产品化：自动打开 fork、展示 base thread、展示 compact summary。
- Running sessions 与 history 并发刷新还需要更多 fixture 验证 sidebar race。

### 3.5 重连、多端同步与视觉稳定

已覆盖：

- 每 socket 写锁，降低 ping/broadcast frame 交错导致 1006 的概率。
- WS URL 和 `/api/nreplay` 都支持 `after=<lastSeq>`。
- 前端对 live/replay 使用统一去重 key，不清 DOM 恢复状态。
- `state_snapshot` 能收敛 stale thinking/turn UI。
- open-WS catch-up polling 能在 socket 显示 open 但漏事件时静默补增量；Codex broadcast 会刷新 session activity，前端看到 `/api/sessions` 的 `last_output_ts` 增长后也会触发 catch-up，所以 idle 状态下的 rename/notice 类事件不必等 socket close 才恢复。
- `tools/codex_ws_smoke.py --clients 2 --launch-temp` 和 `tools/codex_browser_smoke.py` 已覆盖协议层、headless 双页层与默认窄屏/mobile mirror；browser smoke 会标记既有 DOM 节点，分别验证断线 catch-up 和强制 `nativeConnect(..., {force:true})` 重连后未被清空重建，同时检查窄屏 composer/input/submit 和移动抽屉布局仍可用。

仍缺：

- headless 窄屏/mobile mirror 已进入 browser smoke；真实手机浏览器、长会话、后台/前台切换的人工 visual smoke 记录还需要补。
- WS 1006 根因不能假定已根治；当前策略是“降低概率 + 即使断线也不全量刷新/不重复”。
- replay snapshot 与 timeline merge 的极端顺序仍需要 trace fixture。

### 3.6 账号、认证、插件、skills 与非会话 CLI 能力

已覆盖：

- Web 自身有 login/logout、多用户隔离、per-user home/workspace、Origin/Referer 检查、hardened verifier。
- `account/chatgptAuthTokens/refresh`、`attestation/generate` 不再假成功，而是给可见恢复步骤且不泄 token。
- `plugin/installed`、`plugin/list`、`skills/list` 已通过 `/plugins`、`/plugins available`、`/skills` 提供只读 inventory，并以结构化 replay 卡片同步到多端。
- `account/read`、`account/rateLimits/read`、`account/usage/read` 已通过 `/account-status` 提供脱敏只读状态；usage/rate-limit 的 auth-required 情况会显示 warning 而不是伪造成功。

仍缺：

- Codex CLI 的 `login/logout`、token refresh、attestation 仍不是 Web 原生闭环；usage/rate detail 已有只读入口，但 auth 续期、重试和错误解释仍不完整。
- `doctor`、`update`、`features`、plugin/skills 写入安装、`mcp` 管理、`sandbox`、`exec`、`review`、`apply`、`cloud` 等非会话 CLI 能力仍未产品化。
- 这些能力不应直接塞进 CodexSession；需要单独的 admin/diagnostic 模块或明确不做。

## 4. 当前代码问题清单

### P0：继续守住的稳定性/安全风险

1. 真实手机/长会话视觉证据不足。
   协议层和 headless smoke 已经强很多，但用户感知层的闪烁、scroll、pending card、移动端输入、后台恢复还缺固定记录。
2. WS 1006 只能说已缓解，不能说已根治。
   需要继续保留 close code、retry delay、lastSeq、pending 状态、catch-up 结果等诊断，并用重连不清 DOM 兜底。
3. 默认配置仍偏本地兼容，不是 hardened 默认。
   `config.example` 仍保留 `host=0.0.0.0`、`auto_approve=1`、`allow_unconfigured_paths=1`、`primary_user_uses_default_homes=1`、`csrf_allow_missing_origin=1` 这类便捷默认；公网/隧道部署必须通过 verifier 或单独 hardened profile 明确收紧。
4. dynamic MCP passthrough 必须继续 allowlist-first。
   为了像 CLI 而默认任意透传，会扩大工具攻击面；未映射工具应继续可见失败。
5. state-changing API 分级还可以更细。
   当前已有 browser POST/WS Origin 检查、manager/internal route 分离和测试，但 launch/send/terminal/history/action/upload 等写路径仍值得按风险等级建表覆盖。

### P1：CLI parity 用户体验缺口

6. profile/config/account status 可见性仍需继续增强。
   启动弹窗已有第一版只读 `config/read`/account/diagnostics 状态行，能展示 model/approval/sandbox/search/reasoning/service tier、model/profile 数量、Codex home 和 workspace roots；后续还需要完整 layer/profile/account 独立状态页。
7. terminalInteraction 还缺真实复杂命令场景。
   adapter 层、standalone command/exec 和 browser `/exec-stream` smoke 已有，但还需要用真实 Codex coding turn 验证长命令、多次 stdin、移动端输入和异常断开。
8. tool card 仍需继续接近 CLI 的摘要能力。
   command/diff/MCP/account/plugin/skills 卡片已有第一刀；后续重点是失败摘要、重跑/复制动作、文件级跳转、长输出 mobile UX 和真实资源读取闭环。
9. history/lifecycle 的结果展示仍偏“能用”。
   Fork/Rollback/Compact/Goal 应显示更明确的结果对象和下一步动作。
10. slash/command discovery 仍粗糙。
    当前覆盖面不错，但参数提示、纠错、帮助、移动端操作还不够。

### P2：结构和维护性热点

11. `codex_native.py` 仍是最大后端热点。
    当前约 717 行，虽然已拆出 client/config/events/forms/history/replay facade/requests/pending/terminal/turn/notification/state/input/slash/text/thread_history/broadcast/command_exec/mcp/account/inventory，但 `CodexSession` 仍保留大量兼容 wrapper、adapter wiring 和 session core 协调。
12. replay/timeline 的主链路已收进 facade，但 session 仍保留较多兼容 wrapper。
    下一步应避免新增逻辑回流到 wrapper，可继续把 frontend renderer 或 push/notification 边界拆出，而不是继续扩大 `CodexSession`。
13. `common.py` 仍是 818 行兼容 facade。
    已拆出多个 `common_*` helper，但 import-time config、常量 re-export 和跨域职责仍集中，未来服务化或测试隔离会受影响。
14. `web.py` 仍混合 auth、static、proxy、restart/watchdog 和 Origin 检查。
    当前约 502 行可接受，但安全 hardening 继续增加时，建议拆 `web_auth.py`、`web_proxy.py`、`web_lifecycle.py`。
15. `manager_user_api.py` 的 POST 分发继续增长。
    当前按 path 大 if/elif 维护；后续状态变更 API 分级、权限、schema 校验增加时，需要 route table 或小 handler 分组。
16. 前端仍有全局状态和大 renderer。
    `assets/native_events.js` 的 tool-use card 已拆到 `assets/native_tool_cards.js`，tool result/diff/json 渲染已拆到 `assets/native_tool_results.js`，pending approval/Plan/ask/form 事件处理已拆到 `assets/native_pending_cards.js`，terminalInteraction 卡已拆到 `assets/native_terminal_cards.js`，assistant text/thinking/Plan text 渲染已拆到 `assets/native_text_cards.js`，tool body/group helper 已拆到 `assets/native_tool_helpers.js`，sidebar Codex lifecycle actions 已拆到 `assets/app_sidebar_codex_actions.js`，sidebar row/list rendering 已拆到 `assets/app_sidebar_rows.js`；但 replay/socket 协调、push/notification 边界和 backend session core 仍是主要复杂点；新增 card/action/list UI 应继续进入专门 renderer，而不是堆回事件分发函数。
17. `codex_client.py` 的 single-busy fallback 需要 trace fixture。
    对缺 thread/turn/item id 的通知，fallback 很实用，但多会话并发下必须用真实协议 trace 证明哪些方法允许 fallback，哪些应 buffer/丢弃/报 visible warning。

### P2 结构热度计（2026-07-17）

| 文件/区域 | 当前规模 | 问题判断 | 下一步拆分方式 |
| --- | ---: | --- | --- |
| `codex_native.py` | 717 行 | 仍是 Codex session core/wrapper/wiring 聚合点 | 只从仍含实质逻辑的 wrapper 下手，继续拆 backend session core seam，不做行为重写。 |
| `codex_slash.py` / `codex_requests.py` / `codex_command_exec.py` | 489 / 462 / 392 行 | 已承接高价值 CLI parity，但会继续变重 | 新增 CLI 能力优先进独立 adapter，并补静态/helper smoke，避免回流 `CodexSession`。 |
| `codex_client.py` | 403 行 | app-server JSON-RPC、路由、unrouted buffer、command exec output 混在一个 client | 先补真实 trace fixture，再决定哪些 fallback 允许保留，哪些需要 visible warning。 |
| `manager_user_api.py` | 434 行 | 浏览器 API 仍是 path 分发大函数 | route table + 小 handler 分组，便于写入 API 风险分级和 schema 校验。 |
| `web.py` | 502 行 | 登录、静态、代理、生命周期控制和 Origin 检查同文件 | hardening 继续增加前拆 `web_auth.py`、`web_proxy.py`、`web_lifecycle.py`。 |
| `common.py` | 818 行 | 兼容 facade 仍有 import-time config 和大量 re-export | 新代码直接依赖 `common_*` helper，逐步减少从 `common.py` 取跨域职责。 |
| `assets/native_tool_results.js` | 403 行 | 结果卡持续承接 command/diff/MCP/account/plugin 复杂度 | 继续按 result type 拆小 renderer，保留统一入口和 replay event contract。 |
| `assets/native_actions.js` / `assets/native_replay.js` | 307 / 229 行 | 多端动作、catch-up、delegated action 是体验风险点 | 新 action 必须有 replay/second-client/static contract，避免单端假状态。 |

## 5. 适配路线图

### Phase 0：固定当前基线和验收口径

目标：后续拆分前，先把“当前已达成的 CLI parity”和“仍缺的能力”固定成可验证基线。

任务：

- 每次 Codex CLI 升级后运行 `python tools\app_server_protocol_matrix.py --out docs\app-server-protocol-matrix.md`。
- 保留完整验证 bundle：`py_compile`、所有 `tests/check_*.py`、全部 JS `node --check`、`git diff --check`。
- 行为 smoke 分层：WS 双客户端、MCP、browser 双页 + 窄屏 mirror、terminalInteraction；真实手机走 visual checklist。

验收：文档、矩阵、测试、smoke 口径一致；不再凭印象判断 CLI parity。

### Phase 1：Codex replay facade 拆分（下一步优先）

目标：降低 `CodexSession` 最危险的复杂度，不改变行为。

建议切片：

1. 新增 `codex_replay_facade.py`，先只封装 timeline/event identity/merge/events_after/replay_payload/pending snapshot 的调用，`CodexSession` 保留原 public wrapper。（第一刀已落地：event identity、timeline recording/merge、history replay adoption、events_after、replay_payload 已走 facade。）
2. 第二刀把 `poll_events`、`_decorate_for_broadcast()`、`_persist_if_due()` 的协作收进 facade，避免一口气移动 WS loop。（第二刀已落地：broadcast preparation、poll-event trimming、important-event persistence 和节流持久化已走 facade。）
3. 第三刀再评估是否移动 `add_client()` 初始 replay + state snapshot + pending events + keepalive。（第三刀已落地：`add_client()` 委托 facade，facade helper 测试覆盖初始 replay、pending card、client discard 和 close。）

验收：`seq/event_id`、`after=<lastSeq>`、pending snapshot、state snapshot、poll events、持久化节流、双客户端 smoke 全部不变。

### Phase 2：CodexSession 主类职责继续收口

目标：让新增 CLI parity 不再直接塞进大类。

任务：

- 抽 `CodexTurnRunner`：`_ensure_thread`、`_run_turn`、`_turn_params`、collaboration mode、compaction busy 状态。（第一刀已落地：thread/turn params、collaboration sync、thread response adoption、resume、turn start/error handling 已走 `codex_turn.py`。）
- 抽 `CodexNotificationAdapter`：`handle_notification`、item started/completed、plan/diff/usage/thread settings。（第一刀已落地：`CodexSession` notification/notice wrapper 已委托到 `codex_notifications.py`；第二刀已落地：notification helper 实现已迁入 `codex_notifications.py`，`codex_session_events.py` 仅保留兼容导入。）
- 抽 `CodexSessionState`：thread/model/cfg/service tier/current turn timing/persist/recover 数据对象。（第一刀已落地：`codex_state.py` 负责 state path、payload、JSON persist、startup recover 和本地 register；后续再评估 current-turn timing、upload/image state 是否继续迁入。）
- 抽 `CodexInputAdapter`：cwd-bounded file mention、`fuzzyFileSearch` 结果整形、image upload、`localImage` turn input、用户消息图片 replay block。（第一刀已落地：`codex_input.py` 负责上述输入链路，`CodexSession` 保留兼容 wrapper。）
- 抽 `CodexSlashAdapter`：slash dispatch、session config tuning、thread lifecycle、goal、steer、manual MCP status/resource/tool 调用。（第一刀已落地：`codex_slash.py` 负责上述命令链路，`CodexSession` 保留兼容 wrapper；MCP status/resource browser 由 `codex_mcp_status.py` 承接。）
- 收口 `CodexRequestAdapter`：tool event/result、tool output append、approval/ask/form wait、dynamic MCP passthrough/reject、unsupported account/attestation recovery、approve/answer。（第一刀已落地：`codex_requests.py` 负责上述 server request 链路，`CodexSession` 保留兼容 wrapper。）
- 前端 renderer 继续收口：tool-use、tool-result、tool helpers、pending cards、terminalInteraction cards、text/thinking helpers、sidebar Codex action helpers、sidebar rows 已拆出；后端 broadcast/push helper + thread history action facade 已拆出；下一刀优先评估 notification adapter cleanup 或 backend session core seams。
- 保持兼容 wrapper，避免一次修改所有调用点。

验收：新增一种 notification、server request 或前端 card 时，不需要同时理解持久化、WebSocket replay、事件分发和 UI markup。

### Phase 3：CLI 高频产品缺口

目标：让熟悉 CLI 的用户知道 Web 当前到底在用什么配置，并能找到常用入口。

任务：

- 做只读 profile/config/account status 面板：展示 `config/read`、model、approval、sandbox、web search、reasoning、service tier、writable roots、Codex home、workspace roots。（第一刀已落地：launch modal 显示只读 `config/read` 高频字段、model/profile 数量、脱敏 account summary 和 diagnostics；`/account-status` 提供只读 account/usage/rate-limit 卡片。）
- 增强 slash palette：命令说明、参数模板、错误反馈、历史参数复用。
- 优化 lifecycle 结果：fork 后一键打开，rollback 显示保留 turn，compact 显示 summary，goal 显示 status/budget/usage。

验收：不存在“UI 看起来设置成功，但 app-server 没消费”的假状态。

### Phase 4：工具/终端体验接近 CLI

目标：常见 coding turn 不再需要看 raw JSON。

任务：

- command card 分区显示 command、cwd、status、duration、exit code、stdout/stderr、折叠大输出。（第一刀已落地：exit/duration/output lines、stdout/stderr 分区、大成功输出折叠；后续补失败摘要、复制/重跑、长输出移动端体验。）
- file change/diff card 增加多文件导航、patch 摘要和大 diff 折叠。（已落地：文件 chip 列表、`+N more` 摘要、大 diff 默认折叠、patch summary 和按文件分段折叠；后续补文件级锚点、搜索/定位和打开工作区文件联动。）
- terminalInteraction 加真实 app-server command exec E2E，覆盖长时间、多 stdin、resize、terminate、断线恢复。（已落地：终端输入卡片修复、resize UI、adapter smoke、standalone `command/exec` buffered/stream stdin/terminate 真实 app-server smoke、显式 `/exec <command>` buffered 浏览器 workflow、`/exec-stream <command>` streaming/stdin/terminate 浏览器 workflow，以及双页 browser smoke；后续补真实 Codex coding turn 和手机后台恢复。）
- MCP 增加 startup status、resource browser、OAuth/login 降级提示。（第一刀已落地：startup/OAuth notification 可见，`/mcp-status` 与 `/mcp-resources` 调用 `mcpServerStatus/list` 展示 auth/tools/resources/templates，并产生多端 replayable 专用 result card；资源行可直接调用 `/mcp-resource`，真正 OAuth/login 闭环、分页/搜索仍待做。）

验收：用户能从 Web 卡片判断工具做了什么、成功/失败原因和下一步，而不是只能读原始事件。

### Phase 5：共享/公网暴露 hardening

目标：让隧道、局域网、多用户部署有明确安全边界。

任务：

- 增加 state-changing API 风险矩阵和测试：launch/send/slash/terminal/history/upload/restart/stop/gate/control。（第一刀已落地：`docs/state-changing-api-risk-matrix.md` 记录 browser/manager/internal POST 风险、职责和 required guards，`tools/check_state_changing_api_risks.py` 静态校验新增路由必须补分类。）
- 将 hardened profile 从“文档建议 + verifier”推进到可选择配置模板或启动检查。
- 审计 upload/image、workspace roots、per-user Codex/Claude home、MCP config 写入边界。（upload/image 第一刀已落地：`prepare_image_inputs()` 现在校验数量、大小、base64、MIME allowlist 和 magic-byte 签名一致性。）
- 强化 `/api/nterminal` command-I/O 边界。（第一刀已落地：stdin 写入有大小上限，resize 有明确范围，且仍保留 session/process ownership 与 action allowlist。）
- 对 manager/internal endpoint 保持“必须内部 token + 预期来源 + 测试覆盖”。（web lifecycle control 第一刀已落地：测试证明错误 Origin 在 auth/restart/stop side effect 前被拒绝，同源 restart-manager 仍可进入受控路径。）

验收：hardened profile 下跨站 POST、缺 Origin、越界 workspace/upload、未授权 internal control 都被拒绝且有测试。

### Phase 6：非会话 CLI 能力单独决策

目标：避免把 `exec/review/apply/plugin/skills/doctor/update/cloud/features` 盲目塞进会话代码。

建议：

- `doctor/features/account/plugin/skills/mcp`：作为 admin/diagnostic 页面，只读优先。（第一刀已落地：`/skills` 与 `/plugins [installed|available]` 读取 app-server inventory，不做安装/写入。）
- `exec/review/apply/sandbox/cloud`：独立 workflow，不复用 CodexSession 主循环，除非明确需要 Web 产品化。
- `update`：默认不做自动更新；最多提供只读版本和文档提示。

## 6. 推荐推进顺序

1. 继续 Phase 2 剩余结构收口：pending/form renderer、terminalInteraction card、text/thinking renderer、tool helpers、sidebar renderers、Codex broadcast/push helper、thread history action facade、command exec、MCP/account/inventory helper 已完成；下一步优先找 `CodexSession` wrapper 中仍有实质逻辑的 seam，保持行为不变地拆到 backend session core helper。
2. 并行守住 Phase 0/5 验收：每一刀都跑完整轻量验证；涉及 replay/socket/terminal/MCP 的改动再跑 WS 双客户端、browser 双页、terminalInteraction/MCP smoke。
3. 补真实手机/长会话 visual checklist：重点看后台/前台切换、滚动位置、pending card、长输出、窄屏输入和 WebSocket 1006/catch-up 日志。
4. 推进 Phase 3：把 launch modal 的只读诊断升级成独立 profile/config/account status 面板，并增强 slash palette 的参数说明和错误纠正。
5. 推进 Phase 4：围绕失败摘要、文件级 diff 导航、MCP OAuth/resource 搜索、真实 Codex 长命令 stdin/reconnect 做产品化补齐。
6. 最后收紧 Phase 5：hardened profile 模板/启动检查、state-changing API runtime guard、workspace/upload/MCP 写边界审计。

## 7. 不建议做的事

- 不要回到 ttyd/终端 iframe 路线；这会牺牲多端 replay、结构化卡片和移动端体验。
- 不要为 unsupported account/token/attestation 返回假成功；宁愿明确提示回 CLI 恢复。
- 不要默认把所有 dynamic tool 透传给 MCP；必须保持 allowlist。
- 不要在没有 schema 字段和测试证明前做 profile/config 写入 UI。
- 不要把 `exec/review/apply/plugin/skills/doctor/cloud` 直接塞进 `CodexSession`；这些应该单独决策和建模。
- 不要先做大视觉重设计；当前更重要的是稳定、多端、工具真实性、安全边界和结构拆分。

## 8. 验证基线

快速验证：

```powershell
python -m py_compile app.py web.py common.py manager.py native.py codex_native.py codex_broadcast.py codex_account.py codex_command_exec.py codex_config.py codex_input.py codex_inventory.py codex_notifications.py codex_mcp_status.py codex_pending.py codex_replay_facade.py codex_slash.py codex_state.py codex_terminal.py codex_turn.py gate_mcp.py codex_client.py codex_events.py codex_forms.py codex_history.py codex_replay.py codex_requests.py codex_routing.py codex_session_events.py codex_text.py codex_thread_history.py common_auth.py common_binaries.py common_browse.py common_ccswitch.py common_history.py common_http.py common_notify.py common_process.py common_registry.py common_users.py common_ws.py manager_internal_api.py manager_sessions.py manager_user_api.py native_cli.py native_config.py native_gate.py native_replay.py tools\app_server_protocol_matrix.py tools\codex_ws_smoke.py tools\codex_mcp_smoke.py tools\codex_visual_smoke_report.py tools\codex_browser_smoke.py tools\codex_terminal_smoke.py tools\codex_command_exec_smoke.py tools\check_hardened_profile.py tools\check_state_changing_api_risks.py
Get-ChildItem assets -Recurse -Filter *.js | Sort-Object FullName | ForEach-Object { node --check $_.FullName }
Get-ChildItem tests\check_*.py | Sort-Object Name | ForEach-Object { python $_.FullName }
git diff --check
```

行为 smoke：

```powershell
python tools\codex_ws_smoke.py --clients 2 --seconds 2 --launch-temp --cwd .
python tools\codex_mcp_smoke.py --cwd .
python tools\codex_browser_smoke.py --cwd .
python tools\codex_terminal_smoke.py --cwd .
```

`tools\codex_browser_smoke.py` now also validates streamed `/exec-stream`
output plus stdin across the primary and narrow mirror browser tabs before the
disconnect/reconnect DOM-preservation checks.
It also runs `/mcp-status tools` and requires the structured MCP status result
card to appear in both tabs, so MCP inventory visibility is part of the
multi-access browser gate instead of only a helper-level check. When that card
has a `Browse` action, the smoke follows the exposed command and also requires
the resulting MCP resources card to synchronize across both tabs.
The MCP status/resource payload is kept as valid JSON for specialized browser
cards by stripping oversized tool schemas and shortening long descriptions
before replay.
The same browser smoke now simulates an open-but-stale WebSocket by silencing
the mirror tab's live message handler, sending a backend-confirmed rename, and
forcing foreground catch-up; the missed event must appear without replacing the
previously marked DOM node.
That stale-open scenario now goes through normal `/api/sessions` polling and
`rememberSessions()` activity detection instead of directly invoking
`nativeCatchupPoll()`, so idle lifecycle/notice events are covered by the same
automatic path a visible browser uses.

Codex CLI 升级后：

```powershell
python tools\app_server_protocol_matrix.py --out docs\app-server-protocol-matrix.md
```

## 9. 2026-07-17 /exec command workflow checkpoint

- `/exec <shell command>` now provides a first browser-facing buffered `command/exec` workflow for explicit user/admin commands inside the current Codex session cwd.
- Results are replayable across clients as Bash/PowerShell tool cards with stdout/stderr split, exit code, duration, and clipped large output.
- `/exec-stream <shell command>` now registers a process-scoped output handler, streams stdout/stderr into the same replayable result card, and shows the existing browser stdin/close/terminate controls for that process.
- This intentionally does not open a broad unauthenticated exec endpoint; it stays behind the existing session slash path, workspace ownership, Origin/Referer checks, and session sandbox/yolo settings.
- Remaining gap: this is still a session-scoped explicit workflow, not a broad admin terminal; long-running/mobile reconnect evidence should keep being covered by browser and terminal smokes.
