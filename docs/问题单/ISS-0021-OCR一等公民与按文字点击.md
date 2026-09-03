# ISS-0021：OCR 一等公民——click_text 按文字点击与坐标系元数据

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0021 |
| 标题 | AI 被迫手算"图像像素→虚拟坐标"（外部实测：坐标换算是 AI 最易错环节）；引入 click_text 执行原语与 screenshot 坐标元数据 |
| 严重级 | **高**（AI 友好度瓶颈；外部 40 次调用实录的最高杠杆改进点） |
| 状态 | **建单，待评审** |
| 提出 | 2026-09-03（另一个 Claude 驱动 deskpilot 40 次调用给 agent-browser 提 issue 的复盘反馈；审计 audit-20260903.jsonl 全程实录） |

## 1. 问题现状

1. **读写割裂**：自绘 UI（浏览器/加速器）UIA 树为空，唯一可靠定位是
   OCR 坐标；但 OCR 产物（文字+像素框）与执行原语（click 虚拟坐标）
   之间没有桥，AI 必须手动做缩放换算（外部实录：窗口矩形两次 attach
   间从 [-7,0,967,1087] 漂到 [10,10,955,1070]，截图分辨率与窗口矩形
   不总是 1:1，每次点击前被迫 find_window+OCR 双重校验）。
2. **无换算依据**:screenshot 响应只给图像宽高（实证：`{"width":800,
   "height":500}`),不给像素→虚拟坐标的 scale/offset,AI 只能猜。

## 2. 根因分析

| # | 根因 | 说明 |
|---|------|------|
| R1 | **缺"按文字寻址"的执行原语** | OCR 是只读通道；读到文字≠能点文字，中间隔着坐标数学 |
| R2 | **screenshot 响应缺坐标系元数据** | 图像像素与虚拟桌面坐标系的换算参数未随图下发 |

## 3. 整改方案

| 项 | 内容 |
|----|------|
| A | **新工具 `click_text`**：参数 `{text, token, match("contains"\|"exact",默认 contains), index(int,默认 0), button("left"\|"right",默认 left)}`。流程：绑定校验→窗口实拍→OCR（复用 ISS-0008 懒加载通道）→文本匹配→命中框中心→按窗口 rect/图像尺寸换算虚拟坐标→click→before/after 证据图。级别 L2,`BINDING_REQUIRED` |
| B | **fail-closed 三分支**：未命中→`OCR_TEXT_NOT_FOUND`+OCR 文本摘要（前 20 词）；多命中未指定 index→`OCR_AMBIGUOUS`+各命中坐标列表；text 为空→`INVALID_PARAMS`。**多命中默认绝不放行**,index 显式指定才执行 |
| C | **screenshot 元数据**：响应 data 增加 `virtual_rect/scale_x/scale_y`（窗口 scope 取绑定窗 rect;fullscreen scope 取虚拟桌面全集）——已有 width/height，补齐换算全要素 |
| D | **工具描述**:click_text 写明"能用文字定位就不要手算坐标";click 描述补"坐标为虚拟桌面坐标系，先读 screenshot 元数据换算" |

### 约束

- OCR 复用现有懒加载通道，**零新依赖**；命中框中心必须落在绑定窗口
  rect 内，越窗即拒（防 OCR 误识别到窗口外内容）;
- click_text 与 click 同闸：绑定/白名单/急停/级别照常，**不绕任何闸**;
- 坐标换算只认同一实拍图的图像尺寸与同一时刻窗口 rect（先拍后算，
  禁止跨调用复用 rect)。

## 4. 测试设计（五要素）

层级：单元（OCR 通道注入替身，不 mock 产品函数）+ 集成（真 daemon+真记事本）。

| 用例 | 场景 | 前提 | 步骤 | 预期结果 | 断言代码 |
|------|------|------|------|----------|----------|
| TC-CT-01 | 单命中点击（单元） | 假 OCR 返回 [{text:"保存",box:(100,50,160,80)}]；绑定 rect (1000,1000,1800,1600)；图像 800×600 | `click_text(text="保存",token)` | 执行器收到 click，虚拟坐标=(1130,1065)（框中心+rect 偏移） | `executor.instructions[0]["params"]` 的 x==1130、y==1065（直出） |
| TC-CT-02 | 缩放换算（单元） | 图像 400×300、rect 800×600(scale=2);box 中心 (65,32) | 同上 | 坐标按 scale 放大：(rect_l+130, rect_t+64) | instructions 坐标直出 |
| TC-CT-03 | 未命中（单元） | OCR 无该文本 | click_text | `OCR_TEXT_NOT_FOUND`,**零 click**,错误带 OCR 摘要 | reason_code 直出；`executor.instructions==[]`（终效应） |
| TC-CT-04 | 多命中不放行（单元） | 两处"保存" | ①未指定 index ②index=1 | ①`OCR_AMBIGUOUS`+坐标列表，零 click;②点击第二处坐标 | ①reason_code+instructions 空；②坐标直出 |
| TC-CT-05 | 空文本（单元） | text="" | click_text | `INVALID_PARAMS` | reason_code 直出 |
| TC-CT-06 | 越窗拒绝（单元） | box 中心换算后落在 rect 外 | click_text | 拒绝且零 click | reason_code+instructions 空（直出） |
| TC-CT-07 | screenshot 元数据（集成） | 真 daemon 绑定真窗口 | screenshot scope=window | data 含 image_width/image_height/virtual_rect/scale_x/scale_y；且 scale_x×image_width≈rect 宽（±1px) | 响应体字段与数值直出 |

