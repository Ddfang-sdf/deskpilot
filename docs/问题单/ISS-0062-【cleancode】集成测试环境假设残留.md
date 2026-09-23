# ISS-0062:【cleancode】集成测试环境假设残留——ISS-0025 卫生族余孽

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0062 |
| 标题 | --run-integration 用例仍有环境可变断言:icons10 假设 [0,0,230,300] 区域必中且非全量;fuzz04/ct08 打实时屏幕 OCR 文字清单;ct12 在用户活跃用机时前台锁必败(窗口无法前置)——本日 CI 红(icons09:6>=25)即此族外在同类 |
| 严重级 | 低(测试可靠性;CI 红过一次已修 icons09,余者同族未排雷) |
| 状态 | **已关闭(2026-09-23 验收:A~F 全步落地,集成层 953 passed 0 failed;离场授权自决)** |
| 提出 | 2026-09-10(CI v0.3.6 首红复盘:icons09 活桌面阈值/具名图标已修;同族排查发现余孽) |

## 现象与证据

| 用例 | 环境假设 | 风险 |
|------|---------|------|
| icons10 | [0,0,230,300] 必含图标且非全量 | 桌面空角落/全堆角落时败 |
| fuzz04/ct08 | 实时屏幕含可 OCR 的特定文字 | 锁屏/双屏/内容变化时败 |
| ct12 | 前台锁空闲(用户不在用机) | 用户活跃时"窗口无法前置"败 |
| (观察项)test_post_clear_session | 首跑败一次未复现(同种子过) | 线程/时序敏感待诊断 |
| scope03/scope05(ISS-0083) | fullscreen 断言钉本机双屏几何 `[0,-1,3840,1080]`/面积 4151040;fullscreen 的 virtual_rect 全真取自 mss `monitors[0]`,替身几何进不了该路径 | CI runner 单屏 1024×768 必红(v0.3.7 tag 流水线 35044139450 实证 2 红);**已改环境不变量断言**(fullscreen 外接矩形须覆盖 enum_monitors 每一屏,替身双屏下退化为大于任一单屏) |

ISS-0025 已立"默认零副作用/用例独立",但这批集成用例的断言仍打在
可变环境上;icons09 的今天就是它们的明天。

## 方向

逐条改环境不变量断言或加显式环境守卫(skip 带原因,不装过);
CI 同款命令(--run-integration 随机序)纳入推送前本地必跑——
流程补丁写进 CONTRIBUTING/检查单。约束:守卫 skip 必须写明缺什么环境,
禁止静默 skip。

## 评估记录(2026-09-17)

| 项 | 内容 |
|----|------|
| 现状核对 | 仍成立(双屏/1080p/mspaint 在场等隐含假设散布);今日新增用例已带环境守卫先例(mspaint 缺失 skip/单屏 skip/daemon 在线 skip——test_enrollshot_iss73/test_deeptree_iss88/test_freezeguard_iss92) |
| 处置 | **保留排期**。建议:排雷=逐用例列环境假设表(屏数/分辨率/在场进程/真鼠标),无守卫者补 skip 明示;环境守卫模式已在本日新用例定型,随测试批次顺带收敛 |

## 整改方案(2026-09-22 设计)

### 一、现状核验(2026-09-22 复核,行号证据)

问题单四条陈述全部成立,另有两处同族点问题单未覆盖:

