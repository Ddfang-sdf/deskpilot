## DeskPilot v0.2.0 — M1–M3 完整实现

**安全桌面驾驶舱:让 AI agent 自主、安全地操作 Windows 电脑。** 任何 MCP 客户端即插即用。

### 下载

`deskpilot-v0.2.0-windows-x64.zip`(105MB)—— 解压后**保持 `policy.yml` 与 `deskpilot.exe 同目录**(exe 启动时从同目录加载安全策略)。

### 本版内容

- **M1 安全核心**:强制层四道闸(绑定校验 / 白名单 / 按键许可 / L3 审批令牌)、fail-closed、审计留痕、急停(Ctrl+Shift+F12 / 鼠标甩角)
- **M2 元素级操作**:click_element / type_element / launch_app / wait_for_*,UIA 优先零像素坐标
- **M3 SoM + 审批通道**:get_clickable_map 标注截图、L3 本地审批 toast(右下角滑入、目标窗口实拍缩略图、人话描述)
- 23 个 MCP 工具;UIA 元素树 + OCR 文本桥,纯文本模型可用
- 测试:176 用例全绿

### 快速接入(Claude Code 示例)

```powershell
claude mcp add deskpilot -- "C:\path\to\deskpilot.exe"
```

其他客户端配置见 README 安装指南。

### 系统要求

Windows 10/11 x64;无需安装 Python。默认白名单:notepad / explorer / mspaint / powerpnt(编辑 policy.yml 调整)。
