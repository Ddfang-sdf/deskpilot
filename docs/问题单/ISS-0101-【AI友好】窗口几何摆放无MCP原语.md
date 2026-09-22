# ISS-0101:【AI友好】窗口几何摆放无 MCP 原语——AI 只能裸写 Win32 MoveWindow 绕行

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0101 |
| 标题 | 演示编导/多窗协同场景需要把目标窗摆到指定位置(背景板摆位、并排对照、落点避让),MCP 无窗口几何写入原语;AI 唯一出路是裸写 ctypes MoveWindow——绕过强制层与审计面(2026-09-21 sdfang 怒批「为什么不用 MCP」事件的两大真实缺口之一) |
| 严重级 | **中**(能力缺口:迫使 AI 离开 MCP 面;非安全缺陷) |
| 状态 | **已关闭**(2026-09-22 验收通过:set_window_rect返回与读回逐值一致;sdfang 缺席授权自决,证据见 手工测试计划-20260922-四单整改升级验收 W5) |
| 提出 | 2026-09-21 sdfang 裁定:「B 提单」 |

## 1. 实证(机制层)

- 本会话为摆录制背景板,裸写 `ctypes.windll.user32.MoveWindow`——该操作
  不经 enforcement/audit,与「桌面操作必经 MCP 面」纪律直接冲突;
- 现有工具面盘点:attach/activate_window 只管绑定与置前,无任何改变
  窗口 rect 的入口;`move` 是鼠标移动,与窗口几何无关。

## 2. 设计草案(物理层原语,符合「工具=物理层」裁定)

- 新工具 `set_window_rect`:token + rect=[l,t,r,b](虚拟桌面坐标,
  与 screenshot/get_ui_tree 同一坐标系);
- 行为:ShowWindow(SW_RESTORE,最大化窗先还原再摆,防打回)+
  MoveWindow;返回新 rect(直出);
- 闸门:沿用 L2 写操作分级(与 click 同级);绑定进程窗限定(不得
  跨绑定摆别人的窗);
- 不做的事(判断归 AI):不做吸附/不做屏幕归属判定/不做避让计算——
  落点合理性由 AI 用 screenshot 自核(现有感知面足够)。

