# ISS-0106:【修改引入】读回/聚焦 UIA 入口绕过 _ensure_com 缝——打包形态读回全盲 type_text 不可用

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0106 |
| 标题 | ISS-0100/0104 新增的 UIA 访问点 `_read_edit_value`(core.py:1520)与 `_focus_first_edit`(:1545)直调 `uiautomation.ControlFromHandle` **未先 `_ensure_com()`**(ISS-0016 A 缝,:695);打包(PyInstaller)daemon 的 HTTP 工作线程 COM 未初始化即抛异常,被宽泛 try/except 吞掉 → 读回恒 None → type_text 全量 READBACK_UNAVAILABLE——**打包形态 type_text 对编辑类目标不可用**(源码形态因 comtypes 自动初始化差异不受影响) |
| 严重级 | **高**(发布面:打包形态核心写工具不可用;修改引入类,先认账) |
| 状态 | **P3 实现完成待验收**(2026-09-22;TC-106-01/02 红→绿;全量 904 绿;重打包 W6 终验 note「读回校验一致」) |
| 提出 | 2026-09-22 W6 打包形态复验:paste 已落地(SetFocus 生效)但 READBACK_UNAVAILABLE;诊断链见 §1 |

## 0. 认账(修改引入)

ISS-0100(读回修真)与 ISS-0104(SetFocus)新增两处 UIA 访问,均未遵守
ISS-0016 A 确立的「UIA 访问必经 `_ensure_com()` 线程惰性初始化」不变量。
源码形态单测/集成全绿掩盖了它(自动初始化差异),打包形态实盘即盲——
「有打包形态差异必实盘」在本单再次应验(ISS-0094 同族教训)。

## 1. 实证链(2026-09-22,全部直读)

1. W6 复验(dist daemon 21:47 构建):type_text → READBACK_UNAVAILABLE;
   但 UIA 直读记事本文档,`dp100magic-w6final-2148` **已真实落入**(写入侧
   ISS-0104 修复生效)——盲的是读回侧;
2. 同 daemon get_ui_tree(Document)正常(经 `_element_root`:695 有
   `_ensure_com()`)——基础 UIA 在打包形态健康;
3. UIA 入口审计(core.py 共 4 处):`_element_root`:700 ✓有缝;
   `_read_edit_value`:1520 ✗;`_focus_first_edit`:1545 ✗;
   `focused_control_type`:225 ✗(另见 §4 观察项);
4. 同函数源码形态裸线程实测正常(comtypes 自动初始化差异,分叉机理)。

## 2. 根因(机制层)

打包形态(pythoncom 冻结语义)下,每个新线程必须显式 CoInitialize 才能
进行 UIA 跨进程调用;`_ensure_com()`(threading.local 幂等)是既有单点缝。
新增 UIA 访问点绕缝 → 线程级 COM 未初始化异常 → `_read_edit_value` 的
兜底 except 吞掉返回 None → 三通道「全灭」假象 → fail-closed 误伤可用目标。
吞异常+绕缝两因素叠加:缝保证初始化,吞异常把「未走缝」隐藏成「无通道」。

## 3. 改法(实现缺陷修复,设计不变)

- `_read_edit_value` 与 `_focus_first_edit` 函数体首行补 `self._ensure_com()`
  (幂等,零行为面变化;与 _element_root 同缝);
- 测试设计:
  | 用例 | 层级 | 场景 | 前提 | 步骤 | 预期 | 断言 |
  |------|------|------|------|------|------|------|
  | TC-106-01 | 单元 | _read_edit_value 经 COM 缝 | monkeypatch core._com_initialize 记录桩(iss16 缝先例);新 Executor(未初始化态) | 调 _read_edit_value | 缝被调一次 | 桩调用记录直出 |
  | TC-106-02 | 单元 | _focus_first_edit 经 COM 缝 | 同上 | 调 _focus_first_edit | 缝被调一次 | 桩调用记录直出 |
- 交叉面:既有 iss16 COM 钉全绿回归;吞异常语义不动(本单只补缝,不改
  异常面);打包复验=W6 手工路径(响应体 note 直出)。

## 4. 观察项(另案,不在本单)

`focused_control_type`(:222-228)同绕缝,但其「失败返 None」是设计内
fail-closed(enforcement 场景键分类);打包形态若因此恒 None,场景受限键
(backspace)会恒 KEY_DENIED——属**既有潜伏**(非今日引入),建议另立单
诊断,不在本单顺手改(范围控制)。

## 5. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-22 | 建单。打包形态读回全盲实证链(§1);根因=绕 _ensure_com 缝+吞异常(§2);改法=补缝+两单元钉(§3);focused_control_type 潜伏观察项另案(§4) |
| v0.2 | 2026-09-22 | **P1→P3 完成+打包实盘闭环**。P1 红两条(绕缝零调用)→补 `self._ensure_com()`(core.py `_read_edit_value`/`_focus_first_edit` 首行)→TC-106-01/02 绿;全量回归 **904 passed/29 skipped/0 failed**;重打包(21:58)+W6 终验:type_text→ok+note「读回校验一致」(打包形态,响应体直出)。状态转「P3 实现完成待验收」 |
