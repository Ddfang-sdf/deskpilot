# ISS-0109:【cleancode】_IconButton 字形/画布替身族(ISS-0059 测绘外第六族)

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0109 |
| 标题 | tests/test_whitelist_iss12.py 的 `_IconButton` 字形/画布替身族(:802 附近)属 ISS-0059 测绘 16 份清单之外的又一替身族(非弹窗 widget 面),0059 迁移时豁免守卫,待收编评估 |
| 严重级 | **低**(测试面整洁;非缺陷) |
| 状态 | 已关闭(2026-09-23;离场授权自决) |
| 提出 | ISS-0059 步骤 3 迁移实测(2026-09-22) |

## 1. 现状

- ISS-0059 收编的 16 份替身均为弹窗/通用 widget 替身;`_IconButton` 族是白名单管理窗**图形按钮字形与画布**的专用替身,测绘三路 grep(class W:/winfo_screenwidth/Toplevel 补丁)未命中——暴露测绘盲区:按「弹窗替身」框架测绘会漏掉 widget 级替身族;
- 该族已带 faketk 守卫豁免标记,不阻塞。

## 2. 建议

- 收编方向:评估 `_IconButton` 族是否可纳入 tests/faketk.py(作为 widget 级扩展面)或独立 widget 替身库;连同复核其他测试文件是否还有同盲区替身族(建议以「monkeypatch tk 任意属性」为口径做一次全量测绘);
- 优先级低:与 ISS-0060/0062/0064/0055 之后排期。

## 3. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-23 | 立单(ISS-0059 登记项 1 转出)。测绘盲区声明+收编方向 |
| v0.2 | 2026-09-23 | 收编落地,状态→已关闭。**结论:可收编,已收编(无需独立小库)**。①主目标:_IconButton 字形/画布族(TestRemoveIcon 6 用例)收编 tests/faketk.install——faketk 扩 widget 级扩展面(实例级 handlers=bind 记录/afters=实例 after ms 序列/cancelled=after_cancel 记录+tk_class 类名标签+recorder.of_class 检索口);删 _FakeCanvas/_FakeFrame/FakeGlyph 三个本地替身,豁免注释随就地补丁一并移除(守卫扫描面无命中,豁免机制保留)。②全量复测(口径「monkeypatch tk 任意属性」,grep setattr.*tk/tkinter):另命中两处同盲区 Tk 根窗壳——test_managerobs_iss95 的 _Tk 类(withdraw/mainloop/quit 三无操作)、test_window_ext_iss12 的 type("T",()) 内联壳(Tk 创建计数语义)——一并收编(install 补 patch "Tk";计数经 of_class("Tk") 回填,断言行零改动)。③豁免判定:test_freezesingle_iss46 tc46_03/04 的 monkeypatch.setattr("tkinter.Toplevel", Mock) 系 unittest.Mock 标准缝、断言走 Mock API(call_args_list/call_count),收编将迫使断言改写,违反断言零改动纪律→**留原处**(形态守卫本不覆盖字符串形补丁,无需豁免标记;登记在案)。纪律执行:断言零改动(TC-ICON 断言行逐字节未动,仅 _make 装配与观测口取用换 install)、目标文件双跑全绿(87 passed ×2)、守卫钉(test_faketk)绿、全量 939 passed/30 skipped(daemon 在线持锁,ISS-0110 修复后口径) |