## 3. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-21 | 建单。裸 MoveWindow 实证+工具面盘点;设计草案=物理层原语+L2 闸门+判断归 AI |
| v0.2 | 2026-09-22 | sdfang 批准设计草案:set_window_rect 物理层原语(SW_RESTORE+MoveWindow,返回新 rect)+L2 闸门+绑定进程窗限定+判断归 AI |
| v0.3 | 2026-09-22 | **落位设计定稿**(§4:DPI 零换算实证;六装配点+两计数钉;不收 hwnd=结构性跨窗限定);**测试设计 8 用例+交叉面**(§5/§6);适配登记(§7) |
| v0.4 | 2026-09-22 | **P3 完成回填**。①实现落点:probe.py 增模块级 `set_window_rect()` OS 接缝(SW_RESTORE=9 恒定先发→MoveWindow,经模块 user32 单层,替身缝同 iss41 先例;与 activate 的 SW_SHOWMAXIMIZED 命令选择语义相反不复用);core.py `_dispatch` 增 set_window_rect 分支+新方法 `_set_window_rect`(rect=[l,t,r,b] 四点式自解为 MoveWindow (l,t,r-l,b-t);几何非法 r<=l/b<=t→INVALID_PARAMS 且 user32 零调用;MoveWindow False→WINDOW_GONE;返回 {"rect": list(rect_of(hwnd))} 直出);tools/__init__.py 增公开封装(走 enforcement.submit 默认分支,不进 _L0/_L1_DIRECT)。②自查纠偏一次:初版把接缝落成 DesktopProbe 实例方法,单测 FakeProbe 无此方法(替身钉在 probe.user32 模块层)——改为模块级函数接缝(与 P2 裁决②「probe 模块 user32 接缝」严格对齐),core 经 `from .probe import set_window_rect` 调用(禁 core 直引 ctypes)。③测试数字:P1 基线 898 绿 2 红;P3 后受影响面(test_wingeo_iss101+validation+detector_orch+activate_iss41)**72 passed 3 skipped**;全量默认层 **900 passed 0 failed**;全量 --run-integration 916 passed 3 failed——bm03/fuzz04/ct08 经 git stash 基线对照为**既有环境红**(本 session 第四次复验,与本单无引用关系)。④**TC-101-06 逃逸口实证**:`ISS101_FORCE_E2E=1 ... -k tc101_06` → **1 passed**(真 daemon 9420 在线无冲突;真记事本 attach→set_window_rect [100,100,700,600]→返回 rect 与 find_window 读回同口径一致;零窗口残留)。⑤登记项:P2 裁决四点全部照办(返回形态/probe 模块接缝/TC-101-04 既有死窗闸不破坏/description 不动);§7 两条计数钉适配(test_validation==30/test_detector_orch_req03 合法重指==30)随声明落地转绿;逃逸口 ISS101_FORCE_E2E 备案(ISS-93 先例)。⑥文档翻页 §4.3 全项:详设 §14.1(9→10)/§14.2/§14.4/§14.5;功能设计 F-L2 清单+F-L2-10 小节;DESIGN.md 工具契约表;README/README.zh-CN(29→30);测试设计说明书补 TC-N-L2-02b。⑦偏差知悉:DESIGN.md §4.3 所列 :186 为 M2 里程碑历史行(新工具非 M2 内容),未翻历史,仅工具契约表(:118)落行,待裁决;详设 §14.1 计数句口径=本节枚举工具(click_text/mouse_down/mouse_up/hold 等后增工具历史未入本节枚举,属既有漂移,另案记录不混做) |
| v0.5 | 2026-09-22 | **验收通过关单**(sdfang 离场留言授权自决,记录在案)。证据:手工测试计划-20260922-四单整改升级验收 W5,set_window_rect 返回与读回逐值一致 |

## 4. 落位设计(P3 实现依据)

### 4.1 装配六点(+i18n)
①models.py TOOL_LEVELS 加 `set_window_rect: L2`(click 同级);②models.py BINDING_REQUIRED_TOOLS 加;③mcp_server.py TOOL_SCHEMAS 注册(required: token:("str",), rect:("rect",)——rect 四元型有 _check_type 现成先例 :289-295);④tools/__init__.py 公开封装(走 enforcement.submit 默认分支,不进 _L0/_L1_DIRECT);⑤executor/core.py _dispatch 加分支+新方法 `_set_window_rect`;⑥i18n.yml 增 `enf.act.set_window_rect` 双语键(en "Resize/move window"/zh "调整窗口位置尺寸";f-string 键 i01 钉扫不到,但 REQ-007 设计义务,必加)。
入参语义:rect=[l,t,r,b] 四点式(与 screenshot scope=region 的 [x,y,w,h] 不同,实现内自解);**不收 hwnd**——hwnd 由闸一从绑定记录取出(enforcement.py:311-312),**结构上只能摆绑定的那个窗**=「不得跨绑定」的最顺落位(测绘 §4),进程漂移由 binding._is_stale 既有核对兜底。

### 4.2 实现核心(DPI 零换算,测绘实证)
- 坐标系:daemon 启动即 PMv2(main.py:17-65),GetWindowRect/UIA/mss/MoveWindow 全链物理像素=虚拟桌面坐标,detector.py:88-93「逐分量平移不缩放」——**rect 入参直接喂 MoveWindow,零换算**;
- 动作序:`ShowWindow(hwnd, SW_RESTORE)`(恒定先发,最大化/最小化先还原防打回;**与 probe.activate 的 IsZoomed→SW_SHOWMAXIMIZED 相反,不复用其命令选择**)+ `MoveWindow(hwnd, l, t, r-l, b-t, True)`;probe.py 增 MoveWindow ctypes 接缝(生产真 user32,测试 monkeypatch 替身,同 iss41 先例);
- 返回:`probe.rect_of(hwnd)` 直出(新 rect,与 GetWindowRect 同口径——含不可见边框扩展矩形,全仓统一口径,像素级偏移属既定不避让范围);
- 错误码零新增:死窗 WINDOW_GONE(_dispatch 统一检查既有);几何非法(r<=l 或 b<=t)INVALID_PARAMS(executor 拒,与 _resolve_region 先例一致);MoveWindow 返 False→WINDOW_GONE。

