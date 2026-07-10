# codex-web Codex 渲染适配总结报告

生成日期: 2026-07-10
项目: `E:\tools\codex-web`
分支: `feat/session-and-background-launch`
对照对象: 本机 Codex CLI `0.142.4` / `codex app-server --stdio`

## 1. 结论

当前 `codex-web` 的 Codex 路线不是把终端 TUI 直接嵌入浏览器，而是通过 `codex app-server --stdio` 接入 Codex 后端，再在 `index.html` 中重新渲染为结构化 Web 对话。

综合判断:

- 若目标是「远程查看 agent 干活 + 基本交互」: 相似度约 **70-75%**。
- 若目标是「完整替代 Codex CLI TUI」: 相似度约 **55-65%**。
- 主要优势是远程/移动端、Web 审批、多端观看、后台通知、web/manager 分层重启。
- 主要差距是 Codex app-server 协议覆盖、CLI 操作面、历史管理、输入体验、复杂工具/终端交互。

下一步适配重点不应继续做普通聊天 UI 美化，而应优先补齐 **Codex app-server 事件/请求协议映射** 和 **CLI 高价值交互入口**。

## 2. 当前架构

### 2.1 运行链路

```text
Browser
  -> web.py
     - 提供登录、index.html、/api/* 代理、/t/<sid>/ws 代理
  -> manager.py
     - 管理 native session 生命周期
     - 创建/恢复 CodexSession
  -> codex_native.py
     - 启动 codex app-server --stdio
     - 通过 JSON-RPC/JSONL 与 Codex app-server 通信
     - 将 Codex item/notification/request 翻译成 Web 前端通用事件
  -> index.html
     - 渲染 turn、assistant text、thinking、tool card、approval、ask、result meta
```

关键代码入口:

- `app.py`: 选择 web / manager / stop 模式。
- `web.py`: 浏览器-facing 层，可重启，不直接持有会话。
- `manager.py`: 会话注册、launch/resume/send/approve/answer/interrupt。
- `codex_native.py`: Codex app-server 适配器。
- `index.html`: 结构化 Web 渲染和输入交互。
- `common.py`: 配置、二进制发现、注册表、历史、通知、用量。

### 2.2 Codex 接入方式

当前 Codex 后端由 `codex_native.py` 通过:

```text
codex app-server --stdio
```

启动，并发送:

- `initialize`
- `thread/start`
- `thread/resume`
- `turn/start`
- `turn/interrupt`

目前 Web 前端收到的是 `codex_native.py` 转换后的通用事件，而不是 Codex TUI 原始画面。

## 3. 已接近 CLI 的能力

| 维度 | 当前 Web 状态 | 评价 |
| --- | --- | --- |
| 后端同源 | 使用 `codex app-server --stdio` | 高度接近 |
| 文本流式输出 | `item/agentMessage/delta` -> `text_delta` | 接近 |
| Reasoning/Thinking | reasoning delta 渲染为折叠思考块 | 接近 |
| 命令执行显示 | commandExecution 映射为 Bash/PowerShell 工具卡 | 基本可用 |
| 文件修改显示 | fileChange 映射为 Edit 工具卡和 diff 文本 | 基本可用 |
| 审批 | 命令/文件/权限审批映射到 Web 按钮 | 可用且移动端更友好 |
| 用户输入请求 | `item/tool/requestUserInput` / MCP elicitation 映射为 ask 卡 | 可用 |
| 计划/任务 | plan mode + TodoWrite 风格任务面板 | 可用 |
| 打断 | `turn/interrupt` 接入 | 接近 CLI |
| 模型显示 | system event 写入顶栏徽标 | 基本可用 |
| 元信息 | result meta 显示 token/duration/error | 部分接近 |
| 多端观看 | WebSocket + replay | 优于 CLI |
| Web/manager 分层重启 | web 可独立重启，manager 持有会话 | 优于 CLI |

## 4. 当前主要差距

### 4.1 启动参数 UI 与后端未打通

现象:

- 新建会话弹窗有「自定义参数」输入，例如 `--model gpt-5`。
- 前端会把 `args` 发送给 `/api/launch`。
- 但 `manager.py` / `CodexSession` 当前没有消费这份 `args`。

