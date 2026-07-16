# Codex Web vs Codex CLI 差距分析与适配计划

更新时间：2026-07-17  
项目：`E:\tools\codex-web`  
当前基线：`main` / `520a05c Add Codex MCP passthrough smoke`  
Codex CLI：`codex-cli 0.142.4`  
协议快照：`docs/app-server-protocol-matrix.md` 记录 68 个 server notifications、10 个 server requests、87 个 client requests。

## 1. 总体判断

当前项目已经不是“把 CLI 终端嵌进网页”的方案，而是一个通过 `codex app-server --stdio` 驱动的结构化 Codex 会话宿主。这个方向是正确的，因为它能原生支持远程访问、多端旁观、移动端、通知、登录隔离、会话恢复和浏览器组件化渲染。

但它还不能被当成完整的 Codex CLI 替代品。现在更准确的定位是：

| 维度 | 当前估计 | 说明 |
| --- | ---: | --- |
| 远程可用 Codex agent 会话 | 85% | 聊天、流式输出、Plan、审批、历史恢复、图片输入、MCP 首个 E2E smoke 已可用。 |
| Codex CLI TUI 替代 | 65-70% | 高频会话能力已覆盖；profile/config、插件/skills、账号恢复、非交互命令等仍不足。 |
| 多端同步与重连体验 | 75% | `seq`、`after=<lastSeq>`、去重、双客户端 smoke 和 open-WS catch-up 已完成；仍缺真实浏览器/手机视觉验证。 |
| app-server 协议覆盖 | 60% | 重点路径覆盖较好，长尾 account/config/fs/plugin/skills/windows sandbox 方法仍多为降级或泛化可见。 |
| 代码可维护性 | 65-70% | 后端和前端都已拆分，但 `CodexSession`、前端全局状态、事件渲染器和安全边界仍是热点。 |
| 共享/公网暴露硬化 | 55% | 多用户、workspace root、hardened 配置文档已有；Origin/CSRF、默认 profile 和管理端边界还需要继续收紧。 |

## 2. 当前 Codex 会话链路

```text
Browser / Android WebView
  -> web.py
     - 登录、静态资源、/api 代理、WebSocket 代理、manager 生命周期控制
  -> manager.py
     - HTTP/WebSocket shell、session registry、广播入口
  -> manager_sessions.py / manager_user_api.py / manager_internal_api.py
     - launch/resume/send/approve/answer/history/internal gate API
  -> codex_native.py
     - CodexSession：Web 会话状态、turn 生命周期、pending request、通知和 replay 协调
  -> codex_client.py
     - codex app-server --stdio 子进程、JSON-RPC、通知路由和 request response
  -> codex_replay.py / codex_requests.py / codex_session_events.py / codex_config.py
     - replay、request 处理、事件转换、启动/turn 配置归一化
  -> assets/*.js + index.html
     - 消息渲染、工具卡、审批/ask/form/Plan 卡、socket、replay、sidebar/history
```

已经形成优势的地方：

- Web 使用 app-server 协议而不是 TUI scraping，长期可维护性优于终端转发。
- 前端使用结构化事件渲染消息和工具卡，适合多端 replay 与局部更新。
- 后端有 per-user Codex home、workspace root 检查、内部 gate auth 和 browser auth。
- Replay 有稳定 `seq/event_id`、`after=<lastSeq>` 增量恢复、前端去重、state snapshot 收敛和 open-WS catch-up。
- Codex 配置已经覆盖 model、web search、sandbox、approval、reasoning effort/summary、service tier、workspace-write writable roots。
- Slash、`@` 文件提及、图片输入、terminalInteraction、手动 MCP、dynamic MCP passthrough 都有第一版真实路径。

## 3. 与 Codex CLI 的主要差距

### 3.1 启动配置与 profile

已覆盖：

- model / web search / sandbox / approval policy。
- reasoning effort / reasoning summary / service tier。
- workspace-write extra writable roots，且会做用户 workspace 边界检查。

仍缺：

- CLI `--profile` 没有安全的一键等价 Web UI；需要先把 `config/read` 和 profile 来源做只读展示。
- CLI `-c key=value`、`--enable/--disable`、local provider、OSS mode、model provider 等没有通用映射。
- 多 profile 场景下，Web 端还没有“当前配置来自哪里”的解释层，用户容易误判生效范围。

适配原则：不要做假 UI。只有当 app-server schema 有明确字段且后端确实消费时，才开放写入控件；否则先做只读可见性和文档说明。

