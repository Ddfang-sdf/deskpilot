<p align="center">
  <img src="assets/logo.png?v=2" alt="DeskPilot" width="128">
</p>

# DeskPilot

**让 AI 安全地替你操作 Windows 桌面。**

微信、Excel、老式 ERP、内部系统……凡是没留 API 的软件,AI 都能直接上手:看得懂屏幕,点得准按钮,输得了中文。

- 🛡️ **安全不靠 AI 自觉** —— 每一次点击、每一次按键都要过一道硬校验层;碰到关窗口、删除这类危险操作,你的电脑右下角会弹出审批窗,**你点头才执行**
- 🔌 **即插即用** —— 标准 MCP 协议,Claude Code、Claude Desktop、Cursor 等客户端配上就能用
- 👁️ **不挑模型** —— 没有视觉能力的纯文本模型也能用:屏幕内容会被翻译成元素清单和文字
- 📼 **全程留痕** —— 每步操作前后自动截图,出了错能回放复盘

## 安装

### 第一步:下载

到 [Releases](https://github.com/Ddfang-sdf/deskpilot/releases) 下载最新的 `deskpilot-vX.Y.Z-windows-x64.zip`,解压到一个固定目录,例如 `C:\tools\deskpilot\`。

> ⚠️ 解压后**保持 `policy.yml` 和 `deskpilot.exe` 在同一个文件夹**,不要分开。

### 第二步:接入你的 AI 客户端

**Claude Code**(命令行):

```powershell
claude mcp add deskpilot -- "C:\tools\deskpilot\deskpilot.exe"
```

**Claude Desktop** —— 编辑 `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "deskpilot": { "command": "C:\\tools\\deskpilot\\deskpilot.exe" }
  }
}
```

**Cursor** —— 编辑 `%USERPROFILE%\.cursor\mcp.json`(或 Settings → MCP 界面添加),内容与上面相同。

**其他客户端**:凡支持 MCP(stdio 模式)的,把 `command` 指向 `deskpilot.exe` 即可。

### 第三步:重启客户端,验证

对 AI 说一句:「**用 deskpilot 截个屏**」。能看到截图回来,就装好了。

### 开发者:从源码运行

```powershell
git clone https://github.com/Ddfang-sdf/deskpilot.git
cd deskpilot
pip install -e .
python -m deskpilot
```

要求 Windows 10/11 + Python ≥ 3.12。自行打包:`pip install pyinstaller && pyinstaller deskpilot.spec`。

## 安全说明

- 默认只能操作白名单里的日常软件(记事本、画图、资源管理器、PowerPoint),其他程序 AI 碰不到;想加软件,编辑 exe 旁边的 `policy.yml`
- 危险操作(关窗口、删除等)一律弹本地审批窗,60 秒不点自动拒绝
- 任何时候觉得不对劲:**`Ctrl+Shift+F12` 立即熔断**一切操作,`Ctrl+Shift+F11` 恢复;或者把鼠标甩到屏幕角落按住不放

## 了解更多

设计与安全机制的完整文档在 [docs/](docs/DESIGN.md)。

## License

MIT