影响:

- 用户以为已经指定 model/profile/search/sandbox，实际可能没有生效。
- 这是最容易造成误判的体验问题。

建议:

- 短期: 暂时隐藏或标注「暂未接入 Codex」。
- 中期: 将自由文本改成结构化字段:
  - model
  - profile
  - approval policy
  - sandbox mode
  - web search
  - additional writable dirs
- 后端通过 app-server thread/turn 参数或 config 覆盖真实生效。

### 4.2 Codex app-server 协议覆盖仍不完整（已补一轮可见性）

本机 `codex app-server generate-json-schema` 显示 app-server server notification 约 64 类。Web 侧仍不能等同 CLI TUI，但本轮已把“静默缺失”改成“可见轻提示/调试卡”，并补齐一批高价值事件的最小渲染。

当前已覆盖的高价值事件包括:

- `thread/started`
- `thread/status/changed`
- `turn/started`
- `turn/completed`
- `item/agentMessage/delta`
- `item/reasoning/summaryTextDelta`
- `item/reasoning/textDelta`
- `item/started`
- `item/completed`
- `item/commandExecution/outputDelta`
- `item/fileChange/patchUpdated`
- `item/mcpToolCall/progress`
- `turn/plan/updated`
- `thread/tokenUsage/updated`
- `thread/compacted`
- `item/reasoning/summaryPartAdded`
- `item/commandExecution/terminalInteraction`
- `item/fileChange/outputDelta`
- `item/plan/delta`
- `model/rerouted`
- `model/safetyBuffering/updated`
- `account/rateLimits/updated`
- `mcpServer/startupStatus/updated`
- `turn/moderationMetadata`

本轮已推进:

| 事件/请求 | 当前处理 | 剩余差距 |
| --- | --- | --- |
| 未匹配 notification | 分发到已加载 Codex session，显示 `codex_notice`，带 method 与 params 折叠详情 | 仍可能在多开 session 中偏吵，后续可做全局通知区或 thread 过滤 |
| 未匹配 server request | Web 中显示 `Unsupported app-server request` 调试卡，再向 app-server 返回 unsupported error | `item/tool/call`、`openai/form`、认证/attestation 仍缺真实交互实现 |
| `item/reasoning/summaryPartAdded` | 转成 `thinking_delta`，进入当前 thinking 卡片 | 还未按 summary part 做结构化折叠 |
| `item/commandExecution/terminalInteraction` | 显示“命令等待终端交互”的 Codex notice，避免发送后无反馈 | Web stdin 尚未接通，复杂交互仍需转 CLI |
| `item/fileChange/outputDelta` | 追加到对应工具输出 | 还不是 Codex-native 行级 diff UI |
| `item/plan/delta` | 作为文本 delta 可见 | 后续应接入专用 plan 卡流式更新 |
| reroute / safety / rate limit / MCP startup / moderation | 统一显示轻量 Codex notice，保留详情 | 顶栏状态、usage 面板、MCP 状态面板仍待做 |

### 4.3 Server request 还有硬缺口

schema 中存在但当前未处理的 server request:

- `item/tool/call`
- `openai/form`
- `attestation/generate`
- `account/chatgptAuthTokens/refresh`

当前 `_handle_server_request` 对未知 request 会先在 Web 中显示 `codex_notice`，再返回 unsupported error。若未来 Codex CLI 某些工具或登录/认证/表单能力走这些 request，Web 端仍会中断，但用户能看到 method 和 params 摘要，不再是无反馈失败。

建议:

- 对 `item/tool/call` 做 MCP/dynamic tool passthrough 或明确拒绝并显示可读错误。
- 对 `openai/form` 做 Web 表单卡。
- 对认证/attestation 类 request 至少返回明确 UI 提示；基础可见性已完成，真实授权流程待做。

### 4.4 工具渲染还不够 Codex-native

当前 Web 工具卡主要按 Claude 风格通用事件渲染:

- Bash/PowerShell
- Read
- Edit/Write/MultiEdit
- WebFetch/WebSearch
- Glob/Grep
- TodoWrite
- ExitPlanMode

Codex app-server 的 item 类型更丰富:

