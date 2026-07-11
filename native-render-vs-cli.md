# 原生对话 Web 渲染体验 vs 直接使用 Claude CLI — 对比分析报告

> 生成日期：2026-07-10
> 适用代码版本：分支 `feat/session-and-background-launch`（native.py / index.html / manager.py / gate_mcp.py）
> 目的：评估当前「原生 Agent」会话的 Web 渲染体验与在终端直接使用 `claude` CLI 的差距，定位不足，供后续按优先级修改。

---

## 0. 结论先行（TL;DR）

当前原生渲染路线选择正确且**还原度约 70%**：它直接 spawn `claude` CLI 拿 `stream-json` 事件流，再在浏览器里做结构化渲染（turn 卡片 + 流式文本 + thinking 折叠 + 工具卡片 + 审批/提问卡），骨架与 claude.ai / CLI 的信息模型对齐。**核心不足集中在三块**：

1. **工具渲染残缺** — `TodoWrite` / `Read` / `MultiEdit` / `WebFetch` / `WebSearch` / `Task`(子 agent) 全部掉进 `else` 分支变成裸 JSON，而这几个恰恰是 Claude Code agentic 流程里最高频、最该被「美化」的工具（尤其 `TodoWrite`，CLI 里是独立待办面板）。
2. **元信息被丢弃** — `result` 事件里的 `total_cost_usd` / `num_turns` / `usage` / `stop_reason`、`system` 事件里的模型/版本号，全部没有落到 UI，等于丢失了 CLI 的「用量与收尾」信息层。
3. **交互能力弱于 CLI** — 无 `/` 斜杠命令、无 `@` 文件提及、无图片输入、无「打断当前轮但保留会话」、审批无「本次会话不再询问」。

另有**代码块无语法高亮**、**marked.js 未做 XSS 过滤**、**侧边栏状态不反映 pending_approval/plan** 等细节问题。

---

## 1. 渲染管线（机制回顾）

```
浏览器 ──WS──> web.py(/t/<sid>/ws 透传) ──> manager ──> NativeSession.add_client
                                                           │
NativeSession.send(prompt) ──> 子进程 claude -p <prompt>
        --output-format stream-json --verbose --include-partial-messages
        [--resume <claude_sid>]            # 多轮续接
        [--dangerously-skip-permissions]   # yolo
        或 --permission-prompt-tool mcp__cockpit__approve  # 非 yolo 门控
           --mcp-config gate_mcp.py  (stdio MCP,阻塞式审批/提问)
        │
        └─ stdout JSONL 逐行 json.loads ──> _broadcast(ev) ──> 浏览器 nHandle()
```

关键事实（已核对源码）：

- CLI 启动参数固定在 `native.py:29` `_CLAUDE_ARGS`，**已开启** `--include-partial-messages`（所以 `text_delta` / `thinking_delta` 能流式）。
- 终态事件入库（供 replay）只保留 `assistant / user / result` 三类，且 `events[-200:]`（内存）/ `events[-50:]`（落盘 `native_<sid>.json`）（`native.py:295-298, 319`）。`stream_event` 中间帧不入库 —— 重连后靠终态重建，OK。
- 前端唯一渲染入口是 `index.html:839` `nHandle(sid, obj)`，按 `obj.type` 大分支分发。
- 权限/提问走 `gate_mcp.py`：CLI 想跑 `Bash/PowerShell/Edit/Write/NotebookEdit`（`native.py:34` `_ASK_TOOLS`）→ 阻塞 HTTP 到 manager → manager 广播 `pending_approval` → 网页点允许/拒绝（`/api/napprove`）→ 解阻塞回 `{behavior: allow|deny}`。

---

## 2. 相似度：做得对 / 做得好 的地方

