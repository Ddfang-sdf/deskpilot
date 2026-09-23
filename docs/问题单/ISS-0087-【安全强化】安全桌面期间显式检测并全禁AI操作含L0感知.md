# ISS-0087:【安全强化】安全桌面(锁屏/UAC)期间显式检测并全禁 AI 操作——含 L0 感知与截屏

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0087(号段说明:ISS-0086 曾用于误冻结整改单,已按裁定删除,不复用) |
| 标题 | 把「锁屏/UAC 审批弹窗期间 AI 禁止一切操作」从**副作用达成**升级为**显式检测 + 显式强制**;读取面(截屏/OCR/元素树)目前在冻结期默认放行,须纳入禁令 |
| 严重级 | **高**(安全语义缺口:原则已裁定,实现无显式强制) |
| 状态 | **已关闭**(2026-09-23 验收通过:实盘锁屏——锁屏期 get_cursor/screenshot 全拒 SECURE_DESKTOP(含 L0),解锁自动恢复零人工复位;sdfang 在场配合+离场授权自决) |
| 提出 | 2026-09-14/15 sdfang 两度裁定 |

## 1. 背景与裁定原话

sdfang 2026-09-15:「AI 的操作,必须在人类能直接看到的情况下,不应该在锁屏之后,还可以操作电脑。另外,UAC 审批弹框的时候,AI 是绝对禁止操作鼠标键盘的,**连截屏也不可以**。」

语义:**人类不可视 = AI 不可动**。锁屏=人不在场;UAC 弹窗=人类裁决面。

## 2. 现状缺口(实证)

| 面 | 现状 | 出处 |
|----|------|------|
| 冻结触发 | 安全桌面切换时,光标读数退化为角点 → 甩角判定误吞 → 冻结(**副作用达成**,非显式检测;按裁定保持该行为) | `estop.py:72-88`;2026-09-14 20:44 实发(seq 319) |
| 写操作(键鼠) | 冻结后全停 ✅ | 既有 |
| **读取面(截屏/OCR/元素树)** | **冻结期 L0 默认放行,未禁** ❌ | `policy.yml` `estop.l0_during_freeze: true`(ISS-0003「冻结期 L0 默认可用」定案) |
| 副作用脆弱性 | 若 Windows/库行为变化使读数不再退化 (0,0),**冻结本身会静默消失**——写操作面也将裸奔 | 本单立项即含此隐患的消解 |

## 3. 整改方向(立案时已裁定)

| # | 方向 | 说明 |
|---|------|------|
| ① | **显式安全桌面检测通道** | Win32 层探测(如 OpenInputDesktop 与默认桌面对比 / WTS 会话锁事件订阅,具体选型实现期定);检测到锁屏/UAC 安全桌面激活 → 进入「安全桌面态」 |
| ② | **安全桌面态 = 全禁** | 写操作(既有冻结语义)+ **L0 感知(截屏/OCR/元素树)一并拒绝**,返回结构化错误(新码或复用 EMERGENCY_STOP,错误语义评审期定,AI 侧指引:人类正在裁决/不在场,等待恢复) |
| ③ | **审计如实** | 触发理由记「安全桌面激活」,与「鼠标甩角」**可区分**(不再借道误记) |
| ④ | **不弱化既有** | 甩角/热键触发语义不变;ISS-0028(防抖)/ISS-0049(边沿)成果不回退 |

**与被撤单(原 ISS-0086)的边界**:那单是把「安全桌面致冻结」当误报修掉——裁定否决;本单是**承认并强化该冻结**,把触发从副作用升级为显式机制,并把禁令扩展到读取面。方向相反,勿混淆。

## 4. 验收口径(要点,测试设计另立)

