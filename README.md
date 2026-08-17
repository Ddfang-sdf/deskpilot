<p align="center">
  <img src="assets/logo.png" alt="DeskPilot" width="128">
</p>

# DeskPilot

**自定义的安全桌面驾驶舱** —— 让 AI agent 自主、安全地操作 Windows 电脑。

类似 Codex Desktop 的 Computer Use 能力,但:

- 🛡️ **自主安全**:护栏在代码里(fail-closed 强制层),不靠 AI 自觉,不动不动要人确认
- 🔌 **MCP 标准协议**:任何 MCP 客户端(Claude Code、Claude Desktop、Cursor…)即插即用
- 👁️ **多模态可选**:UIA 元素树 + OCR 作"文本桥",纯文本模型也能用;SoM 标注让定位 100% 精确
- 📼 **全程可审计**:每次操作留痕,前后截图可回放

> 设计文档:[docs/DESIGN.md](docs/DESIGN.md) · 状态:**M1–M3 已完成**(v0.2.0,176 测试全绿,已实盘回归)

## 安装

### 方式一:下载成品 exe(推荐)

1. 到 [Releases](https://github.com/Ddfang-sdf/deskpilot/releases) 下载最新 `deskpilot-vX.Y.Z-windows-x64.zip`
2. 解压到固定目录,如 `C:\tools\deskpilot\` —— **必须保持 `policy.yml` 与 `deskpilot.exe` 同目录**(启动时从同目录加载安全策略)
3. 按下表接入你的 MCP 客户端:

**Claude Code**(CLI):

```powershell
claude mcp add deskpilot -- "C:\tools\deskpilot\deskpilot.exe"
# 验证: claude mcp list 应显示 deskpilot ✔ Connected
```

**Claude Desktop** —— 编辑 `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "deskpilot": { "command": "C:\\tools\\deskpilot\\deskpilot.exe" }
  }
}
```

**Cursor** —— 编辑 `%USERPROFILE%\.cursor\mcp.json`(或 Settings → MCP 界面添加),JSON 结构同上。

**其他 MCP 客户端**(DeepSeek Harness、自研 harness 等):任何支持 stdio MCP server 的客户端,按上述 JSON 结构把 `command` 指向 `deskpilot.exe` 即可。

4. 重启客户端。deskpilot 的 23 个工具出现后,可以先来一句「用 deskpilot 截个屏」验证。

### 方式二:源码运行(开发者)

要求 Windows + Python ≥ 3.12:

```powershell
git clone https://github.com/Ddfang-sdf/deskpilot.git
cd deskpilot
pip install -e .
python -m deskpilot          # MCP stdio 服务(加载同目录 policy.yml)
```

自行打包 exe:`pip install pyinstaller && pyinstaller deskpilot.spec`(产物在 `dist\`)。

## 架构

```
AI Agent (MCP 客户端)
   │ MCP stdio
   ▼
MCP 协议层 mcp_server.py     —— 只做协议翻译,零业务逻辑,零直通后门
   │
   ▼
强制层 enforcement.py  ★安全核心
   │ 每个写操作过四道闸:①窗口绑定 ②应用白名单 ③按键许可表 ④L3 审批令牌
   ▼
执行层 executor/             —— UIA 优先(元素级),pyautogui 兜底(像素级)
   │
   ▼
审计层 audit.py              —— 每次操作:时间/工具/参数/裁决/前后截图,append-only
```

**关键决策:MCP 层到桌面只有一条路径,且必经强制层。** 执行层不直接暴露给 AI。

## 工具清单(23 个)

| 级别 | 工具 | 说明 |
|---|---|---|
| **L0 感知** | `screenshot` `ocr` `find_window` `get_ui_tree` `get_clickable_map` `template_match` `get_cursor` `get_clipboard` | 只读,直调执行层 |
| **L1 低险** | `wait_for_window` `wait_for_element` `move` `scroll` `attach` `detach` | 绑定管理 + 无副作用操作 |
| **L2 写入** | `launch_app` `activate_window` `click_element` `type_element` `click` `type_text` `key` `set_clipboard` `drag` | 全部经强制层四道闸 |

L3 危险键(`delete` / `alt+f4` / `ctrl+w` 等,见 `policy.yml`)触发**本地审批弹窗**(右下角 toast,含目标窗口实拍缩略图与人话描述),由人类点批准/拒绝,AI 无法自行签发。

## 安全配置(policy.yml)

exe 旁的 `policy.yml` 是唯一安全策略来源(fail-closed,未列出的进程一律不可写):

- `whitelist`:允许操作的进程与级别上限(默认 notepad / explorer / mspaint / powerpnt 为 L2)
- `keys.l2_allow`:免审批按键;`keys.l3_controlled`:危险键触发本地人工审批
- `terminal_apps`:终端类进程一律升 L3 审批
- **急停**:`Ctrl+Shift+F12` 立即熔断,`Ctrl+Shift+F11` 复位;或鼠标甩到屏幕角落按住 200ms
- **审计**:写操作前后截图 + append-only 日志,在 `audit\` 目录

## 测试

```powershell
python -m pytest tests/ -q
```

覆盖 INV-1~10 安全不变量、强制层四道闸、策略加载、绑定 TTL、审批令牌、急停、审计、M2 元素操作与 M3 审批通道(含打包形态弹窗分发回归)。

## 文档

- [docs/DESIGN.md](docs/DESIGN.md) —— 总体设计(三原则、四层架构、INV-1~10、里程碑)
- [docs/功能设计说明书.md](docs/功能设计说明书.md)
- [docs/详细设计说明书.md](docs/详细设计说明书.md) —— 程序级规格、错误码全集
- [docs/测试设计说明书.md](docs/测试设计说明书.md) —— 测试用例权威来源

## License

MIT