### 3.2 输入体验与命令面

已覆盖：

- 轻量 slash palette：`/model`、`/compact`、`/approval`、`/sandbox`、`/search`、`/rename`、`/archive`、`/unarchive`、`/fork`、`/rollback`、`/goal`、`/steer`、`/reasoning`、`/summary`、`/service-tier`、`/add-dir`、`/mcp-resource`、`/mcp-tool`。
- `@` 文件/目录提及走 app-server `fuzzyFileSearch`，发送为 Codex `mention` input。
- 粘贴/选择图片后发送 `localImage` input，用户消息图片卡片参与 replay。

仍缺：

- Slash palette 还不是完整 CLI 命令面，缺少更强的 discovery、参数提示、历史参数复用和错误纠正。
- `@` 提及体验仍是第一版，移动端键盘、长列表、路径 disambiguation 还需打磨。
- 图片输入缺少清理策略、上传错误细节、历史缩略图一致性验证。

### 3.3 工具、diff、MCP 与终端交互

已覆盖：

- command/file/MCP/dynamic tool 基础渲染。
- `turn/diff/updated` 专用 diff card，重复快照原地更新。
- JSON-shaped result card、special tool start card、MCP/dynamic structured start card。
- `[codex_dynamic_tools]` allowlist passthrough 到 `mcpServer/tool/call`。
- `tools/codex_mcp_smoke.py` 用临时 stdio MCP server 做真实 E2E smoke。
- `item/commandExecution/terminalInteraction` 有 Web stdin/resize/terminate 路径。

仍缺：

- command execution 的 stdout/stderr、exit、工作目录、耗时、折叠策略还不如 CLI 清晰。
- file change card 与 patch preview 仍可继续细化，尤其是多文件/大 diff 的导航。
- terminalInteraction 还缺长时间、多轮 stdin、移动端输入、异常断开和 terminate 的真实 E2E。
- MCP OAuth/login/startup status/resource browser 仍多为泛化通知或手动 slash。

### 3.4 会话生命周期与历史

已覆盖：

- `thread/list/read/resume/delete` 基础历史能力。
- active/archived filter、Archive/Unarchive、Rename、Goal、Fork、Rollback、Compact、Steer 的 Web 入口或 slash 入口。
- 多端会看到后端确认后的状态，避免本地假状态。

仍缺：

- 还没有完整复刻 CLI 的历史列表语义、批量管理、搜索过滤、metadata 展示。
- Fork/Rollback/Compact 的结果链路还可以更产品化，例如自动打开 fork、显示 base thread、展示 compact 摘要。
- History 和 running session 的并发刷新仍要警惕 race；当前有 `sidebarLoadSeq` 一类保护，但还需更多 fixture。

### 3.5 重连、多端同步与视觉稳定

已覆盖：

- server 端每 socket 写锁，降低 keepalive ping 与 broadcast frame 交错导致 1006 的概率。
- replay 统一 `seq/event_id`，WebSocket 重连和 `/api/nreplay` 都支持 `after=<lastSeq>`。
- 前端对 live/replay 使用同一去重 key，不清空已有 DOM 来恢复状态。
- `state_snapshot` 能在错过 result/done 后收敛 stale thinking/turn UI。
- open-WS catch-up polling 可在 socket 仍显示 open 但漏事件时静默拉增量。
- `tools/codex_ws_smoke.py --clients 2 --launch-temp` 已验证协议层双客户端 replay/reconnect/live broadcast。

仍缺：

- 真实浏览器和手机双端的可视化 smoke 仍未完成，不能保证用户感知层无闪烁。
- WS 1006 的根因不一定完全消除；当前策略是“减少概率 + 即使断线也不全量刷新”。
- 后端 replay 存储和 snapshot 策略需要继续用 trace fixture 覆盖极端顺序。

### 3.6 账号、认证、插件和非会话 CLI 能力

已覆盖：

- `account/chatgptAuthTokens/refresh`、`attestation/generate` 不假装成功，而是给出安全恢复提示。
- Rate limit / account 类通知至少能可见化。

仍缺：

- Web-native login、token refresh、attestation、usage/rate detail 还不是完整闭环。
- `doctor`、`cloud`、`exec`、`review`、`apply`、`plugin`、`skills`、`features` 等非会话 CLI 能力基本未产品化。
- plugin/skills 的列表、读取、安装、启停需要非常谨慎，不能先做写入型 UI。

