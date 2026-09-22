# ISS-0104:【设计引入】type_text 粘贴前未聚焦编辑控件——窗口前台但焦点在标签条时粘贴落空

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0104 |
| 标题 | `_type_text` 只 `_activate_if_needed` 置前窗口,不保证键盘焦点在编辑控件上;Win11 记事本(多标签)等窗口焦点可在标签条/非编辑区,ctrl+v 粘贴落空——ISS-0100 C 的 fail-closed 如实拦下(TYPE_MISMATCH),但写操作本身失败 |
| 严重级 | **高**(写操作正确性:与 ISS-0100 同一信任面;实盘实证) |
| 状态 | **已关闭**(2026-09-22 验收通过:SetFocus后粘贴真实落入+读回一致;sdfang 缺席授权自决,证据见 手工测试计划-20260922-四单整改升级验收 W5 + tests/test_typefocus_iss104 TC-104-03) |
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
| v0.2 | 2026-09-22 | sdfang 裁定改法=**A(粘贴前 SetFocus)**;落位设计+测试设计 3 用例+交叉面(§5/§6) |
| v0.4 | 2026-09-22 | **P3 完成回填**。①实现落点(executor/core.py):新增 `_focus_first_edit(hwnd)`(复用 ControlFromHandle+_iter_controls+_EDIT_TYPE_NAMES,取第一个命中节点 SetFocus,无命中/异常吞掉不阻断——聚焦是成功率优化,fail-closed 由读回保证);`_type_text` 在首次 activate 后、进入粘贴循环前调用一次(重贴不重复聚焦,选择态副作用最小化;§5 裁定 A 严格落位)。②测试数字:P1 基线 901 绿 1 红;P3 后受影响面(test_typefocus_iss104+test_typeguard_iss100)**10 passed 2 skipped**;全量默认层 **902 passed 0 failed**。③**TC-104-03 逃逸口实证(ISS104_FORCE_E2E=1,真 daemon 9420 在线)**:W6 正向路径**产品面全绿**——种子文本+SetFocus TabItem 前提(焦点在标签条)下,daemon type_text 返回 ok:true+note=「读回校验一致」,残留窗标题实证种子+魔法串均已落入文档(SetFocus 生效,粘贴不再落空);连续两轮复现。④**停手汇报项(测试卫生尾,非产品)**:TC-104-03 收尾 `assert closed` 在本机确定性红——Store 记事本未保存 '*' 在工具 type_text 后 ~3s 内不消退,_close_all_and_wait 的 5s 自动保存等待耗尽 → WM_CLOSE 触发 XAML 内嵌保存提示模态阻塞(helper 的「不保存」处置仅覆盖经典 #32770 对话框,不覆盖 Store XAML 提示);ct08 同类流程历史上靠 OCR 长浸泡(10s+)让自动保存先行消退而遮掩。根因=本测试键入到关窗之间无浸泡(P1 写法),与产品行为无关(产品断言已全绿)。按「测试不动」裁决未改测试,建议授权:测试 finally 前加 ~8s 自动保存浸泡(对齐 ct08 自然浸泡语义),或由人类裁定接受该环境下本用例以产品断言为准。**(2026-09-22 浸泡修正已授权落地,但实证无效,待二次裁决**:finally 关窗前 time.sleep(8.0) 已按授权加入(断言零改动);逃逸口复跑 closed 仍红——硬实证:本机 Store 记事本未保存 '*' 30s 持续观察不消退,更早残留 10+ 分钟亦不消退(helper 注释的「自动保存使 * 消退」前提在本机当前记事本版本/设置下不成立,浸泡任何时长均无效);对照实证:WM_CLOSE 后 UIA Invoke XAML「不保存」按钮(提示三键序位第二)4+ 次全部可靠关窗。**【收口】二次裁决方案①已落地并全绿(2026-09-22)**:保留浸泡,其后加测试局部 `_dismiss_xaml_save_prompt()`(WM_CLOSE→UIA 找提示三键 保存/不保存/取消→Invoke 序位第二,仅本测试 finally,共享 helper 未改,断言零改动)。逃逸口实证 `ISS104_FORCE_E2E=1 -k tc104_03` **1 passed(16.16s,产品断言+closed 收尾全绿)**;全量默认层 902 passed 0 failed;实证残留复核为零(桌面仅存用户既有窗)。**)⑤ISS-0105(选读自证假阳性)按裁决不在本单修,实现未触碰选读通道。⑥实证残留已全部清理(含 XAML 保存提示处置),桌面仅存用户既有窗 |
| v0.3 | 2026-09-22 | **P1 完成+P2 核对**。P1 实证:全量 901 绿+1 红(TC-104-01 红在无聚焦步,TC-104-03 逃逸口实证 TYPE_MISMATCH 复现 W6,TC-104-02 绿=行为保持面正确落点)。P2 核对:三用例入口/断言出处/五要素与设计一致,不一致 0 项。P2 裁决:①**相邻缺陷另立 ISS-0105**(选读通道「空文档+焦点落空」自证假阳性——读回读到自己写的请求文本;双闸门缺陷先立单,改法待裁定);②TC-104-03 前提形态批准(种子文本+SetFocus TabItem 外部驱动,被测链零打桩,同 ct08 先例);③前台锁瞬态波动知悉(非测试逻辑) |
| v0.5 | 2026-09-22 | **验收通过关单**(sdfang 离场留言授权自决,记录在案)。证据:手工测试计划-20260922-四单整改升级验收 W5 + tests/test_typefocus_iss104 TC-104-03,SetFocus 后粘贴真实落入+读回一致 |

## 5. 落位设计(裁定 A,P3 实现依据)

- `_type_text` 粘贴序列改为:_activate_if_needed → **SetFocus 首个 Edit/Document 控件**(复用 `_iter_controls`+`_EDIT_TYPE_NAMES` 枚举,取第一个命中节点调 `SetFocus()`,异常吞掉=聚焦失败不阻断) → pyperclip.copy → ctrl+v → 读回(既有三级通道兜底不变);
- **无 Edit/Document 控件**:不执行 SetFocus,按现状粘贴并交读回兜底(行为与现版一致,READBACK_UNAVAILABLE 面不回退);
- 聚焦失败(SetFocus 抛异常):不阻断,交读回兜底(fail-closed 语义由读回保证,聚焦只是成功率优化);
- 副作用登记:SetFocus 可能改变目标控件选择态(如全选),属裁定接受的交互副作用;type_element(SetValue 通道)不动。

## 6. 测试设计(五要素+交叉面)

| 用例编号 | 层级 | 测试场景 | 测试前提 | 测试步骤 | 测试预期结果 | 断言代码(断什么/由什么直出) |
|---------|------|---------|---------|---------|-------------|---------------------------|
| TC-104-01 | 单元 | 粘贴前聚焦编辑控件 | UIA 替身:首个 Edit 节点 SetFocus 桩可记录;桥替身(iss100 风格) | _type_text(text) | SetFocus 被调一次且**先于** hotkey(ctrl,v) | 统一调用序列桩记录直出(focus 序位 < hotkey 序位) |
| TC-104-02 | 单元 | 无编辑控件不聚焦不崩 | UIA 替身:树内零 Edit/Document;桥替身 | 同上 | SetFocus 零调用;流程照常进粘贴+读回兜底(行为与现版一致) | 桩零调用记录直出;异常/返回与 READBACK_UNAVAILABLE 面一致 |
| TC-104-03 | 集成 | 真记事本(焦点在标签条)全链 | 真 Win11 记事本;环境守卫 | attach+type_text 魔法串 | ok 且 note=「读回校验一致」(W6 正向路径补验) | 响应体 ok/note 直出 |

### 交叉面清单(§2.1)

| 触及对象 | 其他写入者/读取者 | 覆盖用例 | 或豁免理由 |
|---------|-----------------|---------|-----------|
| _type_text 粘贴序列 | TC-100-01/02/04/07(iss100 钉) | 全量回归 | 仅插入聚焦步,读回/重试/还原不动 |
| _iter_controls/_EDIT_TYPE_NAMES | _read_edit_value 共用 | 回归(test_typeguard_iss100) | 复用不改 |
| SetFocus 副作用(选择态) | 目标应用 UI 态 | TC-104-03 实盘 | 裁定接受,登记 §5 |
| TC-100-04(无编辑控件 READBACK_UNAVAILABLE) | 与 TC-104-02 同前提 | TC-104-02+回归 | 行为不回退 |

### 测试退役/适配登记(双闸门)

无退役无放宽:既有钉全保留;TC-104-02 与 TC-100-04 前提相同断言互补(一个钉零聚焦调用,一个钉 READBACK_UNAVAILABLE 码),不冲突。
