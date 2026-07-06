# Agent Cockpit

> 在手机或任意浏览器上远程驱动本机 **Codex / Claude Code CLI** 的轻量 Web 控制台。挑目录即开 codex 或 claude、多会话切换、**多端实时共享同一个会话**(电脑跑、手机看 + 输入)、历史按目录恢复。

纯 Python 标准库(无第三方依赖)+ [ttyd](https://github.com/tsl0922/ttyd)。Windows 为主,也兼容装了 ttyd 的 Linux/macOS。

## ✨ 功能

- 📂 **新建会话**:本机目录浏览 / 从“用过 codex / claude 的目录”快速选择,一键启动。
- ⚡ **多会话**:同时开多个 codex / claude(每个目录一个),终端内 **≡ 侧边栏** / 「运行中」列表顺畅切换。
- 🌐 **多端实时共享**:电脑和手机(或多个浏览器)连**同一个会话** = 同一个 CLI,实时同看输出、都能输入,后加入的还能看到历史(app.py 做 websocket 集线器)。
- 🕑 **历史**:按目录分组折叠,一键 `codex resume` / `claude --resume` 在原目录恢复某段对话。
- ⌨️ **手机快捷键栏**:Tab / Shift+Tab / Esc / Ctrl+C / 方向键 / 滚动 等(直接注入终端,等价真实按键)。
- 🔒 **单次登录 + 仅本机暴露**:终端内嵌在同一页面(反向代理),ttyd 只绑 `127.0.0.1`,对外只开一个带口令的端口。
- 🟠 **自动批准**:`codex --yolo` / `claude --dangerously-skip-permissions` 跳过审批、无沙箱自动执行(可关)。

## 🔧 工作原理

```
浏览器(电脑 / 手机)  ──HTTP / WS──►  app.py  (7682, 带口令)
                                        │   反向代理 + websocket 集线器
                                        ▼
                              ttyd + codex   (仅 127.0.0.1, --yolo)
                                        │
                                        ▼
                              你的 Codex API (~/.codex/config.toml)
```

- 每个会话 = 一个**常驻** ttyd + codex(只绑本机)。
- app.py 持一条上游 ws 到它,把多个浏览器**多路复用**到同一个 codex(广播输出 / 合并输入 / 新加入回放历史),因此多端真正“同看同输”。
- codex 复用你 `~/.codex` 里现有的配置(API key、模型等),本工具不碰你的密钥。

## 📦 依赖

- **Python 3.8+**(仅标准库,无需 pip 安装)
- **Codex CLI** 和/或 **Claude Code CLI** 已装好并能跑(`codex --version` / `claude --version`),且配好了对应的 API / 模型(`~/.codex/config.toml` 或 `~/.claude`)。
- **ttyd**:Windows 下从 [releases](https://github.com/tsl0922/ttyd/releases) 下载 `ttyd.win32.exe`,放到本目录(或加入 PATH)。

## 🚀 安装与运行

```bash
git clone https://github.com/Misoryan/agents-cockpit.git
cd agents-cockpit
```

1. 把 `ttyd.win32.exe` 重命名为 **`ttyd.exe`** 放进本目录(或设环境变量 `TTYD` 指向它)。
2. 复制 **`auth.txt.example`** 为 **`auth.txt`**,改成你自己的 `用户名:密码`(登录控制台用)。
3. 运行:
   - Windows:双击 `start.cmd`
   - 任意平台:`python app.py`(Linux/macOS 可用 `./start.sh`)

启动后控制台会打印地址,例如:

```
控制台(手机/电脑打开): http://192.168.1.12:7682
账号: codex   密码: ***
```

手机和电脑连**同一个局域网**,浏览器打开该地址,输入 `auth.txt` 里的口令即可。

## ⚙️ 配置(环境变量)

| 变量 | 默认值 | 说明 |
|---|---|---|
| `CODEX_WEB_PORT` | `7682` | 控制台端口 |
| `CODEX_BIND` | `127.0.0.1` | ttyd 绑定网卡(Linux 可设 `lo`) |
| `TTYD` | 本目录 `ttyd.exe` | ttyd 可执行文件路径 |
| `CODEX_BIN` | 自动探测 | codex 原生二进制路径 |
| `CODEX_HOME` | `~/.codex` | codex 配置目录 |
| `AUTH_FILE` | 本目录 `auth.txt` | 口令文件(格式 `用户名:密码`) |
| `CODEX_YOLO` | `1` | `1`=codex `--yolo` 自动执行无审批;`0`=关闭(逐项审批) |

## 🌍 外网访问

默认只在同一局域网用。出门也要用,推荐 **[Tailscale](https://tailscale.com)**(PC 和手机都装,走私网,不开公网端口);国内也可用 cpolar / natfrp 等内网穿透。**请勿**直接把 7682 转发到公网。

## ⚠️ 安全须知

- 终端能让你在 PC 上执行命令、改文件,务必设**强口令**,并仅在自己可信的网络使用。
- `--yolo` 下 codex 会不经确认就执行命令;不放心可设 `CODEX_YOLO=0` 关掉。
- 口令文件 `auth.txt` 已在 `.gitignore` 中,**不会**上传;请勿把自己的真实口令提交进仓库。

## 🙏 致谢

- [OpenAI Codex CLI](https://github.com/openai/codex)
- [ttyd](https://github.com/tsl0922/ttyd)
- [xterm.js](https://github.com/xtermjs/xterm.js)

## 📄 License

MIT