## 4. 当前代码问题清单

### P0：继续守住的稳定性风险

1. 真实 UI 视觉验证不足。
   - 协议层 smoke 已经比较强，但浏览器/手机上的 DOM 闪烁、scroll、pending card 重放、sidebar race 仍缺自动化或固定手工清单。

2. WS 1006 只能缓解，不能假定已根治。
   - 已有写锁、增量 replay、去重和 catch-up；后续仍应记录 close reason、session id、last seq、pending 状态，以便定位根因。

3. dynamic MCP passthrough 需要继续保持 allowlist。
   - 未映射工具必须 visible failure，不应为了“像 CLI”而默认任意转发。

### P1：CLI parity 用户体验缺口

4. profile/config 可见性不足。
   - 用户不知道 Web 启动配置与本机 CLI profile 的继承关系，容易把 UI 控件误认为完整覆盖 CLI。

5. terminalInteraction 缺少长链路验证。
   - 当前有 endpoint 和 card，但还没有覆盖多次 stdin、resize、terminate、断线后的状态恢复。

6. 工具卡还不够 Codex-native。
   - diff/JSON/MCP/special tool 已改善，但 command/file/web/search/context compaction 仍需要更接近 CLI 的摘要、状态、折叠和详情层。

7. 账号恢复仍需回 CLI。
   - 这是短期可接受的降级，但必须一直明显告知，不要让用户以为 Web 端能自动续 token。

### P2：结构和维护性热点

8. `codex_native.py` 仍是最大后端热点。
   - 当前约 1563 行，`CodexSession` 同时处理状态、turn 生命周期、pending request、通知、持久化、replay、push 和 app-server 协调。
   - 继续加功能会重新膨胀，下一步应按职责拆出 session state、turn runner、request adapter、notification adapter、replay facade。

9. `common.py` 仍是兼容 facade 和 import-time side effect 聚集点。
   - 当前约 804 行，配置/auth/binary discovery 等职责仍集中，隔离测试和未来服务化边界会受影响。

10. `web.py` 混合登录、静态资源、代理、manager watchdog 和重启控制。
    - 当前约 448 行，能接受但安全硬化时容易发生边界回归。

11. 前端全局状态和事件渲染器继续增长。
    - `assets/native_events.js`、`assets/native_stage.js`、`assets/app_sidebar.js` 是主要复杂点。
    - `index.html` 仍保留较多样式/结构耦合，后续大 UI 改造前应把 native-stage CSS 下沉。

12. `codex_client.py` 路由 fallback 仍偏经验性。
    - 对缺 thread/turn/item id 的通知，single busy session fallback 有用，但多会话并发下需要 schema/trace fixture 证明哪些方法允许 fallback。

13. 安全边界还没有完成公网化标准。
    - 已有 auth、workspace root、多用户 home、hardened docs；还缺 Origin/CSRF 检查、state-changing API 分级、manager/internal endpoint 审计。

## 5. 适配路线图

### Phase A：先把“多端不中断、不闪、不丢”做实

目标：在 WebSocket 断开、open 但漏事件、移动端切后台、多个客户端旁观时，用户看到的会话尽量稳定。

任务：

- 固化真实浏览器/手机双端 visual smoke checklist，并尽量补一个本地浏览器自动化 smoke。
- 覆盖 pending approval、Plan、ask/form、diff、MCP card、image card、sidebar archive/fork 的 replay 场景。
- 为 WS close/catch-up 添加更可诊断的轻量日志字段。
- 每次 replay/socket 改动都跑 `tools/codex_ws_smoke.py --clients 2 --launch-temp --cwd .`。

验收：断线/重连不全量清 DOM，不重复历史内容，pending 卡能恢复，两个客户端最终内容一致。

### Phase B：补 CLI 高频配置与命令入口

目标：让熟悉 CLI 的用户在 Web 里能找到常用入口，并且所有入口都由后端确认。

任务：

- 增加只读 profile/config/account status 面板，解释当前 Web session 实际使用的 Codex 配置。
- 扩充 slash palette 的参数提示和错误反馈。
- 只在 schema 明确时开放 profile/config 写入；否则继续保留为说明或只读。
- 优化 Fork/Rollback/Compact/Goal 的 sidebar 结果展示。

验收：Web UI 不出现“看似设置成功但 app-server 未消费”的假状态。

