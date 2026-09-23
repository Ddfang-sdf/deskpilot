# ISS-0044：【AI友好】无文字图形定位困难——AI 坐标靠猜

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0044 |
| 标题 | 无文字图形(复选框/图标钮等)无精确寻址通道:OCR 无文字锚点、UIA 全树难辨认、SoM 限 UIA 可见、template_match 鸡生蛋——AI 只能按比例估位置→点击→看效果→调整,多次猜测 |
| 严重级 | **中**(AI 可用性核心缺口;sdfang 实证:"对于文字的坐标很轻易,但对于没有文字的图形坐标,定位非常困难") |
| 状态 | **已关闭**(2026-09-23 验收通过:CT-12 清桌面真机终验收 16 passed(test_clicktarget_iss44 --run-integration);sdfang 离场授权自决) |
| 提出 | 2026-09-08(sdfang 使用实证) |

## 1. 背景(实证与机制)

坐标映射本身不缺:screenshot 返回图像+virtual_rect+scale,
屏幕坐标=图像像素+virtual_rect 原点。缺的是**图形在图里的定位**:
| 通道 | 对文字 | 对无文字图形 |
|------|--------|-------------|
| OCR | [text,position] 直接给 | 无锚点 |
| UIA(get_ui_tree) | name 好认 | 全树翻找,unnamed 难辨认;自绘界面(Electron/游戏/画布)不可见 |
| SoM(get_clickable_map) | 编号标图 | 仅限 UIA 可交互元素 |
| template_match | 模板找图 | 鸡生蛋:无模板需先有图,无图需先知位置 |

## 2. 整改方案(已定,sdfang 2026-09-09 裁定:①+④ 互补双改)

| 子项 | 内容 | 业界依据 |
|------|------|---------|
| **G-01 ① UIA 过滤寻址** | `get_ui_tree` 增 `control_type` 过滤参数(子串大小写不敏感);`click_element` 增 `control_type`+`index` 寻址("第 N 个 X 类型";与 som_id 互斥,混传 INVALID_PARAMS) | 微软 UFO2 a11y 树优先 |
| **G-02 ④ 文字锚点偏移** | `click_text` 增 `offset`(left/right/above/below)+`distance`(像素,默认按常见 Windows 控件间距):OCR 定位标签文字框,落点=标签框边缘±偏移——复选框/单选"点标签旁边的框"主场景消灭 | UiPath Anchor Base 工业实证 |

**几何契约(G-02)**:offset=left → 落点 (标签框左缘−distance, 框垂直中线);
right → (右缘+distance, 中线);above → (水平中线, 上缘−distance);
below → (水平中线, 下缘+distance)。落点越窗/越屏走既有 _check_point/
_check_occlusion fail-closed 链。offset=None 默认零变化。

**补充设计钉(自检 v0.3 增补)**:
- get_ui_tree 过滤语义:walk 后过滤;**截断继承诚实**——树超 800 截断时
  过滤结果继承 truncated=true(AI 得知不完整);
- click_element:name 与 control_type 同传=**交集过滤**(名称子串∧类型子串),
  index 在交集内取;control_type 单独=类型过滤;
- click_text:offset 为 schema enum(left/right/above/below,非法值
  validate_call 拒绝零派发);distance 执行层校验 ≥1(0/负 INVALID_PARAMS)。

## 3. 变更记录

## 2.1 业界调研证据(2026-09-09,原文亲验)

