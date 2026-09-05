# ISS-0037：【AI友好】screenshot 感知自愈

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0037 |
| 标题 | AI 调用 screenshot 但图像不可见（客户端渲染故障等）时,工具不提供任何降级指引,AI 需自行摸索替代感知链,浪费多轮才发现"眼睛瞎了" |
| 严重级 | **中**（AI 友好整改,源自 ai-first-users 原则:工具应可发现、可自愈、可诊断） |
| 状态 | **建单,待评审** |
| 提出 | 2026-09-05(演示录制实证:sdfang 现场质询"为什么不反馈给我") |

## 1. 背景（实证）

2026-09-05 演示录制期间,本会话图像通道持续 `[Unsupported Image]`
(MCP 工具结果、Read 本地 PNG/缩小 JPEG 三个来源统一失败)。代码级验证
服务端无责:`mcp_server.py:321-328/343-348` 两路径均已附加合法
`ImageContent`(base64 PNG + 正确 mimeType),落盘文件 PIL 直读正常——
故障在客户端渲染管道。但 AI 首次调用截图后未获得任何"图像不可见"的
信号,盲目改用 OCR+像素扫描,多轮后才意识到视觉通道整体不可用,且
未向人类上报——sdfang 裁定:这是失职("一个人眼睛坏了会开口说,我没说")。

工具侧缺陷:感知类工具的响应不携带任何"此响应本应可见/不可见时的
替代路径"信息,盲眼的调用方无从自知。

## 2. 整改方案（三项,均可独立交付）

| 项 | 内容 |
|----|------|
| A | **vision_note 降级指引**:screenshot 响应 payload 增加 `vision_note` 字段,内容如"本响应附有图像内容块;若你无法查看图像,请改调 `ocr(source=<路径>)` 获取文字清单,或用 `get_clickable_map`/`get_ui_tree` 替代感知"——盲眼 AI 第一次调用即获替代链,零轮摸索 |
| B | **`ocr:true` 可选参数**:screenshot 一次调用同时返回图像 + OCR 文字清单(引擎复用,单轮感知到位,不依赖视觉通道可用性;消灭"截图→OCR 两轮+OCR 超时重试"链路) |
| C | **工具描述强化**:screenshot 描述明确"图像不可见时的降级路径"(当前仅 ocr 侧写了指引,截图侧缺) |

### 约束

- **不做落点校验等"判断"能力**——sdfang 裁定:工具=AI 的鼠标键盘,
  物理层只提供感知与动作原语,场景判断归 AI;
- 三项均为感知通道增强,不动审批/审计/证据链;
- 测试设计(五要素)于评审通过后产出。

## 3. 测试设计(五要素,2026-09-05)

层级:单元(Executor 层打桩截图 I/O+注入假 OCR 引擎)+ 形态断言(schema/校验/描述)。

### 实现契约(测试断言的目标形态)

- `executor.screenshot(scope, rect=None, window=None, ocr=False)`:
  - 返回 dict 增 `vision_note`(str,内含 `ocr(source=<本截图路径>)` 降级指引);
  - `ocr=True` 时附 `ocr_items`(OCR 引擎 items 直出);
  - OCR 失败:图像字段照常,附 `ocr_error`(显式 {code, message},禁止静默);
  - 默认 `ocr=False` 无 `ocr_items` 键;
- `TOOL_SCHEMAS["screenshot"]` optional 增 `ocr: ("bool",)`,description 增降级指引;
- `_check_type` 增 "bool" 严格分支(1/"yes" 拒绝——bool 是 int 子类陷阱)。

| 用例 | 场景 | 前提 | 步骤 | 预期结果 | 断言代码 |
|------|------|------|------|----------|----------|
| TC-SV-01 | vision_note 随截图返回 | Executor;_resolve_region/_save_shot 打桩(真写 10×10 PNG 至 tmp) | `screenshot("region", rect=[0,0,10,10])` | 返回 dict 含 vision_note:str,含 "ocr(source=" 与本截图路径 | 返回 dict 字段直出 |
| TC-SV-02 | ocr:true 附带文字清单 | 注入假引擎返回固定 items | `screenshot(..., ocr=True)` | `out["ocr_items"] == 固定 items` | 直出 |
| TC-SV-03 | 默认不 OCR(形态) | 同上 | `screenshot(...)` | `"ocr_items" not in out` | 键存在性直出 |
| TC-SV-04 | OCR 失败显式携带,图像不受损 | 假引擎抛 ExecutorError | `screenshot(..., ocr=True)` | 图像字段(path/width/height)齐全 + ocr_error.code/message 非空 | 直出 |
| TC-SV-05 | bool 参数校验 | validate_call+policy | `{"scope":"fullscreen","ocr":True}` 通过;`ocr=1`/`ocr="yes"` 抛 InvalidParamsError | 异常与通过直出 |
| TC-SV-06 | schema 形态 | TOOL_SCHEMAS | 检查 optional 含 `("bool",)`;description 含降级指引关键词 | 形态断言直出 |

### 交叉面清单(§2.1)

| 触及对象 | 其他写入者/读取者 | 覆盖 |
|---------|-----------------|------|
| executor.screenshot 签名 | 消费方 tools/_run_sensing(直调)、tests 打桩面(FakeExecutor 若打桩需同步) | TC-SV-01~04 |
| _check_type | validate_call 全工具参数校验;新增 "bool" 为通用类型 | TC-SV-05 |
| TOOL_SCHEMAS | validate_call 形态断言(test_validation 计数若按工具枚举则回归) | TC-SV-06+既有 |
| OCR 引擎接缝(_ocr_engine/_ensure) | executor.ocr 复用路径;懒加载+锁不动 | TC-SV-02/04 |
| 预算决议 | screenshot 含 ocr:true 时全屏推理 3.6~5.2s 超 L0 5s 预算——与 ISS-0039 覆盖表联动 | ISS-0039 TC-OC-03 |

### 装配守门五条(R1~R5)

R1 装配矩阵:全部单元/形态,无真机装配(不需放宽);
R2 mock 边界:只打桩截图 I/O(_resolve_region/_save_shot)与 OCR 引擎(注入接缝),不打桩被测方法本体;
R3 形态断言:TC-SV-03/05/06;
R4 路径变迁表:executor.screenshot 加参(既有调用点 tools 层一处)、_check_type 加分支(既有类型不受影响)、TOOL_SCHEMAS 加 optional(不影响既有校验);
R5 终效应断言:TC-SV-01 断言 vision_note 含实际截图路径(终效应=AI 可直接复用的降级指令)。

## 4. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-05 | 建单(实证:sdfang 质询"为什么不反馈给我"——图像通道故障静默降级的失职复盘),待评审 |
| v0.2 | 2026-09-05 | 测试设计定稿(sdfang 评审通过,2026-09-05 批次开工):TC-SV-01~06,实现契约+交叉面+装配守门五条随单 |
