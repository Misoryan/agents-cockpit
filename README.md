# Agents Cockpit

<p align="center">
  <img src="assets/agent-cockpit-logo.svg" alt="Agents Cockpit Logo" width="120" height="120">
</p>

Agents Cockpit 是一个轻量的 Web 控制台，用浏览器或 Android WebView 远程驱动本机 Codex 与 Claude Code 会话。它面向长时间运行的 Agent 工作流：目录选择、多会话、任务进度、审批提醒、历史恢复、多端共享同一会话都集中在一个页面里。

## 主要能力

- **本机 Agent 控制台**：通过 `web.py` 对外提供浏览器 UI，并由 `manager.py` 管理本机 Codex / Claude 会话。
- **Codex 与 Claude 双后端**：Codex 使用 `codex app-server --stdio`，Claude 使用 CLI `stream-json` 模式。
- **Work View 任务视图**：将长对话压缩成进度卡片，显示当前状态、耗时、工具调用、变更文件与最终结果。
- **按需查看 diff**：变更文件不会把读取文件算进去，并支持类似 GitHub 的懒加载文件 diff。
- **历史与恢复**：支持最近任务、归档历史、会话恢复、分支/回滚/重命名等 Codex 历史操作。
- **多端同步**：多个浏览器可以同时观察同一个运行中会话。
- **通知系统**：网页通知与 Android 通知统一状态文案，支持确认、计划审阅、完成与错误提醒。
- **Android 壳应用**：WebView 包装层支持前台保活、后台轮询通知、状态恢复、App/通知 logo 与图片上传。

## 运行要求

- Python 3.8+，核心服务只依赖标准库。
- 已安装 Codex CLI，并可通过 `codex` 运行；或在 `config.ini` 的 `[binaries]` 中配置绝对路径。
- 已安装 Claude Code CLI，并可通过 `claude` 运行；或在 `config.ini` 的 `[binaries]` 中配置绝对路径。
- 从 `auth.txt.example` 复制并配置一个本地登录文件 `auth.txt`。

## 快速开始

```bash
cp auth.txt.example auth.txt
# 编辑 auth.txt，设置强密码
python app.py
```

Windows 也可以使用：

- `start.cmd`：后台启动。
- `start-fg.cmd`：前台/调试模式启动。
- `stop.cmd`：停止 web、manager 与运行中会话。

Linux / macOS：

- `./start.sh`
- `./start-fg.sh`
- `./stop.sh`

启动后，控制台会打印访问地址与登录用户。

## 配置

需要覆盖默认配置时，将 `config.example` 复制为 `config.ini`。

常用配置项：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `[server] port` | `7682` | 浏览器访问端口 |
| `[server] host` | `0.0.0.0` | 浏览器访问绑定地址 |
| `[manager] port` | `server.port + 1000` | 本机 manager 端口 |
| `[binaries] claude` | 自动检测 | Claude CLI 绝对路径 |
| `[binaries] codex` | 自动检测 | Codex CLI 绝对路径 |
| `[paths] claude_home` | `~/.claude` | Claude transcript / config home |
| `[paths] auth_file` | `auth.txt` | 登录凭据文件 |
| `[users] data_dir` | `.agent-cockpit/users` | 每个登录用户的本地状态目录 |
| `[users] default_workspace_root` | `.agent-cockpit/users/{uid}/workspace` | 每个登录用户默认工作区根目录 |
| `[users] allow_unconfigured_paths` | `1` | 允许访问任意本机路径；设为 `0` 时限制到工作区根目录 |
| `[users] primary_user_uses_default_homes` | `1` | `auth.txt` 第一个用户继续使用默认 Codex / Claude home |
| `[approval] auto_approve` | `1` | 传递 `--dangerously-skip-permissions`；设为 `0` 时启用网页审批门 |
| `[codex_dynamic_tools] <tool>` | 空 | 将安全的 Codex 动态工具显式映射到 `mcp:<server>/<tool>` 透传目标 |
| `[security] session_ttl` | `86400` | 登录 cookie 有效期，单位秒 |
| `[security] cookie_secure` | `0` | 仅在 HTTPS 后方设为 `1` |
| `[security] csrf_origin_check` | `1` | 根据 Host / allowed origins 检查 POST 与 WebSocket Origin / Referer |
| `[security] csrf_allow_missing_origin` | `1` | 是否允许缺失 Origin / Referer 的客户端 |
| `[security] allowed_origins` | 空 | 反向代理后额外允许的浏览器来源，逗号或分号分隔 |