### Phase C：工具与终端真实性

目标：关键工具体验接近 CLI，而不是 raw JSON。

任务：

- 为 terminalInteraction 增加真实长命令 smoke：多次 stdin、resize、terminate、断线恢复。
- 继续细化 command execution card：status、cwd、duration、stdout/stderr、exit code、折叠大输出。
- 继续细化 file change card：文件列表、patch 预览、大 diff 折叠、跳转。
- 扩展 MCP smoke 到 startup status、resource read、OAuth/login 降级提示。

验收：常见 coding turn 中，用户不用打开 raw JSON 就能判断工具在做什么、成功了什么、失败在哪。

### Phase D：结构拆分，降低后续改动成本

目标：避免继续把 CLI parity 功能塞回大类和大 JS 文件。

任务：

- 拆 `CodexSession`：`CodexSessionState`、`CodexTurnRunner`、`CodexRequestAdapter`、`CodexNotificationAdapter`、`CodexReplayFacade`。
- 将 `assets/native_events.js` 的工具卡 renderer 拆为小模块或清晰命名分区。
- 将 native-stage 相关 CSS 从 `index.html` 下沉到 `assets/`。
- 为 `codex_client.py` 路由 fallback 增加 trace fixtures。

验收：新增一种 Codex event 或 tool card 时，不需要同时理解 session 生命周期、replay 存储和所有前端渲染分支。

### Phase E：共享/公网暴露硬化

目标：局域网、隧道、手机访问时默认更安全。

任务：

- 对 state-changing JSON API 增加 Origin/CSRF 检查。
- 将 hardened profile 做成可验证配置，而不只是 README 建议。
- 审计 manager/internal API，只允许内部 token 和预期来源。
- 对 per-user Codex/Claude home、workspace root、upload dir、MCP config 写入做边界测试。

验收：开启 hardened profile 后，跨站 POST、未授权 manager control、越界 writable root、越界 upload 访问都被拒绝并有测试覆盖。

## 6. 推荐推进顺序

1. 先做真实浏览器/手机 visual smoke 清单或自动化，因为这是当前“多端流畅体验”剩余证据缺口。
2. 做 terminalInteraction 长链路 E2E，补齐 CLI 中最容易出问题的交互命令场景。
3. 做 Origin/CSRF hardening，避免远程暴露能力继续扩大后再补安全边界。
4. 拆 `CodexSession` 的 request/notification/replay 边界，避免 Phase B/C 新功能再次加重主类。
5. 再扩 profile/config/plugin/skills 等长尾 CLI parity，且优先只读后写入。

## 7. 不建议做的事

- 不要回到 ttyd/终端 iframe 路线；这会牺牲多端 replay、结构化卡片和移动端体验。
- 不要为 unsupported account/token/attestation 返回假成功；宁愿明确提示回 CLI 恢复。
- 不要默认把所有 dynamic tool 透传给 MCP；必须继续显式 allowlist。
- 不要在没有 schema 字段的情况下做 profile/config 写入 UI。
- 不要先做大规模视觉重设计；当前更重要的是稳定、多端、工具真实性和安全边界。

## 8. 验证基线

快速验证：

```powershell
python -m py_compile app.py web.py common.py manager.py native.py codex_native.py codex_config.py gate_mcp.py codex_client.py codex_events.py codex_forms.py codex_history.py codex_replay.py codex_requests.py codex_routing.py codex_session_events.py codex_text.py codex_thread_history.py common_auth.py common_binaries.py common_browse.py common_ccswitch.py common_history.py common_http.py common_notify.py common_process.py common_registry.py common_users.py common_ws.py manager_internal_api.py manager_sessions.py manager_user_api.py native_cli.py native_config.py native_gate.py native_replay.py tools\app_server_protocol_matrix.py tools\codex_ws_smoke.py tools\codex_mcp_smoke.py
Get-ChildItem assets -Recurse -Filter *.js | Sort-Object FullName | ForEach-Object { node --check $_.FullName }
Get-ChildItem tests\check_*.py | Sort-Object Name | ForEach-Object { python $_.FullName }
git diff --check
```

行为 smoke：

```powershell
python tools\codex_ws_smoke.py --clients 2 --seconds 2 --launch-temp --cwd .
python tools\codex_mcp_smoke.py --cwd .
```

Codex CLI 升级后：

```powershell
python tools\app_server_protocol_matrix.py --out docs\app-server-protocol-matrix.md
```
