# ISS-0100:【待评审】type_text 纯 ASCII 逐键路径被中文 IME 吞改,读回校验未拦报 ok

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0100 |
| 标题 | `type_text` 对纯 ASCII 文本走逐键模拟(executor/core.py:1179「ASCII 逐键模拟;非 ASCII 走剪贴板桥」),目标窗口中文 IME 激活时,按键被输入法组合成候选字——实发内容≠请求内容;工具自报「带读回校验」却返回 ok:true,乱码落地且被 ctrl+s 存盘 |
| 严重级 | **高**(写操作正确性:AI 自报成功但落地内容错误——AI 友好/可信面根基;附实证) |
| 状态 | **P3 实现完成(2026-09-22),待验收** |
| 提出 | 2026-09-21 demo.gif 英文版录制实拍:请求 "Hello from DeskPilot - typed by AI, approved by a human." 落地为「HellofromDeskPilot - typed不要AI， approv二点不要啊胡曼。」并被保存进 %TEMP%\demo-notes.txt |

## 1. 实证链(全部直读)

- 请求文本(驱动脚本逐字):`Hello from DeskPilot - typed by AI, approved by a human.`
- daemon 取证(audit/shots/20260921/093813_before_key_93328.jpg):记事本
  编辑区=`HellofromDeskPilot - typed不要AI， approv二点不要啊胡晏。.`
  (47 字符);机制吻合:IME 组合期吃空格/大小写,拉丁串拼为候选汉字
  (by a→不要,human→胡曼 等);
- 磁盘证据:%TEMP%\demo-notes.txt 内容=同款乱码(69 字节,09:37 写入,
  ctrl+s 落盘);
- 工具返回:`{"ok": true}`(type_text 自报成功,读回校验未识别偏差)。

## 2. 根因(机制层)

两层失守:
1. **通道选择**:ASCII→逐键模拟的设计(某些应用不吃粘贴)在「IME 激活」
   这一桌面常态下失效——逐键流进 IME 组合器,出来什么由词库决定;
2. **校验失明**:读回校验未比对「请求文本 vs 落地文本」即报 ok——
   校验读的是什么、为何没拦,待查(可能读到的是剪贴板/焦点控件
   的快照而非最终合成结果)。

## 3. 改法方向(待裁定,不自作主张)

- A. type_text 全量改走剪贴板桥(任何文本),ASCII 逐键路径废止——
  简单一致,但失去「不吃粘贴的应用」兼容面;
- B. 逐键前探测目标焦点 IME 态,激活则先切英文(shift)再逐键——
  保双通道,探测成本与误判率待评;
- C. 读回校验修真:比对落地文本与请求文本(fail-closed,
  不一致即报 TYPE_MISMATCH 类新码),通道行为不变;
- D. B+C 组合。

涉及工具行为契约(写正确性语义),按上报界线属设计级,请 sdfang 裁定。

## 3a. 补充实证(2026-09-21 下午,demo 录制事故链)

1. **shift 预切 IME 英文态不可靠**:批次实测 shift → 立即 type_text
   (ASCII)→ 落地仍乱码「He来咯fromDeskPi咯他-typed 不用AI，
   approved不用啊胡曼。」——方向 B 的根基动摇(切换时序/按应用 IME
   状态记忆均不可控);
2. **读回校验对记事本根本不执行**:type_text 返回
   `note: "读回校验不可用（目标无 UIA 值模式）"`——Win11 记事本编辑器
   无 UIA ValuePattern,校验静默跳过却仍报 ok:true。描述「带读回校验」
   对这类目标名不副实——这与其「吞改」是同一信任面的两块;
3. **剪贴板桥逐字可靠**(对照组):文本含非 ASCII(破折号 —)时
   type_text 自动走剪贴板桥,落地逐字(daemon 取证照+磁盘文件双证),
   支持方向 A 的可行性。