- 安全桌面激活(锁屏/UAC,可用替身注入检测信号) → 写操作拒绝 **且** `screenshot`/`ocr`/`get_ui_tree`/`get_clickable_map` 等 L0 **全部**结构化拒绝;
- 安全桌面退出 → 全功能自动恢复,无需人工复位(与甩角冻结的「须人工复位」语义**不同**,须显式设计);
- 真实甩角/热键冻结回归不回归坏;
- 审计:安全桌面态的进入/退出/拒绝各留痕,理由与甩角可区分;
- fail-closed:检测通道自身失效(无法判定桌面态)时按**安全桌面态**处理(宁可误禁,不可漏放)——此点评审期确认。

## 5. 约束

- 「保持原状」裁定的精确边界:**冻结行为保持**,触发机制允许显式化;甩角判据不弱化;
- 与 ISS-0002(瘦代理)、ISS-0003(冻结期 L0 定案的**修订**)、ISS-0004(冻结弹窗)衔接:本单修订 `l0_during_freeze` 在安全桌面场景下的适用边界,其余冻结期 L0 放行语义不变;
- 实现走 SDD P1→P2→P3;文档随代码走(§2 现状表须同步翻页)。

## 6. 测试设计(P1 前置,五要素;2026-09-17 补立)

**设计裁定备案(自主推进授权下自决,系统/功能层面)**:
- **错误码**:新码 `SECURE_DESKTOP`,**不复用 EMERGENCY_STOP**——语义不同:安全桌面退出后**自动恢复**(无需人工复位),急停冻结**须人类复位**;混码会误导 AI 的自愈方向(等待 vs 叫人)。错误消息附 AI 自愈指引(稍后重试)。
- **fail-closed(§4 尾待确认点)**:采纳——检测通道异常按激活处理并审计「安全桌面检测失效」;依据=全局 SDD 安全路径 fail-closed 原则。
- **闸门落点**:`tools.call_tool` 顶部统一闸(覆盖 L0 感知/L1/写/attach/detach 全部工具,http/stdin 两形态共用此入口);不进 executor 层(执行层冻结复核既有,范围控制)。
- **检测通道**:Win32 OpenInputDesktop+GetUserObjectInformationW 读桌面名,非 "Default" 即安全桌面(锁屏/UAC 同属);失败 fail-closed。
- **边沿审计**:SecureDesktopGuard 持有状态,进入记「安全桌面激活」、退出记「安全桌面退出」、每次拒绝记「安全桌面拒绝」——与「急停触发:鼠标甩角」可区分(整改③)。

| # | 场景 | 前提 | 步骤 | 预期 | 断言(出处) |
|---|------|------|------|------|-----------|
| sd01(单元) | 安全桌面激活拒 L0 | detector 桩→True;executor 桩记录;audit 桩 | call_tool("screenshot") | 结构化拒绝 SECURE_DESKTOP;截图未执行;审计含激活+拒绝 | `r.ok is False`+`r.error_code=="SECURE_DESKTOP"`(返回值直出);executor 桩零调用;audit 桩含「安全桌面激活」「安全桌面拒绝」 |
| sd02(单元) | 安全桌面激活拒写/拒绑定 | 同上;enforcement 桩记录 submit | call_tool("click",token)+call_tool("attach") | 均拒 SECURE_DESKTOP;强制层零接触 | 两个 r.error_code=="SECURE_DESKTOP";enforcement 桩 submit 零调用 |
| sd03(单元) | 正常桌面放行(防过修) | detector 桩→False;executor 桩返回 dict | call_tool("screenshot") | 正常执行 | `r.ok is True`;executor 桩 screenshot 调用 1 次 |
| sd04(单元) | 检测失效 fail-closed | detector 桩抛 OSError | call_tool("screenshot") | 按激活拒绝+审计留痕 | r.error_code=="SECURE_DESKTOP";audit 桩含「安全桌面检测失效」 |
| sd05(单元) | 退出自动恢复+边沿审计 | detector 桩序列 [True,False,True] | 连调三次 screenshot | 拒→通→拒;审计边沿各一条 | 三次 r.ok=[False,True,False];audit 桩事件序列含「安全桌面激活」「安全桌面退出」「安全桌面激活」 |
| sd06(集成) | 真实检测通道无误禁 | 真实 SecureDesktopGuard(真 Win32 检测,无桩)+真 Executor | 真 call_tool screenshot fullscreen | 活动未锁屏桌面不误判 | `r.ok is True`;盘上 PNG 存在(数据层直读) |
| sd07(单元) | 普通冻结边界不变 | estop 真冻结(热键入口触发);detector 桩→False | click(写)与 screenshot(L0)各一 | 写仍 EMERGENCY_STOP;L0 仍放行(ISS-0003 边界不回退) | click r.error_code=="EMERGENCY_STOP";screenshot r.ok is True |

