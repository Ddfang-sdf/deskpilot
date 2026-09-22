# ISS-0064:【cleancode】main() 装配 166 行巨函数——启动路径一锅烩

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0064 |
| 标题 | main.py:345-511 的 main() 一函数 166 行:参数分发、策略加载、审计装配、单例守门、双轨指纹守望、白名单装配、暖缓存、弹窗服务、急停监听、执行器/看门狗、OCR 工厂、强制层、守护/托盘/stdio 形态分支全在一锅——启动路径无任何段间观测口 |
| 严重级 | 低(可维护性+可诊断性;本次已付过代价) |
| 状态 | 方案已设计,待 sdfang 评审排期(2026-09-22 方案落档,见「整改方案」章) |
| 提出 | 2026-09-10(cleancode 审查;ast 实证 main()=166 行) |

## 现象与证据

main() 166 行 12 个职责段;本次 ISS-0051(PMV2 静默失效)能潜伏数周,
正因为启动装配是一整块——DPI 形态、监听归属、弹窗接线都没有段间断言
/观测口,坏了无从看见(ISS-0050 的可诊断仪表是第一道光)。
ISS-0046 的单例守门也只能"插进锅里",没有结构位置。

## 方向

拆 `assemble_xxx()` 段函数(策略/审计/弹窗/急停/执行器/形态),
main() 退化为顺序编排;每段产出有审计落点(启动审计逐段可查)。
约束:启动事件序列不变(既有审计断言钉住),无行为变化转绿。

## 评估记录(2026-09-17)

| 项 | 内容 |
|----|------|
| 现状核对 | 仍成立且更长:main() 今日再增(安全桌面守卫装配/ISS-0071 屏解析闭包),装配段已超 200 行;「本次已付过代价」今日再实证(装配点查找耗时) |
| 处置 | **保留排期**。建议拆分=形态分支(daemon/stdio/子命令)+装配段(策略/强制层/急停/对话框/托盘)两组函数;须打包验证+全量回归。宜与 ISS-0055 同一评审窗口 |

## 整改方案(2026-09-22 设计)

### 0. 现状核验(行号实证)

ast 复测:main() = deskpilot/main.py:401-696,**296 行**(建单时 166 行
@345-511,2026-09-17 评估「超 200 行」——问题持续恶化,+78%)。
现 12 个职责段(行号锚):

| # | 段 | 行号 |
|---|----|------|
| 1 | --migrate-policy 子命令分发 | 405-407 |
| 2 | 策略定位+双文件(出厂/用户数据)加载 | 408-421 |
| 3 | 审计装配+fail-closed(rc 3) | 423-428 |
| 4 | daemon 单例预检守门(rc 4) | 430-437 |
| 5 | 双轨指纹审计+守望线程 | 439-449 |
| 6 | 白名单管理装配(WhitelistAdmin) | 450-458 |
| 7 | 暖名称/描述缓存线程 | 459-462 |
| 8 | 弹窗服务/审计路径/共享目录/冻结通知/急停装配 | 464-483 |
| 9 | 探针/绑定/审批通道(TkApprovalChannel)装配 | 485-496 |
| 10 | 执行器+检测器+OCR 工厂+强制层+撤回通道+ToolContext | 497-549 |
| 11 | ISS-0084 属主权装配(4 闭包+daemon/瘦代理/stdio 属主三分支) | 551-655 |
| 12 | 服务启动审计+清理者+daemon 常驻/stdio 收尾 | 657-696 |

**问题单未覆盖的关联点(补充实证)**:

- 段 11 是嵌在函数体内的**闭包状态机**:_become_owner/_cede_owner/
  _alarm_fn/_ownership_watch(:556-599)经 owner_httpd/owner_tray 两个
  dict(:553-554)共享可变状态,外加「9420 绑定失败→放锁退瘦代理」
  时序分支(:642-647)——巨函数里最自成一体、也最难平移的一段。
