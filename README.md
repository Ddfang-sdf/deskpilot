<p align="center">
  <img src="assets/logo-dp.png" alt="DeskPilot" width="128">
</p>

<h1 align="center">DeskPilot</h1>

<p align="center">
  <strong>让 AI 安全地替你操作 Windows 桌面。</strong><br>
  微信、Excel、老式 ERP、内部系统……凡是没留 API 的软件，AI 都能直接上手。
</p>

<p align="center">
  <a href="https://github.com/Ddfang-sdf/deskpilot/releases"><img src="https://img.shields.io/github/v/release/Ddfang-sdf/deskpilot" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Ddfang-sdf/deskpilot" alt="License"></a>
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4" alt="Platform">
  <img src="https://img.shields.io/badge/MCP-stdio-6E56CF" alt="MCP">
  <img src="https://img.shields.io/badge/tests-434%20passed-2DA44E" alt="Tests">
</p>

<p align="center">
  <a href="https://github.com/Ddfang-sdf/deskpilot/releases/latest"><strong>⬇️ 下载最新 exe</strong></a> ·
  <a href="#-30-秒上手">快速开始</a> ·
  <a href="docs/INSTALL.md">安装指导书</a> ·
  <a href="docs/DESIGN.md">设计文档</a> ·
  <a href="README_EN.md">English</a>
</p>

<p align="center">
  <img src="assets/demo.gif" alt="DeskPilot 实机演示：AI 操作记事本 → 关闭窗口触发人工审批 → 批准后才执行" width="880"><br>
  <em>实机演示：AI 通过 MCP 输入文字 → 发起"关闭窗口"危险操作 → 本地审批窗弹出（带目标实拍缩略图）→ 人类批准后才真正执行</em>
</p>

---

## 看得见的安心

危险操作必须经过你本人点头——AI 发起，程序弹窗，你批准才执行，AI 拿不到绕过审批的任何凭证：

<p align="center">
  <img src="assets/screenshot-approval-toast.png" alt="危险操作本地审批" width="520"><br>
  <em>关闭窗口等危险操作：本地审批窗带目标窗口实拍缩略图与倒计时，超时自动拒绝</em>
</p>

AI 想操作白名单之外的新软件？它会先弹**入白审批**——拒绝、只允许本次会话（重启失效）、或点「永久加入」长期可用，超时一律自动拒绝：

<p align="center">
  <img src="assets/screenshot-enroll.png" alt="入白审批弹窗" width="520"><br>
  <em>入白审批：三选一（拒绝 / 本次会话允许 / 永久加入），未经人类裁决超时自动拒绝</em>
</p>

所有授权都摆在明面上：系统托盘 →「白名单管理」，永久白名单与会话允许两本账一目了然，一键移出（移出即墓碑，AI 不会反复弹窗求入白）：

<p align="center">
  <img src="assets/screenshot-whitelist.png" alt="白名单管理窗口" width="520"><br>
  <em>白名单管理：永久白名单（写入本机文件，升级不丢）与本次会话允许（重启清空）</em>
</p>

任何时候觉得不对劲，<code>Ctrl+Shift+F12</code> 一键熔断（或把鼠标甩到主屏左上角按住；多显示器时触发角固定为主屏左上角），冻结事实会主动弹窗告知，而不是等你发现 AI 不动了：

<p align="center">
  <img src="assets/screenshot-freeze-card.png" alt="急停冻结通知" width="440"><br>
  <em>冻结即时通知：立即解冻 / 稍后提醒，热键解冻后自动消失</em>
</p>

<!-- 演示 GIF：assets/demo.gif（实机录制：记事本输入 → alt+f4 触发审批 → 批准执行）。重录方法见 release/RELEASE_NOTES.md -->

## 为什么选择 DeskPilot

- 🛡️ **安全不靠 AI 自觉** —— 每一次点击、每一次按键都要过一道硬校验层（绑定校验 / 进程白名单 / 按键许可 / 危险操作本地审批，四道闸 fail-closed）；批准权只属于坐在电脑前的你
- 🗂️ **加白自己管** —— 入白审批三选一（拒绝 / 本次会话 / 永久加入），托盘「白名单管理」两本账一目了然，移出即墓碑；永久入白写入独立用户文件，升级不丢
- 🔌 **即插即用** —— 标准 MCP 协议，Claude Code、Claude Desktop、Cursor 等客户端配上就能用
- 👁️ **不挑模型** —— 没有视觉能力的纯文本模型也能用：屏幕内容会被翻译成元素清单和文字（UIA 元素树 + OCR 双通道）
- 🛑 **急停有感知** —— 热键/甩角熔断一切写操作，冻结主动弹窗告知，一键解冻
- 📼 **全程留痕** —— 每步操作前后自动截图 + JSONL 审计，出了错能回放复盘

