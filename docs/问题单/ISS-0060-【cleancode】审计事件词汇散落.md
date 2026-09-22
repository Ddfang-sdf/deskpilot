# ISS-0060:【cleancode】审计事件词汇 stringly-typed——19 种事件名散落 7 文件

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0060 |
| 标题 | `record_event("启动抬键清扫")` 这类中文事件名是裸字符串,19 种散落 7 个文件;改名/检索全靠 grep,拼错无编译期拦截,审计消费方(测试断言、未来的分析器)只能跟着裸串走 |
| 严重级 | 低(可维护性;审计是安全件,词汇漂移伤追溯) |
| 状态 | 方案已设计,待 sdfang 评审排期(2026-09-22 方案入单,见「整改方案」) |
| 提出 | 2026-09-10(cleancode 审查;grep record_event 19 种/7 文件实证) |

## 现象与证据

19 种事件名字面量(「服务启动」「急停触发」「daemon 单例退出」…)
散于 main/estop/enforcement/httpd/executor 等 7 文件;测试断言直接写
字面量(如 test_freezesingle_iss46 断「daemon 单例退出」),字面量漂移
两边一起改。ISS-0050 今晨刚新增一种,9/9 新增两种——词汇持续增长。

## 方向

`audit_events.py` 集中常量(类枚举;中文串单源)+ 既有断言改引用;
审计消费方(测试)按常量断言。约束:落盘 JSONL 的事件文本不变
(历史数据可比性)。

## 评估记录(2026-09-17)

| 项 | 内容 |
|----|------|
| 现状核对 | 仍成立且面扩大:今日 ISS-0092(+4 事件)/ISS-0087(+4)/ISS-0073(+2)再增 10 个审计事件名;record_event 字面量散落十余处 |
| 处置 | **保留排期,方案入单**:建议 audit.py 增 AUDIT_EVENT_VOCABULARY 元组(单源)+钉测试 grep 全模块 record_event/record 事件名比对集合相等(防漂移),调用点改常量引用随各单顺带。词汇表化是写法变更,宜一次专项做透而非零碎改 |

## 整改方案(2026-09-22 设计)

### 0. 现状核验(行号实证)

复测(grep `record_event(` 全包):**41 种事件名 / 12 源文件 / 约 50 处调用点**——
建单(09-10)19 种/7 文件、评估(09-17)记再增 10 种,今日较建单翻倍以上,
「词汇持续增长」实证成立且加速。按文件锚点:

| 文件 | 事件名(行号) |
|------|--------------|
| deskpilot/main.py | 急停热键注册失败(128)/急停热键注册(136,140)/甩角轮询异常(157,163,197,203)/策略指纹(267)/用户策略数据指纹(278)/策略文件被外部修改(291 默认参,经 311 透传)/截图清理异常(355)/策略加载(425)/daemon 单例退出(433,612,669)/用户策略数据被外部修改(449)/属主 9420 绑定失败(568)/开机自启注册(618)/瘦代理跳过热键注册(623,634,646,654)/stdio 升属主(649)/服务启动(657,672)/服务停止(692,695) |
| deskpilot/estop.py | 急停触发(86)/复位请求-未冻结(99)/急停复位(105) |
| deskpilot/enforcement.py | 入白取证窗口明细(394)/审批取图失败(410) |
| deskpilot/ownership.py | 进程退出(171)/stdio 接管属主(279)/daemon 死亡告警(299)/stdio 属主让位(315) |
| deskpilot/freeze_notify.py | 共享状态对账修复(133)/共享状态写失败(164) |
| deskpilot/secure_desktop.py | 安全桌面检测失效(82)/安全桌面激活+安全桌面退出(87-88 条件表达式) |
| deskpilot/executor/core.py | 启动抬键清扫(171)/启动抬键清扫-FAILSAFE拦截(173)/screenshot覆盖写(1453) |
| deskpilot/executor/mousehold.py | 悬空按键自愈(85) |
| deskpilot/janitor.py | 截图清理(102)/审计日志清理(109) |
| deskpilot/policy.py | 入白迁移(159) |
| deskpilot/tools/__init__.py | 安全桌面拒绝(65)/白名单移除-经AI请求(234) |
| deskpilot/whitelist_admin.py | 白名单入白-永久(135)/白名单移除(154)(经 _event 包装 251-257 透传 record_event) |

**问题单/评估未覆盖的关联点(补充实证)**:

- **三类非直白字面量形态被漏计**,评估建议的「grep record_event 比对」抓不到:
  ①条件表达式造名(secure_desktop.py:87-88 `"安全桌面激活" if active else "安全桌面退出"`);
  ②默认参数透传(main.py:291 `event_name: str = "策略文件被外部修改"`、:449 传
  `"用户策略数据被外部修改"`,经 :311 `record_event(self._event_name,…)` 落盘);
  ③包装方法透传(whitelist_admin.py:251-257 `_event(name,detail)` 内调
  record_event,字面量在调用点 :135/:154)。守卫必须覆盖三形态,否则留漏。
