# agent-browser 浏览器画 UML 能力边界摸底报告

| 项 | 内容 |
|----|------|
| 日期 | 2026-09-17 |
| 执行人 | Claude Code(CLI 通道,`agent-browser.exe --namespace uml`) |
| 被测对象 | agent-browser 安装二进制 v0.37.1(本地源码仓 v0.38.0:`C:\code\workspace\agent-browser`) |
| 主测站点 | draw.io(app.diagrams.net,kennedy 极简 UI,中文);辅测 excalidraw.com |
| 服务问题单 | ISS-0090 §3 解除暂缓条件 1(三技术形态摸底);战略分叉「联邦 vs 收编」的裁定输入 |
| 存证 | `docs/调研附件/shot-15~18.png`(四图共存/时序图/类图+时序目验/excalidraw 矩形) |

## 0. 结论摘要(裁定级)

1. **agent-browser 能在浏览器里画 UML——四类图全部完成**(流程图/时序图/类图/用例图),且有**两条互补通道**:DOM 手工几何通道(四图全通)与**文本驱动 mermaid 通道**(时序/类图原生语义,draw.io 内发现)。
2. **文本驱动通道是最大发现**:kennedy UI 隐藏经典菜单栏 → 排列 → 插入 → Mermaid… → 对话框 textarea 写入 mermaid 源码 → 插入,一次性产出带完整 UML 语义的图(消息实/虚箭头、继承空心三角)。**连续 3 次插入全成功**,为全测试中最可靠的成图通道。它翻转了两项先前结论:①「时序图消息边手工不可连」(三机制全死)→ mermaid 原生携带消息边;②「kennedy 文本驱动通道死证链」(ctrl+shift+x 死/Extras 无 Edit Diagram/window.ui 无)→ 经隐藏菜单 Mermaid 路径**活着**。
3. **三技术形态**(ISS-0090 §3 条件 1)摸底完毕:文本驱动(draw.io 内 mermaid)✓✓;SVG/DOM 驱动(draw.io 手工)✓(消息边手工✗,mermaid 补偿);canvas 驱动(Excalidraw)✓ 基元放形、✗ 无文本通道、✗ 无原生 UML 语义。
4. **能力边界**:不可手工连时序消息边(三机制死证);canvas 内无 DOM 结构(只能像素级操作);截图像素与 client 坐标存在 ~1.34x 比例偏差(一切鼠标目标只信 DOM eval 坐标);合成事件菜单通道不稳定(派发序列状态依赖、弹层重复)。
5. **战略建议(供 sdfang 裁定)**:证据满足 ISS-0090 §1 联邦条件(「能画」)。建议联邦,且路由指针写明**文本通道优先(draw.io 插入>Mermaid)、手工几何兜底**;联邦前提是 agent-browser MCP 通道可靠性修复(本次全程走 CLI 正因 MCP 会话僵死,见 ISS-0084 族/本次窗口前史)。

## 1. 测试通道与方法

- **通道**:全程 CLI(Bash 调 `agent-browser.exe --namespace uml <cmd>`),MCP 路线因 default 会话僵死判死(继承结论);`tab new` 开新站规避 `open` 卡死(excalidraw 一次成功)。
- **断言谱系**(按强度):DOM eval 几何(getBoundingClientRect/g[transform]/svg text)→ 手柄扫描(svg image width≤18 鉴别顶点/边)→ 合成事件弹层枚举 → screenshot 目验(第二位置参数存盘)。
- **坐标铁律**:screenshot 像素与 client 坐标 ~1.34x 比例+偏移(shot-15 目验:class 框截图宽 215px vs eval 160)——**一切鼠标目标只信 DOM eval client 坐标,禁从截图量坐标**。
- **顶点 vs 边鉴别法**:落位后扫 svg image 手柄——8×18px resize 柄+旋转柄=顶点;2 端点柄+中点柄=边。

## 2. 画图矩阵(四图)结论

| # | 图型 | 结果 | 证据 |
|---|------|------|------|
| 1 | 流程图 | ✓ | StartNode+终止节点+水平边 g1(351,471,529x9);搜索框命名通道+stencil 拖拽 |
| 2 | 时序图 | 手工:lifeline✓+activation✓+**消息边✗**;mermaid:**✓✓** | lifeline(561,231,100x200)×2+activation×4;消息边三机制全死(§4-4);mermaid sequenceDiagram 产出 request 实箭@598,788+response 虚箭@593,832(shot-16/17) |
| 3 | 类图 | 手工✓;mermaid✓ | 手工:class1/class2(160x86 三舱)+关联边 g16(661,339,189x9);mermaid classDiagram:Animal 三舱框(451,660,143x144)+成员 svgtext+**继承边(515,804,13x50 空心三角)**(shot-17) |
| 4 | 用例图 | ✓(actor 按指示跳过) | 2 椭圆(140x70)+关系边 g17(741,741,159x9) |

四图共存存证:shot-15(手工态)、shot-17(手工+mermaid 混合态目验)。

## 3. 三技术形态摸底(ISS-0090 §3 条件 1)

| 形态 | 代表站 | 成图能力 | 文本/模型通道 | UML 原生语义 |
|------|--------|----------|--------------|--------------|
| 文本驱动 | draw.io 内 mermaid | ✓✓ 时序/类一次成型 | **✓**(插入>Mermaid… textarea) | ✓(消息箭/继承三角/隔间) |
| SVG/DOM 驱动 | draw.io 手工 | ✓ 四图 | 同左(mermaid 即其文本面) | 手工拼装,连接边受限于连接点机制 |
| canvas 驱动 | excalidraw.com | ✓ 基元放形(矩形工具+拖拽,shot-18) | **✗**(主菜单枚举:保存到/协作/重置/Excalidraw+/社交项,无导入/插入文本条目) | ✗(仅通用形状;UML 须手工拼) |

