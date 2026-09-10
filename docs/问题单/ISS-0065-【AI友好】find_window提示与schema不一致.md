# ISS-0065:【AI友好】find_window 提示与 schema 不一致——hwnd 查找不到底支不支持

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0065 |
| 标题 | find_window 工具描述/提示语称"可按 hwnd 查找",但 TOOL_SCHEMAS 的 at_least_one 只声明 [title, process],hwnd 传了会被 schema 校验拦——提示与声明面矛盾,AI 按提示走必撞墙 |
| 严重级 | 低(描述一致性;AI 可读错误可自愈,但多绕一轮) |
| 状态 | 建单待评审 |
| 提出 | 2026-09-08 手工测试 A-06 待查①;2026-09-10 转正建单 |

## 现象与证据

- mcp_server.py find_window:optional 仅 title/process,at_least_one 同域;
- probe 层(find)内部支持 hwnd 直查(ISS-0016 时代即有);
- 描述与声明不一致——AI 按描述传 hwnd → INVALID_PARAMS。

## 方向(评审二选一)

| # | 方向 |
|---|------|
| ①(倾向) | schema optional 补 hwnd(int),at_least_one 扩 [title, process, hwnd]——与 probe 能力对齐 |
| ② | 描述删掉 hwnd 提法(能力藏起来) |

约束:选定后描述/schema/测试三同步;用例=hwnd 直查命中(替身 probe 直出)。