- **测试侧断言面**:15 个测试文件约 30 处字面量断言跟着裸串走——test_audit(90-93)、
  test_audit_retention_iss31(127)、test_approval_readability_iss20(165)、
  test_dualfile_iss30(119,136)、test_enrollshot_iss73(274)、test_estop(18,27-28)、
  test_estopreset_iss93(143,216,538)、test_freezeguard_iss92(111,155,196)、
  test_freezesingle_iss46(86,96)、test_estop_reset(43,70-71,87)、
  test_mouse_req01(357,374,383,405)、test_ownership_iss84(179,192)、
  test_secdesk_iss87(99-100,172,187-189)、test_shotpath_iss102(134)、
  test_whitelist_iss12(1107,1122)。改名=双改实证。
- **词法风格已漂移**:中英文混排共存(「daemon 单例退出」「属主 9420 绑定失败」
  「stdio 属主让位」「screenshot覆盖写」 vs 纯中文),无命名规范——词汇表化时
  常量命名映射规则需统一(待裁决②)。
- **JSONL 消费面**:生产码无 reader(仅 audit.py:38-57 写);消费方全在测试侧。
  顺带发现(记录上报,不顺手改):读审计 helper 有 4 份实现——conftest.read_audit
  (:207)与 test_mouse_req01/test_audit_retention_iss31/test_guardfix_iss34 各自的
  `_audit_events` 私有副本,属另一 cleancode 面,建议另立单。
- **基线复测**:全量 899 passed/1 failed/28 skipped(215s);唯一红
  test_enrollshot_iss73::TestRealWindowCapture::test_tc10_hidden_only_never_restored
  单条复跑即绿(真实窗口前台竞争,环境敏感非产品红)——按 900 passed 基线记。

### 1. 根因(机制层)

`record_event(event: str, detail: str)`(audit.py:38)**签名即漏洞**:事件名是
无定义点的自由文本,新增成本为零(就近写字面量),复用/策展成本非零(须 grep 全仓
才知已有哪些词)——成本不对称使每个新安全单(ISS-0050/0073/0087/0092/0093 均如此)
在调用点就地造词,**词汇只增不策展(棘轮)**,41 种/12 文件是 12 天的自然终态。
更深处:中文串**身兼「事件身份」与「落盘文本」两职未分离**——无符号可 import,
改名/检索无编译期拦截,测试断言只能抄字面量,于是漂移=双改、拼错=静默新词。
缺的不是常量文件,是「**注册表 + 注册表外禁造词的强制闸**」:只建词汇表不设闸,
下个迭代照样裸串进仓(评估记录的方向只说了前半)。

### 2. 整改步骤(每步独立验证、独立提交)

| 步 | 内容 | 行为面 | 验证 |
|----|------|--------|------|
| S0 | 基线复跑记录绿数;新增 tests/test_audit_events_iss60.py 三钉(audit_events.py 先空壳占位):TC-60-01 调用点禁裸串守卫(ast 遍历 deskpilot/ 全部 .py,`record_event(`/`_event(` 第一位置参、`event_name` 默认参与传参不得为 str 字面量,audit_events.py 自身豁免)、TC-60-02 词汇表健康(常量全非空 str、值互异)、TC-60-03 落盘文本冻结钉(常量值==钉板中文字面量清单,护历史 JSONL 可比性) | 测试面新增,产品行为不变 | P1 红且红位精确:TC-60-01(约 50 处字面量)/TC-60-02(空壳)/TC-60-03 红;旧用例全绿 |
| S1 | P3 实现 deskpilot/audit_events.py:41 常量,值=现字面量**逐字**转录;docstring 立规——值即落盘文本,改值=改历史格式须另立单;新事件先注册再引用 | 纯新增文件,无人引用 | TC-60-02/03 绿,TC-60-01 仍红;全量基线绿 |
| S2 | 12 源文件调用点常量化,**按文件逐个提交**(enforcement/estop/freeze_notify/janitor/executor/core/executor/mousehold/main/ownership/policy/secure_desktop/tools/whitelist_admin);三形态全覆盖:直白字面量、条件分支(secure_desktop:88)、透传(main.py:291 默认值/:449 传参、whitelist_admin._event 调用点 :135/:154) | 纯重构(值逐字不变) | 每文件提交前全量绿;TC-60-01 红区按文件收缩,末文件提交后转绿 |
| S3 | 测试断言常量化:15 个测试文件断言改引常量;TC-60-03 钉板清单**刻意保留字面量**(值冻结职责,防常量值被顺手改) | 纯重构(断言值逐字等价) | 全量绿 |
| S4 | 收尾:audit.py record_event docstring 指向词汇表;本问题单变更记录 | 文档 | 评审过 |

