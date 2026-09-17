# ISS-0057:【cleancode】任务栏高度 48 三处硬编码,monitors 靠猜

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0057 |
| 标题 | 任务栏高度同一物理量三处独立硬编码 48(approval_dialog._TASKBAR / freeze_dialog.MARGIN_BOTTOM / monitors._taskbar_h),且 monitors 版对主屏恒猜 48——任务栏加大/靠顶/隐藏时 work_area 全错,弹窗落位与区域判定一起偏 |
| 严重级 | 低(正确性隐患:非主流任务栏配置下落位偏差) |
| 状态 | **完成**(2026-09-17;物理高度真查+避让边距单源脱钩,全量回归 848 绿) |
| 提出 | 2026-09-10(cleancode 审查;三处 grep 实证) |

## 现象与证据

- approval_dialog.py:21 `_TASKBAR = 48`(注释"任务栏预留");
- freeze_dialog.py:23 `MARGIN_BOTTOM = 48`(注释"避开任务栏");
- monitors.py:36 `_taskbar_h(m)`:主屏恒返 48、副屏恒 0——**纯猜**,
  work_area 用于 ISS-0007 弹窗落位与 ISS-0054 后区域判定。
- 三处语义不一致:两处是"避让边距"(宁可多留),一处是"物理高度"(必须准确),混用同一数字掩盖语义差。

## 方向

物理高度用 `SystemParametersInfoW(SPI_GETWORKAREA)` 真查(每屏),
避让边距单源常量(与物理高度脱钩);monitors 不再猜。约束:默认配置下
落位与现状逐像素一致(回归钉)。

## 变更记录(补)

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.2 | 2026-09-17 | **完成**(自主推进授权)。monitors.py:`TASKBAR_RESERVE=48` 避让边距单源常量(语义=宁可多留);新增 `_win32_info()`(GetMonitorInfoW rcWork/dwFlags 真查),mss 路枚举的 work_area/is_primary 改真查回填(rect 键匹配,查不到才退旧猜法并注释标注)——副屏不再吃 0 猜值、主屏不再吃「原点即主屏」猜;toast_placement 默认 taskbar 改常量;approval_dialog._TASKBAR 与 freeze_dialog.MARGIN_BOTTOM 同源引用。钉 f57a(三处同源+签名默认值)/f57b(副屏真查+原点≠主屏,红→绿)。行为变化明示:副屏 work_area 由「零避让猜值」变真实工作区(改进=更真实);本机默认配置下主屏数值不变 |
