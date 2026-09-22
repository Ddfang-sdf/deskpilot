# ISS-0055:【cleancode】Executor 上帝类——core.py 1138 行 59 方法六职族

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0055 |
| 标题 | executor/core.py 一个 Executor 类承担六职族:截图与证据图、键鼠原语与动词、文本输入与读回、UIA 元素树与寻址、桌面图标装配桥、遮挡/激活/边界守卫——1138 行 59 个 def,任何改动都在同一体内编译 |
| 严重级 | 低(可维护性;不阻断功能) |
| 状态 | 方案已设计,待 sdfang 评审排期(2026-09-22 方案落档,见「整改方案」章) |
| 提出 | 2026-09-10(cleancode 审查;度量:wc 1138 行 / grep 59 def,全库最大文件) |

## 现象与证据

- `deskpilot/executor/core.py` 1138 行、59 个方法;职族混居:
  截图族(_save_shot/_screenshot 系列)、鼠标族(_click/_drag/_scroll/
  _mouse_down/up/_hold/看门狗)、文本族(_type_text/_read_edit_value)、
  元素族(get_ui_tree/_find_elements/_resolve_typed_element)、图标族
  (list_desktop_icons 桥)、守卫族(_check_point/_check_occlusion/
  _activate_if_needed/_check_drag_end)。
- 伤害实证:本次 ISS-0044/0045/0047/0048 四个不相关修复全部改同一文件,
  提交无法按职责切开(发布期亲历)。

## 方向(排期后细化)

按职族拆模块(mouse.py/text.py/elements.py/screens.py/guards.py),
Executor 退化为装配与路由;`execute()` 分发表注册制。约束:公开入口签名
不动、测试零改动转绿为验收线。

## 评估记录(2026-09-17)

| 项 | 内容 |
|----|------|
| 现状核对 | 仍成立:core.py 1472 行(今日 ISS-0088/0091/0092 又添守卫),Executor 职责面=感知+写入+元素解析+截图证据+OCR/检测桥接 |
| 处置 | **保留排期**(大修级)。建议拆分面:感知(screenshot/ocr/tree)/写入(click/key/drag)/元素解析(_find/_invoke)/证据链(_save_shot)四个模块;须整套回归绿+打包验证。不建议在问题单清扫尾巴上做——风险收益不成比例,宜独立评审窗口 |
| 触发条件 | REQ-005(浏览器翻译层)若落地,执行层结构评审一并做 |

## 整改方案(2026-09-22 设计)

### 0. 现状复核(2026-09-22,行号证据)

| 项 | 建单(09-10) | 评估(09-17) | 今日实测 |
|----|------------|-------------|---------|
| core.py 行数 | 1138 | 1472 | **1620** |
| def 数 | 59 | — | **70**(类内 64 方法 + 模块级函数 3:`_normalize_newlines`:75 / `_failsafe_guard`:82 / `_strictly_inside`:95 + 嵌套 3) |
| 基线 | — | — | 默认层 **900 passed / 28 skipped(integration)**,928 collected,214s 实测绿 |

职族分布(今日行号,较建单新增守卫三处已并入):装配/路由(`__init__`:113、`execute`:183、`_dispatch`:634,15 工具 if 链)、感知/截图证据(`screenshot`:232、`_resolve_region`:1373、`_capture`:830、`_save_shot`:1404、`_save_shot_to`:1420、`_evidence_shot`:1459、`capture_approval_shot`:610)、OCR/检测/SoM 桥接(`ocr`:343、`_ensure_ocr_engine`:365、`_ensure_detector`:388、`template_match`:462、`get_clickable_map`:491)、元素族(`_element_root`:688~`_wait_for_element`:1002、`_walk`:1473、`_iter_controls`:1574、`_iter_summaries`:1585)、写入族(`_click`:1020、`_mouse_down/up/_hold`:1036-1064、`_drag`:1148、`_scroll`:1177、`_key`:1191、`_type_text`:1204、`_read_edit_value`:1502、`_click_text`:1081)、守卫族(`_check_point`:1298、`_check_drag_end`:1308、`_check_occlusion`:1328、`_activate_if_needed`:1268、`_binding_rect`:213)。

**问题单未覆盖的关联点(今日补查)**:

1. **测试钉面远大于公开入口**:108 个测试文件触及 executor;单测直接钉私有面——`ex._element_source` 注入 58 处、`ex._check_occlusion` 直调 11 处、`ex._type_text` 直调 8 处、`ex._shot_fn` 注入 14 处,另有 `_ensure_com`/`_pixel_click`/`_read_edit_value`/`_save_shot`/`_resolve_region`/`_activate_if_needed`/`_enum_monitors`/`_check_point`/`_click_text` 各 1-4 处直调/注入。
2. **模块级接缝被测试直接改写**:`core._occlusion_user32`(test_elevation_iss17:117、test_occlusion_iss42:29)、`core._com_initialize`(test_uia_com_iss16:34/47)——消费方搬走后赋值必须仍生效。
3. **源码形态钉两颗**:①test_cleancode_iss56_57_61.py::test_f56 直读 core.py 源码,断言 `except pyautogui.FailSafeException` **恰 2 处**且 `_failsafe_guard(` **≥7 处**——写入族迁出后 core.py 内调用点只剩 2 处,**必红**;②test_typeguard_iss100.py TC-100-06/09 为**负向**扫描(断言文本不存在),搬移不伤。
4. monkeypatch `core_mod.pyautogui.xxx`/`core_mod.time.sleep`(7 个文件)打在 pyautogui/time 模块对象上,与被测代码住哪个模块无关,搬移天然安全;`test_perf_iss8.py:278` patch `deskpilot.executor.core.subprocess.Popen`——`subprocess` 仅 `_dispatch` 内联 launch_app 使用,留 core 即安全。
5. main.py 装配面外露私有属性:`executor._mouse_watchdog.start()`(main.py:515)、`detector_factory`/`ocr_factory`/`weight_manifest`/`detector_threshold` 公开装配位(main.py:523/532)——拆分后实例属性名一个不能动。

### 1. 根因(机制层)

不是「文件碰巧变大」,是两条引力回路:

- **接缝单例引力**:`Executor.__init__`:113-179 集中持有全部测试接缝(probe/element_source/shot_fn/ocr_engine/audit/clock)+ 全部懒加载状态(OCR/检测器锁与失败记忆)+ 全部缓存(SoM/detect/按下表)。任何新能力要复用其中任何一项,最小代价路径就是往 Executor 上加方法——**状态没有族属边界,方法便向状态持有者聚集**。六职族共享同一 self,是「一个类」的结果不是原因。
- **钉面反引力**:58 处 `_element_source` 注入等私有面直钉,使「新加守卫继续在类内加 `_xxx`」成为唯一不破坏既有钉的写法;每单都在加(ISS-0088/0091/0092/0100/0102),9 个月 1138→1472→1620 行(+42%),且加速。发布期 ISS-0044/0045/0047/0048 四单同改一文件,是同一机制的合并冲突面显形。

### 2. 改法:六步「搬函数、留委托」(strangler fig)

总策略:Executor 保留**全部公开方法与被钉私有方法的名字、签名、形态(含 staticmethod)**,函数体逐族外迁为新模块的模块级函数(首参收 `ex`);类内方法退化为单行委托。跨族调用一律经 `ex._xxx(...)` 走委托门面——**新模块互不 import**,依赖图天然无环。模块级接缝(`_occlusion_user32`/`_com_initialize`)**留在 core.py**,消费函数体内延迟 `from . import core` 读属性——测试对 core 的赋值在调用前发生,语义等价(机制上唯一的非平凡点)。每步独立提交、独立验证;除标注外**全部为纯重构(行为不变)**。