| 用例 | 现状核验(文件:行号) | 结论 |
|------|---------------------|------|
| icons10 | tests/test_desktop_icons_req02.py:370 region 硬编码 `[0,0,230,300]`;:378 `assert 0 < part.count < full.count` 双重环境假设(左上角必中**且**非全量) | 成立,且无任何守卫 |
| fuzz04 | tests/test_selfheal_iss27.py:96-138:真记事本(:101)、真 OCR(:103-106)、真键入+`time.sleep(0.5)`(:123);隐含假设=记事本可前置可见、屏幕内容可 OCR、键鼠可注入 | 成立,无守卫;**本机 --run-integration 当前即红**(见下) |
| ct08 | tests/test_clicktext_iss21.py:172-222:同 fuzz04 族;另 :180-181 `monkeypatch.setattr(Executor, "_check_occlusion", ...)` 打桩 | 成立;**附带标签卫生问题**:按 SDD-开发流程 §3.2 标签判定(集成禁打桩,含替身接缝应降级 assembly 并写明断层面),本条挂着 integration 标却带 monkeypatch——问题单未覆盖 |
| ct12 | tests/test_clicktarget_iss44.py:267-347:已有两处守卫(:329-331 无未遮挡图标 skip、:336-341 OCR 污染 skip);残留假设=Program Manager 在场(:312-315)、桌面图标有 graphic_rect、真鼠标点击落屏不被用户活跃干扰 | 部分收敛,仍有残留假设 |
| post_clear_session | tests/test_whitelist_iss12.py:457-464;daemon fixture 已带就绪等待(:422-430) | 观察项维持,flake 未复现,不放宽不装过 |
| scope03/scope05 | tests/test_screenshot_scope_iss83.py:107-120/:150-159 已改 mss 自洽不变量(非退化矩形),替身几何不进 fullscreen 路径 | **本族已完成项,即本方案的断言范式** |
| (新增)bm03 | tests/test_benchmark_iss8.py:57-60:`l0_latency_ms < 500`、`dialog_thread_ms < 2000`——计时阈值是机器负载函数,属「计时」族环境假设,问题单未覆盖 | 同族漏项;CI 虽 --ignore 该文件(release.yml:34),本地 --run-integration 暴露 |
| (新增)bm04 | tests/test_benchmark_iss8.py:62-65:断言 `127.0.0.1:9420/health` 在线——假设跑前真 daemon 在场,属「真 daemon」族 | 同族漏项 |
| 外部实证 | ISS-0101 变更记录(2026-09-22):本机全量 --run-integration **916 passed 3 failed**,红即 bm03/fuzz04/ct08,经 git stash 基线对照为既有环境红 | 本族已从「CI 才红」恶化为「本机常红」,排雷紧迫性上调 |

基线核验:默认层 `pytest tests -q` = **900 passed, 28 skipped**(2026-09-22 本机实测,201s),即本方案须保持的绿色基线。

### 二、根因(机制层)

1. **断言层缺「环境不变量」判定规则**。ISS-0025 立的是执行层卫生(默认零副作用/用例独立),没立断言层规则:集成用例的断言只许打在「被测方法直出、与环境无关的不变量」上。于是桌面布局(icons10 左上角)、前台独占(ct08/fuzz04)、机器负载(bm03)这类**环境采样值**被当成行为不变量写进断言。这些断言在开发机上恒真——假设永不暴露,形成「开发机恒真盲区」,只有 CI 环境(无前台桌面/单屏 1024×768/干净桌面)才引爆。icons09 的修复(2026-09-10)与 scope03/05 的修复(2026-09-18)都是同一机制的事后个案,没沉淀成规则,故同族余孽存活至今。
2. **环境差异无统一表达通道**。仓库没有共享的环境守卫 helper,各用例自发长出 5+ 种写法(test_clicktarget_iss44.py:330/test_clickguard_iss91.py:238/test_deeptree_iss88.py:209/test_typeguard_iss100.py:339/test_estopreset_iss93.py:494);没长出守卫的用例(icons10/fuzz04/ct08/bm03/bm04)只能裸断言。写法发散还导致「缺什么环境」的说明口径不一。
3. **流程层跑法断裂**。本地默认跑法(无 --run-integration,集成全 skip)≠ CI 跑法(release.yml:34,--run-integration + pytest-randomly 随机序);推送前无强制同款命令的纪律落点——CONTRIBUTING.md 不存在(Glob 实证),ISS-0062「方向」节写的流程补丁至今无处落地,集成红只能发版/tag 流水线事后发现(v0.3.7 流水线 35044139450 实证 2 红)。

### 三、改法(小步快走;每步独立可验证、独立提交)

**步骤 A(纯重构,行为不变):环境守卫 helper 收敛**
- 新增 `tests/envguard.py`(或并入 conftest):统一入口 `env_skip(缺什么)`(封装 `pytest.skip(f"环境守卫:缺{...}", allow_module_level=False)` 口径)、`notepad_mains()`(自 test_clicktext_iss21.py:90-95 抽出)、`pick_unoccluded_desktop_icon()`(自 test_clicktarget_iss44.py:316-331 与 test_desktop_icons_req02.py:341-357 两处同构逻辑抽出)、`real_daemon_online(port=9420)`(自 test_typeguard_iss100.py:339/test_estopreset_iss93.py:494 抽出)。
- 迁移既有散落守卫(上列 5 文件 + test_window_ext_iss12.py:57/66、test_detector_int_req03.py 各 skip)到 helper,skip 语义与消息口径保持「写明缺什么环境」。
- 验证:纯重构——默认层 900 passed 基线全绿 + 本机 --run-integration 层 skip 总数不减少,即证。

