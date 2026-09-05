# ISS-0039：【AI友好】OCR 超时指引与预算评估

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0039 |
| 标题 | 全屏 OCR(RapidOCR ONNX CPU 推理)在高负载下必然 TOOL_TIMEOUT,工具描述未明示"优先局部实拍/路径直读"——调用方反复撞超时 |
| 严重级 | **低**(超时响应本身 fail-closed 正确,重试指引有效,未造成事故;属指引与预算匹配度问题) |
| 状态 | **建单,待评审** |
| 提出 | 2026-09-05(演示录制实证:sdfang 质询"ocr 为什么会超时") |

## 1. 背景（实证）

2026-09-05 演示期间:
- 首次 OCR 调用必 TOOL_TIMEOUT 一次——`executor/core.py:170-190`
  引擎懒加载(ISS-0008 P2),RapidOCR 加载 ONNX 模型耗时吃光预算,
  500ms 重试即好;
- 14:41~14:44 连续 3 次重试均超时——录像进程(4fps 全屏截帧+缩放)
  抢 CPU,OCR 的 CPU 推理次次超预算;
- 机制:`models.py:40` 内部时限预算 + `httpd.py:53-65` 临期返回
  TOOL_TIMEOUT"处理中"+重试指引(ISS-0009 §6 / ISS-0023),fail-closed
  设计正确;超时 = 全屏大图 × CPU ONNX × 固定预算,负载高时必撞。

## 2. 整改方案

| 项 | 内容 | 定性 |
|----|------|------|
| A | ocr 工具描述明示:"全屏识别在系统繁忙时可能超时(预算保护),优先用局部实拍(dict source)或图像路径直读;超时按指引 500ms 重试" | **必做**(文档级) |
| B | 预算评估:L0 感知类(ocr/template_match)预算与 CPU 引擎实测耗时匹配度核对,必要时调档 | 评审期定(需实测数据) |
| C | 引擎预热:daemon 启动即初始化 OCR 引擎,消灭冷启动首调超时 | 候选(与懒加载设计的取舍评审期定) |

### 约束

- 不改超时机制本身(fail-closed 是硬约束);
- 若做 C,须保留"初始化失败记忆化+显式报错"(INV-7)语义;
- 测试设计(五要素)于评审通过后产出。

### 实测数据(2026-09-05,与 daemon 同一适配路径)

| 场景 | 耗时 |
|------|------|
| 引擎冷启动(构建) | 0.48s |
| 全屏 1920×1080 实拍图 首次推理 | **5.20s**(> L0 预算 5.0s,必 TOOL_TIMEOUT) |
| 全屏 二次推理 | 3.59s |
| 区域 640×360 | 0.34s / 0.31s |

**B 项结论**:全屏首推 5.2s 超预算坐实,需 per-tool 预算覆盖;
**C 项结论**:冷启动仅 0.48s,预热收益(省一次 500ms 重试)与新增后台线程
的复杂度不成比例——**C 不做**,理由如上(首调超时主因是全屏推理超预算,
B 项覆盖后首调亦在 12s 预算内)。

## 3. 测试设计(五要素,2026-09-05)

层级:单元(预算决议纯函数)+ 形态断言(描述/调用点接线)。

### 实现契约

- `models.TOOL_BUDGET_OVERRIDES = {"ocr": 12.0, "screenshot": 12.0}`
  (12.0 = 全屏首推 5.2s 的 2.3 倍,负载下 ~10s 亦覆盖);
- `httpd.resolve_budget(tool, level, policy)`:覆盖表优先,否则既有级别逻辑
  (L1/L2 → approval_ttl+5,L0 → 5.0);调用点 httpd invoke 处传 tool;
- `TOOL_SCHEMAS["ocr"].description` 增"局部实拍/路径直读优先+超时按指引重试"。

| 用例 | 场景 | 前提 | 步骤 | 预期结果 | 断言代码 |
|------|------|------|------|----------|----------|
| TC-OC-01 | ocr 描述指引(形态) | TOOL_SCHEMAS["ocr"] | 检查 description | 含"局部"/"区域"类关键词与"重试" | 形态断言直出 |
| TC-OC-02 | 预算覆盖:ocr | policy | `resolve_budget("ocr","L0",policy)` | 12.0 | 返回值直出 |
| TC-OC-03 | 预算覆盖:screenshot | 同上 | `resolve_budget("screenshot","L0",policy)` | 12.0 | 直出 |
| TC-OC-04 | 无覆盖工具不受影响 | 同上 | `resolve_budget("find_window","L0",policy)` | 5.0 | 直出 |
| TC-OC-05 | 级别语义不变 | policy(approval_ttl=90) | `resolve_budget("drag","L2",policy)` | 95.0 | 直出 |
| TC-OC-06 | 调用点接线(形态) | httpd 源码 | 检查 invoke 处预算决议 | 传 tool 入 resolve_budget | 源码形态断言直出 |

### 交叉面清单(§2.1)

| 触及对象 | 其他写入者/读取者 | 覆盖 |
|---------|-----------------|------|
| resolve_budget 签名(level→tool, level) | 生产调用点仅 httpd.py:168;既有测试 test_budget_iss24.py TC-BT-01~03、test_timeoutchain_iss33.py TC-TC-03/04 | R4 路径变迁表(见下) |
| TOOL_TIME_BUDGETS | 不动(级别表保持,覆盖表为独立注册表) | TC-OC-04 |
| TOOL_SCHEMAS["ocr"].description | validate/_list 描述面 | TC-OC-01 |
| ISS-0037-B(ocr:true) | screenshot 预算覆盖同表 12.0——两单共用覆盖机制 | TC-OC-03 ↔ ISS-0037 |

### 装配守门五条(R1~R5)

R1 装配矩阵:全部单元/形态,无真机装配;
R2 mock 边界:纯函数直出,零打桩;
R3 形态断言:TC-OC-01/06;
R4 路径变迁表:①resolve_budget 签名 +tool——生产调用点 httpd.py:168 同步改;既有测试 test_budget_iss24.py:25/29/34 与 test_timeoutchain_iss33.py:35/39 五处断言改新签名(合法重指,断言值不变);②TOOL_SCHEMAS 描述改写——无校验影响;
R5 终效应断言:TC-OC-02/03 断言覆盖值 12.0(终效应=全屏 OCR 不再因预算误杀)。

## 4. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-05 | 建单(演示实证+sdfang 质询后归纳),待评审 |
| v0.2 | 2026-09-05 | 实测三组耗时定案:B 做 per-tool 覆盖(12s)、C 不做(冷启动 0.48s 收益不成比例);测试设计定稿(sdfang 评审通过,2026-09-05 批次开工):TC-OC-01~06 |
