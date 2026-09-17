# ISS-0056:【cleancode】FailSafeException 容错模板 7 处复制

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0056 |
| 标题 | `try: pyautogui.xxx / except FailSafeException → ExecutorError(EMERGENCY_STOP)` 模板在 core.py 复制 7 处(click/drag/key/hold/mouse_down/up/scroll),新增鼠标动词极易漏接 |
| 严重级 | 低(可维护性;漏接=异常逃逸成 500) |
| 状态 | **完成**(2026-09-17;_failsafe_guard 单点化,全量回归 848 绿) |
| 提出 | 2026-09-10(cleancode 审查;grep FailSafeException=7 处同形) |

## 现象与证据

core.py 内 7 处同构 try/except(pyautogui.FailSafeException →
EMERGENCY_STOP 结构化)。ISS-0048 的启动清扫崩溃正是"漏接该模板"的实例
——复制模板的安全范式,复制一次就多一处漏接面。

## 方向

抽单点:`_failsafe_guard(fn, *a, **k)` 或装饰器,一处转换全族受益;
新增动词编译期躲不开。约束:错误消息语义(含 pyautogui 原文)不变。

## 变更记录(补)

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.2 | 2026-09-17 | **完成**(自主推进授权)。core.py 新增模块级 `_failsafe_guard(fn,*a,**k)` 单点(FAILSAFE→EMERGENCY_STOP,消息语义不变含原文);7 处模板副本全部转换(execute/move/_pixel_click/click/click_text/drag 段级/key),启动清扫容错变体(语义不同=容忍+续行)保留。**顺序认账**:实现先于钉落地(会话内偏差);行为红绿证据=t52b(move 收敛红→绿)+test_reliability_iss9/test_mouse_req01 既有 FAILSAFE 钉全绿;新增形态钉 f56(复制面计数≤2 立红)防漂移。全量回归 848 passed/25 skipped/0 failed |
