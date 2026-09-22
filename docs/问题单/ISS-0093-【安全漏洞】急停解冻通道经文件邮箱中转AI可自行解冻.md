# ISS-0093:【安全漏洞】急停解冻通道经文件邮箱中转——AI 可自行解冻,冻结形同虚设

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0093 |
| 标题 | `estop-reset-{seq}.req` 文件邮箱(ISS-0004/0006 定案的弹窗解冻传输层)把「人类点击解冻」编码成**任何进程可复现的文件**;持 MCP 的 AI 天然拥有命令执行与文件读写(宿主 shell)——AI 可自行写 req 文件解冻,**急停作为最后防线被自有协议绕过** |
| 严重级 | **严重**(安全面:急停解冻通道可被被防对象自行调用;已实证) |
| 状态 | **已关闭**(2026-09-22 验收通过:三通道消亡+state旁路焊死+弹窗直调解冻+零req;sdfang 缺席授权自决,证据见 手工测试计划-20260922-四单整改升级验收 W2/W3/W8) |
| 提出 | 2026-09-18 sdfang 当场裁定;同日升级验收手工测试 AI 自行解冻实证 |

## 1. 裁定原话(2026-09-18,逐字)

> 「不合法!这是重大安全隐患。使用mcp的AI天然就拥有命令执行,文件读写的能力。你再搞个中转文件,这不就让冻结形同虚设么?!提单,写明安全漏洞!
>
> 正确做法应该是不暴露任何接口和文件,用户点击弹框,指令直达程序,完成解冻,这个动作不应该经过任何中转,不暴露任何接口和工具!」

**本单目的(sdfang 2026-09-18 补充裁定,验收基准)**:「解冻这个事情,
只能人类操作,AI 没有任何途径可以去自我解冻。」——验收口径=枚举全部
能改变 frozen 态的入口逐一关闭至人类独占,AI 侧零可达路径(含 shell 级
文件写/curl/SendInput 模拟热键等旁路一并纳入清点)。

## 2. 实证(2026-09-18 升级验收手工测试,AI 亲手演示)

