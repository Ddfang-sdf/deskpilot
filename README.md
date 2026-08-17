# DeskPilot

**自定义的安全桌面驾驶舱** —— 让 AI agent 自主、安全地操作 Windows 电脑。

类似 Codex Desktop 的 Computer Use 能力，但：

- 🛡️ **自主安全**：护栏在代码里（fail-closed 强制层），不靠 AI 自觉，不动不动要人确认
- 🔌 **MCP 标准协议**：任何 MCP 客户端（Claude Code、DeepSeek Harness、Cursor…）即插即用
- 👁️ **多模态可选**：UIA 元素树 + OCR 作"文本桥"，纯文本模型也能用；SoM 标注让定位 100% 精确
- 📼 **全程可审计**：每次操作留痕，前后截图可回放

> 设计文档：[docs/DESIGN.md](docs/DESIGN.md) · 状态：**M1–M3 已完成**（v0.2.0，测试全绿，已实盘回归）

## 架构

```
AI Agent (MCP 客户端)
   │ MCP stdio
   ▼
MCP 协议层 mcp_server.py     —— 只做协议翻译，零业务逻辑，零直通后门
   │
   ▼
强制层 enforcement.py  ★安全核心
   │ 每个写操作过四道闸：①窗口绑定 ②应用白名单 ③按键许可表 ④L3 审批令牌
   ▼
执行层 executor/             —— UIA 优先（元素级），pyautogui 兜底（像素级）
   │
   ▼
审计层 audit.py              —— 每次操作：时间/工具/参数/裁决/前后截图，append-only
```

**关键决策：MCP 层到桌面只有一条路径，且必经强制层。** 执行层不直接暴露给 AI。

## 工具清单（23 个）

| 级别 | 工具 | 说明 |
|---|---|---|
| **L0 感知** | `screenshot` `ocr` `find_window` `get_ui_tree` `get_clickable_map` `template_match` `get_cursor` `get_clipboard` | 只读，直调执行层 |
| **L1 低险** | `wait_for_window` `wait_for_element` `move` `scroll` `attach` `detach` | 绑定管理 + 无副作用操作 |
| **L2 写入** | `launch_app` `activate_window` `click_element` `type_element` `click` `type_text` `key` `set_clipboard` `drag` | 全部经强制层四道闸 |

L3 危险键（`delete` / `alt+f4` / `ctrl+w` 等，见 `policy.yml`）触发**本地审批弹窗**，由人类点批准/拒绝，AI 无法自行签发。

## 快速开始

要求：Windows + Python ≥ 3.12

```powershell
pip install -e .
python -m deskpilot          # 启动 MCP stdio 服务（加载同目录 policy.yml）
```

### 接入 Claude Code

```powershell
claude mcp add deskpilot -- python -m deskpilot
# 或使用打包好的 exe：
claude mcp add deskpilot -- C:\path\to\deskpilot.exe
```

### 打包 exe（PyInstaller）

```powershell
pip install pyinstaller
pyinstaller deskpilot.spec
# 产物在 dist\deskpilot.exe；将 policy.yml 复制到 exe 同目录（exe 从同目录加载策略）
```

## 安全机制

- **Fail-closed**：默认拒绝，规则明确允许才放行；任何未覆盖的情况 = 拒绝
- **窗口绑定（Binding）**：写操作必须先 `attach` 目标窗口获得令牌，令牌有 TTL，窗口失活即失效
- **白名单**：`policy.yml` 声明允许操作的进程及级别上限（如 `notepad.exe: L2`）
- **按键许可表**：L2 放行常规键，L3 危险键走人工审批
- **急停**：`Ctrl+Shift+F12` 立即熔断 / `Ctrl+Shift+F11` 复位；鼠标甩到屏幕角落按住同样触发
- **审计**：写操作前后自动截图存证，日志 append-only，AI 不可写

## 测试

```powershell
python -m pytest tests/ -q
```

覆盖 INV-1~10 安全不变量、强制层四道闸、策略加载、绑定 TTL、审批令牌、急停、审计、M2 元素操作与 M3 审批通道。

## 文档

- [docs/DESIGN.md](docs/DESIGN.md) —— 总体设计（三原则、四层架构、INV-1~10、里程碑）
- [docs/功能设计说明书.md](docs/功能设计说明书.md)
- [docs/详细设计说明书.md](docs/详细设计说明书.md) —— 程序级规格、错误码全集
- [docs/测试设计说明书.md](docs/测试设计说明书.md) —— 测试用例权威来源

## License

MIT
