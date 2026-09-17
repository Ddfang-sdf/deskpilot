# ISS-0091:【设计引入】click_element 像素兜底无退化矩形守卫——误点屏幕原点 (0,0) 诱发甩角急停冻结

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0091 |
| 标题 | `_invoke_element` 像素兜底只挡 `rect is None` 不挡退化 rect(宽/高/面积=0),中心算得 (0,0) → 真实点击屏幕原点;原点恰为甩角判定点(CORNER_X=CORNER_Y=0),光标停角 ≥1s → 误触发「鼠标甩角」冻结。兜底路径同时缺落点/遮挡校验;`_find_elements` 无可见性过滤,不可见元素照常成为点击候选 |
| 严重级 | **高**(安全面:AI 写操作被误冻结 + 原点真实点击可误操作系统左上角组件;2026-09-16 内网实机故障链根因,与 ISS-0092 成对) |
| 状态 | **P3 完成待验收**(2026-09-17;自主推进授权下按 SDD P1红→P2核对→P3绿实施;全量回归 767 passed/23 skipped/0 failed;①③矛盾裁定 Option A、既有用例适配与描述压缩均备案于 §6 v0.2) |
| 提出 | 2026-09-16 内网实机故障取证(sdfang 报障:「我几乎确定了,就是点击的时候,会触发冻结」) |

## 1. 现象与证据

**实机症状**(内网机,v0.3.7,2026-09-16):
1. AI 调 click_element 频繁触发冻结,弹窗「触发:鼠标甩角」,人类未甩角;
2. key/type_text「也会触发」——实为光标已被前序 click 停在 (0,0),pyautogui 撞 FAILSAFE → EMERGENCY_STOP 报错映射(core.py:148-150、:841、:895、:1011、:1040、:1068),叠加甩角 1s hold 到期的时序伪相关;
3. 截屏「也触发」= 同一时序伪相关(截屏本身不动光标)。

**代码实证**:
- core.py:816-835 `_invoke_element` 像素兜底:仅 `rect is None` 走拒绝分支;rect=(0,0,0,0) 时中心=(0,0) → `_pixel_click(0,0)`(:837-841)真实点击;
- 退化 rect 守卫**只存在于** get_clickable_map(core.py:447),点击链路无;
- 兜底路径不经过 `_check_point`/`_check_occlusion`(对照 `_click` :881-896 与 :1137-1181)——落点在屏幕外/被遮挡/退化均不设防;
- core.py:650-684 `_find_elements` 无可见性过滤(IsOffscreen/零面积元素照常入候选);
- estop.py:72-82:光标「外→内」进角 + 停留 ≥ corner_hold_ms=1000(policy.yml:89,ISS-0028)→ `_trigger("鼠标甩角")`。(0,0) 正是判定点。

**证据缺口(如实标注)**:2026-09-16 14:39:50 实机触发(estop-state.json seq15)与本机制吻合,但属主进程(pid 50960,role=stdio)当天下午的审计未落 `C:\tools\deskpilot`(当日文件止于 11:15 上午)——该机存在第二份安装,触发前秒级的 click_element 调用记录在第二安装目录的审计里。**「本次触发由 click 缺陷所致」为强推断,待属主审计坐实**;机制本身(退化 rect → 点 (0,0) → 入角 → 冻结)为代码级实证。

## 2. 根因(机制层)

设计遗漏:像素兜底被定位为「UIA 点击失败时的保底」,但保底入口未做 fail-closed 守卫——**退化矩形是「元素不可操作」的明确信号,应拒绝并显式报错,却被当作可计算几何继续求中心**。原点又与甩角触发点重合,单点缺陷穿透两层:点击错位 → 急停误报 → AI 写操作全面拒绝。违反安全路径 fail-closed 原则(未覆盖情况=显式报错,禁止静默降级)。

## 3. 整改方向

| # | 方向 | 说明 |
|---|------|------|
| ① | **退化 rect 守卫** | `_invoke_element` 像素兜底:rect 宽≤0 或 高≤0(面积≤0)→ 不点击,返回显式错误码 `ELEMENT_RECT_DEGENERATE`(附元素标识+rect 读数,AI 可自诊) |
| ② | **兜底接入落点校验** | 兜底真实点击前走与 `_click` 相同的 `_check_point` + `_check_occlusion` 链路,校验失败显式拒绝 |
| ③ | **可见性过滤** | `_find_elements` 过滤或标注不可见元素(IsOffscreen/退化 rect),不再进入点击候选 |
| ④ | **描述随代码** | click_element 工具描述声明退化 rect/遮挡拒绝语义(文档随代码走) |

## 4. 测试设计(五要素;完整矩阵 P1 补齐)

**用例1(单元)退化 rect 拒点**
- 场景:_invoke_element 像素兜底遇退化矩形元素
- 前提:元素桩 rect=(0,0,0,0)(单元层允许打桩);pyautogui 打桩记录调用
- 步骤:调用 _invoke_element 执行 click
- 预期:显式错误 ELEMENT_RECT_DEGENERATE;零真实点击
- 断言:`err.code == "ELEMENT_RECT_DEGENERATE"` 且 `mock_click.call_count == 0`

