# ISS-0088:【设计引入】get_ui_tree 与定位链深度截断不一致(10 vs 8)——AI 在树上看得见、click_element 却点不到

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0088 |
| 标题 | `get_ui_tree` 走 `_walk`(深度上限 **10**),`click_element`/`get_clickable_map` 的解析链走 `_iter_summaries`(深度上限 **8**)——同一棵树两个深度口径。画图形状钮的内层 `ButtonControl` 位于深度 9:树上可见、SoM 不编号、点击 ELEMENT_NOT_FOUND,只有其深度 8 的 `ListItemControl` 外壳可被(名字路径)点中。**AI 按树上读到的 `control_type` 去点,必然踩空** |
| 严重级 | **中**(可达性+AI 可发现性缺陷:UIA 可见元素的类型信息把 AI 引向一条必然失败的寻址路径;安全面无影响) |
| 状态 | **已关闭**(2026-09-22 验收通过:真画图深度链命中ButtonControl;sdfang 缺席授权自决,证据见 手工测试计划-20260922-批次②积压验收 X13) |
| 提出 | 2026-09-15 验收作业(画房子和树)实测暴露,sdfang 追问「为什么开发阶段没有发现」 |

## 1. 现象与证据(2026-09-15 实测,mspaint.exe 真机)

1. `get_ui_tree(hwnd)`:形状钮内层按钮 **可见**,报 `control_type="ButtonControl"`(如 `矩形` @ [514,82,534,102],**depth 9**);
2. `click_element(control_type="ButtonControl", name="矩形")` → **ELEMENT_NOT_FOUND**(候选列表里根本没有它);
3. `click_element(name="矩形")` → **ok**,但命中的是其外层 `ListItemControl`(depth 8,响应的 `element.control_type` 字段证实);
4. 同一 SoM 取图(`_iter_summaries`)里,这些深度 9 的按钮**也不进编号空间**——所以 SoM 图上形状钮无编号,与②同源。

**机制层根因(源码实证)**:
- `deskpilot/executor/core.py` `_iter_summaries`:`if control is None or depth > 8: return`(截断 8);
- 同文件 `_walk`(get_ui_tree 用):`if depth > 10 or len(nodes) >= 800: return`(截断 10);
- 画图 ribbon 的真实嵌套深度:窗口→Pane→Custom→Group→ScrollViewer→Group→List→ListItem→**Button = 深度 9**,正好卡在两口径之间。

**版本差嫌疑排除**:`git merge-base --is-ancestor` 实证 ISS-0044(类型寻址)已在 v0.3.6(dist)内,源码与 dist 同码——不是新旧包差异。

## 2. 为什么开发阶段没发现(测试设计遗漏,如实认账)

- 单测的 `FakeElement` 树全是**浅树**(深度 1~2),从未造过深度 >8 的树 → 截断差从未被触发;
- 没有「**get_ui_tree 可见 ⇒ click_element 可点**」的跨工具一致性用例 → 两口径各自单测都过,矛盾不暴露;
- 既有真机用例(CT-12 等)走的是 explorer 桌面图标,深度浅,没踩到 ribbon 深嵌套。

## 3. 整改方向(候选,评审裁定)

| # | 方向 | 说明 |
|---|------|------|
| ①(倾向) | **深度上限单源化并统一**:`_walk` 与 `_iter_summaries` 共用一个常量(取较深者,或按性能实测定),口径一致 | 消除「看得见点不到」;SoM 编号面随定位链一起加深 |
| ② | 维持两档,但 get_ui_tree 条目对超定位链深度的节点**标注「不可寻址」** | 保留性能考虑,但要在条目上加字段,键集变化牵动面大 |
| ③ | 配套:跨工具一致性测试(树上每个可交互类型+名称 ⇒ 可解析)入测试设计;深树 fixture(深度 9~10)入单测 | 无论①②都该补 |

**性能认账**:加深截断 = 更多 COM 往返;`_iter_summaries` 的一次成型(ISS-0008 P4)不受影响,量的增加须实测(画图全树 ~200 节点,深度 +2 的增量有限)。

## 4. 验收口径(要点,测试设计另立)

- 画图形状钮:`click_element(control_type="ButtonControl", name="矩形")` 与 name 路径**同目标同结果**;
- `get_ui_tree` 可见且可交互的节点,定位链**必然可达**(一致性断言);
- 既有 SoM/click 回归全绿;深树 fixture 覆盖 depth 9~10。

## 5. 约束

- 800 条节点上限(防爆炸)不动;
- 两截断口径统一后,`_iter_summaries` 的一次成型语义(ISS-0008 P4)不动;
- 实现走 SDD。

## 6. 测试设计(P1 前置,五要素;2026-09-17 补立)

**设计裁定备案(自主推进授权下自决)**:
- **方向①采纳**:深度上限单源化为模块级常量 `_UI_TREE_MAX_DEPTH=10`(取较深者),`_walk`/`_iter_summaries`/`_iter_controls` 三处共用——`_iter_controls` 是同族同根因(读回校验链同样在深度 8 截断),一并统一(范围注:同根因最小差);800 条防爆炸上限不动(§5)。
- **嵌套同名歧义化解(实现细节自决,验收「同目标同结果」的必要机制)**:加深后名字路径会同时看到外壳(ListItem,depth 8)与内层按钮(Button,depth 9)两个「矩形」精确同名匹配 → 歧义报错=名字路径回归。化解规则:匹配项中若某匹配存在「矩形严格内含且深度更深」的子孙匹配,祖先让位(最内层=最精确目标;Invoke-first+像素兜底保证点击几何等价);无内含关系的同名并列(兄弟)保持歧义报错不变;矩形缺失/相等(幽灵去重已滤)保守保留。
- **行为变化明示**:浅层嵌套同名(如 Button⊃Text「保存」)由原 AMBIGUOUS 报错变为解析最内层——几何等价(像素兜底落在同一控件中心),dt05 钉此新语义。
- **性能认账**(沿用 §3):仅深层树增加 COM 往返;一次成型(ISS-0008 P4)语义不动。