| 业界路线 | 代表 | 关键证据(原文亲验/检索) | 对本单 |
|---------|------|------------------------|--------|
| 可及性树优先 | 微软 UFO2(UIA+CV 混合控件探测) | [UFO2: Desktop AgentOS](https://www.microsoft.com/en-us/research/publication/ufo2-the-desktop-agentos/) | 支持方向① |
| 锚点相对定位 | UiPath Anchor Base(RPA 工业成熟模式:找文字标签,操作相对图形) | 工业实证 | 支持方向④ |
| SoM 标记提示 | 微软 SoM(arXiv 2310.11441,840+ 引用) | **裸坐标直接输出效果差(REC 25.7);是标记而非坐标解锁定位**;deskpilot 已有 get_clickable_map(SoM 实现) | ⑥修正:纯网格不如语义标记;真问题=SoM 覆盖面从 UIA 扩到非 UIA |
| 纯视觉检测模型 | 微软 OmniParser(arXiv 2408.00203,191+ 引用;YOLOv8 图标检测+BLIP 图标描述+OCR+SoM) | V2 ScreenSpot-Pro SOTA 39.5%;**检测模型继承 YOLO 的 AGPL 许可**(与 deskpilot MIT 冲突) | ③' 候选需求(模型工程+许可地雷),不进本单 |
| 传统轮廓法 | REMAUI/Xianyu | **FSE2020 原文亲验**(Table 2,IoU>0.9):REMAUI F1=0.201、Xianyu F1=0.154——纯轮廓法死刑 | ③ 不做 |
| 组合方案(研究最优) | FSE2020(arXiv 2008.05132)作者方案 | 原文亲验(§4.2):GUI 专用自上而下传统法+ResNet50 分类器+EAST 文本检测,非文本 F1=0.523(vs 最优基线 0.438),全部 F1=0.573(vs 0.388) | 证明"检测模型路线"有效但属工程项目 |

**调研后决策收敛(待 sdfang 终审)**:本单 = ①UIA 过滤+类型寻址 + ④文字
锚点偏移(两个互补小改动,均有业界实证);③纯轮廓放弃(数据死刑);
③'检测模型+SoM 扩面 = 另立候选需求(许可/成本评审);⑤模板库不进;
②工作流指引顺手带。

## 3. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-08 | 建单(sdfang 使用实证+机制分析;方案候选待评审) |
| v0.2 | 2026-09-09 | 业界调研入单(§2.1,原文亲验);sdfang 裁定 ①+④ 收敛为本单方案(G-01/G-02),检测模型+SoM 扩面转候选需求单;几何契约定稿 |
| v0.3 | 2026-09-09 | sdfang 终审自检指令触发完备性审计:补 TC-CT-13(截断树过滤声明)/14(联合过滤)/15(offset/distance 非法零派发)/16(index+offset 组合)四场景,补充设计钉入 §2;用例 12→16 |
| v0.4 | 2026-09-09 | SDD 完成:P1 红(15 红)→P3 绿;三处修改引入被测试逮住并修复(缺 FakeProbe 注入 WINDOW_GONE/Invoke 路径断言修正/bindings+enforcement 装配缺失 500);R4 零计数变化(29 不变);描述双超长修剪(214/230→≤200);CT-12 真机终验收环境守卫跳过(桌面全覆盖),待清桌面跑。全量 599 过 17 跳 |

## 4. 测试设计(五要素,2026-09-09)

层级:单元(FakeElement/pyautogui/OCR 替身,断言=替身记录直出)+形态
+集成(真机 offset 落点对照 graphic_rect,--run-integration)。

| 用例 | 场景 | 前提 | 步骤 | 预期结果 | 断言代码 |
|------|------|------|------|----------|----------|
| TC-CT-01 | control_type 过滤命中 | 替身元素树:CheckBox×2+Button×1+Text×1 | get_ui_tree(control_type="checkbox") | 仅 2 个 CheckBox 返回(子串+大小写不敏感) | 替身元素清单直出 |
| TC-CT-02 | 过滤无命中 | 同上 | get_ui_tree(control_type="radio") | elements=[],count=0(查询空集如实,非错误) | 直出 |
| TC-CT-03 | click_element 类型+序号正面 | 替身两 CheckBox(rect 各不同) | click_element(control_type="CheckBox", index=1) | 点击落第 2 个矩形中心 | pyautogui 替身坐标直出 |
| TC-CT-04 | 序号越界 fail-closed | 仅 2 个 CheckBox | index=5 | ELEMENT_NOT_FOUND,零点击 | 异常码+替身零调用直出 |
| TC-CT-05 | control_type 与 som_id 混传 | — | 两参同传 | INVALID_PARAMS,零点击 | 异常码直出 |
| TC-CT-06 | schema 形态 | TOOL_SCHEMAS | 检查 get_ui_tree.optional.control_type、click_element.optional.control_type/index、click_text.optional.offset/distance | 形态齐 | 形态断言直出 |
| TC-CT-07 | offset=left 落点 | OCR 替身命中框 [200,100,260,120] | click_text(text, offset="left") | 落点=(200−默认 distance,110 垂直中线) | 替身坐标直出 |
| TC-CT-08 | offset 四方向换算 | 同上 | 依次 left/right/above/below | 左缘−d/右缘+d/上缘−d/下缘+d+中线对应 | 直出 |
| TC-CT-09 | offset 落点越窗 fail-closed | 命中框贴绑定窗左缘,左偏出窗 | click_text(offset=left) | OUT_OF_BOUNDS,零点击 | 异常码直出 |
| TC-CT-10 | 默认 offset 零变化 | 既有 click_text 链路 | 不传 offset | 落点=命中框中心(旧行为) | 既有回归 |
| TC-CT-11 | distance 自定义与默认 | 同上 | distance=50 / 缺省 | 偏移 50 / 默认值 | 直出 |
| TC-CT-13 | **截断树过滤声明**(自检增补) | 替身元素树 800+ 元素截断 | get_ui_tree(control_type="checkbox") | 过滤结果继承 truncated=true(AI 得知不完整,诚实) | 直出 |
| TC-CT-14 | **name+control_type 联合过滤**(自检增补) | 替身:"文件"Button×1+"文件"MenuItem×1+"编辑"Button×1 | click_element(name="文件", control_type="MenuItem") | 仅命中交集(名称子串∧类型子串)那条 | 替身点击坐标直出 |
| TC-CT-15 | **offset/distance 非法零派发**(自检增补,R7) | — | offset="leftside";distance=0/-5 | 前者 validate_call 拒绝(enum);后者执行层 INVALID_PARAMS;均零点击 | 异常码+替身零调用直出 |
| TC-CT-16 | **多命中 index+offset 组合**(自检增补) | OCR 替身两命中框 | click_text(text, index=1, offset="left") | 先 index 定位第 2 框,再左偏移落点 | 替身坐标直出 |
| TC-CT-12 | **真机终验收**(集成) | 真桌面;--run-integration | click_text("回收站", offset="above") → target 对照 list_desktop_icons 的 graphic_rect | target 落入 graphic_rect 内(锚点点中图形,两新能力联动) | 响应 target+graphic_rect 对照直出 |

### 交叉面清单(§2.1)

| 触及对象 | 其他写入者/读取者 | 覆盖 |
|---------|-----------------|------|
| TOOL_SCHEMAS(增参数,计数 29 不变) | validate/_input_schema(str/int/enum 既有类型)、描述质量测试 | TC-CT-06+回归 |
| get_ui_tree 签名加参 | tools/_run_sensing 调用点;test_elements 既有无参调用零变化 | TC-CT-01/02+回归 |
| executor._click_element | dispatch 链路;test_elements 打桩面 | TC-CT-03~05 |
| executor._click_text | dispatch 链路;textclick.resolve_click 纯寻址不动(offset 换算在执行层) | TC-CT-07~12 |
| 预算面 | 全部 L0/L2 既有档,无新增 | 豁免 |

### 装配守门五条(R1~R5)+完备性两道(R6/R7)

R1 装配矩阵:单元×11+形态×1+集成×1(--run-integration);无放宽。
R2 mock 边界:替身仅 UIA 根/pyautogui/OCR 接缝;被测过滤/寻址/换算
本体全部真实。
R3 形态断言:TC-CT-06。
R4 路径变迁表:①get_ui_tree 加参——tools 调用点同步传参,既有无参
调用零变化;②click_element/click_text 加参——默认零变化,既有用例
零修改;③TOOL_SCHEMAS 计数不变(29)。
R5 终效应断言:TC-CT-12(真机落点对照 graphic_rect,锚点命中图形终效应)。
R6 双映射:G-01→TC-CT-01~06/13/14;G-02→TC-CT-06~12/15/16——双向无孤儿。
R7 失效原因核对:TC-CT-04 预期 ELEMENT_NOT_FOUND(而非 INVALID_PARAMS);
TC-CT-05 预期 INVALID_PARAMS(混传);TC-CT-09 预期 OUT_OF_BOUNDS——
逐条失败机制与设计一致,P2 核对点。

### 双闸门

无放宽:既有用例零修改;无计数重指(29 不变)。

| v末 | 2026-09-23 | **验收通过关单**:CT-12 清桌面终验收绿(16 passed);环境=全窗最小化实盘 |