- commandExecution
- fileChange
- mcpToolCall
- dynamicToolCall
- webSearch
- imageGeneration / imageView
- sleep
- contextCompaction
- plan
- reasoning
- agentMessage

差距:

- `dynamicToolCall` / MCP 工具现在多半退化成 JSON。
- `fileChange` 不是行级交互 diff。
- `turn/diff/updated` 可能回挂不到对应工具卡，只能变成散装结果。
- image/sleep/contextCompaction 没有专属 UI。

建议:

- 在 `codex_native.py` 层尽量保留 Codex item type、id、status、metadata。
- 在 `index.html` 为 Codex item 增加专用 renderer，而不是全部压成 Claude tool_use 形状。

### 4.5 输入体验明显弱于 CLI

Codex CLI 的常见输入能力:

- `/` 命令
- `@` 文件/目录提及
- 图片输入
- 初始 prompt 附带 image
- 模型/审批/sandbox/profile 快捷配置
- resume / fork / archive / delete
- compact / rollback / steer

当前 Web:

- 主输入是普通 textarea。
- 只有 Enter 发送、Shift+Enter 换行。
- 有 plan/task 两个按钮。
- 没有 `/` 命令面板。
- 没有 `@` 文件选择。
- 没有图片粘贴/上传。
- 没有 Codex thread history 的完整管理。

建议:

1. 先做 `/` 命令面板:
   - `/compact`
   - `/model`
   - `/search`
   - `/sandbox`
   - `/approval`
   - `/clear`
2. 再做 `@` 文件/目录提及:
   - 复用 app-server `fuzzyFileSearch/*` 或自建轻量文件搜索。
3. 最后做图片输入:
   - UI 支持粘贴/选择图片。
   - 后端确认 app-server input schema 后传入 image content。

### 4.6 Codex 历史管理不等价

当前:

- Claude 历史来自 `~/.claude/projects/**/*.jsonl`。
- Codex 历史已通过 app-server `thread/list` 接入 `common.load_history()`，Sidebar 可以看到 CLI/app-server 持久化 thread。
- Codex resume 已通过 `thread/read(includeTurns=true)` 读取历史 turns，并在 Web 中重放最近事件，再用 `thread/resume` 继续同一个 thread。
- Codex 删除已通过 app-server `thread/delete` 接入 `common.delete_history()`。
- `.agent-cockpit/codex_<sid>.json` 仍保留为 Web runtime / 软重启快照，不再是 Codex 历史唯一来源。

影响:

- Web 已能浏览、恢复并删除普通 Codex thread，覆盖日常 resume/delete 闭环。
- manager 重启后，历史入口不再依赖近期 Web 快照；可从 Codex app-server 持久化 thread 列表恢复。
- CLI 的 fork/archive/unarchive、thread rename、goal 等高级管理还没有搬到 Web。

建议:

- 已接入 app-server:
  - `thread/list`
  - `thread/read`
  - `thread/resume`
  - `thread/delete`
- 下一轮接入 app-server:
  - `thread/fork`
  - `thread/archive`
  - `thread/unarchive`
  - thread name / goal 相关能力
- Sidebar 历史应区分:
  - running session
  - persisted Codex thread
  - archived thread

### 4.7 并发和状态保护不足

当前 `/api/nsend` 会直接调用 `ns.send(prompt)`。

风险:

- 多端同时点发送可能对同一个 Codex thread 开多个 turn。
- 前端按钮 disabled 不能作为后端安全保证。

建议:

- 后端在 `_busy` 时拒绝或排队。
- 推荐先做拒绝:

```json
{"error": "session is busy"}
```

- 之后再考虑队列。

### 4.8 用量/限流/模型状态层不完整

当前:

- result meta 可显示部分 token/duration。
- `thread/tokenUsage/updated` 只缓存最后一次 usage。
- `codex_usage` 前端直接 return。
- `account/rateLimits/updated` 已作为轻提示显示，但还没有进入 usage/rate-limit 面板。

建议:

- 顶栏显示:
  - current model
  - reroute info
  - rate limit / cooldown
  - current turn token
- 用量页区分:
  - Codex app-server account usage
  - cc-switch usage
  - session-local token usage

## 5. 适配优先级

### P0: 消除误导和硬失败