| # | 场景 | 前提 | 步骤 | 预期 | 断言(出处) |
|---|------|------|------|------|-----------|
| dt01(单元) | 深度9叶子名字路径可点 | FakeElement 深度9链(叶=ButtonControl「深层按钮」);真 Executor+元素源接缝 | execute(click_element name) | 命中叶子,Invoke 一次 | `r["status"]=="ok"`;`leaf.invoked==1`(替身记录直出) |
| dt02(单元) | 深度9叶子类型+名字路径可点 | 同上 | execute(click_element name+control_type) | 同目标命中 | 同上 |
| dt03(单元) | 嵌套同名同目标同结果 | ListItem「矩形」(depth8,外壳)⊃Button「矩形」(depth9,内含矩形) | get_ui_tree + 类型路径点击 + 名字路径点击 | 树见两者(既有);两路径都命中 Button | 树节点计数=2;两响应 `element.control_type=="ButtonControl"`;`button.invoked==2`;`shell.invoked==0` |
| dt04a(单元) | 深度10可达(统一上界) | 深度10链叶子 | click name | 命中 | `leaf.invoked==1` |
| dt04b(单元) | 深度11两表面同不可见(不过冲) | 深度11链叶子 | get_ui_tree + click name | 树不含;点击 ELEMENT_NOT_FOUND | 树节点名清单无该名;`pytest.raises` code==ELEMENT_NOT_FOUND |
| dt05(单元) | 浅层嵌套同名→最内层 | Button「保存」(depth1)⊃Text「保存」(depth2,矩形内含) | click name | 解析 Text(最内层) | `text.invoked==1`;`button.invoked==0`;`r["status"]=="ok"` |
| dt06(单元) | 兄弟同名保持歧义(防过修) | 两个并列「保存」(矩形互不包含) | click name | ELEMENT_AMBIGUOUS 不变 | `pytest.raises` code==ELEMENT_AMBIGUOUS |
| dt07(集成) | 真画图形状钮类型路径命中 Button | 真 mspaint;树上存在 depth≥9 ButtonControl 有名字(无则环境守卫 skip) | get_ui_tree 找目标 → execute 类型路径点击 | 命中 ButtonControl(非外壳) | `r["element"]["control_type"]=="ButtonControl"`(响应直出) |
| dt08(单元) | 800 防爆炸上限不动 | 801 个并列子节点 | get_ui_tree | truncated=True 且 ≤800 | 响应字段直出 |
| dt09(单元) | SoM 编号面随定位链加深 | 深度9链叶子(有矩形);_shot_fn 接缝替身图 | get_clickable_map | 编号条目含深层按钮 | `entries` 含 name=="深层按钮"(响应直出) |

## 7. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-15 | 建单。实证链:树上可见(depth 9)→ 类型路径 ELEMENT_NOT_FOUND → 名字路径命中 ListItem(depth 8);深度截断 8 vs 10 两行源码定位;版本差嫌疑经 merge-base 排除;测试设计遗漏认账(浅 fixture + 无跨工具一致性用例) |
| v0.2 | 2026-09-17 | **P3 完成回填**。①实现落点:core.py——模块级 `_UI_TREE_MAX_DEPTH=10` 单源常量,`_walk`/`_iter_summaries`/`_iter_controls` 三处共用(800 上限不动);新增 `_strictly_inside` 纯函数(矩形严格内含判据,缺失/相等保守 False);`_find_elements` 改集摘要并加嵌套同名让位过滤(存在「矩形严格内含且深度更深」子孙匹配的祖先出局;兄弟并列保持歧义)。②SDD 实证:P1 红六条——dt01/dt02/dt04a NOT_FOUND(深度>8 不可见)、dt03 类型路径 NOT_FOUND、dt05 AMBIGUOUS(2 匹配)、dt09 SoM 无深层条目;dt04b/dt06/dt08 红期即绿(边界钉正确就位);P3 绿(9 passed 默认跑);dt07 真机实测通过(真 mspaint 深度≥9 形状钮类型路径命中 ButtonControl,--run-integration 10 passed);全量回归 **793 passed, 25 skipped, 0 failed**(基线 784/24);零修复(P3 一次过)。③行为变化明示(设计授权内):浅层嵌套同名(Button⊃Text)由 AMBIGUOUS 变为解析最内层(dt05 钉住);既有 test_elements 歧义/幽灵去重/可见性用例全绿不回退。④§2 认账闭环:深树 fixture(深度 9/10/11)+跨工具一致性用例(dt03)已入测试套件——「开发阶段为什么没发现」的两条遗漏均补上 |
| v0.3 | 2026-09-22 | **验收通过关单**(sdfang 离场留言授权自决,记录在案)。证据:手工测试计划-20260922-批次②积压验收 X13,真画图深度链命中 ButtonControl |
