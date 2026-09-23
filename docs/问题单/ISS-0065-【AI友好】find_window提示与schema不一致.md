# ISS-0065:【AI友好】find_window 提示与 schema 不一致——hwnd 查找不到底支不支持

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0065 |
| 标题 | find_window 工具描述/提示语称"可按 hwnd 查找",但 TOOL_SCHEMAS 的 at_least_one 只声明 [title, process],hwnd 传了会被 schema 校验拦——提示与声明面矛盾,AI 按提示走必撞墙 |
| 严重级 | 低(描述一致性;AI 可读错误可自愈,但多绕一轮) |
| 状态 | **已关闭**(2026-09-22 验收通过:find_window(hwnd=)直查命中;sdfang 缺席授权自决,证据见 手工测试计划-20260922-批次②积压验收 X3) |
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

## 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-10 | 转正建单(手工测试 A-06 待查①) |
| v0.2 | 2026-09-17 | **P3 完成**。方向①采纳(与 probe 能力对齐,自主推进授权):mcp_server schema optional 增 `hwnd`("int")、at_least_one 扩 [title, process, hwnd];tools/_run_sensing 透传 hwnd;描述同步(157 字,desc03「attach/绑定」与 ≤200 闸门过)。测试 tests/test_descfix_iss65_70.py fw01~03(P1 红:fw01 InvalidParamsError/fw02 ok=False→P3 绿;fw03 title 路径钉)。全量回归 802 passed/25 skipped/0 failed |
| v0.3 | 2026-09-22 | **验收通过关单**(sdfang 离场留言授权自决,记录在案)。证据:手工测试计划-20260922-批次②积压验收 X3,find_window(hwnd=) 直查命中 |