**步骤 B(行为面):icons10 断言改环境不变量**
- tests/test_desktop_icons_req02.py:366-379:region 不再硬编码;从 full 清单自适应构造(取首个实体项 cell_rect 外扩数像素为 region),断言改为全部由响应体直出的不变量:① part 每项与 region 相交(保留 :374-377);② part 的 cell_rect 集合 ⊆ full 的 cell_rect 集合;③ round-trip 自洽:用 full 在本地以 `rects_intersect`(deskpilot/executor/desktop_icons.py:29,纯函数)重算期望集合,与 part 逐项相等——过滤正确性由重算钉死,不再依赖「左上角有图标且非全量」。
- 桌面仅虚拟项(无实体项可选区)→ 步骤 A 的 env_skip("桌面实体图标")。
- 走测试放宽双闸门:变更记录登记「去掉 :378 的 `0 < count < full.count`——它探测的是桌面布局而非过滤逻辑;过滤逻辑的正确性改由 round-trip 重算探测,无被掩盖行为」。

**步骤 C(行为面):fuzz04/ct08 守卫补齐 + ct08 标签正名**
- 两条用例补前置守卫(用步骤 A helper):记事本主窗口未出现 → skip("可拉起的记事本窗口",照 test_typeguard_iss100.py:343 先例);attach 前窗口被遮挡/不可前置 → skip("可前置的记事本窗口")。既有通过路径零改动。
- ct08 标签正名:tests/test_clicktext_iss21.py:180-181 的 `_check_occlusion` 打桩使该条按 SDD §3.2 定义属 assembly——类 docstring 补「真实部件清单/替身清单/断层面」三件套,标注保留 integration 标的理由或降级(裁决点 4)。注意 test_mouse_req01.py:59 有同款打桩但它在单元层,合规,不动。
- 先红后绿形态:新守卫在「记事本被遮挡」构造环境下先红(无守卫时 OCR 必败,本机常红已是实证),补守卫后 skip 明示转绿;守卫分支本身用「遮挡构造」用例钉(skip 消息含缺失环境名)。

**步骤 D(行为面):bm03 计时断言 + bm04 真 daemon 假设**
- bm03(test_benchmark_iss8.py:57-60):按双闸门登记后二选一(裁决点 1):①阈值改为只挡「路径级回退」(dialog_thread_ms < 2000 的既有注释意图:l0 同理改为挡 10× 劣化量级);②改报告式(只测不挡,断言只留结构/采样数,数值入报告)。推荐①,与既有注释口径一致。
- bm04(:62-65):补守卫——测前 `real_daemon_online(9420)` 为 False → skip("运行中的真 daemon(:9420)");或改基准脚本自拉起/恢复(裁决点 2)。推荐守卫路线,与本单「环境假设显式化」主旨一致。

**步骤 E(行为不变):post_clear_session 观察项处置**
- 不放宽、不装过:fixture 就绪等待已在其位(test_whitelist_iss12.py:422-430)。仅在该用例 docstring 登记「2026-09-10 首跑败一次未复现(线程/时序敏感)」观察记录;复现即另立缺陷单诊断,本单不碰。

**步骤 F(流程面,文档):推送前本地必跑 CI 同款命令**
- 把「推送前必跑 `pip install pytest-randomly && python -m pytest tests -q --tb=short --run-integration --ignore=tests/test_benchmark_iss8.py`」写进流程文档(裁决点 3:新建 CONTRIBUTING.md 或写入 docs/SDD-开发流程.md §5 工作纪律表;docs/手工测试记录-20260908.md:229 已认账此纪律,落点未定)。

提交序:A 先行(helper 是 B/C/D 依赖)→ B/C/D 互相独立可并行、各自单独提交 → E 随手 → F 文档收尾。

### 四、测试设计要点(五要素,按步)