## 4. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-21 | 建单。录制事故全盘实证(请求/落地/磁盘/返回值四对照);根因两层(通道选择+校验失明);改法 A~D 待裁定 |
| v0.2 | 2026-09-21 | 补三条实证:shift 预切 IME 不可靠(方向 B 动摇);读回校验对记事本根本跳过(「带读回校验」名不副实);剪贴板桥逐字可靠(对照组,方向 A 可行性) |
| v0.3 | 2026-09-22 | sdfang 裁定改法=**A+C 组合**:type_text 全量走剪贴板桥(ASCII 逐键路径废止)+读回校验修真(比对落地 vs 请求,fail-closed,不一致报 TYPE_MISMATCH 类新码);B/D 废止(shift 预切实证不可靠) |
| v0.4 | 2026-09-22 | **落位设计定稿**(§5:读回三通道序+不可用独立新码 READBACK_UNAVAILABLE);**测试设计 9 用例+交叉面清单**(§6/§7);退役/适配登记(§8)。测绘补获:逐键分支零测试钉(废止零误伤);读回失败现用 INTERNAL_ERROR 泛码;iss21/iss27 真记事本集成用例是 C 的最大连带面(P3 实证 TextPattern 可用性后定) |
| v0.6 | 2026-09-22 | **P3 完成回填**。①实现落点(executor/core.py):删 ASCII 逐键分支(全量走桥,docstring 翻页);读回失败 INTERNAL_ERROR→TYPE_MISMATCH;读回三通道全灭 raise READBACK_UNAVAILABLE(fail-closed,删「不可用仍 ok」放行路径,消息指引 screenshot 自核);`_read_edit_value` 扩三级通道序(ValuePattern→TextPattern→选读 ctrl+a/ctrl+c,选读覆盖剪贴板由桥 finally old_clip 还原覆盖);`_node_text`/`_read_via_selection` 新增;ELEMENT_UNSUPPORTED 引导句「键盘路径」→「剪贴板路径」(:969,:788/:944 同类措辞按裁决不动,另案)。详设翻页:§14.5 输出项 type_text 行补登两码、§14.6 表述与规则表翻页、附录 A 两码行+计数 29→31(P1 已落)。②**实机取证两条(P3 测绘新发现,实现据此落地,测试替身缝未变)**:a) uiautomation 2.0.29 的 ControlTypeName 带 Control 后缀(EditControl/DocumentControl)且 ValuePattern.Value/TextPattern.DocumentRange 为属性非方法——既有 `("Edit","Document")` 谓词+`.Current.Value` 访问在本库版本**从未命中**,通道①实为死代码(读回失明的更深一层根因);实现按双形态兼容(裸名=设计/替身缝,后缀名=真机;DocumentRange callable 双形)。b) **TextPattern 归一化换行**:真记事本 GetText(-1) 把 CRLF 呈现为孤立 (实测 repr 'dp探测串99999'),原样子串包含对多行文本必误报——双侧换行归一(_normalize_newlines)后比对,仅统一换行表示,乱改字符仍必拦(登记待人类复核)。③测试数字:P1 基线 876 绿 9 红;P3 后受影响面(test_typeguard_iss100+test_textchannel_iss35+test_bigtext_iss45)**17 passed 1 skipped**(TC-100-08 环境守卫 skip=真 daemon 在线);全量默认层 **885 passed 0 failed**;全量 --run-integration 903 passed 3 failed——bm03/fuzz04/ct08 三条经 git stash 基线对照为**既有环境红**(真 OCR/桌面/计时;ct08 基线与现码同一断点同一签名「未找到文本 dp测试串」,且现码下其 type_text 步骤已真实通过=通道②真记事本实盘取证成功,红在后续 OCR 步骤)。④登记项:TC-TX-02/TC-45-02 适配(§8 已登记)P3 转绿;P2 裁决四项全部照办(UIA 缝/raise 形态/文案范围 :969-only/附录 A §14.5 补登)。⑤待验收事项:TC-100-08 真记事本端到端(集成层)需无 daemon 环境或打包后手工测试取证(真 daemon 为 dist 旧码,不含本实现) |

## 5. 落位设计(P3 实现依据)

### 5.1 A:逐键路径废止
- 删 `executor/core.py:1182-1184` ASCII 逐键分支,全量进剪贴板桥(桥本体:1186-1231 保留,暂存/粘贴/轮询/重试/finally 还原语义不动);
- 文案对齐:`core.py:1179` docstring、详设 §14.6(:1422「非 ASCII 分支」表述)、type_element 引导语「键盘路径」→「剪贴板路径」(`core.py:969`、`mcp_server.py:207`);
- type_text 描述「带读回校验」保留——修真后名实相符。

### 5.2 C:读回校验修真
- **比对失败**:重试耗尽后 `INTERNAL_ERROR` → 新码 `TYPE_MISMATCH`(errors.py 常量+详设附录 A 表行+计数 29→31+§14.5 输出项,iss74 钉守口径);
- **读回通道扩展**(`_read_edit_value`,core.py:1409-1424)三级序:
  ① ValuePattern(现状,Edit 类);
  ② **TextPattern**(Document 类,Win11 记事本富文本编辑器预期走此——`GetText(-1)` 取全文);
  ③ **选读通道**(前两路无值且存在 Edit/Document 控件时):ctrl+a + ctrl+c 读剪贴板比对,读后还原(finally 还原语义须覆盖本通道——选读会覆盖剪贴板中的请求文本,还原目标=暂存的 old_clip,语义不变);