| 维度 | CLI 体验 | Web 渲染现状 | 评价 |
|---|---|---|---|
| 文本流式 | 逐 token | `text_delta` 逐 token 追加（`index.html:853-858`） | ✅ 基本一致 |
| Thinking | 折叠 + 计时 | `<details>` 折叠 + 秒表（`index.html:859-877`） | ✅ 一致，且收尾时折叠+显示总耗时 |
| 工具调用结构化 | 各工具专属视图 | turn 卡片 + 工具卡 + 结果回挂（`index.html:888-915`） | 🟡 骨架对，工具覆盖不全（见下） |
| Bash/PowerShell | `$ cmd` + 输出 | `$ cmd` 样式 + 结果折叠（`index.html:896`） | ✅ 一致 |
| Edit/Write | diff 视图 | 红/绿 diff（`index.html:898-906`） | 🟡 思路对，但非行级 diff（见 §4） |
| 工具结果归属 | 跟在工具下 | 按 `tool_use_id` 回挂到工具卡（`index.html:934`） | ✅ 一致 |
| 权限审批 | 行内 yes/no | 行内 允许/拒绝 按钮 + 高危红框（`index.html:943-951`） | ✅ 且 Web 按钮在手机上更友好 |
| ask_user | —（CLI 无此交互） | 行内提问卡 + 文本框（`index.html:952-964`） | ✅ 优于 CLI |
| 压缩通知 | 提示 | `compacted` → 系统提示（`index.html:975`） | ✅ 一致 |
| 多轮续接 | `--resume` | `--resume <claude_sid>`（`native.py:246`） | ✅ 一致 |
| Markdown | 渲染 | `marked.parse`（`index.html:770`） | 🟡 渲染了但无语法高亮/无 XSS 过滤 |
| 历史恢复 | 本地 transcript | 读 `~/.claude/projects/*/<sid>.jsonl` 重建事件（`common.py:878`） | ✅ 一致 |
| 断线重连 | — | WS 自动重连 + `replay_batch`（`index.html:995,843`） | ✅ 优于 CLI |

**整体相似度结论**：信息模型（turn→text/thinking/tool_use→tool_result→result）与流式时序与 CLI 高度一致，**这是路线选对的红利**（直接复用 CLI 的全部能力：20+ 工具、compaction、thinking、skills）。

---

## 3. 不足之处（按影响排序）

### A. 工具渲染残缺（影响最大）

`nHandle` 里 `assistant` 分支对 `tool_use` 只特判了三类：`bash/powershell`、`edit/str_replace_edit/write/write_file`、其余全 `JSON.stringify(input)`（`index.html:893-909`）。后果：

- **`TodoWrite`** —— Claude Code 最核心的「待办清单」工具，在 Web 里渲染成 `{"todos":[{"content":...,"status":"in_progress"}]}` 的裸 JSON。CLI 里它是一块独立、随执行实时勾选的待办面板。这是**最明显的体验落差**。  ✅ **已修复（2026-07-10）**：tool_use 分支新增 TodoWrite 专用渲染（勾选清单 `☐/◐/☑` + 摘要进度 + 自动折叠旧快照）。
- **`Read`** —— 只显示 `{"file_path":..., "offset":..., "limit":...}`，看不到被读到的文件内容（内容在后续 `tool_result` 里，且 Read 不在 `_ASK_TOOLS` 不会审批，但其调用卡缺「读的是哪个文件 / 第几行」的友好展示）。
- **`MultiEdit`** —— 入参是 `edits:[]` 数组，不走 `old_str/new_str` 分支，掉进 JSON，看不到多段 diff。
- **`WebFetch` / `WebSearch`** —— URL/查询词被 JSON 化，看不到「正在抓取 https://…」的摘要卡。
- **`Grep` / `Glob`** —— `grep` 勉强进了 `_isShell`（`index.html:894`），但 Glob 走 JSON；结果列表无高亮命中。
- **`Task`（子 agent / sidechain）** —— stream-json 里子 agent 的事件带 `parent_tool_use_id` / `sidechain:true`，当前**完全未做嵌套**，子 agent 的输出会和主对话平铺混在一起（`index.html:851` 的 `stream_event` 分支不区分 sidechain）。CLI 是缩进折叠展示子 agent 转写。

**建议**：在 `tool_use` 分支按 `b.name` 增加专用渲染器：`TodoWrite`→勾选清单、`Read`→文件路径 chip、`MultiEdit`→多段 diff、`WebFetch`/`WebSearch`→链接/查询卡、`Task`→嵌套子卡片（按 `parent_tool_use_id` 归组）。