| 步骤 | 形态 | 五要素要点 |
|------|------|-----------|
| A | 纯重构 | 不新增用例;既有钉全绿即证(默认层 900 passed;--run-integration 层 skip 数不减少、无静默 skip) |
| B | 行为面 | 场景=桌面任意布局下图标 region 过滤;前提=桌面至少 1 实体图标(缺→env_skip);步骤=取 full→自适应构造 region→取 part;预期=part 与「full 经 rects_intersect 重算」逐项相等;断言=两边 cell_rect 集合直出比对(无中间转换) |
| C | 行为面 | 场景=前台受限/记事本不可见时集成用例表现;前提=构造遮挡(或不构造,靠本机常红实证);预期=skip 且消息含缺失环境名,非 fail 非静默;断言=`pytest.skip` 出口与消息文本;通过路径既有用例不动、保持绿 |
| D | 行为面 | 场景=高负载机器跑基准;预期=路径级回退仍被挡(红),负载波动不再误红(绿/skip);bm04 前提=9420 daemon 在场(缺→skip 明示);断言=阈值/守卫出口直出 |
| E | 行为不变 | 仅 docstring 登记;既有钉全绿即证 |
| F | 流程 | 文档评审;下次推送前实证执行一次并留记录 |

### 五、交叉面清单(SDD §2.1)

| 触及对象 | 其他写入者/读取者 | 覆盖/豁免 |
|---------|------------------|-----------|
| 新增 envguard helper | 全部集成/装配用例(潜在读取者) | 步骤 A 迁移的 7 文件逐一点检;未迁移的新用例由评审把关 |
| `_check_occlusion` 打桩 | test_mouse_req01.py:59(单元层同款) | 豁免:单元层允许 mock(SDD §3.3),不动 |
| 9420 端口真 daemon | test_typeguard_iss100.py:339、test_estopreset_iss93.py:494(已有在线 skip 先例)、bm04 | 步骤 D 统一经 `real_daemon_online()` |
| region 矩形语义 | screenshot scope=region 是 [x,y,w,h](test_screenshot_scope_iss83.py:162-166 钉死);list_desktop_icons 的 region 是 [l,t,r,b] 相交过滤(desktop_icons.py:29-31) | 步骤 B 只碰后者;自适应构造时不得混用两种约定 |
| 计时阈值 | scripts/benchmark_iss8.py measure_all(写入者) | 步骤 D 只改断言侧,脚本不动(范围控制) |
| CI 命令行 | .github/workflows/release.yml:34 | 步骤 F 只写文档,不动 workflow(范围控制) |

### 六、约束

- fail-closed 语义不回退:本单零产品代码改动;所有守卫 skip 显式写明缺什么环境,禁止静默 skip、禁止把红改装过;测试放宽一律走双闸门先登记。
- 全量基线保持绿:默认层 900 passed(2026-09-22 实测)每步提交前必过;目标终态:本机 --run-integration 全绿(skip 明示),CI 同款命令绿。
- 范围控制:bm03/bm04、ct08 标签、post_clear_session 注释之外发现的相邻问题只记录上报,不顺手改。

### 七、工作量粗估

6 步(1 纯重构 + 3 行为面 + 1 注释级 + 1 文档);受影响文件约 10~12 个,全在 tests/ 与流程文档:tests/conftest.py 或新增 tests/envguard.py、test_desktop_icons_req02.py、test_clicktext_iss21.py、test_selfheal_iss27.py、test_benchmark_iss8.py、test_whitelist_iss12.py(注释级)、test_clicktarget_iss44.py、test_clickguard_iss91.py、test_deeptree_iss88.py、test_typeguard_iss100.py(守卫迁移)、SDD-开发流程.md 或新建 CONTRIBUTING.md;产品代码 0 文件。

### 八、待人类裁决

1. bm03 计时断言处置:宽阈值(只挡路径级回退,推荐)vs 报告式(只测不挡)。
2. bm04 真 daemon 假设:补在线守卫 skip(推荐)vs 基准脚本自拉起/恢复 daemon。
3. 流程补丁落点:新建 CONTRIBUTING.md vs 写入 docs/SDD-开发流程.md §5。
4. ct08 打桩正名:本单内降级 assembly/补三件套,还是另立标签卫生单(范围控制纪律倾向另立,但本机常红止血倾向随单做)。
5. 止血排序:fuzz04/ct08/bm03 本机 --run-integration 当前即红(ISS-0101 实证),是否 B/C/D 优先于 A 合入止血,还是按 A→B/C/D 顺序一次收敛。