## 7. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-15 | 立项。sdfang 裁定原话入库(§1);现状缺口三行实证(§2);方向①~④立案时已裁。与原 ISS-0086 的边界明示(§3 尾) |
| v0.2 | 2026-09-17 | **P3 完成回填**。①实现落点:`secure_desktop.py` 新模块——`is_secure_desktop_active`(OpenInputDesktop+GetUserObjectInformationW UOI_NAME 读桌面名,≠"Default" 即安全桌面=锁屏/UAC 同属;任何 API 失败 fail-closed 按激活)+`SecureDesktopGuard`(detector 注入缝;边沿审计「安全桌面激活/退出」,首检即激活记激活、首检正常不记基线;「安全桌面检测失效」节流=失效边沿一条);errors.py 新码 `SECURE_DESKTOP`;tools/__init__.py——`call_tool` 顶部统一闸(全覆盖 L0 感知/L1/写/attach/detach,http/stdio 两形态共用此入口),拒绝逐次审计「安全桌面拒绝」+结构化错误附 AI 自愈指引(稍后重试),`ToolContext.secure_guard` 字段+`_default_guard()` 缺省真检测兜底(防「忘装配=静默放行」);main.py:556 装配 `SecureDesktopGuard(audit=audit)`。②裁定备案(自主推进授权,系统/功能层面):a)**新码 SECURE_DESKTOP 不复用 EMERGENCY_STOP**——安全桌面退出自动恢复、急停冻结须人工复位,自愈方向不同,混码误导 AI;b)§4 尾 fail-closed 待确认点**采纳**(检测失效按激活,SDD 安全路径原则);c)闸门落点 tools.call_tool 顶部,不进 executor 层(范围控制;执行层冻结复核既有);d)已知边界明示:L3 同步审批等待期间锁屏的中途案例由甩角副作用冻结+闸四后 estop 复核(enforcement.py:267)覆盖,安全桌面闸不设中途复核。③SDD 实证:P1 红四条——sd01 ok=True/sd02 error_code=''/sd04 ok=True/sd05 [True,True,True],禁令未启用全现形;sd03/sd06/sd07 红期即绿(放行回归+真实检测通道验证链+边界钉);P3 绿(tests/test_secdesk_iss87.py 7 passed);全量回归 **784 passed, 24 skipped, 0 failed**(基线 777/24)——默认守卫真 Win32 检测在全套件每次 call_tool 实跑,零误禁;零修复(P3 一次过)。④既有边界核验:sd07 钉住普通冻结语义(写 EMERGENCY_STOP+L0 放行);甩角/热键触发语义未动,ISS-0028/ISS-0049 成果不回退(全量回归绿为证)。⑤衔接修订明示:ISS-0003 `l0_during_freeze` 定案的修订边界=**安全桌面态**全禁(独立闸门+独立码+独立审计事件),普通冻结期 L0 放行语义不变,旗标本身未改;§2 现状表据此翻页:读取面在安全桌面态已显式拒绝 |

| v末 | 2026-09-23 | **验收通过关单**(实盘锁屏全链:检出→全禁含截屏→自动恢复;sdfang 在场 Win+L 配合) |
