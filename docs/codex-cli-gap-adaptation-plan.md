# Codex Web vs Codex CLI 差距分析与适配计划

更新时间：2026-07-17
项目：`E:\tools\codex-web`
当前基线：`main` / `a02753a Extract Codex pending adapter`
Codex CLI：`codex-cli 0.142.4`
协议快照：`docs/app-server-protocol-matrix.md` 基于本机 app-server schema，记录 68 个 server notifications、10 个 server requests、87 个 client requests。当前标注为：server notifications supported=30/degraded=7/generic_visible=31；server requests supported=5/degraded=3/generic_visible=2；client requests supported=27/not_integrated=60。

## 1. 总体判断

当前项目已经从“把 Codex CLI 终端塞进网页”转成了“通过 `codex app-server --stdio` 驱动结构化 Web 会话”的路线。这个方向比 ttyd/TUI iframe 更适合多端旁观、移动端、登录隔离、结构化工具卡、通知、replay 和历史恢复。

但它仍不能被当成完整 Codex CLI 替代品。更准确的定位是：高频交互式 agent 会话已经可用，CLI 的完整配置层、账号/插件/skills/doctor/update/exec/review/apply/cloud 等长尾能力仍未产品化，且 Web 多端同步需要继续用真实浏览器和手机场景守住体验。