> **✅ 已修复（2026-07-10，P2）**：`tool_use` 分支按工具名补齐专用渲染 —— `MultiEdit` 入参 `edits[]` 渲染为逐段红绿 diff +「N 处」计数 + `#序号`(标 `全部` 即 replace_all)；`WebFetch` 渲染为 URL 链接卡（仅 `http(s)` 才生成可点 `<a>`，防 `javascript:` 注入，URL 经 `nEscAttr` 封引号）+ 抓取目的 prompt；`WebSearch` 渲染为查询词卡；顺手把 `Glob`（pattern + path）也做成卡片，不再掉进裸 JSON。另加图标映射（`bash→💻`/`read→📖`/`edit→✏️`/`webfetch→🌐`/`websearch→🔍`/`glob→📂`/`grep→🔎`…）替换原先千篇一律的 `🔧`，并在 summary 灰色 hint 补 multiedit/websearch/glob 的关键入参。**`Task`(sidechain 嵌套）仍为 P3 待办。**

### B. 元信息丢弃（用量/收尾层缺失）

- `result` 事件包含 `total_cost_usd / duration_ms / num_turns / usage{input,output,cache tokens} / subtype / is_error / stop_reason`（`index.html:979`），但 `nHandle` **只读了 `obj.error` 就 `nEndTurn`**，其余全丢。→ **每轮结束无 token/花费/耗时显示**，而 CLI 底栏常驻累计用量。
- `system` 初始事件含 `model / version / session_id / mcpServers / tools`，`nHandle` 直接 `return`（`index.html:850`）。→ 顶部无模型/版本徽标，用户不知道当前跑的是哪个模型。
- `stop_reason`（`end_turn / tool_use / max_tokens / refusal / pause_turn`）未展示 → **限流/拒绝/截断**这些异常收尾用户感知不到（只在 `result.error` 时有提示）。

**建议**：`result` 分支追加一行「✅ 完成 · X 轮 · 入 Nk/出 Mk/缓存 Kk · $0.xx · 用时 Ys」轻量元信息条（可折叠）；`system` 事件把 `model` 写进 `#nativettl` 或顶部徽标。

> **✅ 已修复（2026-07-10，P1）**：`result` 分支新增 `nMetaRow(st,obj)`，按 `✅ 完成 · N 轮 · 入 Xk / 出 Yk / 缓存 Zk · $0.xx · Ys` 渲染轻量元信息条（挂在 turn 卡尾部）；收尾图标随 `stop_reason`/`is_error` 变化——`max_tokens`→✂️、`refusal`→⛔、`pause_turn`→⏸、`tool_use`→🔧，异常收尾给红框警示，补齐了 CLI 里限流/拒绝/截断的感知层。`system`→顶部模型徽标（§B 第 2 点）仍为待办（P2）。
>
> **✅ 已修复（2026-07-10，P2）**：`system` 分支不再直接 `return`——捕获 `obj.model` 存入 `st.model` 并渲染顶栏徽标 `#nativemodel`（`nShortModel` 去掉尾部 `-YYYYMMDD` 日期快照精简显示，`title` 挂完整模型名 + CLI version）。`showNativeSession` 切会话时按 `st.model` 刷新徽标（重连/恢复不重发 system，徽标靠 stage 内缓存保持）。窄屏（≤860px）隐藏徽标避免顶栏拥挤。

### C. 代码 / Markdown 渲染粗糙

- **无语法高亮**：`renderMd`（`index.html:769`）只用 `marked.parse`，**未引入 highlight.js / prism / shiki**，代码块全 `#cdd2dc` 单色。CLI 是有主题配色的。CSS 也只给行内 `code` 上了黄色（`index.html:269`）。
- **代码块无语言标签 / 无复制按钮**：CLI 与 claude.ai 都有「语言 + 一键复制」。
- **表格未单独样式**：`marked` 支持 GFM 表格，但 CSS 无 `table` 规则，渲染出来无边框无对齐。
- **diff 视图非行级**：现在是把整段 `old_str` 染红、整段 `new_str` 染绿（`index.html:900-905`），不是逐行 diff，对「改了几行」的可读性差；且 `white-space:pre-wrap; word-break:break-all`（`index.html:288-289`）会**把代码/命令强行断字**，长命令被从中间劈开，体验不佳（应改为 `overflow-x:auto; white-space:pre`）。

**建议**：引入 highlight.js（CDN 一行）+ 在 `renderMd` 里对 `pre code` 调用 `hljs.highlightElement`；代码块外包一层带「语言 + 复制」的工具条；diff 换成行级 diff 库（如 `jsdiff`）；表格加最小边框样式。

> **✅ 已修复（2026-07-10，P1）**：引入 `@highlightjs/cdn-assets@11.9.0`（atom-one-dark 主题）；assistant 终态渲染后 `nHljs()` 对每个 `pre>code` 调 `hljs.highlightElement`，并在代码块上方插「语言标签 + 复制按钮」工具条（`navigator.clipboard.writeText`，复制后短暂回显「已复制 ✓」）。hljs 未就绪时降级为只补工具条、不高亮。为避免主题的 `display:block;overflow` 与外层 `pre` 撞出双层滚动条，`pre code.hljs` 覆写为 `display:inline`，横向滚动交给 `pre`。**行级 diff / 表格样式 / `word-break` 修正仍为 P3 待办。**

### D. 流式覆盖不全

- **工具执行输出不流式**：`--include-partial-messages` 只覆盖文本/thinking。Bash 长命令的输出在 Web 上是工具卡里一直转「⏳ 运行中…」，直到 `tool_result` 一次性灌入（`index.html:914,937`）。CLI 交互模式是**边跑边出**。
- **工具入参不流式**：`input_json_delta`（`stream_event` 里）未处理，工具调用是「整块冒出」而非「命令逐字生成」（`index.html:851` 只认 `text_delta`/`thinking_delta`）。

**说明**：stream-json 协议下 Bash 输出本就只在结束时回传，**这一项无法 100% 追平 CLI**；但 `input_json_delta` 可以补，让工具调用有「正在键入命令」的动效。

### E. 交互能力弱于 CLI

| 能力 | CLI | Web 现状 |
|---|---|---|
| `/` 斜杠命令（/clear /compact /model …） | ✅ | ❌ 纯文本输入框 |
| `@` 文件/目录提及 | ✅ | ❌ |
| 图片粘贴/输入 | ✅ | ❌（也无法发送图片给模型） |
| `!` bash 直跑 | ✅ | ❌ |
| `#` 写入记忆 | ✅ | ❌ |
| Esc 打断当前轮（保留会话） | ✅ | ❌ ——「停止」= `/api/stop` 杀掉整个会话并 `dropNativeStage`（`index.html:1039`），无「只打断这一轮」 |
| 审批「本会话不再询问」/ 允许清单 | ✅ | ❌ ——只有逐次 允许/拒绝（`index.html:948`），无「always allow」，非 yolo 长任务要反复点 |

**建议**（性价比排序）：① 加「停止」与「打断当前轮」分离（打断 = kill 当前 claude 子进程但保留 sid 与历史，下条消息重新 `--resume`）；② 审批卡加「本会话不再询问此类」选项（在 NativeSession 内存里维护 allow set，gate 直接放行）；③ 输入框支持 `/` 命令补全与 `@` 路径补全；④ 支持图片粘贴（`/api/nsend` 改为 multipart，prompt 带 image content block）。

> **✅ ① 已完成（2026-07-10，P1）**：顶栏「停止」旁新增「打断」按钮（`#nativeintr`）——`/api/ninterrupt` → `NativeSession.interrupt()` 只 `proc.kill()` 当前 claude 子进程，**不关 WS、不删会话、不清历史**；`_run_cli` 检测 `_interrupted` 标志后广播 `interrupted`（而非「已完成」推送），前端补「⏹ 已打断本轮」系统提示并复位发送按钮。若打断时正卡在审批/提问门控，顺带放行挂起项，免得门控线程空等 600s。下次 `send` 自动走 `--resume <claude_sid>` 续接。「停止」行为不变（杀整个会话）。**②③④ 仍为 P2/P3 待办。**
>
> **✅ ② 已完成（2026-07-10，P2）**：审批卡非高危时新增第三个按钮「允许并不再询问」→ `/api/napprove` 带 `always` → `NativeSession.approve(..., always=True)` 把 `tool_name` 存进内存 `_allow_tools` 集（并持久化进 `native_<sid>.json`，manager 软重启也保留）。`await_permission` 命中该集时**直接返回放行**（不广播 pending_approval 卡片、不阻塞、不推送），实现「本会话不再询问此类」。**安全护栏**：`_is_dangerous`（rm -rf / format / shutdown …）即便在允许集里也强制弹审批，按钮在高危卡上不显示。生效后广播 `auto_allow_added`，前端补「🔒 本会话不再询问 X 类操作」反馈行。**③④ 仍为 P3 待办。**

### F. 状态反映不完整  ✅ 已修复（2026-07-10）

`NativeSession.state()`（`native.py:87-92`）只返回 `idle / running / new`，**不返回 `confirm` / `plan`**。但前端 CSS 与通知逻辑（`index.html:62-63, 597-599`）是为 `confirm/plan` 设计的。后果：

- 等待审批（`pending_approval`）时，侧边栏小圆点仍是「运行中」绿色，**不会变「需确认」黄色脉冲**，用户扫一眼侧边栏发现不了「有个会话卡在等审批」。
- `plan`（ExitPlanMode）同理。

**建议**：`state()` 在 `self._pending` 非空时返回 `confirm`（或区分 approve/ask 两种），让侧边栏与通知联动起来（这套通知+外推 Telegram/Bark 基建已就绪，白白没触发）。

> **✅ 已修复（2026-07-10）**：`state()` 现在在 `_pending` 非空时返回 `confirm`（`native.py:99`）→ 侧边栏黄点 + 站内 notice 接通；并新增 `_push()`（`native.py:108`）在审批/提问/完成三个事件点后台线程调用此前无人调用的 `common.push_notify`，真正把推送发到 Telegram/Bark/飞书 webhook（按事件类型 `NOTIFY_MIN_INTERVAL` 去抖）。

### G. 安全：marked.js 输出未过滤（XSS 风险）  ✅ 已修复（2026-07-10）

`renderMd`（`index.html:770`）与多处 `innerHTML = renderMd(...)`（如 `index.html:887`）**直接把 marked 的 HTML 塞进 DOM，没有 DOMPurify / `marked.setOptions(sanitize)`**。assistant 文本理论上来自模型，但模型会复述 `WebFetch` 抓到的网页内容、用户提供的代码片段 —— 这些都可能带 `<img onerror>` / `<script>`。CLI 是 TUI 无此问题，**Web 必须补**。

**建议**：引入 DOMPurify，`return DOMPurify.sanitize(marked.parse(s))`；或换 marked 的 sanitizer。工具结果/命令本就走了 `nEsc`（`index.html:768`）是安全的，问题只在 markdown 路径。

> **✅ 已修复（2026-07-10）**：`index.html` 加载 DOMPurify CDN；`renderMd` 改为 `DOMPurify.sanitize(marked.parse(s))`。关键安全点：marked 或 DOMPurify 任一未就绪时**绝不注入原始 HTML**，回退到 `nEsc` 转义。

### H. 其它细节

- **重连后历史截断**：落盘 `events[-50:]`（`native.py:319`），manager 重启后长会话早期历史丢失（仅显示最近 50 条终态）。建议放大或改为「按 token 截断」。
- **并发发送无保护**：`ns.send`（`native.py:59`）不检查 `_busy`，理论上可并发起两个 claude 子进程互相 `--resume` 抢写。建议 busy 时拒绝/排队。
- **审批超时**：门控 `_GATE_TIMEOUT=600s`（`native.py:32`），超时按拒绝处理 —— 长时间不点的用户回来发现「被拒了」，UI 上未必有明显提示（approval_decision 会 remove 卡片，但缺「已超时拒绝」的系统提示）。
- **`replay_batch` 标记**：恢复时插「⟳ 历史对话恢复」（`index.html:849`）OK，但 thinking 在 replay 时只对 `assistant.thinking` 块渲染（`index.html:916-921`），与流式的秒表体验略不一致（可接受）。

---

## 4. 优于直接用 CLI 的地方（保留并强化）

1. **Web 审批/提问 UI** —— 手机友好、高危命令红框、行内 ask_user，交互比 CLI 行内 yes/no 更清晰。
2. **多设备 / 远程** —— 内网穿透 + 会话化登录 + 访客隔离（`ac_visitor`），手机/iPad 随时接入同一个 agent。
3. **异步通知** —— 站内 notice + 外推 Telegram / Bark / webhook（`common.py:1272`）；CLI 必须盯着终端。**（✅ 2026-07-10 已接线：`state()` 返回 confirm + `_push()` 调用 `push_notify`，confirm/done 现在真的会推到手机了。）**
4. **结构化历史 + 跨重启续接** —— manager 软重启保留会话、transcript 重建、可删除历史。
5. **用量面板** —— cc-switch 用量/额度（`refreshCC`），CLI 没有这种跨会话汇总视图。
6. **危险命令静态识别** —— `rm -rf / format / shutdown` 自动高亮（`native.py:163`）。

---

## 5. 改进优先级建议（供后续排期）

| 优先级 | 项 | 预期收益 | 大致工作量 | 状态 |
|---|---|---|---|---|
| P0 | **`state()` 反映 pending_approval/plan**（§F）→ 接通侧边栏黄点 + 异步通知 | 高（修复「已建好却没触发」的通知能力） | 小 | ✅ 已完成（2026-07-10） |
| P0 | **`TodoWrite` 专用渲染**（§A） | 高（消除最显眼的体验落差） | 小 | ✅ 已完成（2026-07-10） |
| P0 | **marked.js 加 DOMPurify**（§G） | 高（安全） | 极小 | ✅ 已完成（2026-07-10） |
| P1 | **`result` 元信息条**（cost/tokens/turns/stop_reason）（§B） | 中高（补齐用量收尾层） | 小 | ✅ 已完成（2026-07-10） |
| P1 | **「打断当前轮」与「停止」分离**（§E） | 中高（长任务体验） | 中 | ✅ 已完成（2026-07-10） |
| P1 | **代码块语法高亮 + 复制 + 语言标签**（§C） | 中（观感） | 小 | ✅ 已完成（2026-07-10） |
| P2 | **审批「本会话不再询问」**（§E） | 中（非 yolo 流畅度） | 中 | ✅ 已完成（2026-07-10） |
| P2 | **`Read`/`MultiEdit`/`WebFetch`/`WebSearch` 专用卡**（§A） | 中 | 中 | ✅ 已完成（2026-07-10，含 Glob） |
| P2 | **`system` 事件 → 顶部模型徽标**（§B） | 低中 | 极小 | ✅ 已完成（2026-07-10） |
| P3 | **`Task` sidechain 嵌套渲染**（§A） | 中（复杂任务可读性） | 大 | ⬜ 待办 |
| P3 | **斜杠命令 / `@` 提及 / 图片输入**（§E） | 中（输入能力追平 CLI） | 大 | ⬜ 待办 |
| P3 | **行级 diff、表格样式、word-break 修正**（§C） | 低中（打磨） | 小 | ⬜ 待办 |
| P3 | **`input_json_delta` 流式工具入参**（§D） | 低（动效） | 小 | ⬜ 待办 |

---

## 6. 附：关键代码位置索引（改的时候直接跳）

- 渲染总入口：`index.html:839` `nHandle()`
- 流式 text/thinking：`index.html:851-878`
- 工具卡渲染（待扩）：`index.html:880-925`
- 工具结果回挂：`index.html:927-941`
- 审批/提问卡：`index.html:943-973`
- result 处理（待补元信息）：`index.html:979-984`
- markdown 渲染（待加高亮+过滤）：`index.html:769-772`
- 停止/打断（待拆分）：`index.html:1039`
- CLI 启动参数：`native.py:29`、`native.py:244` `_build_argv`
- 事件入库截断：`native.py:295-298`、`native.py:319`
- 会话状态机（待补 confirm/plan）：`native.py:87-92`
- 门控工具清单：`native.py:34` `_ASK_TOOLS`
- 审批/提问网关：`gate_mcp.py:86-117`
- transcript 重建：`common.py:878`
