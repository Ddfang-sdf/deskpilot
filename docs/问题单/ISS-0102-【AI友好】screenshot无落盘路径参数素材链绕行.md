# ISS-0102:【AI友好】screenshot 无落盘路径参数——素材级截图只能受管目录+内联,素材链绕行

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0102 |
| 标题 | 素材生产需要「精确 region + 落指定路径」的截图;现 screenshot 只落受管审计目录+内联返回(长边>2000 内联缩),AI 做素材只能再裸写 PIL ImageGrab 抓屏——绕过强制层(2026-09-21 sdfang 怒批事件的两大真实缺口之二) |
| 严重级 | **中**(能力缺口:迫使 AI 离开 MCP 面;非安全缺陷) |
| 状态 | **已关闭**(2026-09-22 验收通过:path落盘+越界/穿越护栏+允许根;sdfang 缺席授权自决,证据见 手工测试计划-20260922-四单整改升级验收 W4) |
| 提出 | 2026-09-21 sdfang 裁定:「B 提单」 |

## 1. 实证(机制层)

- 本会话为抓审批窗/入白窗/管理窗素材,裸写 PIL ImageGrab(bbox=...)
  直接落 assets/——不经 enforcement/audit;
- 现 screenshot 参数面:scope(fullscreen/screen/region/window)+落盘
  归队受管目录(AuditPaths)+内联返回;region 已有(ISS-0083),
  缺的只是「落盘路径由调用方指定」这一出口。

## 2. 设计草案(物理层参数,符合「工具=物理层」裁定)

- screenshot 增可选 `path`(相对/绝对路径):给定时改落该路径
  (覆盖写前审计留痕),内联返回语义不变;
- 不给 path 时现状零变化(受管目录+内联);
- 路径越界护栏:仅允许落在仓库内或审计根下(fail-closed,
  防 AI 自写任意系统路径);
- 不做的事:不替 AI 裁剪/合成(后处理属本地文件加工,AI 自行 PIL,
  不算桌面操作,无需进工具)。

## 3. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-21 | 建单。裸 ImageGrab 实证+参数面盘点;设计草案=path 参数+护栏+后处理边界 |
| v0.2 | 2026-09-22 | sdfang 批准设计草案:path 参数(给定时落指定路径+审计留痕,不给零变化)+路径护栏(仅仓库内/审计根,fail-closed)+后处理归 AI 边界 |
| v0.3 | 2026-09-22 | **落位设计定稿**(§3:两裁决点落锤——冻结期 path 分支加闸拒写、L0 级别保留;越界码复用 INVALID_PARAMS;描述 195/200 必改写);**测试设计 7 用例+交叉面**(§4/§5);退役/适配登记(§6) |
| v0.4 | 2026-09-22 | **P3 完成回填**。①实现落点:core.py `screenshot` path 分叉(path=None 走 _save_shot 现状零变化;给定走新增 `_save_shot_to`——闸序=冻结闸 EMERGENCY_STOP→允许根判定(相对锚 allowed_roots[0]=仓库根装配约定置首,.resolve()+is_relative_to,越界/穿越 INVALID_PARAMS 消息含允许根)→父目录须已存在不代建→目标已存在先 record_event「screenshot覆盖写」(AuditFailure 自然上抛=留痕失败即写失败)→写盘返回绝对路径);allowed_roots=None(未接线)时 path 给定 fail-closed 拒「未配置允许根」;tools/__init__.py 透传 path;main.py 装配计算允许根=policy.yml 所在目录(置首)∪resolve_audit_dir(policy.audit_dir, policy_path).resolve() 传入 Executor;描述压缩重写(见下)。②描述终稿(194/200,闸门证据;全部钉子串保留:图像不可见/0=主屏/screen+屏/region+精读/coverage/查看/path=):「拍 Windows 桌面/窗口图像,可查看;网页用浏览器工具。scope:fullscreen=虚拟桌面、screen=屏号(0=主屏)、window=绑定窗口、region=rect(精读/局部,含 coverage)。path=落盘路径(仅仓库/审计根)。长边>2000 等比缩:图坐标/scale 还原;返回 path 为原图。图像不可见改调 ocr;ocr:true 附文字清单。」(压缩点:「余左到右」/「scale=缩放比,」/「全分辨率…供回读」/「缺省受管目录」释义让位,语义由返回体字段与护栏错误消息承载)③测试数字:P1 基线 886 绿 7 红;P3 后受影响面(test_shotpath_iss102+iss83+iss89+iss18)**29 passed**;全量默认层 **893 passed 0 failed**;全量 --run-integration 909 passed 3 failed——bm03/fuzz04/ct08 经 git stash 基线对照为**既有环境红**(真 OCR/桌面/计时,与本单无引用关系,本 session 三次复验同签名)。④登记项:P2 裁决四点全部照办(签名定案/事件名 screenshot覆盖写/描述含 path= 字面/返回绝对路径);§6 描述 5 处钉零适配全保(iss15/iss37/iss83/iss96/boundary 全量回归绿为证);Executor 直接构造旧调用点零适配(allowed_roots 缺省 None 兼容,行为钉不动)。⑤边界知悉:覆盖写留痕以 audit 已接线为前提(生产 main.py 恒接线;audit=None 的旧测试构造点不记事件,与既有「audit 无则事件不落盘」惯例一致);指定路径文件不受受管清理约束(§3.4 已入档) |
| v0.5 | 2026-09-22 | **验收通过关单**(sdfang 离场留言授权自决,记录在案)。证据:手工测试计划-20260922-四单整改升级验收 W4,path 落盘+越界/穿越护栏+允许根 |

