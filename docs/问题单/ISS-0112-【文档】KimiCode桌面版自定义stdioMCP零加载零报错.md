# ISS-0112:【文档】Kimi Code 桌面版自定义 stdio MCP 零加载零报错——配置合法却被静默跳过

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0112 |
| 标题 | 项目级(`.kimi-code/mcp.json`)与用户级(`~/.kimi-code/mcp.json`)注册的 deskpilot stdio MCP server,在 Kimi Code **桌面应用**新会话中均未被加载:无信任弹窗、无加载尝试、无报错日志,工具箱零 `mcp__deskpilot__*`;配置文件本身合法且命令可独立启动——自定义 MCP 在桌面版处于「静默不工作」态(REQ-012 分发面第一实案) |
| 严重级 | **中**(生态接入:onboarding 断点;非 DeskPilot 产品缺陷,属客户端兼容面实证归档) |
| 状态 | **已归档(证据链完整),REQ-012 素材** |
| 提出 | 2026-09-24 ISS-0015 客户端观察(Claude Code 对照组)中连环实证 |

## 1. 证据链(2026-09-24,全部直读)

1. **配置合法**:`.kimi-code/mcp.json`(项目级)与 `~/.kimi-code/mcp.json`(用户级)均含合法 deskpilot 条目(stdio,`python -m deskpilot`),JSON 校验通过;
2. **命令可跑**:同一命令手工启动 stdio server 正常(stdin EOF 干净退出);
3. **wire 零注册**:新会话(session_b30165bb)wire.jsonl 中 `mcp.tools_discovered` 仅 `desktop_browser` 一条,`mcp__deskpilot__*` 调用零命中;
4. **桌面日志零尝试**:`~/.kimi-code/logs/kimi-code-desktop.log` 仅 Browser MCP 监听记录,无 deskpilot 加载尝试/错误;
5. **配置可读**:会话内 agent 经 `/mcp-config` 能读到该条目(「已配置但本会话未加载」)——读取面正常,加载面缺失;
6. **对照组**:同一 daemon、同一机器,Claude Code 用户级注册 `√ Connected` 且全链工作(ISS-0015 验收)——server 侧无问题,断点在 Kimi Code 桌面版加载环节。

## 2. 影响与定性

- 影响:Kimi Code 桌面用户无法按官方文档(用户级/项目级 mcp.json)接入 deskpilot;模型会退化为 Bash+裸 UIA 绕行(ISS-0015 观察首轮实证);
- 定性:非 DeskPilot 缺陷;作为 REQ-012(分发与生态接入)的客户端兼容实案归档——立项时决定:上报 Kimi Code 渠道 / 文档标注规避 / 等待官方修复三选一。

## 3. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-24 | 立单归档。证据链六条(配置/命令/wire/桌面日志/读取面/对照组);定性=客户端兼容面,REQ-012 素材 |