- **既有钉以模块属性 monkeypatch 为接缝**,拆分不得移出 main.py 或改名,
  否则钉碎(实证清单):test_freezesingle_iss46.py:49-57 patch
  `m._find_policy_path/m.probe_daemon/m._start_estop_listeners/m.Executor/
  m.TrayIcon/m.time.sleep`;test_estop_reset.py:33-37 patch `m.serve`;
  test_tray_iss12e.py:58-60 断言 `m.os` 存在;test_dpi_iss50/iss51 钉
  `_DPI_MODE/_query_dpi_mode`;test_whitelist_iss12 钉
  `policy_sha256_audit/_start_policy_watch`;test_dualfile_iss30/iss32 钉
  `local_policy_sha256_audit/_run_migrate_policy`;test_freezeguard_iss92 钉
  `_corner_loop`。**另:函数体内惰性 import(deskpilot.dialog_service 等)
  本身也是 patch 接缝,移动即碎钉。**
- 无 main() 行数形态钉(grep ast/end_lineno 零命中)——无防漂移闸;
  ISS-0056 有 f56 计数钉先例可仿。
- 详设 §3(docs/详细设计说明书.md:148-163)只写 6 功能,与双轨指纹/
  属主权/瘦代理/清理者现实脱节——文档同步须列入实施。

### 1. 根因(机制层)

main() 是**唯一装配位即唯一编译单元**:每个新单的安全/守卫装配没有
结构落点,只能「插进锅里」(ISS-0046 守门、ISS-0084 属主权、ISS-0093
复位收口均如此进锅);后到的装配**依赖先到段产的局部变量**
(ctx/estop/audit/supervisor),闭包捕获使后续代码无法离开该作用域;
且 fail-closed 早退(rc 2/3/4)分散在段内,抽出段函数必须先处理早退
语义——在安全关键路径动刀的心理门槛高,于是**只增不减(棘轮)**。
ISS-0051 潜伏数周正是「整块装配无段间观测口」的直接代价。

### 2. 整改步骤(每步独立验证、独立提交;全部段函数留在 main.py 内,不做跨模块搬迁)

| 步 | 内容 | 行为面 | 验证 |
|----|------|--------|------|
| S0 | 基线+形态钉:跑全量记录绿数;新增 test_main_assembly_iss64.py——ast 断言 main() 行数 ≤ 296(只减不增)+ 既有接缝符号存在性清单断言(_find_policy_path/probe_daemon/_start_estop_listeners/serve/Executor/_corner_loop/_hotkey_loop/_DPI_MODE 等) | 测试面新增,产品行为不变 | 钉绿(现状即过) |
| S1 | 段 1+2 抽 `_stage_load_policy()`:子命令分发+策略定位+双文件加载,返回策略束(或早退 rc) | 纯重构 | 既有钉全绿(test_dualfile_iss30/iss32)+形态钉收紧 |
| S2 | 段 3+4 抽 `_stage_audit()`/`_stage_daemon_precheck()`:审计装配 rc 3、单例预检 rc 4,stderr 文案与审计事件逐字节不动 | 纯重构 | test_freezesingle_iss46 TC-46-01/02 绿 |
| S3 | 段 5+6+7 抽 `_stage_whitelist()`:双轨指纹+守望+WhitelistAdmin+暖缓存 | 纯重构 | test_whitelist_iss12/test_dualfile_iss30 绿 |
| S4 | 段 8+9+10 抽 `_stage_runtime()`(急停弹窗子段+执行器强制层子段,可再分两提交):产出运行时束(estop/notifier/executor/enforcement/ctx 等) | 纯重构 | test_freezeguard_iss92/test_estop_reset 绿 |
| S5 | 段 11 抽属主裙子系统:4 闭包+owner dict 收口为模块级 `OwnershipRuntime` 类(显式持有 ctx/estop/notifier/audit/policy/shared_dir),三分支逻辑抽 `_stage_ownership()`——**风险最大步,单独提交** | 纯重构(结构新物) | test_freezesingle_iss46/test_estop_reset TC-N-EST-02/test_tray_iss12e 绿+实盘 daemon/stdio 双形态 |
| S6 | 段 12 抽 `_run_daemon_loop()`/stdio 收尾;main() 退化为 ≤ 60 行顺序编排,形态钉收紧至 ≤ 60 | 纯重构 | 全量绿+形态钉终值 |
| S7 | 启动逐段审计落点(问题单「方向」原意:每段产出有审计可查) | **有行为面(新增审计事件)——先红后绿,且需 sdfang 裁定是否本单做(见 §5)** | 新用例五要素见 §3 |
| S8 | 文档同步:详设 §3 段函数清单+main.py docstring | 文档 | 评审过 |
| S9 | 打包验证:PyInstaller dist 实盘(daemon 起停/托盘/弹窗/急停/瘦代理共存) | — | 实盘证据留档 |

