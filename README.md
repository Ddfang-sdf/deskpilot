# DeskPilot

**自定义的安全桌面驾驶舱** —— 让 AI agent 自主、安全地操作 Windows 电脑。

类似 Codex Desktop 的 Computer Use 能力，但：

- 🛡️ **自主安全**：护栏在代码里（fail-closed 强制层），不靠 AI 自觉，不动不动要人确认
- 🔌 **MCP 标准协议**：任何 MCP 客户端（Claude Code、DeepSeek Harness、Cursor…）即插即用
- 👁️ **多模态可选**：UIA 元素树 + OCR 作"文本桥"，纯文本模型也能用；SoM 标注让定位 100% 精确
- 📼 **全程可审计**：每次操作留痕，前后截图可回放

> 设计文档：[docs/DESIGN.md](docs/DESIGN.md) · 状态：设计评审中，代码未开始

## License

MIT