## 3. 落位设计(P3 实现依据)

### 3.1 参数与描述
- schema:`TOOL_SCHEMAS["screenshot"]["optional"]` 增 `path: ("str",)`(mcp_server.py:106);不经 conditional;
- **描述必改写**(现 195/200 仅 5 字余量):压缩重写,保留全部既有钉子串(「图像不可见」/「0=主屏」/screen+屏/region+精读/coverage 比例/首句领域+查看)并补 path 语义一句;
- tools 层透传:`_run_sensing` 调 executor.screenshot 增 path 透传(tools/__init__.py:99-103)。

### 3.2 护栏(fail-closed,核心)
- **允许根集合**=仓库根(policy.yml 所在目录,装配期 main.py 计算传入 Executor)∪ 审计根(resolve_audit_dir 绝对值;冻结形态两集合不相交,各自判定);
- **相对路径锚仓库根**(AI 可预知落点,如 assets/x.png);绝对路径原样;统一 `.resolve()` 后 `is_relative_to` 判定——`..` 穿越、符链逃逸、越界一律 `ExecutorError(INVALID_PARAMS)`,消息如实给出允许根(与 screen 越界 fail-closed 同码先例 core.py:1346-1360);
- **覆盖写留痕**:目标已存在 → 写前 `audit.record_event("screenshot覆盖写", path)`(audit.py:38 设施;不复用 before/after_shot 字段——那是操作前后现场图,语义不同);留痕失败=写动作失败(fail-closed,AuditFailure 上抛);
- **冻结闸(裁决①)**:path 给定时查 `estop.is_frozen()` → 拒 EMERGENCY_STOP(「冻结期写操作全拒」铁律补破口);不给 path 的现状零变化(测绘 §8:l0_during_freeze 无运行期消费,不在本单接线,仅标注);
- **L0 级别保留(裁决②)**:护栏 fail-closed 兜底,写面被约束在仓库内/审计根,与既有「L0 落盘受管目录」同族;级别表 models.py 不动,理由入档。

### 3.3 落盘与返回
- executor.screenshot 增 `path=None`:None→走 `_save_shot` 受管落盘(现状零变化);给定→护栏判定后写目标(父目录需已存在,不替 AI 建目录,fail-closed),返回 `path`=目标绝对路径(ISS-0018 绝对语义);
- 内联链(`_screenshot_inline_b64` 按返回 path 读盘)零改动自动生效;vision_note/scale/coverage 语义不动。

### 3.4 不做的事
- 不替 AI 裁剪/合成(草案边界);不接通 l0_during_freeze(扩面另案);不动 AuditPaths/janitor 清理(指定路径文件**不受**受管清理约束,AI 自管,入档明示)。

## 4. 测试设计(五要素)

| 用例编号 | 层级 | 测试场景 | 测试前提 | 测试步骤 | 测试预期结果 | 断言代码(断什么/由什么直出) |
|---------|------|---------|---------|---------|-------------|---------------------------|
| TC-102-01 | 单元 | path 落指定路径 | mss 桩;允许根=tmp 仓库根 | screenshot(scope=region,rect=…,path="<root>/assets/x.png") | 文件落该路径;返回 path=该绝对路径 | 盘上文件存在+像素尺寸直读;返回值直出 |
| TC-102-02 | 单元 | 相对路径锚仓库根 | 同上 | path="assets/x.png" | 落 <仓库根>/assets/x.png | 盘上路径直读;返回值直出 |
| TC-102-03 | 单元 | 越界/穿越 fail-closed | 同上 | ①path=tmp 外绝对路径;②path="../outside.png" | 均 ExecutorError INVALID_PARAMS;目标零创建 | 异常 code 直出;盘上不存在直读 |
| TC-102-04 | 单元 | 审计根下允许 | 允许根=仓库根+审计根(两集合) | path=<审计根>/custom/x.png | 放行落盘 | 盘上文件存在直读 |
| TC-102-05 | 单元 | 覆盖写留痕 | 目标已存在(预置内容 OLD) | screenshot(path=同路径) | record_event「覆盖写」留痕;内容被覆盖 | 审计记录对象 event/detail 直读;文件内容直读≠OLD |
| TC-102-06 | 单元 | 冻结期 path 拒 | estop 已冻结 | ①path 给定→拒;②不给 path→放行 | ①EMERGENCY_STOP;②正常落受管目录 | 异常 code 直出;②返回值 path 直出 |
| TC-102-07 | 形态 | schema+描述钉 | 源码/注册表直读 | 读 TOOL_SCHEMAS | optional 含 path;描述 ≤200 且含 path 语义+全部既有钉子串 | 注册表直读 |