约束(全程):fail-closed 语义不回退——rc 2/3/4、stderr 文案、审计事件
序列(策略加载→…→服务启动/停止)逐字节不变;全量测试基线
(默认层 900 passed)每步保持绿,红即停。

### 3. 测试设计要点

- **S0-S6 纯重构=既有钉全绿即证**(SDD §4:不许改测试迁就)。关键钉
  清单:test_freezesingle_iss46(单例/rc 4/审计)、test_estop_reset
  TC-N-EST-02(瘦代理跳过热键)/TC-N-EST-03(热键退避)、
  test_tray_iss12e(m.os 守门)、test_dpi_iss50/iss51(DPI 形态)、
  test_whitelist_iss12(策略指纹)、test_dualfile_iss30/iss32(双轨/迁移)、
  test_freezeguard_iss92(甩角守卫)。形态钉随步收紧行数阈值。
- **S7 行为面=先红后绿,新用例五要素**:场景=启动逐段留痕;前提=
  临时策略目录+全替身装配(沿用 test_freezesingle_iss46._main_stubs
  模式);步骤=main();预期=审计 JSONL 含段事件且顺序固定;断言=
  read_audit 事件序列直出。交叉面清单(§2.1 必附):新审计事件的
  消费者=审计检索/仪表盘/既有事件名空间,须查重+标注覆盖。
- frozen 分支(policy.yml 查找/_open_manager_for env/ensure_autostart)
  源码单测覆盖不到,S9 打包实盘兜底。

### 4. 工作量粗估

9 步(S0-S9);受影响文件:deskpilot/main.py(唯一代码文件)、
tests/test_main_assembly_iss64.py(新增)、docs/详细设计说明书.md §3、
本问题单——共 4 文件。约 3-5 人日(S5 占近半)。

### 5. 风险与待裁决

- 风险:S5 闭包→类的共享状态时序(9420 绑定失败放锁退瘦代理
  :642-647)最易碎,须单独提交+双形态实盘;惰性 import 接缝迁移
  须逐一对照 _main_stubs patch 点;形态钉阈值需随步调。
- 待 sdfang 裁决:① S7 启动段审计落点是否本单做(有行为面)或另立单;
  ② main() 终值行数阈值(建议 ≤ 60);③ S5 是否允许引入
  OwnershipRuntime 类(结构新物)还是闭包平移;④ 是否与 ISS-0055
  同一评审窗口(2026-09-17 评估建议)。

## 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-10/09-17 | 建单(ast 实证 main()=166 行)+评估记录入单(超 200 行,保留排期) |
| v0.2 | 2026-09-22 | 整改方案落档:现状复测 296 行 12 段(行号锚)+既有 monkeypatch 接缝清单补证;根因写到机制层(唯一装配位棘轮+闭包作用域锁定+早退分散);9 步拆分(S0 形态钉基线→S1-S6 六段纯重构→S7 段审计行为面待裁→S8 文档→S9 打包验证),main() 目标 ≤60 行,段函数不出 main.py;fail-closed 与 900 绿基线不回退;状态→方案已设计,待 sdfang 评审排期 |