## 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-10 | 建单:CI v0.3.6 首红(icons09)复盘,同族排查发现 icons10/fuzz04/ct08/ct12 环境假设残留;方向=环境不变量断言+显式守卫+CI 同款命令推送前必跑 |
| v0.2 | 2026-09-17 | 评估记录入单:现状仍成立,环境守卫模式已在新用例定型,保留排期 |
| v0.3 | 2026-09-22 | 整改方案落档:现状核验(四条全成立+新增 bm03 计时/bm04 真 daemon 两漏项,本机 --run-integration 916 passed 3 failed 实证 bm03/fuzz04/ct08 常红);机制层根因三条(断言层缺环境不变量规则/守卫无统一通道/本地与 CI 跑法断裂);六步改法(A 守卫 helper 收敛=纯重构,B icons10 round-trip 断言,C fuzz04/ct08 守卫+标签正名,D bm03 阈值+bm04 守卫,E 观察项登记,F 流程补丁),交叉面清单与五裁决项;状态转「方案已设计,待 sdfang 评审排期」 |
| v0.4 | 2026-09-22 | 裁决批准(按§8 推荐项):①bm03 采宽阈值(只挡路径级回退,与既有注释口径一致),不采报告式;②bm04 补在线守卫 skip(real_daemon_online(9420)),基准脚本不自拉起;③流程补丁写入 docs/SDD-开发流程.md §5,不新建 CONTRIBUTING.md;④ct08 标签正名随单做(补三件套/降级 assembly);⑤止血排序=按 A→B/C/D 顺序一次收敛,不插队。离场授权自决,记录在案;状态→方案已批准,待开发 |
| v0.5 | 2026-09-23 | **A~F 全部执行完毕(8 提交)**。①A(6f1d3c3):tests/envguard.py 收敛(env_skip 统一「环境守卫:」口径禁静默/notepad_mains/real_daemon_online/is_unoccluded_point/pick_unoccluded_desktop_icon),12 文件散落写法迁移(5 文件 _spawn_notepad 内联枚举/4 文件 daemon 守卫/window_ext 自定义文案 3 处/detector_int_req03 6 处/deeptree_iss88 4 处/clickguard_iss91 3 处/clicktarget_iss44 选图标同构/desktop_icons 全遮挡),纯重构 90 passed 18 skipped。②B(e572cb5):icons10 round-trip 环境不变量(region=首实体项 cell_rect 外扩 2px 自适应;part==full 经 rects_intersect 重算,直出比对);**双闸门登记①**:去除 0<count<full.count(探测桌面布局非过滤逻辑,过滤正确性由 round-trip 探测,无被掩盖行为)。③C(10ccca8):共享 _spawn_notepad assert→env_skip(可拉起的记事本窗口);ct08/fuzz04 补「可前置记事本窗口(前台锁受限)」守卫;ct08 迁入 TestClickTextAssembly(三件套+integration 标记保留=调度用途,批准④);**卫生根因实证**:Store 未保存 '*' 本机不消退,XAML 保存提示阻塞关窗(ct08 此前清理假绿全靠前置断言先败),_dismiss_xaml_save_prompt 自 test_typefocus_iss104 收敛入 envguard(ISS-0104 二次裁决形态共享化)——ct08/fuzz04 常红转绿,失败轮残留窗清零。④D(9b8fbc1):bm03 value=None 改 env_skip 明示;**差异上报(与现状不符)**:bm03 红根因非阈值而是触发前提残留——no-such-xyz-app.exe 已在本机静态白名单(演示期残留,launch 直达执行层报 WinError 2 无窗可测),阈值复核 l0 500ms/dialog 2000ms 已处路径级口径故不放宽反加守卫;**双闸门登记②**:None 场景不探测弹窗延迟(该行为由 test_perf_iss8 TestDialogService 单元钉+实盘手工测试覆盖);bm04 补 real_daemon_online(9420) 守卫(批准②)。⑤E(d2a4ddd):post_clear_session flaky 仅 docstring 观察登记,不放宽不装过。⑥F(cff8acd):推送前必跑 CI 同款命令入 SDD-开发流程.md §5 工作纪律表(批准③,不新建 CONTRIBUTING)。⑦**数字对比**:默认层全程 935 passed 0 failed(基线 935);集成层 --run-integration 由 ISS-0101 实证的 916 passed 3 failed(bm03/fuzz04/ct08 常红)→ **953 passed 0 failed 12 skipped**(bm03 明示 skip,ct08/fuzz04 真绿)。⑧相邻发现(范围控制只登记):test_enrollshot_iss73 tc13_second_screen_shot 同族环境敏感红(stash 对照=既有,非本单引入;与 tc10 同族,建议另案);no-such-xyz-app.exe 白名单残留属用户真实配置,未擅动(清理与否请人类裁决) |
