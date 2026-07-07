# Agents Cockpit

> 在手机或任意浏览器上远程驱动本机 **Codex / Claude Code CLI** 的轻量 Web 控制台。挑目录即开 codex 或 claude、多会话切换、**多端实时共享同一个会话**(电脑跑、手机看 + 输入)、历史按目录恢复。

纯 Python 标准库(无第三方依赖)+ [ttyd](https://github.com/tsl0922/ttyd)。Windows 为主,也兼容装了 ttyd 的 Linux/macOS。

## ✨ 功能

- 📂 **新建会话**:本机目录浏览 / 从“用过 codex / claude 的目录”快速选择,一键启动。
- ⚡ **多会话**:同时开多个 codex / claude(每个目录一个),终端内 **≡ 侧边栏** / 「运行中」列表顺畅切换。
- 🌐 **多端实时共享**:电脑和手机(或多个浏览器)连**同一个会话** = 同一个 CLI,实时同看输出、都能输入,后加入的还能看到历史(app.py 做 websocket 集线器)。
- 🕑 **历史**:按目录分组折叠,一键 `codex resume` / `claude --resume` 在原目录恢复某段对话。
- ⌨️ **手机快捷键栏**:Tab / Shift+Tab / Esc / Ctrl+C / 方向键 / 滚动 等(直接注入终端,等价真实按键)。
- 🔒 **会话登录 + 仅本机暴露**:登录后用 HttpOnly Cookie 存登录态(口令不再明文重放),终端内嵌同一页面(反向代理),ttyd 只绑 `127.0.0.1`,对外只开一个端口。
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

1. 把 `ttyd.win32.exe` 重命名为 **`ttyd.exe`** 放进本目录(也可在 `config.ini` 里用 `[binaries] ttyd =` 指定路径)。
2. 复制 **`auth.txt.example`** 为 **`auth.txt`**,改成你自己的 `用户名:密码`(登录控制台用)。
3. (可选)复制 **`config.example`** 为 **`config.ini`** 按需改端口/路径等;不改也能跑(全部默认值)。
4. 运行:
   - Windows:双击 `start.cmd` —— **后台运行**:启动窗口秒关,整套服务在后台常驻,关窗口 / 断开远程桌面都不影响。要看实时日志或排查启动问题,双击 `start-fg.cmd`(前台模式,窗口里直接显示输出)。
   - Linux/macOS:`./start.sh`(同样后台运行,关终端不停);调试用 `./start-fg.sh`,或直接 `python app.py`

后台模式下,地址 / 账号等信息也写入日志 `.agent-cockpit\web.log`。控制台同样会打印,例如:

```
控制台(手机/电脑打开): http://192.168.1.12:7682
账号: codex   密码: ***
```

手机和电脑连**同一个局域网**,浏览器打开该地址,输入 `auth.txt` 里的口令即可。

## ⏹ 完全停止(彻底关闭,不留残留)

本工具是 **监督进程 + 三层服务**(`start.cmd` → 后台 supervisor → web → manager → ttyd → codex/claude)。Windows 下 `start.cmd` 会拉起一个**隐藏的后台 supervisor**,负责在 web 退出时自动重启——**关掉 start.cmd 窗口不会停止服务**(这正是后台模式的目的),所以停止必须用专门的命令:

- **Windows:双击 `stop.cmd`**(或命令行 `python app.py --stop`)
- **Linux/macOS:`./stop.sh`**

它会按顺序:通知 web 冻结看门狗 → 让 manager 杀光全部会话并退出 → 按 `.agent-cockpit/sessions.json` 里的 PID 清扫任何残留 ttyd 树 → 退出码 42 / 写 `stop.sentinel` 通知 supervisor **别再重启** → 最后按 `.agent-cockpit/supervisor.pid` 兜底杀掉隐藏的 supervisor。一句话:**`stop.cmd` 之后再启动就只能靠你手动 `start.cmd`**。

底层保险(任一失败仍能清干净):

- web 进程启动时把自己绑进一个 **Win32 Job Object**(KILL_ON_JOB_CLOSE),web 一旦因任何原因退出(崩溃 / 关窗口 / 被杀),内核会**连带杀掉整个 manager→ttyd→codex/claude 树**,不会留孤儿。
- 停止单个会话时统一用 `taskkill /F /T`(树杀),不再只杀 ttyd 而把 codex/claude 孙子进程漏成孤儿。
- 万一端口仍被占用(通常是上次没正常停),先跑一次 `stop.cmd`;还不行就在任务管理器里结束 `python.exe`(后台 supervisor 的 PID 见 `.agent-cockpit\supervisor.pid`)和 `ttyd.exe`,然后重新 `start.cmd`。

> ⚠️ 升级代码后,正在运行的是**旧代码**的进程。先 `stop.cmd` 停掉旧实例,再 `start.cmd` 启动新代码——直接改完文件不会热生效到已运行的进程。

> 📋 后台模式的边界:`start.cmd` 启动的服务能扛住**关闭窗口**和**断开远程桌面**(RDP 断开时会话保留);但**注销**或**关机**会结束该会话内所有进程(含后台 supervisor)——这是 Windows 会话机制决定的。需要注销 / 重启后仍自启,请改用「任务计划程序(登录时运行)」或 Windows 服务,超出本工具范围。

## ⚙️ 配置(config.ini)

所有配置都从一个文件读:复制 `config.example` 为 **`config.ini`** 按需修改,重启生效。没有 `config.ini` 也能跑(全部走默认值)。常用项:

| 配置项 | 默认 | 说明 |
|---|---|---|
| `[server] port` | `7682` | 控制台端口(浏览器打开的那个) |
| `[server] bind` | `127.0.0.1` | ttyd 绑定网卡(Linux 可设 `lo`) |
| `[server] host` | `0.0.0.0` | 对外监听地址 |
| `[manager] port` | `8682` | manager 进程端口(本机,web 与它通信) |
| `[binaries] ttyd` | 自动探测 | ttyd 可执行文件路径(留空=本目录 `ttyd.exe` 或 PATH) |
| `[binaries] codex` / `claude` | 自动探测 | CLI 路径(留空=自动探测) |
| `[paths] codex_home` / `claude_home` | `~/.codex` / `~/.claude` | CLI 配置目录 |
| `[paths] auth_file` | `auth.txt` | 口令文件(格式 `用户名:密码`) |
| `[approval] auto_approve` | `1` | `1`=codex `--yolo` / claude `--dangerously-skip-permissions`;`0`=逐项审批 |
| `[security] session_ttl` | `86400` | 登录会话有效期(秒);过期需重新登录 |
| `[security] max_fail` / `lockout_secs` | `5` / `300` | 同一访客连续失败 N 次锁定 M 秒(防爆破;内网穿透下按访客 Cookie 区分,不被公网同 IP 连坐) |
| `[security] cookie_secure` | `0` | 走 HTTPS 入口填 `1` 加固;纯 HTTP 直连填 `0` |

完整字段见 `config.example`(每项都有注释)。`config.ini` 已在 `.gitignore` 中,不会被上传。

## 🌍 外网访问

默认只在同一局域网用。出门也要用,推荐 **[Tailscale](https://tailscale.com)**(PC 和手机都装,走私网,不开公网端口);国内也可用 cpolar / natfrp 等内网穿透。**请勿**直接把 7682 转发到公网。

## 🔐 登录与会话安全

登录采用**会话化**机制(替代旧的浏览器 Basic 认证):

- 打开控制台 → 未登录弹登录框 → `POST /api/login` 校验用户名/口令 → 成功后服务端下发一个 **HttpOnly + SameSite=Lax** 的 Cookie(`ac_session`),之后所有请求(含 WebSocket 终端)都凭它鉴权。口令只在登录那一次传输,不再每个请求明文重放。
- 登录态是**带签名+过期**的 token(默认 1 天),过期需重新登录;签名密钥落盘在 `.agent-cockpit/session_secret`,web 重启不丢登录态。
- 同一访客连续失败 5 次会临时锁定 5 分钟(防暴力破解;参数见 `[security]`)。**内网穿透场景下,每个浏览器各持一个访客标识 Cookie(`ac_visitor`),登录限速按访客标识(而非穿透后的公网 IP)计数**——不会出现“一个访问者登录失败连坐锁定所有公网同 IP 访问者”。前端默认模型 / 自动批准 / 自定义参数等设置也改存 Cookie(读取时优先 Cookie、自动从旧 `localStorage` 迁移),每个访问者各自独立。访客标识可在「设置」页查看;它仅用于限速/区分,不是安全边界(不信任的网络可直接 `[security] max_fail = 0` 关闭限速)。
- 凭证推荐存 **PBKDF2 哈希**而非明文:`python -c "import common; print(common.hash_password('口令'))"` 生成,把 `用户名:$pbkdf2$...` 写进 `auth.txt`。明文格式仍兼容。

**端口映射 / 内网穿透(frp、ngrok、Cloudflare Tunnel 等)务必走 HTTPS 入口**:Basic 时代口令是明文重放的;会话化后口令虽只在登录时传一次,但仍只有 HTTPS 能保证它不被链路嗅探。注意 frp/ngrok 这类穿透公网段虽加密,**穿透服务商能解密看到应用层明文**——所以推荐优先用 Cloudflare Tunnel / Tailscale,或自建 frps + 自有域名证书。Cookie 的 `Secure` 标志在 HTTPS 入口下有效(浏览器侧是 HTTPS),可在 `[security] cookie_secure = 1` 开启加固。若想连穿透商都看不到明文,可设 `[server] use_https = 1`(自动生成自签证书,需 `pip install cryptography`)+ 穿透改用 **tcp** 隧道直通,实现端到端加密(代价:自签证书浏览器首次需手动信任)。

## ⚠️ 安全须知

- 终端能让你在 PC 上执行命令、改文件,务必设**强口令**,并仅在自己可信的网络使用。
- `--yolo` 下 codex 会不经确认就执行命令;不放心可在 `config.ini` 里设 `[approval] auto_approve = 0` 关掉。
- 口令文件 `auth.txt` 已在 `.gitignore` 中,**不会**上传;请勿提交真实口令。推荐存 PBKDF2 哈希而非明文(见「登录与会话安全」)。

## 🙏 致谢

- [OpenAI Codex CLI](https://github.com/openai/codex)
- [ttyd](https://github.com/tsl0922/ttyd)
- [xterm.js](https://github.com/xtermjs/xterm.js)

## 📄 License

MIT