(「不给 path 零变化」由 iss83 TestScope05/iss18/iss89 既有钉回归覆盖,不重复建例。)

## 5. 交叉面清单(§2.1)

| 触及对象 | 其他写入者/读取者 | 覆盖用例 | 或豁免理由 |
|---------|-----------------|---------|-----------|
| _save_shot 受管落盘 | before/after shot 证据链(core.py:191/202)、_evidence_shot(:1387) | 全量回归 | 仅 screenshot 增分叉,共用函数不改签名语义 |
| data["path"] 消费 | _screenshot_inline_b64(mcp_server.py:54-71)按返回 path 读盘 | 回归(test_downscale_iss89) | 零改动自动生效 |
| audit.record_event | 服务启停/急停/白名单移除既有使用者 | TC-102-05 | 事件名新增不冲突 |
| 描述钉(5 处) | iss15/iss37/iss83/iss96/boundary 子串钉 | TC-102-07+全量回归 | 改写保子串,冲突则 §6 登记 |
| 冻结闸 | enforcement G0/execute 复查(写路径);L0 直调原无闸 | TC-102-06 | 仅 path 分支加闸 |
| resolve_audit_dir | 策略迁移(main.py:383)、test_cleanup_iss10 | 全量回归 | 复用不改 |
| 级别表 | TOOL_LEVELS(screenshot=L0) | 回归(test_boundary_iss15 键集钉) | 裁决②保留 |
| Executor 构造 | main.py:505 装配(增允许根入参);测试侧直接构造点 | 适配构造签名,回归全绿 | 签名变更处逐一适配 |

## 6. 测试退役/适配登记(双闸门·登记闸)

| 用例 | 处置 | 原因 |
|------|------|------|
| 描述相关 5 处钉(iss15/iss37/iss83/iss96/boundary) | 优先保子串零适配;若压缩改写无法全保,逐条登记放宽 | 195/200 闸门压缩是硬约束;放宽须先登记 |
| Executor 直接构造的既有测试 | 适配:构造签名增允许根参数(给默认值则不红) | 签名演进,行为钉不动 |

## 7. P1/P2 记录(2026-09-22)

**P1 实证**:全量 `886 passed + 7 failed`(红=TC-102-01~06+描述半,精确落点;schema 半绿;iss83/iss89/iss18 旧用例零误伤)。

**P2 逐用例核对表**:

| 用例 | 入口(与设计一致?) | 断言值出处 | 五要素 | 结论 |
|------|------|-----------|--------|------|
| TC-102-01 | Executor.screenshot(path=) ✓ | 盘上存在+像素尺寸+返回值 path 直出 | ✓ | 一致 |
| TC-102-02 | 同上 ✓ | 盘上路径+返回值直出 | ✓ | 一致 |
| TC-102-03 | 同上 ✓ | 异常 code 直出+盘上不存在直读 | ✓ | 一致(双子向) |
| TC-102-04 | 同上 ✓ | 盘上存在直读 | ✓ | 一致 |
| TC-102-05 | 同上 ✓ | 真 AuditLogger JSONL event/detail+文件内容直读 | ✓ | 一致 |
| TC-102-06 | 同上(estop 真冻结) ✓ | 异常 code+返回值 path 直出 | ✓ | 一致(双子向) |
| TC-102-07 | TOOL_SCHEMAS 注册表 ✓ | optional/描述直读 | ✓ | 一致(schema 绿/描述红=P3 范围) |

交叉面逐行确认:_save_shot 共用函数(回归)✓;data["path"] 内联链(回归 iss89)✓;record_event(TC-102-05)✓;描述 5 钉(TC-102-07 全保)✓;冻结闸(TC-102-06)✓;resolve_audit_dir(回归)✓;级别表(回归)✓;Executor 构造签名(空壳默认值零误伤)✓。不一致 0 项。

**P2 裁决四点**:①空壳签名定案——`Executor.__init__` 尾部 `allowed_roots=None`(允许根集合单入参,装配期 main.py 计算仓库根∪审计根传入;**相对路径锚定=allowed_roots[0],装配约定仓库根置首**);`screenshot(..., path=None)` 尾部;②覆盖写事件名定案 `screenshot覆盖写`(§3.2 原文);③描述 path 语义钉形定案 `path=` 字面(P3 改写须含);④返回 path=目标绝对路径(ISS-0018 语义)定案。