约束(全程):**落盘 JSONL 事件文本逐字节不变**(历史数据可比性硬约束,TC-60-03
看守);**fail-closed 语义不回退**——AuditFailure 抛错路径(audit.py:56-57)、
whitelist_admin._event 尽力而为吞异常语义(whitelist_admin.py:256-257)、
enforcement 两阶段强审计、record() 主审计通道均不动;**全量测试基线
(默认层 900 passed/28 skipped)每步保持绿,红即停**。

### 3. 测试设计要点

- **S0 三钉=行为面新增,先红后绿**,五要素要点:
  - TC-60-01[单元/结构守卫] 场景=新审计事件必须经词汇表注册;前提=deskpilot
    包源码在仓;步骤=ast.walk 收集三形态字面量节点;预期=空集;断言=字面量
    节点集合由 ast 直出(无正则、无中间转换)。红→S2 末绿。
  - TC-60-02[单元] 场景=词汇表自身可依赖;步骤=import 取全部常量;预期=41 个、
    非空 str、值互异(防两名同值致身份混淆);断言=常量值直出。
  - TC-60-03[单元] 场景=落盘事件文本冻结;步骤=常量值逐一比对钉板字面量清单;
    预期=逐字相等;断言=常量值直出——「改值即红」的永久守卫。
  - **交叉面清单(§2.1)**:触及对象=41 常量;读取者=12 源文件调用点(S2 逐文件
    覆盖)、15 测试文件断言(S3 覆盖)、conftest.read_audit 等 4 份 reader(只读
    event 字段文本,值不变故无感,豁免)、历史 JSONL(TC-60-03 冻结值,豁免);
    写入者=未来新事件(TC-60-01 长期守卫)。
- **S1-S3 纯重构=既有钉全绿即证**(SDD §4:不许改测试迁就)。关键钉清单:
  test_estop(急停触发/复位)、test_estop_reset(瘦代理/热键注册/复位请求)、
  test_freezesingle_iss46(daemon 单例退出)、test_freezeguard_iss92(共享状态/
  甩角)、test_secdesk_iss87(安全桌面五事件序)、test_mouse_req01(抬键清扫/
  悬空自愈/FAILSAFE 拦截)、test_ownership_iss84(进程退出)、
  test_shotpath_iss102(覆盖写)、test_whitelist_iss12(策略指纹/外部修改)、
  test_enrollshot_iss73(入白取证窗口明细)、test_audit(JSONL 结构)。
- 值转录风险加强闸(可选):S2 完成后实盘一次(起停 daemon+急停触发复位),
  比对新旧 JSONL 事件序列逐字一致,截图留档。

### 4. 工作量粗估

5 步(S0-S4),约 14 次提交(S0/S1/S3/S4 各 1,S2 按 12 文件);新增 2 文件
(deskpilot/audit_events.py、tests/test_audit_events_iss60.py),改 12 源文件 +
15 测试文件 ≈ 29 文件;41 常量、约 50 调用点、约 30 断言点。约 1.5-2 人日
(S2 占近半),评审往返另计。

### 5. 风险与待裁决

- 风险:①值转录错别字——TC-60-03 钉板 + S2 后实盘 diff 双闸;②透传形态遗漏
  (event_name/_event)——TC-60-01 已按三形态设计;③拼接造名绕过守卫
  (f"安全桌面{x}")——TC-60-01 首版禁字面量,可升级连 JoinedStr 一并禁;
  ④测试 stub(FakeRecorder.record_event 签名)与实现本就脱钩,常量化后断言值
  仍来自调用入参直出,风险不增。
- 待 sdfang 裁决:①常量形态——模块级 `EV_*` vs `class AuditEvent` 类属性
  (引用写法与 IDE 跳转体验不同);②41 个值里中英文混排名(「daemon 单例退出」
  「属主 9420 绑定失败」「screenshot覆盖写」)本单是否保持原样——建议保持,
  值英文化涉历史数据迁移策略,另立单;③S3 测试断言常量化是否强制,还是允许
  测试保留字面量当文本钉——本方案采纳「常量化 + TC-60-03 单点字钉」;
  ④S2 按 12 文件逐个提交还是按模块域合批;⑤读审计 helper 4 份复制是否另立
  cleancode 单(本单不动,范围控制)。

## 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-10/09-17 | 建单(grep record_event 19 种/7 文件实证)+评估记录入单(再增 10 种,保留排期;建议 AUDIT_EVENT_VOCABULARY 单源+钉测试防漂移,调用点随各单顺带) |
| v0.2 | 2026-09-22 | 整改方案落档:复测 41 种/12 文件/约 50 调用点(行号锚)+三类非字面量透传形态(条件表达式/默认参/包装方法)与 15 测试文件断言面补证;根因写至机制层(自由文本签名=零成本造词棘轮,事件身份与落盘文本两职未分离,缺注册表+强制闸);5 步(S0 三钉先红后绿→S1 词汇表逐字转录→S2 十二文件常量化小步→S3 断言常量化→S4 文档),JSONL 文本逐字冻结+fail-closed 不回退+900 绿基线每步保持;状态→方案已设计,待 sdfang 评审排期 |
