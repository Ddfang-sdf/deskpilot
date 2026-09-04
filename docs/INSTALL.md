# DeskPilot 安装指导书

按"从下载到跑起来"的用户旅程组织，每步都可照做、可验证。适用于集成方与内网环境。

> 赶时间？一键脚本可完成 ①~④ 全部步骤，见 [§9 一键安装脚本](#9-一键安装脚本installps1)。

## ① 下载与校验

1. 打开发布页：<https://github.com/Ddfang-sdf/deskpilot/releases/latest>
2. 下载两个文件：
   - `deskpilot-vX.Y.Z-windows-x64.zip`（主程序包）
   - `deskpilot-vX.Y.Z-windows-x64.zip.sha256`（校验值）
3. 核对校验值（PowerShell，在下载目录执行）：

   ```powershell
   (Get-FileHash .\deskpilot-vX.Y.Z-windows-x64.zip -Algorithm SHA256).Hash.ToLower()
   Get-Content .\deskpilot-vX.Y.Z-windows-x64.zip.sha256
   ```

   两行输出的十六进制串一致 → 包未被篡改，继续；不一致 → 删除重下。

## ② 落位

解压到**固定目录**（不要放桌面/下载目录这类会被清理的位置），推荐：

```
C:\tools\deskpilot\
├── deskpilot.exe
├── policy.yml             ← 出厂安全策略（升级时会被新版覆盖）
└── policy.local.yml       ← 你的数据：永久入白记录（首次运行自动生成，升级保留）
```

> ⚠️ **`policy.yml` 必须和 `deskpilot.exe` 在同一个文件夹。** exe 启动时从同目录加载安全策略；缺失时启动直接报错（fail-closed），不会静默用默认策略跑。
>
> `policy.local.yml` 是**用户数据文件**（ISS-0030 双文件分离）：你在审批窗点「永久加入」的软件写在这里，升级、重新安装都不会丢。

## ③ 注册到 AI 客户端

四选一（或都配）。配置后**重启客户端**生效。

### Claude Code（命令行）

```powershell
claude mcp add deskpilot -- "C:\tools\deskpilot\deskpilot.exe"
```

验证：`claude mcp list` 出现 `deskpilot`。

### Claude Desktop

编辑 `%APPDATA%\Claude\claude_desktop_config.json`（没有就新建），在 `mcpServers` 中加：

```json
{
  "mcpServers": {
    "deskpilot": { "command": "C:\\tools\\deskpilot\\deskpilot.exe" }
  }
}
```

### Cursor

编辑 `%USERPROFILE%\.cursor\mcp.json`（或 Settings → MCP 界面添加），内容同上。

### 通用 MCP 客户端（stdio 模式）

任何支持 MCP stdio 的客户端，把 server 的 `command` 指向 `deskpilot.exe` 的完整路径即可，无需参数、无需环境变量。

## ④ 常驻 daemon（推荐）

不配 daemon 也能用——但每次 MCP 调用都会重启服务进程（约十几秒），且绑定关系不跨调用保持。daemon 常驻后单次调用约 1.2s，**生产使用请开 daemon**。

### 启动

```powershell
Start-Process "C:\tools\deskpilot\deskpilot.exe" -ArgumentList "--daemon" -WindowStyle Hidden
```

### 验证在线

```powershell
Invoke-RestMethod http://127.0.0.1:9420/health
```

返回 JSON（含 `version` 字段）即在线。daemon 在线时，各 MCP 客户端的瘦代理会自动走 daemon，无需改配置。

daemon 启动后**系统托盘会出现 DeskPilot 图标**——它在跑就有图标。右键菜单：
- **白名单管理…**：打开管理窗口，查看/移出已加入的软件（永久与会话分组，逐行 [移出]，会话区 [全部清空]）。

### 开机自启（两种方式，选一）

**方式一：启动文件夹**（简单，当前用户登录后启动）

```powershell
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\DeskPilot.lnk")
$lnk.TargetPath = "C:\tools\deskpilot\deskpilot.exe"
$lnk.Arguments = "--daemon"
$lnk.Save()
```

**方式二：计划任务**（可在未登录时运行，需管理员）

```powershell
schtasks /create /tn "DeskPilot" /tr "\"C:\tools\deskpilot\deskpilot.exe\" --daemon" /sc onlogon /rl limited /f
```

### 停止 daemon

```powershell
Stop-Process -Name deskpilot -Force
```

## ⑤ policy.yml 定制

安全策略分**两个文件**，改完**重启 daemon / 客户端会话**生效：

- `policy.yml` —— **出厂策略**（键表/时限/急停/终端表等安全参数只能在这里）。升级时会被新版覆盖，手改前请留备份；
- `policy.local.yml` —— **你的白名单数据**（只允许 `whitelist` 一节；写入安全参数会被拒绝，fail-closed）。升级、重装都不会动它。

出厂策略常用字段：

```yaml
whitelist:                  # 出厂白名单：AI 只能操作列出的程序
  - { process: notepad.exe, max_level: L2 }   # L2 = 可点击可输入
  - { process: msedge.exe,  max_level: L2 }
  # max_level: L0 仅感知 / L1 仅窗口管理 / L2 键鼠 / L3 需审批（危险操作）

terminal_apps:              # 终端类程序（AI 输入在终端里有额外约束）
  - cmd.exe
  - powershell.exe

keys:
  l2_allow: [enter, tab, space, backspace, ...]   # 自由可用键
  l3_controlled: [delete, alt+f4, ctrl+w, ...]    # 需本地审批的键
  # 浏览器标签/窗口类组合键（ctrl+t / ctrl+n / ctrl+l / ctrl+tab / ctrl+r）也属 L3 审批

timeouts:
  approval_ttl: 90          # 审批窗最长等待（秒），超时自动拒绝

estop:
  corner_hold_ms: 1000      # 甩角（主屏左上角）停留多少毫秒触发急停
  l0_during_freeze: true    # 冻结期是否允许只读感知工具

cleanup:                    # 审计数据保留：日志 90 天；截图 90 天 + 450MB
  logs_max_age_days: 90     #   （容量为硬顶，先于时长触发；合计 ≤500MB）
  shots_max_age_days: 90
  shots_max_bytes: 471859200

audit_dir: ./audit          # 审计与截图受管目录（相对 exe 目录）
```

**加自家软件（推荐，零命令）**：直接让 AI 去操作它——AI 发起请求时本地会弹出**入白审批窗**（带进程名与三态按钮）：
- 「**本次会话允许**」：重启前有效（会话级，不落盘），daemon 重启后需重新授权；
- 「**永久加入**」：由系统写入 `policy.local.yml` 长期有效（AI 全程碰不到任何策略文件）；
- 「**拒绝**」：本次拒绝。

误加入没关系：确认 toast 自带 [撤销]；以后想撤回，托盘图标右键 → 白名单管理 → 对应行 [移出]。
也可以跟 AI 说"以后别操作 XX 了"，AI 会弹一个确认窗，你点 [移出] 即可。

**加自家软件（管理员手动方式）**：编辑 `policy.local.yml`，只写 `whitelist` 一节：

```yaml
whitelist:
  - { process: 自家软件.exe, max_level: L2 }     # 加入
  - { process: notepad.exe, max_level: null }    # 撤回一条出厂白名单（墓碑）
```

重启 daemon 生效。**不要**把手动条目写进 `policy.yml`——升级覆盖时会丢（手动改动 `policy.yml` 会被指纹守望写进审计留痕）。

## ⑥ 验证清单（装完三连）

重启客户端后，依次对 AI 说：

1. 「**用 deskpilot 截个屏**」→ 能看到当前屏幕截图回来；
2. 「**用 deskpilot 取一下鼠标光标位置**」→ 返回坐标；
3. 「**用 deskpilot 打开记事本，读一下它的界面元素**」→ 记事本被打开，返回元素清单；
4. 「**用 deskpilot 点击记事本里的「文件」两个字**」→ 不用坐标，按文字定位点击（v0.3.4 新能力）。

三项全过 = 安装完成。再试一句「**用 deskpilot 关掉记事本窗口**」→ 应弹出本地审批窗（带实拍缩略图与倒计时），批准后才关闭——这验证安全审批通道也在工作。

## ⑦ 升级

你的**永久入白记录升级后自动保留**（它们存在 `policy.local.yml`，与出厂文件分离）——不再需要手动备份合并。

1. 按 ① 下载新版 zip 并校验；
2. 停 daemon：`Stop-Process -Name deskpilot -Force`（没开 daemon 跳过）；
3. **用 `install.ps1` 升级**：脚本会在覆盖 `policy.yml` 前自动执行 `--migrate-policy`，把旧出厂文件里你自己加入的条目迁进 `policy.local.yml`；
   **手动解压覆盖**：先跑一步迁移，再覆盖：
   ```powershell
   & "C:\tools\deskpilot\deskpilot.exe" --migrate-policy `
       "C:\tools\deskpilot\policy.yml" "C:\path\to\新版zip解压\policy.yml" `
       "C:\tools\deskpilot\policy.local.yml"
   # 输出「入白迁移: xxx.exe」即迁移成功；「无差异」也正常
   ```
   `policy.local.yml` 永远不覆盖；`policy.yml` 会被新版出厂文件替换；
4. 重新启动 daemon（④）。客户端注册不用动（路径没变）。

## ⑧ 常见问题（FAQ）

| 症状 | 处置 |
|------|------|
| **杀软报毒/删 exe** | PyInstaller 单文件 exe 常见误报。把安装目录加白：`Add-MpPreference -ExclusionPath "C:\tools\deskpilot"`（Windows Defender，管理员 PowerShell）；企业杀软交安全团队加白。发布页 SHA256 可核对包未被篡改。 |
| **9420 端口被占用** | 查占用：`netstat -ano \| findstr :9420`。若是旧 deskpilot 进程残留：`Stop-Process -Name deskpilot -Force`。确需换端口：给 daemon 与 MCP 客户端都设环境变量 `DESKPILOT_DAEMON_PORT=<新端口>`。 |
| **启动报 policy 未找到** | `policy.yml` 不在 exe 同目录。放回同目录后重启。 |
| **内网/离线机器怎么装** | 在有网机器下载 zip + sha256，经审批通道拷到目标机 → 按 ①③④ 照做（跳过下载）；或用 `install.ps1 -LocalZip <zip路径>`，全程无需外网。 |
| **审批窗没弹、操作超时被拒** | ① 确认目标进程在白名单（出厂 `policy.yml` 或你的 `policy.local.yml`）；② 多显示器用户看另一块屏（v0.3.1 起弹窗跟随目标窗口/鼠标所在屏）；③ 看 `audit\` 目录日志；④ 确认未处于急停冻结（冻结中写操作一律拒绝，`Ctrl+Shift+F11` 或 `deskpilot.exe --reset` 解冻）。 |
| **审批窗挂着，AI 先报超时了** | v0.3.4 起已修复：审批 90 秒内调用一直在线，超时才自动拒绝。若客户端有自己的工具超时，把它放宽到 120s：`$env:MCP_TOOL_TIMEOUT = "120000"`。 |
| **AI 说连不上 deskpilot** | 客户端配置路径含空格没加引号 / 改配置后没重启客户端 / daemon 端口被改但客户端环境变量没同步。 |

## ⑨ 一键安装脚本（install.ps1）

仓库 `scripts/install.ps1` 把 ①~④ 串成一条命令，幂等（重复执行结果一致）：

```powershell
# 在线安装：下载 latest → 落位 → 注册 Claude Code → 启动 daemon → 写开机自启
powershell -ExecutionPolicy Bypass -File install.ps1 -Client claude-code -WithDaemon -AutoStart

# 离线/内网：就地使用 zip，注册全部客户端
powershell -ExecutionPolicy Bypass -File install.ps1 -LocalZip D:\pkgs\deskpilot-v0.3.1-windows-x64.zip -InstallDir D:\tools\deskpilot -Client all
```

| 参数 | 说明 |
|------|------|
| `-InstallDir` | 安装目录，默认 `C:\tools\deskpilot` |
| `-LocalZip` | 就地使用指定 zip；缺省从 GitHub releases/latest 下载 |
| `-Client` | `none`(默认)/`claude-code`/`claude-desktop`/`cursor`/`all` |
| `-WithDaemon` | 装完启动 daemon 并验证 `/health` |
| `-AutoStart` | 写开机自启（启动文件夹方式） |

退出码：`0` 成功；`2` zip 获取失败；`3` 解压落位失败；`4` 客户端注册失败；`5` daemon 验证失败；`6` 自启写入失败。

## ⑩ 卸载

1. 停 daemon：`Stop-Process -Name deskpilot -Force`；
2. 摘注册：Claude Code 执行 `claude mcp remove deskpilot`；其余客户端删配置文件里的 `deskpilot` 条目；
3. 删自启：删启动文件夹里的 `DeskPilot.lnk`（或 `schtasks /delete /tn DeskPilot /f`）；
4. 删安装目录。