1. **启动参数真实生效或隐藏**
   - 修复 `args` 不生效问题。
   - 先支持 model/profile/search/sandbox/approval。

2. **未知 server request 可见化**
   - 已对 `item/tool/call`、`openai/form` 等未知请求显示明确错误卡。
   - app-server 收到 unsupported 后，用户可看到原因摘要；真实交互实现仍待做。

3. **发送并发保护**
   - `_busy` 时拒绝或排队。
   - 前后端都要保护。

### P1: 补 Codex 协议核心体验

1. `terminalInteraction` - 已可见提示；stdin 输入仍待做。
2. `fileChange/outputDelta` - 已追加到工具输出；Codex-native diff UI 待做。
3. `plan/delta` - 已可见为文本 delta；专用 plan 卡流式更新待做。
4. `reasoning/summaryPartAdded` - 已进入 thinking。
5. `model/rerouted` - 已轻提示；顶栏状态待做。
6. `account/rateLimits/updated` - 已轻提示；usage/rate-limit 面板待做。
7. `mcpServer/startupStatus/updated` - 已轻提示；MCP 状态面板待做。

### P2: 补 CLI 高频入口

1. `/` 命令面板
2. `@` 文件/目录提及
3. 图片粘贴/上传
4. compact / rollback / steer
5. 模型、sandbox、approval 快捷切换

### P3: 完整历史和高级管理

1. Codex `thread/list/read/resume/delete` - 已接入 Sidebar 历史、恢复和删除。
2. fork/archive/unarchive
3. thread name update
4. thread goal set/clear/get
5. 更完整 usage/rate limit 面板

## 6. 建议实施路线

### 阶段 1: 稳定基础映射

目标: 不误导、不静默失败、不并发踩踏。

任务:

- 梳理 app-server schema，建立 `handled_methods.md` 或测试用例。
- 修复启动参数。
- 后端 `_busy` 防并发。
- 未知 notification/request 统一落到 debug/system card。（已完成基础可见性）
- 为 `codex_native.py` 增加事件转换单元测试。

交付标准:

- 用户填 model/search/sandbox 后可验证生效。
- 未知 request 不会静默失败。
- 同一会话连续快速发送不会开多个 turn。

### 阶段 2: 补齐 Codex 事件体验

目标: 让 Web 渲染跟上 app-server 主要事件。

任务:

- terminal interaction 卡。（已完成提示；stdin 待做）
- 文件变更增量输出。（已完成基础追加）
- plan delta 流式计划卡。（已完成文本可见；专用卡待做）
- reasoning summary part 渲染。（已进入 thinking）
- model reroute / safety buffering / rate limit 系统提示。（已完成轻提示）
- MCP server 状态提示。（已完成轻提示）

交付标准:

- 长命令执行、文件修改、计划模式、限流、MCP 异常都能在 Web 上看懂。

### 阶段 3: 补 CLI 输入与历史

目标: 从「可远程观察」升级到「可长期替代 CLI 常用操作」。

任务:

- `/` 命令面板。
- `@` 文件提及。
- 图片输入。
- Codex thread list/read/resume/delete。（已完成）
- Codex thread fork/archive/unarchive。（待做）
- compact/rollback/steer。

交付标准:

- 日常 Codex CLI 高频动作 80% 可在 Web 内完成。

## 7. 验证清单

### 基础会话

- 新建 Codex 会话。
- 发送普通问题。
- 显示 model 徽标。
- 显示流式文本。
- 显示 result meta。
- manager 重启后仍能恢复会话。
- web 重启不杀会话。

### 工具调用

- 执行 PowerShell/Bash。
- 长命令输出 delta。
- 命令需要审批。
- 文件编辑需要审批。
- 文件 patch 更新。
- MCP 工具调用进度。
- WebSearch。
- Todo/Plan 更新。

### 交互

- 打断当前 turn。
- 审批允许。
- 审批拒绝。
- 本 session 允许同类操作。
- request user input。
- 多浏览器同时观看。
- 多浏览器同时发送时不会并发踩踏。

### 历史

- 列出 Codex thread。（已接入 `thread/list`）
- 恢复 Codex thread。（已接入 `thread/read` + `thread/resume`）
- 删除 Codex thread。（已接入 `thread/delete`）
- 归档/反归档 thread。
- fork thread。
- Web session 快照与 Codex thread 历史不混淆。