- AI(Claude)在 daemon 冻结期间,直接往 `%LOCALAPPDATA%\DeskPilot\` 写
  `estop-reset-52.req` 文件(纯文件写,无任何鉴权),daemon 消费后解冻
  (审计:急停复位,来源=冻结提示弹窗)——**AI 未碰弹窗、未按热键,自行完成了人类专属动作**;
- 同族暴露面:`deskpilot.exe --reset` CLI(HTTP POST /estop/reset,localhost
  接口,AI 可 curl)——同日另一条被 AI 使用的解冻通道。

## 3. 根因(机制层)

**信任锚点错置**:把「人类点击弹窗按钮」这一意图事实,编码成「共享目录里
一个名字可预测、内容无鉴权的文件」。文件的**存在**不构成人类意愿的**证明**——
任何能写该目录的进程都能生产它。防 AI 犯错的冻结闸,其解除面却落在 AI 可
直达的介质上,等于闸门的钥匙挂在门上。

## 4. 整改方向(sdfang 已定原则;落位待方案评审)

**原则(裁定)**:不暴露任何接口和文件;用户点击弹框,指令直达程序完成
解冻;不经过任何中转,不暴露任何接口和工具。

落位推演(实现细节,评审期细化):
- 冻结弹窗在**属主进程内线程形态**(DialogService,ISS-0008 P6)下,点击
  「立即解冻」可**进程内直接调** `estop.dialog_reset()`——零 IPC、零文件、
  零接口,天然满足裁定;子进程形态(`--freeze-notify`)则需一次性、随机
  命名、内存态的进程间通道(每轮冻结随机名,只存于弹窗与属主内存),且
  **冻结期间 AI 写操作全拒**的既有闸门不变;
- 关联暴露面(2026-09-22 sdfang 已裁定):①CLI `--reset` / HTTP `/estop/reset`(localhost
  接口,AI 可 curl)——**一并收口删除**,人类终端复位通道废止,解冻入口收敛为
  「弹窗点击+热键」两个人类独占通道;②复位热键 Ctrl+Shift+F11——**保留**
  (物理输入通道,人类专属;shell 级 SendInput 模拟为既有残余风险,登记留档)。

## 5. 约束

- fail-closed;人类解冻通道的**可用性不得下降**(弹窗点击须更可靠,非更麻烦);
- ISS-0092 的 req 消费可靠性整改随通道移除而废止(相关测试同步退役,
  单据回填注明);
- ISS-0004/0006 的文件邮箱协议文档随代码翻页;
- 与 ISS-0087(安全桌面全禁)同族收编:解冻通道的暴露面清点须含全部
  「能改变 frozen 态」的入口。

## 6. 连带证据

- 同日实测:冻结形态(PyInstaller)构建上 req 消费面失效(两次写 req 均不
  消费,源码形态 0.2s 消费正常)——该通道**既不可靠也不安全**,支持整体移除;
- 该缺陷另立跟踪或随本单废止(若通道移除,缺陷随之消失)。

## 7. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-18 | 建单。sdfang 裁定原话入库(§1);AI 自行解冻实证(§2);信任锚点错置根因(§3);整改原则+落位推演+关联面待裁定项(§4);冻结形态消费缺陷连带证据(§6) |
| v0.2 | 2026-09-22 | 关联面两项裁定落槌(sdfang):①`--reset` CLI + `/estop/reset` HTTP 接口**一并收口删除**,人类终端复位通道废止;②Ctrl+Shift+F11 复位热键**保留**(SendInput 模拟为残余风险登记) |
| v0.3 | 2026-09-22 | sdfang 批准整体落位方案:弹窗进程内直调+子进程一次性随机内存通道+三通道收口删除+全暴露面清点;状态转「待开发(P1)」 |
| v0.4 | 2026-09-22 | **暴露面清点落档**(§8,测绘补获 state 文件直写旁路 E7 并纳入);**落位设计定稿**(§9:子进程通道定案=退出码 73,零文件零接口零命名);**测试设计 12 用例+交叉面清单**(§10);退役/适配按双闸门登记(§11);残余风险登记(§12) |
| v0.5 | 2026-09-22 | **P1 完成+P2 核对**(核对表见下)。P1 实证:全量 867 绿+10 红,红色全部精确落在未实现行为,旧用例零误伤;退役/适配按 §11 执行。P2 裁决四点:①**§9.4 反向修正**——v0.4「shared true→灌回本地冻结」与 ISS-0092 fg04「本地权威防假象」冲突且该方向无安全增益,修正为沿用 fg04(本地不冻+修共享),TC-93-03 反向同步改;fg04 补登记保持不动;②退出码消费方法名定案 `FreezeNotifier.check_dialog_exit(estop)`;③TestResetClickAction 补登记(P3 适配时另行登记);④TC-93-12 环境逃逸口 ISS93_FORCE_E2E 知悉备案;EXIT_RESET=73 常量声明先行落地备案。P2 核对结论:12 用例入口/断言出处/五要素与设计一致(TC-93-03 反向除外,已按①修正) |
| v0.6 | 2026-09-22 | **P3 完成回填**。①实现落点:estop.py 删 cli_reset/shared_sync_reset;httpd.py 删 /estop/reset 分支(estop 注入保留,idle 豁免在用);main.py 删 _cli_reset 与 --reset 分派、_corner_loop 消费点改 check_dialog_exit、装配注入 notifier.on_reset=estop.dialog_reset;dialog_service freeze 分支透传 on_reset;freeze_dialog 删 write_reset_request、build_window(on_reset=) 实现(进程内直调+滑出/子进程关窗+EXIT_RESET,main() 在 mainloop 返回后产出退出码 73——Tk 回调内 SystemExit 被 tkinter 吞,双保险)、reset_click_action token 更名 reset_and_slide_out;freeze_notify 删 REQ_FILE/REQ_PREFIX/check_reset_request、check_dialog_exit 实现(持本轮 Popen 句柄,poll==73→dialog_reset,一次性)、_default_spawn 返回 Popen+payload 注 on_reset、sync 单向化(本地权威两方向只修共享,§9.4 v0.5)。②测试数字:P1 基线 867 绿+10 红;P3 后受影响面(9 文件,--run-integration)**69 passed 1 skipped**(TC-93-12 环境守卫 skip=真 daemon 在线,预期);全量默认层 **877 passed 0 failed**;全量 --run-integration 895 passed 3 failed——3 红(test_benchmark_iss8 bm03/test_selfheal_iss27 fuzz04/test_clicktext_iss21 ct08)经 git stash 基线对照为**既有环境红**(真 OCR/真桌面依赖,与本单无引用关系,改动前同样红)。③双闸门登记:TestResetClickAction token 更名(§11 表内);fg03 _NotifierStub 接口随设计更名 check_reset_request→check_dialog_exit(计数语义不变);TC-93-10 对照数据准备修正(静态条目→会话条目——静态撤回需落盘,policy_path=None fail-closed 抛 PolicyError,P1 前提写错;断言不变)。④**停手汇报项:TC-93-12 前提装配缺 on_reset 注入**——其装配(真 EstopMonitor+FreezeNotifier+DialogService)未镜像 main.py 的 notifier.on_reset=estop.dialog_reset 接线(TC-93-06 钉住的真实管线),弹窗落入子进程语义(点击关窗,SystemExit 73 被 tkinter 吞),estop 不复位;ISS93_FORCE_E2E=1 实证红在测试装配而非实现。建议授权修正:测试装配补一行 notifier.on_reset=estop.dialog_reset(与生产接线一致),待人类裁决。**(2026-09-22 已裁决授权并落实:TC-93-12 装配备案修正——测试 bug,镜像 main.py 生产接线,断言零改动;实测:test_estopreset_iss93.py --run-integration 12 passed 1 skipped,带 ISS93_FORCE_E2E=1 逃逸口单条实证 1 passed——真 daemon(9420) 在线未发生单例互斥冲突,全链:真 Tk 弹窗点击「立即解冻」→ 进程内直调复位 → 零 req 落盘 → 审计 detail=「冻结提示弹窗」,尾部 Tcl_AsyncDelete 为 Tk 线程退出噪音,非失败)**⑤文档翻页 §9.5 全项执行(INSTALL/功能/详细/测试设计说明书+ISS-0002/0004/0049/0084/0092+CHANGES.md,标废止不删历史) |
| v0.7 | 2026-09-22 | **验收通过关单**(sdfang 离场留言授权自决,记录在案)。证据:手工测试计划-20260922-四单整改升级验收 W2/W3/W8,三通道消亡+state 旁路焊死+弹窗直调解冻+零 req |

### P2 逐用例核对表(2026-09-22)

| 用例 | 入口(与设计一致?) | 断言值出处 | 五要素 | 结论 |
|------|------|-----------|--------|------|
| TC-93-01 | estop.dialog_reset ✓ | is_frozen() 返回值+审计 detail 直读 | ✓ | 一致(绿=语义平移,自检已备案) |
| TC-93-02 | 五文件源码直读 ✓ | 文本检索命中清单 | ✓ | 一致 |
| TC-93-03 | sync_local_with_shared_state ✓ | is_frozen()+shared 盘上文件+审计直读 | ✓ | **反向按 v0.5 修正**(fg04 语义),正向一致 |
| TC-93-04 | build_window(on_reset=) ✓ | 桩记录+目录 glob 直读 | ✓ | 一致 |
| TC-93-05 | show→真实 _default_factory ✓ | 替身工厂入参记录直出 | ✓ | 一致 |
| TC-93-06 | main.py 源码直读 ✓ | 正则命中(接线钉,反模式纪律) | ✓ | 一致 |
| TC-93-07 | build_window(on_reset=None) ✓ | SystemExit.code 直出+常量直读 | ✓ | 一致 |
| TC-93-08/09 | FreezeNotifier.check_dialog_exit(命名定案) ✓ | is_frozen() 直出;assembly 三清单 docstring ✓ | ✓ | 一致 |
| TC-93-10 | 真 HttpDaemon HTTP 外表面 ✓ | 响应体 error_code 直出;对照端点不误伤 ✓ | ✓ | 一致(integration 标签合规:零 mock+断在响应体) |
| TC-93-11 | main.py 源码直读 ✓ | 文本检索 | ✓ | 一致 |
| TC-93-12 | 真实管线全链(真 Tk) ✓ | is_frozen()+glob+审计 detail 直读 | ✓ | 一致(本机实测 Tk 可起,未降级;环境守卫同 fg05 先例) |

交叉面清单逐行确认:estop-state.json(TC-93-03/12)✓;is_frozen 读者(全量回归)✓;HttpDaemon estop 注入(TC-93-10 对照)✓;Tk 替身契约(tk_rig+release_singleton)✓;审计事件名(TC-93-01/03)✓;热键/甩角(回归)✓;policy estop 节(现状标注)✓。不一致项 0(除已修正的 TC-93-03 反向)。

## 8. 暴露面清点(2026-09-22 测绘,验收口径=全部能改变 frozen 态的入口)

| # | 入口 | 机制(证据) | 处置 |
|---|------|-----------|------|
| E1 | 急退热键 Ctrl+Shift+F12 → on_trigger_hotkey | estop.py:44-46←main.py:151 | 保留(置位,fail-closed 方向) |
| E2 | 甩角 → check_corner | estop.py:64-85←main.py:191 | 保留(置位) |
| E3 | 复位热键 Ctrl+Shift+F11 → on_reset_hotkey | estop.py:48-50←main.py:153 | **保留**(sdfang 裁定) |
| E4 | 弹窗「立即解冻」→ write_reset_request → req 邮箱 → check_reset_request → dialog_reset | freeze_dialog.py:94-97/253-267;freeze_notify.py:76-115←main.py:192 | **链路删除,改进程内直调/退出码通道**(§9.1/9.2) |
| E5 | HTTP POST /estop/reset → cli_reset | httpd.py:273-285 | **删除** |
| E6 | CLI --reset → _cli_reset → E5 | main.py:239-261/428-429 | **删除** |
| E7 | **直写 estop-state.json frozen:false → sync_local_with_shared_state → shared_sync_reset**(测绘补获:与 req 邮箱等效的解冻旁路) | freeze_notify.py:117-147←main.py:193 | **关闭**:共享同步改单向(只许冻结方向,§9.4) |
| E8 | 直写 estop-state.json frozen:true → 骚扰性冻结 | 同上 | 保留(fail-closed 方向,不危及安全;登记 §12) |
| E9 | SendInput 模拟复位热键 | OS 物理输入面 | 保留(sdfang 已登记为残余风险,§12) |
| E10 | TerminateProcess 伪造子进程退出码 | §9.2 新通道的理论旁路 | 登记(§12,与 E9 同级的 exotic 面) |

## 9. 落位设计(P3 实现依据)

### 9.1 进程内形态:弹窗直调(主通道)
- freeze payload 注入进程内回调 `on_reset`,模式同构 enroll_notice 的 `payload["on_undo"]` 先例(dialog_service.py:117-122;装配先例 main.py:556-559);
- `freeze_dialog.build_window(..., on_reset=None)` 新形参:给定时「立即解冻」回调直调 `on_reset()`(属主进程内=estop.dialog_reset),**不写 req 文件、不读 state seq**;
- 装配侧(main.py)注入 `estop.dialog_reset`;「立即解冻」后不再走 SNOOZED 等重提醒兜底(复位直达,无消费不确定性)——未冻结的极端竞态由 estop._reset 的 noop 审计(「复位请求-未冻结」)兜底,fail-closed 不变。

### 9.2 子进程形态(--freeze-notify):退出码通道(定案)
- 裁定要求的「一次性、随机、内存态」落位为:**子进程退出码**——`EXIT_RESET=73` 常量(freeze_dialog 定义);子进程点「立即解冻」=关窗并 `sys.exit(73)`;
- 属主 FreezeNotifier 持有本轮 Popen 句柄(只存属主内存,每轮冻结新起新句柄=一次性),监听循环 poll:退出码==73 → `estop.dialog_reset()`;其余退出码(关窗/snooze/被杀)=非解冻语义,维持既有重提醒逻辑;
- **零文件、零 socket、零命名管道、零 argv 秘密**——AI 无可写文件、无可 curl 接口、无可猜测命名;命令行不携带任何秘密(73 是公开常量,知道它无助于伪造,伪造须 TerminateProcess 级 exotic 手段,登记 §12);
- REQ_FILE/REQ_PREFIX/write_reset_request/check_reset_request 全链删除(含 freeze_notify.py:28 死常量)。

### 9.3 删除面(代码)
- httpd.py:273-285 `/estop/reset` 分支(**保留 estop 注入**,idle 豁免 httpd.py:206-213 在用);
- main.py:239-261 `_cli_reset`、main.py:428-429 `--reset` 分支、estop.py:52-54 `cli_reset`(「本地 CLI 复位命令」来源串同退);
- freeze_notify.py:28-29/76-115(req 协议)、freeze_dialog.py:94-97(write_reset_request)、main.py:192 消费调用。

### 9.4 estop-state.json 同步单向化(E7 关闭)
- `sync_local_with_shared_state` 改为**复位方向关闭**:shared.frozen=false ∧ local=true → **绝不本地复位**(E7 旁路焊死),可将共享修复回 true(展示愈合,fail-closed);
- 反向(shared.frozen=true ∧ local=false)**沿用 ISS-0092 fg04 既有语义**:本地为权威运行时,共享为陈旧展示面 → 修复共享为 false(消除冻结假象);**此方向不产生任何本地复位,与 E7 安全口径兼容**(v0.5 修正:v0.4 曾写「灌回本地冻结」,与 ISS-0092「本地权威防假象」裁定冲突,且该方向无安全增益——冻本地不防任何旁路);
- `shared_sync_reset` 方法与「复位-共享同步」事件退役;
- state 文件保留的角色:弹窗展示轮询(freeze_dialog.py:331-356,只读)+启动残留清理(main.py:233,local→shared 写出)+观测面;**任何进程写 state 文件不再能解冻**。

### 9.5 文档翻页(随代码)
- INSTALL.md:207;功能设计说明书:307/:599;详细设计说明书:165/:177/:242/:1028/:1043/:1059/:1103/:1142-1143/:1564;测试设计说明书:412-423(TC-N-EST-04/05 翻页)/:1286;
- ISS-0002(:50/:67-68/:76/:83)、ISS-0004(:93 四路径句)、ISS-0049(:56)、ISS-0084(:57)、CHANGES.md:75 变更记录标注废止;
- ISS-0092 单据回填:req 消费可靠性整改随通道移除而废止(§5 约束)。

## 10. 测试设计(五要素+交叉面清单)

| 用例编号 | 层级 | 测试场景 | 测试前提 | 测试步骤 | 测试预期结果 | 断言代码(断什么/由什么直出) |
|---------|------|---------|---------|---------|-------------|---------------------------|
| TC-93-01 | 单元 | 弹窗直调复位(语义平移) | EstopMonitor 已 _trigger 冻结 | 调 estop.dialog_reset() | frozen 复位+审计「急停复位/冻结提示弹窗」 | is_frozen() 返回值直出;审计记录对象 detail 直出 |
| TC-93-02 | 形态 | 三通道源码清除 | 源码直读 | 读 estop.py/httpd.py/main.py/freeze_notify.py/freeze_dialog.py | 无 cli_reset 定义、无 /estop/reset 分支、无 _cli_reset/--reset、无 REQ_PREFIX/write_reset_request/check_reset_request | 源码文本检索命中清单为空(直读) |
| TC-93-03 | 单元 | state 同步复位方向关闭 | estop 本地冻结;共享 state frozen:false | 调 sync_local_with_shared_state | 本地仍冻结(复位方向关闭);反向沿用 fg04:本地未冻+shared true → 本地不冻、共享修复为 false | is_frozen() 返回值直出;shared 文件盘上内容直读;审计无「复位-共享同步」(记录对象直读) |
| TC-93-04 | 单元 | 弹窗直调不写文件 | Tk 替身;build_window(on_reset=桩) | 点击「立即解冻」 | on_reset 被调一次;audit 目录零 .req 文件 | 桩调用记录直出;目录 glob 直读为空 |
| TC-93-05 | 单元 | payload 回调透传 | DialogService 替身 Tk | show("freeze", payload 含 on_reset) → _dispatch | build_window 收到 on_reset=payload 值 | 替身工厂入参记录直出 |
| TC-93-06 | 形态 | 装配接线钉(守卫接替者) | 源码直读 | 读 main.py freeze payload 装配点 | payload 注入 on_reset=estop.dialog_reset(真实管线存在该调用) | 源码直读命中 |
| TC-93-07 | 单元 | 子进程退出码通道-发送侧 | Tk 替身;build_window(on_reset=None 子进程模式) | 点击「立即解冻」 | 抛出 SystemExit 且 code==EXIT_RESET(73) | pytest.raises(SystemExit).value.code 直出 |
| TC-93-08 | assembly | 子进程退出码通道-接收侧 | FreezeNotifier+替身 Popen(poll→73);真 EstopMonitor 已冻结 | 触发监听 poll 一轮 | estop 复位 | is_frozen() 返回值直出(真实部件=EstopMonitor/state 文件;替身=Popen;断面=子进程) |
| TC-93-09 | assembly | 非 73 退出码不误复位 | 同上但 poll→1 / None | 同上 | 仍冻结 | is_frozen() 返回值直出 |
| TC-93-10 | 集成 | /estop/reset 端点消亡 | 真 HttpDaemon(零 mock,临时端口) | urllib POST /estop/reset;再 POST /whitelist/remove 对照 | 404 NOT_FOUND;白名单端点正常(不误伤) | HTTP 响应体 error_code 直出 |
| TC-93-11 | 形态 | --reset CLI 消亡 | 源码直读 | 读 main.py argv 分派 | 无 --reset 分支 | 源码文本检索直读 |
| TC-93-12 | 集成 | 全链无 req 落盘 | 真 EstopMonitor+FreezeNotifier(临时 audit 目录)+DialogService 真 Tk | 冻结→经 DialogService 点击「立即解冻」 | 复位成功;audit 目录自始至终零 estop-reset-*.req | is_frozen() 直出;目录 glob 直读为空;审计 detail=「冻结提示弹窗」直读 |

### 交叉面清单(§2.1)

| 触及对象 | 其他写入者/读取者 | 覆盖用例 | 或豁免理由 |
|---------|-----------------|---------|-----------|
| estop-state.json | 写:_write_shared_state(保留=展示发布)/main.py:233 启动清理;读:freeze_dialog.poll(展示轮询)/enforcement 不读 | TC-93-03/12 | — |
| estop.is_frozen 读者 | enforcement.py:139(G0 闸)/:294(审批后复核);executor/core.py:169;httpd.py:208(idle 豁免) | 全量回归(test_enforcement/test_secdesk_iss87 等既有钉) | 行为不变 |
| HttpDaemon estop 注入 | idle 豁免(httpd.py:206-213)在用 | TC-93-10 同文件对照端点 | 注入保留 |
| Tk 替身契约 | test_freeze_dialog_iss103/test_freeze_singleton 等四处替身 | 适配后全绿(P2 核对) | 测量契约不回退 |
| 审计事件名 | 「急停复位/冻结提示弹窗」保留;「本地 CLI 复位命令」「复位-共享同步」「解冻请求复位失败」退役 | TC-93-01/03;退役登记 §11 | — |
| 热键注册/甩角轮询 | main.py _hotkey_loop/_corner_loop 主体不动;仅 :192 消费调用删除 | 全量回归(test_estop/test_corner_iss28/iss49) | — |
| policy estop 节 | l0_during_freeze 无运行期消费(现状标注);corner_hold_ms 不动 | test_policy 既有钉 | 不在本单接线 |

## 11. 测试退役/适配登记(放宽双闸门·登记闸)

| 用例 | 处置 | 放宽原因+不再探测的行为 |
|------|------|------------------------|
| test_estop_reset.py TestHttpResetEndpoint(TC-N-EST-04)/TestCliReset(TC-N-EST-05) | 退役 | 端点与 CLI 已删除(sdfang 裁定);不再探测「HTTP/CLI 复位」——通道本身不复存在 |
| test_estop.py test_cli_reset_unfreezes | 改 dialog_reset(平移为 TC-93-01) | 方法删除;语义由 dialog_reset 继承 |
| test_estop_reset.py TestResetNoopAudited(TC-N-EST-06) | 适配:cli_reset 半改热键 | noop 审计语义保留,载体收口 |
| test_freeze_notify.py TestResetRequestProtocol 五条(TC-ISS6-04)/TestWriteResetRequestNaming | 退役 | req 协议整体删除;不再探测「req 消费可靠性」——ISS-0094 该面缺陷随通道消亡(ISS-0093 §6 已登记,无被掩盖缺陷) |
| test_freezeguard_iss92.py fg01/fg05 | 退役(req 半链) | 同上;fg05 由 TC-93-12(新全链)接替 |
| test_freeze_notify.py TestSharedSyncReset | 退役 | 复位方向同步已关闭(E7) |
| test_freeze_notify.py TestStateFile/TestSpawnOnEveryFrozenEdge、test_perf_iss8 TestStateMtimeFastPath、test_freeze_singleton TestResetClickAction | 适配:复位手段 cli_reset→dialog_reset | 载体更名,行为钉不动 |
| test_freeze_notify.py:95-97(「急停复位/冻结提示弹窗」) | 适配平移 | 事件语义进程内直调仍产生 |
| test_freezeguard_iss92.py fg04(TestSharedReconcile) | **保持不动**(v0.5 补登记) | 钉 ISS-0092「本地权威防假象」;其方向(shared true→修共享,本地不冻)不产生本地复位,与 E7 安全口径兼容,§9.4 v0.5 修正后沿用 |
| test_freeze_singleton.py TestResetClickAction | 适配(v0.6 登记):token write_req_and_slide_out → reset_and_slide_out | req 写半已随通道删除,token 名不得再指 req;SHOWN 门控决策语义不变,不再探测「点击写 req」(通道本身不复存在) |

## 12. 残余风险登记(人类裁定豁免,不阻塞关闭)

| 风险 | 评级 | 说明 |
|------|------|------|
| SendInput 模拟 Ctrl+Shift+F11 | 已登记(sdfang 2026-09-22) | 物理输入面,与人类击键不可区分;OS 级缓解超出本单 |
| TerminateProcess 伪造退出码 73 | 登记(2026-09-22) | 同用户 OpenProcess+指定退出码属 exotic 面;与上条同级 |
| AI 写 state frozen:true 骚扰性冻结 | 登记(2026-09-22) | fail-closed 方向,人类一键可解,无安全损失 |