- **仍不可用**(三通道全灭,目标无 Edit/Document):fail-closed 新码 `READBACK_UNAVAILABLE`,**不再 ok:true 放行**;消息如实说明「目标无可读回通道,落地内容未经校验」并指引 AI 用 screenshot 自核(感知面自核,项目既有哲学);
- 比对语义保留子串包含(读回=窗口全部 Edit/Document 值拼接,请求文本应出现其中)。

### 5.3 不做的事
- 不动粘贴时序/轮询缩放(ISS-0045)/重试上限;不动闸三按键许可(粘贴 ctrl+v 本就走 executor 内部,不触发审批);不动 type_element 的 SetValue 通道(不同病)。

## 6. 测试设计(五要素)

| 用例编号 | 层级 | 测试场景 | 测试前提 | 测试步骤 | 测试预期结果 | 断言代码(断什么/由什么直出) |
|---------|------|---------|---------|---------|-------------|---------------------------|
| TC-100-01 | 单元 | 纯 ASCII 全量走桥 | 替身 pyperclip/pyautogui/_read_edit_value(命中) | _type_text(text="Hello ASCII") | pyperclip.copy 被调;pyautogui.write **零调用**;返回 mode="clipboard" | 桩调用记录直出;返回值直出 |
| TC-100-02 | 单元 | 读回不匹配报新码 | 替身 _read_edit_value 恒返不匹配 | _type_text(中文走桥) | 重试耗尽抛 ExecutorError,code==TYPE_MISMATCH | 异常对象 code 属性直出 |
| TC-100-03 | 单元 | TextPattern 读回通道 | UIA 替身:ValuePattern 抛异常、TextPattern.GetText 给值 | 调 _read_edit_value | 返回 TextPattern 文本(非 None) | 返回值直出 |
| TC-100-04 | 单元 | 三通道全灭 fail-closed | 替身:目标无 Edit/Document(三通道全不可用) | _type_text | ok False,error_code==READBACK_UNAVAILABLE;**不再 ok:true+note**;old_clip 已还原 | 返回值/异常直出;pyperclip 桩还原调用记录直出 |
| TC-100-05 | 形态 | 新码登记口径 | 源码直读 | 读 errors.py | 含 TYPE_MISMATCH、READBACK_UNAVAILABLE 常量 | 源码文本检索直读(附录 A 一致性由 iss74 既有钉守) |
| TC-100-06 | 形态 | 逐键分支消亡 | 源码直读 | 读 core.py | 无 `pyautogui.write`;docstring 无「ASCII 逐键」 | 源码文本检索直读 |
| TC-100-07 | 单元 | 选读通道(第三级) | 替身:ValuePattern/TextPattern 均无值,存在 Edit 控件;pyautogui/pyperclip 桩 | _type_text | 触发 ctrl+a/ctrl+c 选读;比对命中则 ok+note「读回校验一致」;剪贴板还原 | 桩热键调用序列直出;返回值直出 |
| TC-100-08 | 集成 | 真记事本读回真实发生 | 真 Win11 记事本(无 ValuePattern);环境守卫 | attach+type_text 魔法串 | ok True 且 note=「读回校验一致」(TextPattern/选读通道实盘取证) | 响应体 note/ok 直出 |
| TC-100-09 | 形态 | 描述面名实相符 | 源码直读 | 读 mcp_server.py/core.py | type_element 引导语无「键盘路径」;type_text 描述 ≤200(ISS-0015 闸门既有钉守) | 源码文本检索直读 |

## 7. 交叉面清单(§2.1)