| 维度 | 当前估算 | 依据 |
| --- | ---: | --- |
| 远程可用 Codex agent 会话 | 88-90% | 对话、流式、Plan、审批/ask/form、历史恢复、图片、`@` 文件、MCP、terminalInteraction、双端 smoke 已有真实路径。 |
| Codex CLI TUI 高频替代 | 72-78% | 高频会话能力覆盖较好；profile/config layer、插件/skills、账号闭环、非交互命令仍明显缺失。 |
| 多访问源同步与重连体验 | 82-86% | `seq/event_id`、`after=<lastSeq>`、去重、state snapshot、open-WS catch-up、headless 双页 smoke 已完成；手机/窄屏/长会话手工记录仍缺。 |
| app-server 协议高价值覆盖 | 65-70% | 会话核心 request/notification 覆盖较好；完整 schema 数量上仍有大量 account/config/plugin/windows sandbox/remote-control 能力未集成。 |
| 代码可维护性 | 70% | manager/common/native/frontend 已多轮拆分；`CodexSession`、前端事件渲染、web 入口和协议路由仍是复杂热点。 |
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
  -> codex_config.py / codex_requests.py / codex_replay.py / codex_session_events.py / codex_pending.py / codex_terminal.py
     - 配置归一化、server request、replay helper、notification 转换、pending 状态、terminalInteraction 映射
  -> assets/*.js + index.html
     - 消息渲染、工具卡、审批/ask/form/Plan 卡、socket/replay、sidebar/history、launch modal
```

已形成优势：

- 不再依赖终端 scraping；Web 使用 app-server 协议和结构化事件。
- 多用户路径已有：web login、per-user state/workspace/Codex home、session ownership、内部 gate auth。
- Codex replay 已有稳定 `seq/event_id`、`after=<lastSeq>`、前端 live/replay 统一去重、state snapshot 收敛、open-WS catch-up。
- Codex 启动/turn 配置覆盖 model、approval、sandbox、web search、reasoning effort/summary、service tier、workspace-write extra writable roots。
- Slash 和 UI 覆盖 `/model`、`/compact`、`/approval`、`/sandbox`、`/search`、`/reasoning`、`/summary`、`/service-tier`、`/add-dir`、`/rename`、`/archive`、`/unarchive`、`/fork`、`/rollback`、`/goal`、`/steer`、`/mcp-resource`、`/mcp-tool`。
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
- MCP 手动调用和 dynamic allowlist passthrough 有真实 E2E smoke。
- terminalInteraction 有 Web stdin/resize/terminate 路径和 adapter smoke。

仍缺：

- command execution card 还不如 CLI 清晰：cwd、duration、stdout/stderr 分区、exit code、长输出折叠、失败摘要仍可加强。
- 多文件/大 diff 缺文件级导航、折叠、定位和 patch summary。
- terminalInteraction 仍缺真实 Codex 长时间命令、多轮 stdin、断线恢复、移动端输入的完整 E2E。
- MCP startup status、resource browser、OAuth/login 降级提示仍偏泛化。

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
- open-WS catch-up polling 能在 socket 显示 open 但漏事件时静默补增量。
- `tools/codex_ws_smoke.py --clients 2 --launch-temp` 和 `tools/codex_browser_smoke.py` 已覆盖协议层与 headless 双页层。

仍缺：

- 手机真实浏览器、窄屏、长会话、后台/前台切换的 visual smoke 记录还需要补。
- WS 1006 根因不能假定已根治；当前策略是“降低概率 + 即使断线也不全量刷新/不重复”。
- replay snapshot 与 timeline merge 的极端顺序仍需要 trace fixture。

### 3.6 账号、认证、插件、skills 与非会话 CLI 能力

已覆盖：

- Web 自身有 login/logout、多用户隔离、per-user home/workspace、Origin/Referer 检查、hardened verifier。
- `account/chatgptAuthTokens/refresh`、`attestation/generate` 不再假成功，而是给可见恢复步骤且不泄 token。

仍缺：

- Codex CLI 的 `login/logout`、token refresh、attestation、usage/rate detail 还不是 Web 原生闭环。
- `doctor`、`update`、`features`、`plugin`、`mcp` 管理、`skills`、`sandbox`、`exec`、`review`、`apply`、`cloud` 等非会话 CLI 能力基本未产品化。
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

6. profile/config/account status 可见性不足。
   用户仍难判断 Web session 实际继承了哪些 Codex 配置，哪些 UI 控件只是 Web 层覆盖。
7. terminalInteraction 还缺真实复杂命令场景。
   adapter 层 smoke 已有，但还需要用真实 Codex command exec 验证长命令、多次 stdin、移动端输入和异常断开。
8. tool card 仍需接近 CLI 的摘要能力。
   command/file/webSearch/MCP card 需要更清楚的 status、cwd、duration、stdout/stderr、exit code、文件列表和大输出折叠。
9. history/lifecycle 的结果展示仍偏“能用”。
   Fork/Rollback/Compact/Goal 应显示更明确的结果对象和下一步动作。
10. slash/command discovery 仍粗糙。
    当前覆盖面不错，但参数提示、纠错、帮助、移动端操作还不够。

### P2：结构和维护性热点

11. `codex_native.py` 仍是最大后端热点。
    当前约 1473 行，虽然已拆出 client/config/events/forms/history/replay/requests/pending/terminal/text/thread_history，但 `CodexSession` 仍同时承担 session state、turn runner、slash/config、input/image、app-server notification、server request、replay/broadcast、persistence 和 push。
12. replay 低层 helper 已拆出，但 session 仍直接管理 timeline/poll_events/clients。
    下一刀应抽 `CodexReplayFacade`，把 event identity、timeline merge、poll event、replay payload、add_client 初始 replay 和 persist 触发边界收口。
13. `common.py` 仍是 818 行兼容 facade。
    已拆出多个 `common_*` helper，但 import-time config、常量 re-export 和跨域职责仍集中，未来服务化或测试隔离会受影响。
14. `web.py` 仍混合 auth、static、proxy、restart/watchdog 和 Origin 检查。
    475 行可接受，但安全 hardening 继续增加时，建议拆 `web_auth.py`、`web_proxy.py`、`web_lifecycle.py`。
15. `manager_user_api.py` 的 POST 分发继续增长。
    当前按 path 大 if/elif 维护；后续状态变更 API 分级、权限、schema 校验增加时，需要 route table 或小 handler 分组。
16. 前端仍有全局状态和大 renderer。
    `assets/native_events.js`、`assets/native_stage.js`、`assets/app_sidebar.js` 仍是主要复杂点；新增 tool card 不应继续堆进同一个长函数。
17. `codex_client.py` 的 single-busy fallback 需要 trace fixture。
    对缺 thread/turn/item id 的通知，fallback 很实用，但多会话并发下必须用真实协议 trace 证明哪些方法允许 fallback，哪些应 buffer/丢弃/报 visible warning。

## 5. 适配路线图

### Phase 0：固定当前基线和验收口径

目标：后续拆分前，先把“当前已达成的 CLI parity”和“仍缺的能力”固定成可验证基线。

任务：

- 每次 Codex CLI 升级后运行 `python tools\app_server_protocol_matrix.py --out docs\app-server-protocol-matrix.md`。
- 保留完整验证 bundle：`py_compile`、所有 `tests/check_*.py`、全部 JS `node --check`、`git diff --check`。
- 行为 smoke 分层：WS 双客户端、MCP、browser 双页、terminalInteraction；手机/窄屏走 visual checklist。

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

- 抽 `CodexTurnRunner`：`_ensure_thread`、`_run_turn`、`_turn_params`、collaboration mode、compaction busy 状态。
- 抽 `CodexNotificationAdapter`：`handle_notification`、item started/completed、plan/diff/usage/thread settings。
- 抽 `CodexSessionState`：thread/model/cfg/service tier/current turn timing/persist/recover 数据对象。
- 保持兼容 wrapper，避免一次修改所有调用点。

验收：新增一种 notification 或 server request 时，不需要同时理解持久化、WebSocket replay 和 UI 渲染。

### Phase 3：CLI 高频产品缺口

目标：让熟悉 CLI 的用户知道 Web 当前到底在用什么配置，并能找到常用入口。

任务：

- 做只读 profile/config/account status 面板：展示 `config/read`、model、approval、sandbox、web search、reasoning、service tier、writable roots、Codex home、workspace roots。
- 增强 slash palette：命令说明、参数模板、错误反馈、历史参数复用。
- 优化 lifecycle 结果：fork 后一键打开，rollback 显示保留 turn，compact 显示 summary，goal 显示 status/budget/usage。

验收：不存在“UI 看起来设置成功，但 app-server 没消费”的假状态。

### Phase 4：工具/终端体验接近 CLI

目标：常见 coding turn 不再需要看 raw JSON。

任务：

- command card 分区显示 command、cwd、status、duration、exit code、stdout/stderr、折叠大输出。
- file change/diff card 增加多文件导航、patch 摘要和大 diff 折叠。
- terminalInteraction 加真实 app-server command exec E2E，覆盖长时间、多 stdin、resize、terminate、断线恢复。
- MCP 增加 startup status、resource browser、OAuth/login 降级提示。

验收：用户能从 Web 卡片判断工具做了什么、成功/失败原因和下一步，而不是只能读原始事件。

### Phase 5：共享/公网暴露 hardening

目标：让隧道、局域网、多用户部署有明确安全边界。

任务：

- 增加 state-changing API 风险矩阵和测试：launch/send/slash/terminal/history/upload/restart/stop/gate/control。
- 将 hardened profile 从“文档建议 + verifier”推进到可选择配置模板或启动检查。
- 审计 upload/image、workspace roots、per-user Codex/Claude home、MCP config 写入边界。
- 对 manager/internal endpoint 保持“必须内部 token + 预期来源 + 测试覆盖”。

验收：hardened profile 下跨站 POST、缺 Origin、越界 workspace/upload、未授权 internal control 都被拒绝且有测试。

### Phase 6：非会话 CLI 能力单独决策

目标：避免把 `exec/review/apply/plugin/skills/doctor/update/cloud/features` 盲目塞进会话代码。

建议：

- `doctor/features/account/plugin/skills/mcp`：作为 admin/diagnostic 页面，只读优先。
- `exec/review/apply/sandbox/cloud`：独立 workflow，不复用 CodexSession 主循环，除非明确需要 Web 产品化。
- `update`：默认不做自动更新；最多提供只读版本和文档提示。

## 6. 推荐推进顺序

1. 先做 Phase 1 的 `CodexReplayFacade` 第一刀；这是当前最大复杂热点，也最贴近多端稳定性。
2. 跑完整轻量验证：`py_compile`、所有 helper tests、JS `node --check`、`git diff --check`。
3. 跑行为 smoke：WS 双客户端、browser 双页、terminalInteraction；如时间允许补一次手机 visual checklist。
4. 再做 Phase 3 的只读 profile/config/account status 面板，避免继续盲补 CLI 控件。
5. 然后补 Phase 4 的 command/file card 体验和 terminalInteraction 真实 E2E。
6. 最后收紧 Phase 5 hardened profile 和 state-changing API 分级。

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
python -m py_compile app.py web.py common.py manager.py native.py codex_native.py codex_config.py codex_pending.py codex_replay_facade.py codex_terminal.py gate_mcp.py codex_client.py codex_events.py codex_forms.py codex_history.py codex_replay.py codex_requests.py codex_routing.py codex_session_events.py codex_text.py codex_thread_history.py common_auth.py common_binaries.py common_browse.py common_ccswitch.py common_history.py common_http.py common_notify.py common_process.py common_registry.py common_users.py common_ws.py manager_internal_api.py manager_sessions.py manager_user_api.py native_cli.py native_config.py native_gate.py native_replay.py tools\app_server_protocol_matrix.py tools\codex_ws_smoke.py tools\codex_mcp_smoke.py tools\codex_visual_smoke_report.py tools\codex_browser_smoke.py tools\codex_terminal_smoke.py tools\check_hardened_profile.py
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

Codex CLI 升级后：

```powershell
python tools\app_server_protocol_matrix.py --out docs\app-server-protocol-matrix.md
```