### 4.3 两计数钉+文档翻页
- test_validation.py:26-27 `len(TOOL_SCHEMAS)==29`→30(注释沿革更新);test_detector_orch_req03.py:444-445 `==29`「本单零新工具」历史钉**合法重指**(REQ-002 先例,§7 登记);
- 文档:详设 §14.1 计数句/§14.2 功能表/§14.4 输入项/§14.5 输出项;功能设计 :124 F-L2 清单+:438;DESIGN.md:118/:186;README(:115「29 MCP tools」→30,zh-CN 同步);测试设计说明书 :275 附近。

### 4.4 不做的事(裁定边界)
不做吸附/屏幕归属判定/避让计算——落点合理性 AI 用 screenshot 自核;不接 hwnd 入参(防跨窗);不做 DPI 换算(PMv2 前提,documented 残留:非 main.py 启动的独立直跑场景落系统缩放坐标系,登记)。

## 5. 测试设计(五要素)

| 用例编号 | 层级 | 测试场景 | 测试前提 | 测试步骤 | 测试预期结果 | 断言代码(断什么/由什么直出) |
|---------|------|---------|---------|---------|-------------|---------------------------|
| TC-101-01 | 形态 | 注册面三处一致 | 注册表直读 | 读 TOOL_SCHEMAS/TOOL_LEVELS/BINDING_REQUIRED_TOOLS | 三处均含 set_window_rect;级别 L2;required=token+rect(rect 型);描述 ≤200 含领域词 | 注册表直读 |
| TC-101-02 | 单元 | 正常摆放动作序 | probe user32 替身(iss41 先例);Executor 真装配 | execute set_window_rect(token 链 hwnd,rect=[100,100,700,600]) | ShowWindow(SW_RESTORE) 先于 MoveWindow;MoveWindow 收 (hwnd,100,100,600,500,True);返回新 rect | 替身调用序列直出;返回值=rect_of 直出 |
| TC-101-03 | 单元 | 几何非法 fail-closed | 同上 | rect=[700,100,100,600](r<l)/[100,600,700,100](b<t) | ExecutorError INVALID_PARAMS;user32 零调用 | 异常 code 直出;替身零调用记录 |
| TC-101-04 | 单元 | 死窗 | hwnd_alive 替身 False | 同上合法 rect | WINDOW_GONE;user32 零调用 | 异常 code 直出 |
| TC-101-05 | 形态 | 结构性跨窗限定 | 注册表直读 | 读 schema required/optional | 无 hwnd 参数(仅 token+rect) | 注册表直读(闸一绑定链由既有 NO_BINDING 钉回归覆盖) |
| TC-101-06 | 集成 | 真记事本摆放读回 | 真记事本;环境守卫(daemon 在线 skip) | attach→set_window_rect [100,100,700,600] | 返回 rect 与 find_window 读回矩形同口径一致 | 返回值直出;find_window rect 直读对照 |
| TC-101-07 | 形态 | 审批文案双语键 | i18n.yml 直读 | 读 enf.act.set_window_rect | en/zh 双键非空 | YAML 解析直读 |
| TC-101-08 | 形态 | 计数钉重指 | 注册表直读 | len(TOOL_SCHEMAS) | ==30 | 直读 |

## 6. 交叉面清单(§2.1)