> 自检校准点（v0.2):daemon 已 PMv2 DPI 感知，理论 scale≡1.0;GetWindowRect
> 含 DWM 阴影边框可能致 ±7px 偏差。实施时先实测 _capture 实际行为：
> scale 恒 1 则断言改 ==1.0 精确值（更严）;有固定 inset 则按实测值断言，
> 并把 inset 写入 virtual_rect 语义注释。不允许为迁就实现放宽成"差不多"。
| TC-CT-08 | 真机 OCR 点击（集成） | 真记事本窗口，UIA 可查 | click_text(text="文件") | 记事本文件菜单展开 | UIA 树出现展开的 Menu 控件（系统外表面直出） |

装配守门（R1~R5):R1 executor/OCR/binding 真替组合入矩阵；R2 单元层
替身只注入 OCR 通道接缝，不 mock 产品函数；R3 instructions/响应体做
形态断言；R4 无持久化路径变迁；R5 集成层终效应=菜单展开（UIA 外表面）。

## 5. 施工接缝与装配矩阵(v0.2 评审稿——代码现场勘察后钉死)

### 入口链(全实名)

```
mcp_server TOOL_SCHEMAS["click_text"] 注册(描述/参数形态)
  → tools/__init__.py 新增 click_text(ctx, *, token, text,
      match="contains", index=0, button="left")  → call_tool
  → enforcement.submit(L2,与 click 同闸:绑定/白名单/急停)
  → executor.execute({"tool":"click_text", params:{...}})
  → Executor._click_text: _capture(绑定 rect)→ocr(region)→
      resolve_click(...)→pyautogui click→before/after 证据图
```

| 接缝 | 现场 | 用途 |
|------|------|------|
| `resolve_click(items, query, match, index, img_w, img_h, rect)` 纯函数(新) | 新模块级函数(executor 侧) | OCR items→点击坐标/失败分类,**零 I/O,单元主战场,断言全在返回值** |
| OCR items 契约 | `{"text": str, "position": [x1,y1,x2,y2]}`(main.py:153-171 `_build_ocr_engine` 平铺包围盒) | 假 OCR 注入按此形态构造 |
| `Executor.ocr(source)` | executor/core.py:161;`_ocr_engine` 可注入(core.py:63 注释"测试接缝") | 集成层注入假引擎/真引擎两档 |
| 错误码 | `OCR_TEXT_NOT_FOUND` / `OCR_AMBIGUOUS` 入 errors.py + ALL_REASON_CODES | fail-closed 三分类 |
| `models.TOOL_LEVELS` / `BINDING_REQUIRED_TOOLS` | models.py | click_text 注册 L2+必绑定 |
| screenshot 元数据 | executor screenshot 返回 data(已有 width/height)同点增补 `virtual_rect/scale_x/scale_y`;mcp_server.py:310/332 仅 b64 包装不动 data | TC-CT-07 断言点 |
| click_text 响应 data | `{"status","target":[x,y],"matched","before_shot","after_shot"}` | 落点坐标直出,供 AI 自检 |

### R1 装配矩阵

| 用例 | executor | OCR | daemon | 断言面 |
|------|----------|-----|--------|--------|
| TC-CT-01~06 | 不需(纯函数) | 合成 items | 不需 | resolve_click 返回值 |
| TC-CT-07 | 真 | 不需 | 真(port=0) | HTTP 响应体字段+数值 |
| TC-CT-08 | 真 | 真引擎(RapidOCR 懒加载) | 真(port=0) | 响应 ok + data.target∈rect |

### TC-CT-08 修正(v0.1 菜单展开断言作废)

Store 记事本 UI 随版本漂移,"文件菜单展开"不是通用终效应(违反通用性
原则)。改为:真记事本 type_text 写入独特字符串 ` dp测试串2099`→
`click_text(text="dp测试串2099")`→**响应 ok 且 data.target 坐标∈
窗口 rect**(响应直出)。终效应=真实 OCR 命中+真实点击落点,与应用
UI 结构无关。

### R4 路径变迁

无持久化路径变迁(证据图走既有受管目录)。

## 6. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-03 | 建单(现状/根因/方案/测试设计),待评审 |
| v0.2 | 2026-09-03 | 施工接缝全实名(OCR 契约/错误码/装配矩阵);TC-CT-08 改通用终效应;sdfang 指示做测试设计+自检 |