| 触及对象 | 其他写入者/读取者 | 覆盖用例 | 或豁免理由 |
|---------|-----------------|---------|-----------|
| 系统剪贴板 | 桥写(copy text)/桥还原(finally old_clip);**新写入者=选读通道 ctrl+c** | TC-100-04/07(还原断言) | 还原目标=old_clip,语义不变 |
| pyautogui.write 其他调用点 | key 工具走 press/hotkey,不用 write(测绘 §1) | TC-100-06 形态钉 | — |
| ISS-0045 轮询缩放/重试 | test_bigtext_iss45 TC-45-01(缩放) | 全量回归 | TC-45-02 适配见 §8 |
| INTERNAL_ERROR 既有断言 | TC-TX-02(test_textchannel_iss35)、TC-45-02 | — | 适配 TYPE_MISMATCH,§8 登记 |
| iss21/iss27 真记事本集成 | assert ok True(依赖「不可用仍放行」) | TC-100-08 接替实证 | TextPattern 不可用则**上报裁决**,不私改 |
| type_element 引导语断言 | test_elements:261/475(message 含「type_text」) | 全量回归 | 只改「键盘路径」措辞,type_text 字样保留 |
| 描述 ≤200 闸门 | test_tool_descriptions_iss15 | 全量回归 | — |
| 附录 A 计数 29→31 | test_errorregistry_iss74 | 全量回归(自动守) | — |
| type_text 审批文案(enf.act.type_text) | enforcement.py:536-544/i18n.yml:179 | 全量回归(test_approval_readability_iss20) | 行为不变 |

## 8. 测试退役/适配登记(双闸门·登记闸)

| 用例 | 处置 | 放宽原因+不再探测的行为 |
|------|------|------------------------|
| test_textchannel_iss35 TC-TX-02 | 适配:INTERNAL_ERROR→TYPE_MISMATCH | 泛码换专用码(C 修真);「不一致必失败」语义不放宽 |
| test_bigtext_iss45 TC-45-02 | 适配:同上 | 同上 |
| test_clicktext_iss21:196-215/test_selfheal_iss27:114-130(集成) | 优先不动(TextPattern 可用则自然绿);不可用则上报裁决 | 「不可用仍 ok」是被本单判死的行为,不得为其放宽断言;若 TextPattern 实证不可用,由人类裁决目标控件或降级通道 |
| (无) | 逐键分支零测试钉(测绘实证) | 废止 A 无需退役任何用例 |

## 9. P1/P2 记录(2026-09-22)

**P1 实证**:全量 `876 passed + 9 failed`(红=TC-100-01/02/03/04/06/07/09+适配两条 TC-TX-02/TC-45-02,全部精确落在未实现行为;TC-100-05 绿;TC-100-08 环境守卫 skip);旧用例零误伤。

**P2 逐用例核对表**:

| 用例 | 入口(与设计一致?) | 断言值出处 | 五要素 | 结论 |
|------|------|-----------|--------|------|
| TC-100-01 | _type_text ✓ | 桩 copy/write 记录+返回值 mode 直出 | ✓ | 一致 |
| TC-100-02 | _type_text ✓ | 异常 code 属性+hotkey 计数直出 | ✓ | 一致 |
| TC-100-03 | _read_edit_value ✓ | 返回值直出(GetText(-1) 缝内联校验) | ✓ | 一致(缝约定见裁决①) |
| TC-100-04 | _type_text ✓ | 异常 code+copy 序列(还原)直出 | ✓ | 一致(形态裁决②取 raise) |
| TC-100-05 | errors.py 源码 ✓ | 文本检索 | ✓ | 一致(绿,P1 空壳+附录 A 同步,保 iss74 钉) |
| TC-100-06 | core.py 源码 ✓ | 文本检索 | ✓ | 一致 |
| TC-100-07 | _type_text+真实 _read_edit_value ✓ | hotkey 序列/返回值/还原记录直出 | ✓ | 一致 |
| TC-100-08 | POST /call type_text ✓ | 响应体 ok/note 直出;环境守卫先例 | ✓ | 一致 |
| TC-100-09 | core.py/mcp_server.py 源码 ✓ | 文本检索+描述长度直出 | ✓ | 一致(范围收窄裁决③) |

交叉面逐行确认:剪贴板新写入者(TC-100-04/07 还原断言)✓;pyautogui.write 调用点(TC-100-06)✓;ISS-0045 缩放(回归+TC-100-02 重贴计数)✓;INTERNAL_ERROR 断言(§8 适配)✓;iss21/iss27(TC-100-08 接替)✓;type_element 引导语(回归)✓;≤200 闸门(TC-100-09)✓;附录 A 计数(iss74 钉)✓。不一致 0 项。

**P2 裁决四点**:①UIA 缝约定定案(GetValuePattern/GetTextPattern 便捷口+DocumentRange().GetText(-1)),P3 按缝实现;②TC-100-04 失败形态定案 raise ExecutorError(与 core.py:1224 既有形态及 TC-100-02 一致,工具层统一转 ok:false);③TC-100-09 钉范围收窄定案(:969 引导句+mcp_server 全文);core.py:788/:944 的「键盘路径」措辞属相邻面,**记录不顺手改**(范围控制),另案评估;④附录 A 两码表行随 P1 空壳落地备案(保 iss74 钉红在正处)。
