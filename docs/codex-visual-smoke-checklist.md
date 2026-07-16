# Codex 多端视觉 Smoke Checklist

更新时间：2026-07-17  
用途：补齐协议 smoke 之外的真实浏览器/手机体验验证，重点确认多访问源同步、会话加载不卡顿、重连不全量刷新、对话窗口不频繁闪烁。

## 1. 前置条件

- 当前分支已同步到要验证的提交，且 `git status --short --branch` 为 clean 或只包含本次待验改动。
- 本地 web/manager 已启动，并能从桌面浏览器访问 codex-web。
- 至少准备两个访问源：
  - 桌面主浏览器窗口。
  - 第二浏览器窗口、隐身窗口、手机浏览器或 Android WebView 包装壳。
- 打开 DevTools Console，并在两个客户端执行：

```javascript
window.NATIVE_DEBUG = true
```

- 先跑协议层基线：

```powershell
python tools\codex_ws_smoke.py --clients 2 --seconds 2 --launch-temp --cwd .
python tools\codex_mcp_smoke.py --cwd .
```

- 可先跑 headless 浏览器自动化 smoke，验证真实 DOM 的双端同步和断线后不清空内容：

```powershell
python tools\codex_browser_smoke.py --cwd .
```

## 2. 必验场景

| ID | 场景 | 操作 | 通过标准 | 记录证据 |
| --- | --- | --- | --- | --- |
| V01 | 双端打开同一 Codex 会话 | 在客户端 A 新建 Codex 会话，再用客户端 B 从侧边栏/历史打开同一会话 | 两端显示同一标题、同一模型/模式 badge；B 加载时只出现短暂 replay 状态，不清空 A 的内容 | 两端截图、session id |
| V02 | 普通流式回复同步 | A 发送一个简单问题，B 保持旁观 | 两端增量文本顺序一致；B 不需要刷新页面即可看到回复；没有重复 assistant 段落 | 两端最终文本截图 |
| V03 | Plan/pending 卡同步 | 触发 Plan Mode 或需要用户确认的请求 | pending approval/ask/form/Plan 卡在两端可见；任一端处理后另一端同步消失或更新 | 卡片前后截图 |
| V04 | 工具卡 replay 一致 | 触发包含命令、diff、JSON result、MCP/dynamic card 的 turn | 两端工具卡类型、折叠状态入口、diff/JSON 摘要一致；replay 后不退化成 raw JSON | 工具卡截图 |
| V05 | 图片输入同步 | A 粘贴或选择一张小图发送 | 两端用户消息都显示图片卡；历史/replay 后仍显示图片卡，不只显示本地路径 | 图片卡截图 |
| V06 | WebSocket 断开后恢复 | 在 A DevTools Network 临时切 Offline 或关闭网络 10-20 秒后恢复 | A 不全量清空对话；恢复后只拉取缺失增量；Console 可见 close/catch-up 诊断但没有连续闪屏 | 恢复前后截图、Console close code |
| V07 | open 但疑似漏事件 catch-up | 让 B 保持后台或手机锁屏 30-60 秒，A 继续发送内容，再切回 B | B 切回后自动补齐内容；对话窗口不从头重绘；scroll 位置没有大跳动 | B 切回前后截图 |
| V08 | 历史/归档生命周期 | Archive/Unarchive/Fork/Rollback/Compact/Rename/Goal 至少选择 2 个操作 | 触发端和旁观端都看到后端确认后的状态；history filter 不混入错误会话 | 侧边栏截图 |
| V09 | 移动端窄屏输入 | 在手机或窄屏模拟下发送文本、slash 命令、`@` 提及 | 输入框、slash menu、file mention menu 不遮挡确认卡；发送后内容同步到桌面端 | 手机截图 |
| V10 | 长会话加载 | 打开一个已有多轮 Codex 历史会话 | 首屏不长时间空白；replay progress 不停留；加载完成后内容不重复、不闪烁 | 加载耗时、最终截图 |

## 3. 失败判定

出现以下任一情况都应记录为失败并优先修复：

- 重连或切回前台时，整个对话 DOM 被清空后从头重绘。
- 已显示的 assistant/tool 卡重复出现。
- pending approval/ask/form/Plan 卡只在一个客户端可见。
- 两个客户端最终内容不一致，且手动刷新后才恢复。
- WebSocket 1006 后连续重连造成 3 次以上明显闪烁。
- 工具结果 replay 后从结构化卡片退化成 raw JSON。

## 4. 建议记录格式

可以用 `tools/codex_visual_smoke_report.py --out <path>` 生成记录模板。每次视觉 smoke 至少保存：

- Git commit、Codex CLI 版本、浏览器/手机型号。
- 两个访问源的 URL、session id、测试时间。
- V01-V10 的 pass/fail/skip 状态。
- 失败截图、Console 日志中的 close code、last seq、catch-up URL。

## 5. 与自动化 smoke 的边界

- `tools/codex_ws_smoke.py` 证明协议层双客户端 replay/reconnect/live broadcast 不重复。
- `tools/codex_browser_smoke.py` 证明两个真实 Chromium/Edge 页面能打开同一 Codex 会话，收到同一后端确认事件，并在其中一个 WebSocket 关闭后通过 replay/catch-up 补齐内容且不清空已有 DOM。
- `tests/check_native_replay_frontend_logic.py` 证明前端去重、silent catch-up、diff/JSON/MCP card 分支仍存在。
- 本 checklist 证明用户感知层：加载、闪烁、scroll、pending 卡可见性、移动端布局和真实浏览器行为。