## 🚀 30 秒上手

**第一步：下载。** 下载 [最新 Release](https://github.com/Ddfang-sdf/deskpilot/releases/latest) 的 `deskpilot-vX.Y.Z-windows-x64.zip`（附 `.sha256` 校验值），解压到固定目录，例如 `C:\tools\deskpilot\`。

> ⚠️ 解压后**保持 `policy.yml` 和 `deskpilot.exe` 在同一个文件夹**，不要分开。（`policy.local.yml` 是首次运行自动生成的用户数据文件，里面保存你的永久入白记录，升级不会丢。）

**第二步：接入你的 AI 客户端。**

Claude Code（命令行）:

```powershell
claude mcp add deskpilot -- "C:\tools\deskpilot\deskpilot.exe"
```

Claude Desktop / Cursor / 通用 stdio 客户端配置样例见[安装指导书](docs/INSTALL.md)。

**第三步：重启客户端，验证。** 对 AI 说一句:「**用 deskpilot 截个屏**」。能看到截图回来，就装好了。

> 📖 生产使用请开**常驻 daemon**（单次调用约 1.2s、绑定跨调用保持）：启动、开机自启、policy.yml 定制、升级、内网分发与常见问题，全在 **[docs/INSTALL.md](docs/INSTALL.md)**；一键安装脚本见 `scripts/install.ps1`。

## 工作原理

```
AI 客户端 ──MCP(stdio)──▶ deskpilot ──四道闸硬校验──▶ Windows 桌面
                              │
                              ├─ 危险操作 → 本地审批窗（你点头才执行）
                              ├─ 急停熔断 → 冻结通知弹窗（一键解冻）
                              └─ 全程审计 → 截图 + JSONL 留痕
```

25 个 MCP 工具（截图 / OCR / 按文字点击 / 元素树 / 点击 / 输入 / 窗口管理……）。安全模型、四道闸细节、协议设计的完整文档在 [docs/](docs/DESIGN.md)。

## 安全说明

- 默认只能操作白名单里的日常软件（记事本、画图、资源管理器、PowerPoint），其他程序 AI 碰不到；想让 AI 操作新软件，它发起请求时**你在入白审批弹窗里点一下「永久加入」即可**，不用改任何文件；系统托盘图标可随时打开「白名单管理」查看和移出
- 白名单分两本账：基础白名单随包分发（`policy.yml`），你点「永久加入」的条目写入独立用户文件（`policy.local.yml`）——升级不丢、移出即墓碑（不会因旧配置回流而复弹）
- 危险操作（关窗口、删除等）一律弹本地审批窗，超时自动拒绝；审批令牌不经 AI 之手
- 任何时候觉得不对劲：**`Ctrl+Shift+F12` 立即熔断**一切操作，`Ctrl+Shift+F11` 恢复；或者把鼠标甩到主屏左上角按住不放（多显示器时触发角固定为主屏左上角）

## 客户端超时建议

危险操作的本地审批默认最长等待 90 秒。Claude Code 的默认工具执行超时可能短于该值，
建议在客户端环境中配置（毫秒）：

```powershell
$env:MCP_TOOL_TIMEOUT = "120000"   # 单次工具调用上限放宽到 120s
```

daemon 断链后无需任何手工恢复：状态（绑定/急停/SoM 缓存）全部保存在常驻进程里，
客户端进程重开会自动续接。

## 开发者：从源码运行

```powershell
git clone https://github.com/Ddfang-sdf/deskpilot.git
cd deskpilot
pip install -e .
python -m deskpilot
```

要求 Windows 10/11 + Python ≥ 3.12。运行测试：`python -m pytest tests/ -q`（默认零副作用：不开真实窗口、不读生产目录）。真机集成用例（会开启真实记事本窗口）需显式 `--run-integration`，CI 全量执行。自行打包：`pip install pyinstaller && pyinstaller deskpilot.spec`。

## 路线图

- [x] M1 安全核心：四道闸强制层、审计留痕、急停熔断
- [x] M2 元素级操作：UIA 优先、零像素坐标的点击/输入
- [x] M3 SoM 标注截图 + 本地审批通道
- [x] 冻结人类感知：冻结通知弹窗、审批同步阻塞执行
- [ ] 多显示器支持
- [ ] 更多客户端的一键配置向导

## 贡献

Issue 和 PR 都欢迎。安全相关改动请连同 `docs/` 里的设计说明书一起更新——这个项目的设计文档与代码同库同评审。

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Ddfang-sdf/deskpilot&type=Date)](https://star-history.com/#Ddfang-sdf/deskpilot&Date)

## License

MIT