### 失败场景

- app-server 退出。
- 未知 server request。
- MCP server 启动失败。
- 模型 reroute。
- rate limit/cooldown。
- 网络断开后重连。

## 8. 关键代码索引

- `codex_native.py`
  - app-server 启动: `CodexAppServerClient._start_locked`
  - JSON-RPC 分发: `CodexAppServerClient._dispatch`
  - server request 处理: `CodexAppServerClient._handle_server_request`
  - session 启动/发送/打断: `CodexSession.start/send/interrupt`
  - turn 参数: `CodexSession._turn_params`
  - notification 映射: `CodexSession.handle_notification`
  - item -> tool event: `CodexSession._tool_event_from_item`
  - item -> result event: `CodexSession._tool_result_from_item`
  - 审批/提问: `CodexSession._await_approval/_await_user_input`

- `manager.py`
  - 创建会话: `launch_native`
  - 恢复会话: `reattach_sessions`
  - resume: `ManagerHandler._resume_native`
  - send: `/api/nsend`
  - interrupt: `/api/ninterrupt`
  - approval: `/api/napprove`
  - answer: `/api/nanswer`

- `index.html`
  - 渲染入口: `nHandle`
  - Markdown: `renderMd`
  - 任务面板: `nRenderTasks`
  - result meta: `nMetaRow`
  - thinking: `nStartThinking/nFinalizeThinking`
  - 工具卡: `assistant` -> `tool_use` 分支
  - 审批卡: `pending_approval`
  - 提问卡: `pending_ask`
  - 发送: `nativeSend`
  - 打断: `nativeintr` click handler

- `common.py`
  - Codex 二进制发现: `resolve_codex_bin/codex_argv`
  - backend 归一化: `normalize_backend`
  - registry: `registry_*`
  - history: `load_history/delete_history`
  - session projection: `session_public`
  - external notification: `push_notify`

## 9. 立即可开的任务单

### Task A: 修复 Codex launch args

描述:

- 将 launch modal 的 `args` 从纯文本升级为结构化配置。
- 后端在 `launch_native` / `CodexSession` 中保存并应用这些配置。

验收:

- 启动时选择 model 后，system model 徽标与预期一致。
- search/sandbox/approval 至少有一个可验证开关生效。

### Task B: Codex unknown event/request debug panel

状态: 已完成基础闭环。

描述:

- 所有未识别 server notification/request 都要进入 UI debug/system 卡。
- 不再只在后台日志里出现。

验收:

- 构造未知 method 时，Web 会话中可见 method 名、params 摘要、处理结果。

### Task C: Busy guard

描述:

- `_busy` 时 `/api/nsend` 返回 409 或排队。
- 前端收到 busy 时显示系统提示。

验收:

- 快速双击发送不会创建两个 concurrent turn。

### Task D: Codex history via app-server

状态: 已完成 list/read/resume/delete；fork/archive/unarchive 未包含在本轮。

描述:

- 用 `thread/list` / `thread/read` 替代 Codex 侧 `.agent-cockpit` 假历史，并接入 `thread/delete`。

验收:

- Sidebar 能看到 Codex CLI 历史 thread。
- 能恢复历史 thread 并继续对话。
- 能删除普通 Codex thread。

### Task E: terminalInteraction support

状态: 已完成可见提示；Web stdin 待做。

描述:

- 接入 `item/commandExecution/terminalInteraction`。
- UI 至少能显示「命令正在等待交互输入」。
- 若可行，支持 Web 输入 stdin。

验收:

- 交互式命令不再表现为无响应。

## 10. 风险提示

- `codex app-server` 标记为 experimental，协议可能随 Codex CLI 版本变化。
- 当前 Web 适配不应硬编码过多旧字段，应保留原始 method/type 以便兼容升级。
- Web 比 CLI 多了 XSS/鉴权/远程暴露风险，所有 markdown 和工具输出必须继续走 DOMPurify/escape。
- 如果启用公网访问，必须配 HTTPS/VPN/强密码；否则 Web 端审批按钮等于远程执行本机命令入口。