| 触及对象 | 其他写入者/读取者 | 覆盖用例 | 或豁免理由 |
|---------|-----------------|---------|-----------|
| TOOL_SCHEMAS 计数 | test_validation:26/test_detector_orch_req03:444 两 ==29 钉 | TC-101-08+§7 登记 | 合法重指先例 REQ-002 |
| 全工具遍历钉 | iss15/iss40/boundary/i01 | 全量回归 | rect 型 type_map 已有,零扩展 |
| _dispatch 统一死窗检查 | 全工具共用(core.py:635-636) | TC-101-04 | 机制复用不改 |
| probe user32 接缝 | activate/rect_of 既有使用者 | TC-101-02+回归(test_activate_iss41) | MoveWindow 新增不扰既有 |
| ShowWindow 语义分歧 | probe.activate(IsZoomed→SW_SHOWMAXIMIZED) | 回归(iss41 钉) | 本单 SW_RESTORE 恒发,两语义各自钉守不混 |
| enforcement 审批描述 | _describe 兜底 f"执行 {tool}"(:556-563) | TC-101-07 | i18n 键补齐;缺键兜底路径回归 |
| 冻结期行为 | L2 写路径 enforcement G0/execute 复查既有 | 回归(test_secdesk_iss87 sd07 类) | 新工具走同一 enforcement.submit 自动获闸 |
| PMv2 前提 | main.py:17-65 声明;httpd dpi_mode 回报 | 回归 | 独立直跑残留风险登记 §4.4 |

## 7. 测试退役/适配登记(双闸门·登记闸)

| 用例 | 处置 | 原因 |
|------|------|------|
| test_validation.py:26-27(==29) | 适配:29→30+注释沿革 | 新工具合法增量 |
| test_detector_orch_req03.py:444-445(==29「本单零新工具」) | 合法重指:29→30(REQ-002 先例:历史单据钉按现状重指,登记) | 该钉锁的是 REQ-003 时点的工具面,新工具经 ISS-0101 立项批准,非私改迁就 |

## 8. P1/P2 记录(2026-09-22)

**P1 实证**:全量 `898 passed + 2 failed`(红=TC-101-02/03,精确落在 _dispatch 未接线;TC-101-06 逃逸口实证红;其余绿;两条计数钉适配后绿;旧用例零误伤)。

**P2 逐用例核对表**:

| 用例 | 入口(与设计一致?) | 断言值出处 | 五要素 | 结论 |
|------|------|-----------|--------|------|
| TC-101-01 | 三注册表 ✓ | 注册表直读 | ✓ | 一致(绿=声明已落) |
| TC-101-02 | Executor.execute 全链 ✓ | 替身调用序列+rect_of 直出 | ✓ | 一致 |
| TC-101-03 | 同上 ✓ | 异常 code+替身零调用直出 | ✓ | 一致(双子向) |
| TC-101-04 | 同上 ✓ | 异常 code 直出 | ✓ | 一致(P1 即绿=既有死窗闸复用,正确落点,备案) |
| TC-101-05 | schema 直读 ✓ | 注册表直读 | ✓ | 一致 |
| TC-101-06 | POST /call ✓ | 响应体 rect+find_window 读回对照直读 | ✓ | 一致(逃逸口 ISS101_FORCE_E2E 备案) |
| TC-101-07 | i18n.yml ✓ | YAML 解析直读 | ✓ | 一致 |
| TC-101-08 | TOOL_SCHEMAS ✓ | 直读 | ✓ | 一致 |

交叉面逐行确认:两计数钉(§7 登记)✓;遍历钉(回归)✓;_dispatch 死窗闸(TC-101-04)✓;probe user32 缝(TC-101-02 缝约定)✓;ShowWindow 语义分歧(iss41 回归)✓;审批描述兜底(回归)✓;冻结闸(enforcement.submit 路径自动获闸,回归)✓;PMv2 前提(登记)✓。不一致 0 项。

**P2 裁决四点**:①TC-101-04 P1 即绿备案(既有机制正确继承,非误绿);②返回形态定案 `{"rect": list(rect_of(hwnd))}`(响应侧 data.rect);③替身缝定案=probe 模块 user32(P3 必须经 probe 调用 MoveWindow/ShowWindow,禁 core.py 直引 ctypes);④逃逸口 ISS101_FORCE_E2E 备案;description 终稿 138/200 备案(全文见 P1 交接与 mcp_server.py)。
