# ISS-0104:【设计引入】type_text 粘贴前未聚焦编辑控件——窗口前台但焦点在标签条时粘贴落空

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0104 |
| 标题 | `_type_text` 只 `_activate_if_needed` 置前窗口,不保证键盘焦点在编辑控件上;Win11 记事本(多标签)等窗口焦点可在标签条/非编辑区,ctrl+v 粘贴落空——ISS-0100 C 的 fail-closed 如实拦下(TYPE_MISMATCH),但写操作本身失败 |
| 严重级 | **高**(写操作正确性:与 ISS-0100 同一信任面;实盘实证) |
| 状态 | **方案已评审批准(sdfang 2026-09-22 裁定改法 A),待开发(P1 写测试)** |
| 提出 | 2026-09-22 四单升级验收 W6:type_text 纯 ASCII 到真记事本,读回校验(fail-closed)连续拦下——先 READBACK_UNAVAILABLE(dist daemon)后 TYPE_MISMATCH(源码复现),逐层诊断为焦点落空 |

## 1. 实证链(全部直读,2026-09-22)

1. type_text("dp100magic-ascii-2037") → 记事本文档内容**始终不变**(UIA 直读 `\rdp测试串72633\rdp测试串72633`);
2. 探针实证:`probe.activate(hwnd)=True` 且 `GetForegroundWindow()==目标 hwnd`(窗口确在前台);`ctrl+v` 后内容仍不变——**前台≠编辑控件有焦点**;
3. 对照组:UIA `SetFocus()` 到 DocumentControl 后 `ctrl+v` → **粘贴成功**(内容尾部追加 `spy-focus-7702`,直读)——焦点假设坐实;
4. 正面佐证:读回三级通道在真记事本全部健康(①ValuePattern ②TextPattern 均取到全文),fail-closed 链条按设计工作(不匹配→TYPE_MISMATCH,零谎报)——**本单不是读回的问题,是写入侧焦点前提缺失**。

## 2. 根因(机制层)

`_type_text`(executor/core.py)的粘贴前提链:置前窗口 → pyperclip.copy → ctrl+v。
缺一环:**窗口内键盘焦点落在哪个控件不受控**。Win11 记事本多标签形态下,程序
化 SetForegroundWindow 不把焦点放进编辑区(焦点可在标签条);ctrl+v 对非编辑
焦点控件是空操作。旧逐键路径同病(按键同样进空焦点),被 IME 问题掩盖;ISS-0100
§3a 桥接成功例证均发生在「焦点恰在编辑区」的会话(此前有过人工/键入交互)。
ISS-0100 C 的读回 fail-closed 把这个 latent 缺口从「静默丢字」变成「显式报错」
——信任面按设计工作,现在补写入侧前提。

## 3. 改法方向(待裁定,不自作主张)

- A. **粘贴前 SetFocus**:_type_text 在粘贴前对目标窗首个 Edit/Document 控件
  调 UIA SetFocus(无焦点控件则按现状尝试粘贴并交给读回兜底)——最小改动,
  与读回通道共用控件枚举;风险:SetFocus 对某些应用有选择副作用(全选态),
  需实测;
- B. 粘贴前 click 编辑区(物理点击获焦)——更重,有点击副作用面;
- C. A+读回轮询期内若首拍不匹配则补一次 SetFocus 重贴(把聚焦纳入重试语义)。

涉及写路径行为前提,按上报界线属设计级,请 sdfang 裁定。

## 4. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-22 | 建单。W6 事故链四层实证(粘贴落空/前台非焦点/SetFocus 对照成功/读回链健康);根因=写入侧焦点前提缺失;改法 A~C 待裁定 |
