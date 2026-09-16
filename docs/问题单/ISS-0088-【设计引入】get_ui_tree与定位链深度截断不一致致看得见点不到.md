# ISS-0088:【设计引入】get_ui_tree 与定位链深度截断不一致(10 vs 8)——AI 在树上看得见、click_element 却点不到

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0088 |
| 标题 | `get_ui_tree` 走 `_walk`(深度上限 **10**),`click_element`/`get_clickable_map` 的解析链走 `_iter_summaries`(深度上限 **8**)——同一棵树两个深度口径。画图形状钮的内层 `ButtonControl` 位于深度 9:树上可见、SoM 不编号、点击 ELEMENT_NOT_FOUND,只有其深度 8 的 `ListItemControl` 外壳可被(名字路径)点中。**AI 按树上读到的 `control_type` 去点,必然踩空** |
| 严重级 | **中**(可达性+AI 可发现性缺陷:UIA 可见元素的类型信息把 AI 引向一条必然失败的寻址路径;安全面无影响) |
| 状态 | 建单待评审 |
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

## 6. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-15 | 建单。实证链:树上可见(depth 9)→ 类型路径 ELEMENT_NOT_FOUND → 名字路径命中 ListItem(depth 8);深度截断 8 vs 10 两行源码定位;版本差嫌疑经 merge-base 排除;测试设计遗漏认账(浅 fixture + 无跨工具一致性用例) |
