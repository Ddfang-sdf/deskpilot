# ISS-0114:【修改引入】type_text 聚焦助手抢焦点——ComboBox 类输入目标(浏览器地址栏等)粘贴落空

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0114 |
| 标题 | ISS-0104 引入的 `_focus_first_edit` 无条件对窗口内首个 Edit/Document 控件 SetFocus;当用户/AI 已把焦点放在**非首个**可输入控件(典型=Firefox 地址栏 ComboBoxControl)时,聚焦助手把焦点抢回页面 Document,粘贴落空、读回比对页面文本报 TYPE_MISMATCH——修复「无焦点」变成了「抢焦点」 |
| 严重级 | **高**(写正确性:浏览器地址栏/运行框/搜索框等 ComboBox 输入面全灭;修改引入类,先认账) |
| 状态 | **建单待评审**(2026-09-24 Firefox 实测抓出;改法方向待裁定) |
| 提出 | 2026-09-24 REQ-005 Firefox 实测:type_text 写 Firefox 地址栏 TYPE_MISMATCH,逐层定位实证 |

## 1. 实证链(2026-09-24,全部直读)

1. 点击 Firefox 地址栏(2912,62)→ 焦点实测 = **ComboBoxControl**「使用百度搜索，或者输入网址」(建议下拉已弹出,焦点成立);
2. type_text("www.bing.com") → 地址栏**仍为空**(截图直读占位符未变);
3. `_focus_first_edit` 模拟走查:首个 Edit/Document = **DocumentControl「新标签页」(页面)**——SetFocus 把焦点从地址栏抢到页面;
4. 读回 fail-closed 如实拦下:TYPE_MISMATCH「粘贴读回校验不一致且重试耗尽」;
5. 对照组:焦点留在地址栏(ComboBox)时 set_clipboard+ctrl+v → **粘贴成功**,enter 后必应加载(文档树出现「必应 - Microsoft 搜索」)——验证改法方向。

## 2. 根因(机制层)

ISS-0104 的聚焦助手隐含假设:「焦点必然不在任何可输入控件上(须我代劳)」。
它解决的问题(记事本焦点在标签条)是**焦点在非输入区**的场景,但实现没有
先回答「当前焦点是否已经可输入」。ComboBox(地址栏/运行框/搜索框)不在
`_EDIT_TYPE_NAMES`(Edit/Document)内,于是「焦点已在地址栏」被判成「无
编辑焦点」→ 抢回首个 Document(页面)。

## 3. 改法方向(待裁定,不自作主张)

- A. **有焦点则不抢**:聚焦助手先查当前焦点是否在可输入控件集合
  (Edit/Document/**ComboBox**)上——已在则不 SetFocus,仅当焦点不在任何
  可输入控件时才聚焦首个 Edit/Document;
- B. A + 可输入集合扩 ComboBox(同时影响读回通道的控件谓词,需评估);
- C. 回退 ISS-0104 为「仅当窗口无 Edit/Document 命中焦点模式」的窄化版本。

涉及写路径行为前提,按上报界线属设计级,请 sdfang 裁定。

## 4. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-24 | 建单。Firefox 地址栏事故链五步实证(ComboBox 焦点/抢焦模拟/落空截图/TYPE_MISMATCH/绕过对照组);根因=假设缺「焦点已可输入」分支;改法 A~C 待裁定 |