| 步 | 内容 | 性质 | 验证 | 文件 |
|----|------|------|------|------|
| S1 | 守卫族→`executor/guards.py`:`_check_point`/`_check_drag_end`/`_check_occlusion`/`_activate_if_needed`/`_enum_monitors`/`_resolve_window`/`_binding_rect`;`_occlusion_user32` 留 core 延迟读 | 纯重构 | 默认层 900 全绿;重点 test_elevation_iss17 / test_occlusion_iss42 / test_drag_iss47 / test_clickguard_iss91(接缝等价性由此步钉死) | core.py +guards.py |
| S2 | 感知/证据族→`executor/screens.py`:`screenshot`/`_resolve_region`/`_capture`/`_save_shot`/`_save_shot_to`/`_evidence_shot`/`capture_approval_shot`/`get_cursor`/`get_clipboard`/`_region_dict` | 纯重构 | 全绿;重点 test_screenshot_scope_iss83 / test_shotpath_iss102 / test_monitors_iss7 / test_m3 | core.py +screens.py |
| S3 | OCR/检测/SoM 桥接→`executor/vision.py`:`ocr`/`_ensure_ocr_engine`/`_ensure_detector`/`template_match`/`get_clickable_map`/`_DEDUP_EXCLUDE_TYPES`;懒加载状态与装配位(ocr_factory/detector_factory/weight_manifest/detector_threshold)留实例不动 | 纯重构 | 全绿;重点 test_detector_orch_req03 / test_detector_cv_req03 / test_perf_iss8 / test_somcache_iss81 / test_clicktext_iss21 | core.py +vision.py |
| S4 | 元素族→`executor/elements.py`:`_element_root`/`_ensure_com`/`_find_elements`/`_resolve_unique_element`/`_hidden_hint`/`_candidate_names`/`_element_summary`/`_resolve_typed_element`/`_invoke_element`/`_click_element`/`_type_element`/`_wait_for_element`/`_walk`/`_iter_controls`/`_iter_summaries`/`_node_rect`/`get_ui_tree`/`list_desktop_icons`/`_UI_TREE_MAX_DEPTH`/`_strictly_inside`;`_com_initialize` 留 core 延迟读 | 纯重构 | 全绿;重点 test_elements / test_deeptree_iss88 / test_clicktarget_iss44 / test_clickguard_iss91 / test_uia_com_iss16 / test_desktop_icons_req02 | core.py +elements.py |
| S5 | 写入族→`executor/input.py`:`_click`/`_mouse_down`/`_mouse_up`/`_hold`/`_mouse_watchdog_tick`/`_force_release_button`/`_force_release_all`/`_drag`/`_scroll`/`_key`/`_pixel_click`/`move`/`_type_text`/`_read_edit_value`/`_node_text`/`_read_via_selection`/`_click_text`/`_normalize_newlines`/`_EDIT_TYPE_NAMES`/`_pyauto_key_alias` | 纯重构,但 **f56 形态钉必红**(core.py 内 `_failsafe_guard(` 跌至 2 处)——见裁决① | 全绿(f56 按裁决处置后);重点 test_mouse_req01 / test_textchannel_iss35 / test_typeguard_iss100 / test_bigtext_iss45 / test_clicktext_iss21 / test_startcall_iss52 | core.py +input.py(+f56) |
| S6 | 收口:`_dispatch` 15 连 if → 分发表 dict(tool→委托方法),未知工具错误消息(core.py:684)逐字不变;core.py 余量 ≈300 行(`__init__`/execute/分发表/接缝变量/64 委托);**打包验证**(PyInstaller 全量构建+冒烟,评估记录硬要求) | 纯重构(分发表为同语义替换) | 全绿 + 打包冒烟 + `from deskpilot.executor.core import Executor` 全消费方面(main/tools/enforcement/approval)实盘走一遍 | core.py(+dist 验证) |

落地后 core.py 预计 ~300 行,五族模块各 150-450 行,与既有 detector/mousehold/probe/textclick/desktop_icons 五兄弟模块形态一致(executor 包拆分文化已确立,本次是把内联六族按同形态外迁)。

### 3. 约束确认

- **fail-closed 不回退**:全部步骤为搬移,守卫判定逻辑(`_check_point`/`_check_occlusion`/`_check_drag_end`/读回三通道/检测器记忆化口径/落盘护栏闸序)逐字迁移,无一条语义改写;S6 分发表不改变任何工具的参数校验与错误码。
- **基线保持绿**:今日实测 900 passed/28 skipped 为验收基线;每步提交前全量跑一遍(214s),且 collected 数须恒为 928(防钉被意外 deselect)。
- **测试零改动为默认验收线**;唯一例外是 f56 形态钉的扫描面迁移(裁决①),按 SDD「测试放宽双闸门」先登记后执行——属形态钉扫描面随迁,非掩盖产品缺陷,无须另立缺陷单。

### 4. 测试设计要点

