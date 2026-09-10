# ISS-0058:【cleancode】弹窗落位数学两处手写,同语义两份

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0058 |
| 标题 | 审批弹窗(approval_dialog._toast_placement)与冻结卡(freeze_dialog 滑入轨迹+落位)各自手写"目标屏右下角+任务栏避让"几何;ISS-0007 双屏落位是分别接的,今后落位规则再变要改两处 |
| 严重级 | 低(可维护性;两处已现漂移:避让逻辑细节不同) |
| 状态 | 建单待排期 |
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
