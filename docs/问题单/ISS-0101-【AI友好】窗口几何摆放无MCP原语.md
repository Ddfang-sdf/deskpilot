# ISS-0101:【AI友好】窗口几何摆放无 MCP 原语——AI 只能裸写 Win32 MoveWindow 绕行

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0101 |
| 标题 | 演示编导/多窗协同场景需要把目标窗摆到指定位置(背景板摆位、并排对照、落点避让),MCP 无窗口几何写入原语;AI 唯一出路是裸写 ctypes MoveWindow——绕过强制层与审计面(2026-09-21 sdfang 怒批「为什么不用 MCP」事件的两大真实缺口之一) |
| 严重级 | **中**(能力缺口:迫使 AI 离开 MCP 面;非安全缺陷) |
| 状态 | **方案已评审批准(sdfang 2026-09-22),待开发(P1 写测试)** |
| 提出 | 2026-09-21 sdfang 裁定:「B 提单」 |

## 1. 实证(机制层)

- 本会话为摆录制背景板,裸写 `ctypes.windll.user32.MoveWindow`——该操作
  不经 enforcement/audit,与「桌面操作必经 MCP 面」纪律直接冲突;
- 现有工具面盘点:attach/activate_window 只管绑定与置前,无任何改变
  窗口 rect 的入口;`move` 是鼠标移动,与窗口几何无关。

## 2. 设计草案(物理层原语,符合「工具=物理层」裁定)

- 新工具 `set_window_rect`:token + rect=[l,t,r,b](虚拟桌面坐标,
  与 screenshot/get_ui_tree 同一坐标系);
- 行为:ShowWindow(SW_RESTORE,最大化窗先还原再摆,防打回)+
  MoveWindow;返回新 rect(直出);
- 闸门:沿用 L2 写操作分级(与 click 同级);绑定进程窗限定(不得
  跨绑定摆别人的窗);
- 不做的事(判断归 AI):不做吸附/不做屏幕归属判定/不做避让计算——
  落点合理性由 AI 用 screenshot 自核(现有感知面足够)。

## 3. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-21 | 建单。裸 MoveWindow 实证+工具面盘点;设计草案=物理层原语+L2 闸门+判断归 AI |
| v0.2 | 2026-09-22 | sdfang 批准设计草案:set_window_rect 物理层原语(SW_RESTORE+MoveWindow,返回新 rect)+L2 闸门+绑定进程窗限定+判断归 AI |