- 未测项(如实记录):mermaid.live / plantuml 外站、tldraw。战略问题(「能否画 UML」)的结论不依赖二者:文本形态已由 draw.io 内 mermaid 代表,canvas 形态已由 excalidraw 代表。
- canvas 形态附加发现:画布无每形状 DOM 节点(选择手柄为 canvas 像素),断言只能靠截图/导出;工具栏按钮为具名 DOM(矩形/菱形/椭圆/箭头…),放形链路=DOM 点工具+canvas 坐标拖拽。

## 4. 通道机制与可靠性发现全集

1. **坐标比例陷阱**:screenshot 像素≠client 坐标(~1.34x+偏移);铁律见 §1。
2. **搜索框命名通道**:侧栏 INPUT(110,68) click→ctrl+a→keyboard type→enter;结果网格 a.geItem(38x36)。**搜索后 settle→双枚举一致→再拖**(网格异步 reflow)。
3. **连接点拖拽**:矩形 4 connpts/椭圆 8 connpts 可连;lifeline 0 connpts。
4. **消息边三机制死证**:①连接点拖拽(lifeline 无连接点);②形状缘直拖(no-op);③自由端点手柄吸附——**阳性对照拖到可连的 class1 左缘亦拒=经鼠标原语普遍不可操作**(非 lifeline 特异)。
5. **合成事件隐藏菜单通道(不稳定)**:kennedy 隐藏经典菜单栏(a.geItem@0,0)对合成事件响应但序列状态依赖:mousedown 单发曾成功一次(「其它」);其后同法全死;**mousedown+mouseup+click 三连成功**(「排列」×2,副作用=弹层重复开 2 份)。旧弹层未关会拦截后续派发;escape 关不掉 mxPopupMenu,真实点击空白可关;插入完成后弹层自动清。
6. **mermaid 文本通道(最可靠)**:排列→插入→Mermaid…→textarea 写值(eval 直写+input/change 派发,避开键盘换行问题)→点插入→对话框自动关闭、图落画布。连续 3 次(sequence/class/前置探查)全成功。对话框控件:SELECT[绘图]+预览/关闭/插入(1244,691)。
7. **kennedy 文本通道死路由**(被 #6 部分翻转,仍成立的路由):ctrl+shift+x 无响应;「其它」菜单=主题/语言/外观/单位/绘图语言/折叠/动画/提示/配置(**无 Edit Diagram/XML**);window.ui/editor/actions=undefined;mxGraph/mxUtils 类全局在但**无实例**;container 无 mxGraph expando。
8. **画布状态波动**:paths 计数随选中态 ±2(overlay);escape 不取消刚落位选中;press delete/ctrl+z 可用;lifeline 组 textContent 空。
9. **eval 教训**:`"x="+a.join()||"NONE"` 恒 truthy(join 优先级 bug);absPoints 判废无效教训(顶点无 absPoints,边才有——判废须 typeof 直测)。
10. **CLI 命令谱**:eval/mouse move|down|up/press/screenshot <path>/tab new/keyboard type;**无 wait_for_selector**(MCP 有、CLI 无)。
11. **open 卡死规避**:`tab new <url>` 一次成功(excalidraw);继承结论:`open` 在僵死会话下卡死。
12. **MCP 通道可靠性**(继承):MCP server 会话僵死/config 指纹死循环/timeoutMs 不生效——本次全程 CLI 的根因,亦为联邦方案的先决修复项。

## 5. 能力边界总结(AI 视角)

- **能做**:四图成图(手工);mermaid 文本成图(UML 原生语义);DOM eval 全谱断言;具名控件点击(工具栏/菜单/对话框);新 tab 多站;canvas 站基元放形。
- **不能做**:手工连时序消息边(#4-4);读 canvas 内部结构(仅像素/OCR/导出);在无文本通道的站做文本成图(excalidraw);稳定使用合成事件菜单(#4-5,需试错序列)。
- **高风险陷阱**:截图量坐标(#4-1);网格 reflow 时序(#4-2);弹层残留拦截(#4-5);选中态计数波动(#4-8)。

## 6. 联邦 vs 收编建议(供裁定,不代裁)

- **证据面**:「能画」成立(§0-1),ISS-0090 §1 联邦条件满足。
- **建议联邦**,理由:①mermaid 文本通道使 UML 成图收敛为「文本→图」单步,DeskPilot 无需自建浏览器操作层;②draw.io 手工通道兜底文本通道覆盖不到的编辑;③收编成本=重做 CDP 操作层+文本通道,无增量价值。
- **路由指针写法建议**(ISS-0090 #2 具名化时):浏览器画 UML → 优先 agent-browser 操作 draw.io 的「插入>Mermaid」文本通道;手工几何为兜底;canvas 站(excalidraw/tldraw)仅基元放形、无 UML 语义,不作 UML 目标站。
- **先决条件**:agent-browser MCP 通道可靠性(§4-12)——联邦下 Claude 经 MCP 调用,本次 CLI 通道结论不自动传递到 MCP 通道;MCP 僵死族问题修复前,联邦路由指针应注明降级路径(CLI)。

## 7. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-17 | 摸底完成落档。四图矩阵收口+mermaid 文本通道发现(翻转消息边/文本通道两结论)+三形态摸底(draw.io 文本✓/DOM✓/excalidraw canvas 基元✓无文本通道)+可靠性发现 12 条+联邦建议。存证 shot-15~18 入 `docs/调研附件/` |
