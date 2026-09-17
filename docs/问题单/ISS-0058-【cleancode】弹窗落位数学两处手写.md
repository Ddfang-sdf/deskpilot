# ISS-0058:【cleancode】弹窗落位数学两处手写,同语义两份

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0058 |
| 标题 | 审批弹窗(approval_dialog._toast_placement)与冻结卡(freeze_dialog 滑入轨迹+落位)各自手写"目标屏右下角+任务栏避让"几何;ISS-0007 双屏落位是分别接的,今后落位规则再变要改两处 |
| 严重级 | 低(可维护性;两处已现漂移:避让逻辑细节不同) |
| 状态 | **部分消解,余量排期**(2026-09-17;toast 语义已单源,freeze 滑入轨迹留 deskgeo 专项) |
| 提出 | 2026-09-10(cleancode 审查) |

## 现象与证据

- approval_dialog.py:36 `_toast_placement(screen, width, height)`;
- freeze_dialog.py:158-175 build_window 内联 screen_w/screen_h/y 计算
  + slide_in/out_frames;
- 同一"右下角、避任务栏、跟目标屏"语义两份实现;freeze 侧吃
  target_screen["work_area"],approval 侧自算 work_area——细节已漂移。

## 方向

抽 `deskgeo.py`(屏内落位单点:给定屏+窗尺寸→x/y/轨迹参数),两弹窗共用;
与 ISS-0057 任务栏真查同批做。约束:两弹窗现有落位像素不变(截图基线比对)。

## 变更记录(补)

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.2 | 2026-09-17 | **部分消解**(ISS-0071 顺带):toast 落位公式单源化完成——monitors.toast_placement 公共家,approval_dialog._toast_placement 委托(test_m3 精确值钉像素不变),whitelist_window 两浮窗接入。余量:freeze_dialog 滑入轨迹(slide_in_frames+色键圆角卡)与 toast 公式不同构(无 -16 底缘边距,轨迹动画),按单据约束「现有落位像素不变」不宜强并——建议 deskgeo 单点收敛随专项窗口做(轨迹函数需原样托管),本单保持开放排期 |