**用例2(单元)落点被遮挡拒绝**
- 场景:rect 正常但中心点被遮挡
- 前提:元素桩 rect=(100,100,200,50);_check_occlusion 桩返回遮挡
- 步骤:调用 _invoke_element 执行 click
- 预期:拒绝,错误含遮挡语义;零真实点击
- 断言:错误码为遮挡类;`mock_click.call_count == 0`

**用例3(集成,真实窗口+真实文件)端到端不误冻结**
- 场景:真实 MCP 服务对退化 rect 控件调 click_element
- 前提:服务启动、未冻结;记录调用前光标读数(get_cursor)与 estop-state.json
- 步骤:MCP 调 click_element 指向目标控件;等待 2s(> corner_hold 1s)
- 预期:工具返回显式错误;光标位置不变;共享状态未冻结
- 断言:盘读 estop-state.json `frozen is False`;get_cursor 读数与调用前相等;响应体错误码 == ELEMENT_RECT_DEGENERATE

**用例4(黑盒回归)正常元素仍可点(防过修)**
- 场景:真实窗口(如记事本)click_element 正常按钮
- 前提:窗口 attach 成功,目标按钮 rect 正常且可见
- 步骤:click_element 点击;观察 UI
- 预期:点击成功、UI 状态变化
- 断言:工具返回成功;系统外表面变化(如对话框关闭/焦点切换)可观测

## 5. 约束

- fail-closed:退化 rect = 拒绝 + 显式报错,禁止静默点击、禁止静默跳过;
- 错误码 AI 友好:附读数、可发现、可自诊(记忆:AI 才是直接用户);
- 不改 get_clickable_map 既有退化 rect 守卫语义(core.py:447);
- 与 ISS-0092 成对:本单修「误触发源」,0092 修「触发后的状态机灾难恢复」;落点校验类能力不进工具、只做内部守卫(记忆:工具=物理层,判断归 AI——此处守卫属安全 fail-closed,非智能判断,不冲突)。

## 6. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-16 | 建单。内网实机故障取证:症状链(点击触发冻结/key与截屏伪相关)+ 代码实证(core.py:816-835/:447/:650-684/:148-150,estop.py:72-82)+ 证据缺口如实标注(属主当日审计在第二安装目录,待补) |
| v0.2 | 2026-09-17 | **P3 完成回填**。①设计勘误与裁定:用例2 rect (100,100,200,50) 高度为负系笔误→勘误 (100,100,200,150)(中心 (150,125)∈FIXTURE_RECT,_check_point 放行、遮挡桩可达);整改①③内在矛盾(③过滤退化 rect 则用例1/3 永远打不到①的兜底守卫)→**裁定 Option A**:③只滤 IsOffscreen=True,退化 rect 元素保留候选(Invoke-first 对折叠控件仍有效,过滤=过修),退化防护由①在像素兜底时刻(唯一动鼠标处)fail-closed;用例3 断言随裁定集合化:error_code∈{ELEMENT_RECT_DEGENERATE, ELEMENT_NOT_FOUND},任一层显式拒绝皆可,关键是不许静默成功点击。②实现落点:errors.py 新增 ELEMENT_RECT_DEGENERATE;core.py 八处(_invoke_element 重写=退化守卫在 _check_point **之前**——否则 (0,0) 先吃 OUT_OF_BOUNDS 错误码失真+校验链接入镜像 _click 的 ISS-0017 C 次序 check_point→激活→check_occlusion;_find_elements/_resolve_unique_element/_resolve_typed_element 加 visible_only;_click_element 三调用点 visible_only=True;_iter_summaries 独立防御读 IsOffscreen;_hidden_hint AI 友好增强=不可见命中时 NOT_FOUND 消息附自愈指引);mcp_server.py 描述随代码。③SDD 实证:P1 红(cg01/cg02 DID NOT RAISE——兜底真点 (0,0)/不调遮挡校验,复现缺陷机制)→P3 绿(tests/test_clickguard_iss91.py 2 passed 2 skipped,集成 cg03/cg04 需 --run-integration);全量回归 **767 passed, 23 skipped, 0 failed**。④既有用例适配备案:tests/test_elements.py::TestInvokeFallback::test_pixel_fallback 受整改②**设计授权的契约变更**影响(兜底从不调 _check_occlusion→必调),旧测试未桩致真实 ctypes WindowFromPoint 打到测试机前台窗口报 WINDOW_OCCLUDED;修法=单元层规则加 no-op 桩,**原断言不动**(兜底仍打出 click(135,125));「兜底确实调用遮挡校验」由 cg02 专测覆盖,非私改测试迁就实现。⑤描述长度闸门适配:整改④初稿 347 字符超 ISS-0015 既有质量预算(desc05/GOV01≤200,bound05≤260)→压缩至 200 字符整(拒绝语义短式「不可见/退化矩形/遮挡→错误码+自愈指引」,错误码全称与自愈指引由拒绝时错误消息承载);压缩保留全部必需子串(绑定/Windows/detect/get_ui_tree/som_id),三闸门复跑绿。⑥行号漂移:实施后 core.py 变长,_check_occlusion 由 :1167→约 :1260,后续引用以 grep 为准 |