- **S1-S6 均为纯重构**:不新增用例;「既有钉全绿即证」。每步附**必绿钉清单**(见上表「重点」列),评审按清单逐文件确认,不只看总数。
- **f56 处置(若裁决①通过)**:先红后绿——S5 落地后 f56 红(扫描面过时,红在形态钉自身而非产品行为)→ 按登记改扫描面为 executor 包(core.py+input.py 合计,`except FailSafeException` 全包恰 2 处、`_failsafe_guard(` 全包 ≥7)→ 绿。用例五要素不变(场景/前提/步骤/预期/断言=源码文本计数直读),仅扫描面一行。
- **行为面新用例**:本方案无行为面步骤,无需新用例;若 S6 评审中任何人提出分发表顺带改消息/改序,立即停手另立范围(工作纪律:不顺手改)。
- **交叉面清单(§2.1)**:触及对象与覆盖标注——`_occlusion_user32`(写:test_elevation_iss17/test_occlusion_iss42;读:S1 后 guards;覆盖=S1 两钉绿)/ `_com_initialize`(写:test_uia_com_iss16;覆盖=S4 钉绿)/ `_UI_TREE_MAX_DEPTH`(读:_walk/_iter_summaries/_iter_controls;覆盖=test_deeptree_iss88)/ `_EDIT_TYPE_NAMES`(读:_read_edit_value;覆盖=test_typeguard_iss100)/ `_failsafe_guard` 调用面(覆盖=f56 处置)/ Executor 实例状态 13 项(_mouse/_mouse_watchdog/_som_cache/_detect_cache/_ocr_engine/_ocr_lock/_ocr_failed/_detector/_detector_failed/_detector_lock/_shots_dir/_allowed_roots/_probe 等,写读全在类内+main.py 装配;覆盖=test_mouse_req01/test_somcache_iss81/test_detector_orch_req03/test_shotpath_iss102 全绿)/ main.py 装配面 4 项(覆盖=S6 实盘+打包冒烟)/ 私有面直钉 30+ 处(覆盖=委托同名同签名,既有钉全绿)。

### 5. 工作量粗估

6 步;受影响文件 = core.py + 5 个新模块(S1-S5 各触 2 文件,S6 触 1 文件)+ f56 一个测试文件(若裁决①通过);其余测试/文档/装配代码 0 改动。逐步 0.5-1 人日(搬移+全量回归+评审),S6 加打包验证 +0.5 人日;**合计约 4-6 人日**(不含评审排期间隙)。

### 6. 风险点

1. **接缝双写地雷**(最大风险):`core._occlusion_user32`/`core._com_initialize` 若随迁新模块,4 处测试赋值静默失效(钉转绿假象——替身没装上,真 user32/COM 进了测试进程)。处置=留 core+延迟读,且 S1 首件事是跑 test_occlusion_iss42 证明赋值仍生效。
2. **f56 必红**:S5 无法绕开(见裁决①);若裁决不通,S5 收缩为「鼠标族迁、键盘/文本族留 core」,拆分不完整。
3. **委托面漂移**:30+ 处私有面直钉要求委托同名同签名同形态(staticmethod 4 个:`_region_dict`/`_node_rect`/`_node_text`/`_read_via_selection`);评审逐名核对。
4. **嵌套函数随行**:`_do_drag`/`_send`/`walker` 随宿主函数迁移,不单独处理。
5. **REQ-005 触发条件**(评估记录):浏览器翻译层若先落地,执行层结构评审应合并做——排期时确认先后。

### 7. 待人类裁决问题

1. **f56 形态钉**:是否允许其扫描面从 core.py 单文件扩为 executor 包(守护价值不变:全包恰 2 处 except+单点调用 ≥7)?(推荐:允许,按双闸门登记)若否,S5 收缩为仅迁鼠标族。
2. **分发表注册制**(原「方向」提出):S6 纳入本次,还是仅做搬移、分发表留待 REQ-005 评审?(推荐:纳入,同语义替换成本低)
3. **排期窗口**:维持 09-17 评估「独立评审窗口、不在问题单清扫尾巴上做」?是否与 REQ-005 结构评审合并?
4. **打包验证频率**:仅 S6 收口做(推荐),还是逐步做?

## 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-22 | 整改方案落档(本章「整改方案(2026-09-22 设计)」):现状复核 1620 行/70 def、机制层根因、六步「搬函数留委托」拆分(S1 守卫→S6 分表收口+打包验证)、f56 形态钉与模块级接缝两处处置、测试设计要点与交叉面清单、工作量 4-6 人日;状态推进为「方案已设计,待 sdfang 评审排期」。本单此前无变更记录表,随本次落档补建 |