`[codex_dynamic_tools]` 是允许列表，不是通配执行模式。可以使用 `namespace.tool`、`namespace.*` 或 `tool` 形式；未映射的动态工具会明确失败，而不是被静默执行或伪装成功。

## 会话模型

- 新建任务时选择本机目录，再选择 Codex 或 Claude 后端。
- Codex 会话支持粘贴图片与文件选择图片；图片会保存到会话上传目录，并以 `localImage` 输入发送给 Codex。
- 每个登录用户在 `.agent-cockpit/users/<uid>/` 下有独立 cockpit 状态，并只能浏览或启动其配置允许的工作区根目录。
- Claude 历史与配置通过 `CLAUDE_CONFIG_DIR` 按用户隔离；Codex app-server 使用 cockpit 状态目录下的用户级 `CODEX_HOME`。
- 为了兼容旧用法，当 `[users] primary_user_uses_default_homes = 1` 时，`auth.txt` 第一个用户继续使用系统默认 Codex / Claude home。
- manager 软重启后，会从每个用户的 cockpit 状态中恢复运行中会话。
- 多个浏览器可以通过 WebSocket 同时观察同一个会话。

## 代码结构

- `common_*.py`：认证、进程、注册表、历史、文件浏览、通知、WebSocket 与 HTTP 等共享逻辑；`common.py` 负责兼容性导出。
- `manager_sessions.py`、`manager_user_api.py`、`manager_internal_api.py`：manager 生命周期与 API。
- `native_*.py`：Claude CLI 配置、审批门、回放与进程辅助逻辑。
- `codex_*.py`：Codex app-server 客户端、事件、请求、回放、路由、文本/表单、历史与 session event 逻辑。
- `assets/`：前端脚本、样式、图标与 logo。
- `android/`：Android WebView 壳应用与本地构建脚本。
- `work_summary.py`：Work View 的任务摘要、工具统计与文件变更汇总。
- `tests/`：脚本化静态与行为校验。

## Android 应用

Android 壳应用位于 `android/`，用于在手机端长期保持 cockpit 页面与通知能力。

配置地址：编辑 `android/app/src/main/res/values/strings.xml`：

```xml
<string name="cockpit_url">http://YOUR_PC_LAN_IP:7682/</string>
```

本地构建：

```powershell
.\android\build-local.ps1
```

输出 APK：

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

当前 Android wrapper 支持：

- 前台服务保活与后台轮询 `/api/sessions`。
- 使用 WebView 登录 cookie 做通知同步。
- Android 13+ 通知权限请求。
- App launcher / 通知 logo。
- 系统图片选择器，多图上传到 Codex 会话。

## 安全建议

Agents Cockpit 可以通过 Codex 或 Claude 工具在宿主机执行命令。请使用强密码，只在可信网络、HTTPS、VPN 或安全隧道后暴露。

如果要离开可信个人局域网，建议使用更严格的配置：

```ini
[server]
host = 127.0.0.1
use_https = 1
http_port = 0

[users]
allow_unconfigured_paths = 0
primary_user_uses_default_homes = 0

[approval]
auto_approve = 0

[security]
cookie_secure = 1
csrf_origin_check = 1
csrf_allow_missing_origin = 0
# allowed_origins = https://agents.example.com
session_ttl = 28800
```

通过隧道或反向代理暴露时，请在浏览器到达 Agents Cockpit 前终止 HTTPS，并保持 manager 端口仅本机可访问。

暴露前可以校验加固配置：

```powershell
python tools\check_hardened_profile.py --config config.ini
# 如果 HTTPS 在 Agents Cockpit 前方的可信反向代理终止：
python tools\check_hardened_profile.py --config config.ini --behind-https-proxy
```

生成密码哈希：

```bash
python -c "import common; print(common.hash_password('your-password'))"
```

## Codex 账号恢复

Codex 会话使用 `codex app-server --stdio`，因此共享当前 `CODEX_HOME` 下的本地 Codex 账号状态。大多数普通任务都可以直接在网页中完成，但以下账号/安全流程仍需要 CLI：

- `account/chatgptAuthTokens/refresh`：用相同的 `CODEX_HOME` 运行 `codex login` 或打开一次 Codex CLI，完成账号刷新后重试或重启网页会话。
- `attestation/generate`：在 Codex CLI 中运行同一任务一次，让 Codex 完成设备/安全 attestation，再回到网页 UI。

Agents Cockpit 会在对话中明确报告这些情况，不会伪装成功，也不会在浏览器中展示 token 材料。

## 许可证

MIT
