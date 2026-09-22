# ISS-0094:【待诊断】冻结形态(PyInstaller)与源码形态行为分叉——req 消费面失效 + 心跳/属主锁间歇不写

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0094 |
| 标题 | 同一源码(0.4.1)下:冻结形态 daemon 的甩角线程 req 消费面失效(两次实测不消费不删除),且三次启动中两次不写 daemon-heartbeat/owner.lock;源码形态同代码完全正常(req 0.2s 消费、心跳即时写)——打包产物与源码行为分叉,构建完整性存疑 |
| 严重级 | **中高**(打包产物不可信=发布面风险;观测面间歇缺失=ISS-0084 死亡检测可靠性受损)。注:req 消费面本身随 ISS-0093 通道移除而废止,但**打包分叉本身是独立缺陷**,必须查明 |
| 状态 | **诊断结论已回填(§4),待人类裁决整改立项 + 待打包/异机实证 B-2 拦截源** |
| 提出 | 2026-09-18 v0.4.1 升级验收手工测试中发现 |

## 1. 实证(2026-09-18,全部盘上文件/进程证据)

**分叉点 A:req 消费面**。
- 冻结形态(v0.4.1,三次实例):冻结触发正常(seq 52/54/57 甩角均触发),但
  `estop-reset-{seq}.req` 写入后 20s~120s+ 不被消费、不被删除,无「甩角轮询
  异常」审计、stderr 干净;
- 源码形态(`.venv python -m deskpilot --daemon`,同码):req 写入后 **0.20s**
  消费+删除,链路完全正常。

**分叉点 B:观测面间歇不写**。冻结形态三次启动:①09:19 首启 owner.lock/
heartbeat 滞留死亡旧实例内容(25392/0.3.7)且从不刷新;②09:31 带 stderr
重定向启动一切正常(25112/0.4.1 新鲜);③10:47 前后启动又不写(heartbeat
滞留源码形态 14808 的内容)。**同代码同机器,概率性不写**。

**同源嫌疑(未坐实)**:PyInstaller 打包构建(build-new 缓存复用)与源码
运行的模块内容分叉——PYZ 压缩致字符串探针不可验证,须用行为差分或解包比对
坐实。**禁止据此下结论**,诊断方向见 §2。

## 2. 待诊断方向

| # | 方向 |
|---|------|
| ① | 解包比对:冻结 exe 的 PYZ 内 main.py/freeze_notify.py/ownership.py 字节码与源码是否一致(构建缓存污染排查;PyInstaller --workpath 复用行为核实) |
| ② | 干净构建复测:全新 workpath/distpath 重打包,复测 req 消费+心跳写入——区分「打包缓存污染」与「真代码分叉」 |
| ③ | 若排除打包:冻结形态专有差异面排查(sys.frozen 分支/启动时序/线程调度差异) |
| ④ | ISS-0093 通道移除后,分叉点 A 随之消失;分叉点 B(观测面)独立验收 |

## 3. 约束

- 定位结论必须有直接证据支撑,禁止臆想和猜测;
- 复测冻结链时遵守 ISS-0093 边界:**AI 不得写 req 文件自行解冻**(测试只到
  「冻结+观察消费」为止的读侧观察须评审后另行设计;冻结由人类触发/解冻);
- 与 ISS-0093(安全漏洞,通道移除)衔接:本单的 req 消费缺陷若通道移除则消亡,
  观测面缺陷独立修。

## 4. 诊断结论(2026-09-22 诊断回填,分叉点 A 随 ISS-0093/commit 5c7c394 废止不再查;以下仅分叉点 B 观测面)

### 4.1 心跳机制全链测绘(确定)

- 写入者:`deskpilot/ownership.py:99-145` `HeartbeatWriter`;周期 `BEAT_INTERVAL_S=10s`(:27),
  内容 `{pid, role, ts, version}`;写法 = 先写 `daemon-heartbeat.tmp` 再 `os.replace` 原子换名(:115-124)。
- 起停装配:`RoleSupervisor.start()`(ownership.py:247-260)**心跳先于抢锁**(复出信号),
  抢锁失败立即 `heartbeat.stop()`(:254-257);daemon 侧重试 12 次(约 23s)全败则退出码 4
  (main.py:604-614);锁得主 = 唯一心跳写手。
- 文件锚点:`LOCALAPPDATA\DeskPilot\daemon-heartbeat.json`(main.py:473-474 `_shared_dir`),
  **形态无关**——冻结/源码同一路径,无任何 `sys.frozen` 分支触碰属主面/心跳面(全仓 grep 实证)。
- 异常守卫形态:`_loop` 内 `except Exception: pass`(ownership.py:130-135)——**全吞、无重试、
  无审计、stderr 无字**;线程本身不会被打死(每 10s 重试),但写盘若被持续拦截则**进程健康、
  心跳永不落盘、零痕迹**。对照:`freeze_notify.py:142-168` state 文件写已有三段退避重试
  (0.05/0.15/0.45s)+终败审计「共享状态写失败」(ISS-0092 ②,**本机已实证 os.replace 会
  瞬时失败**)——同类失败在心跳路径既无重试也无留痕,防护不对称。

### 4.2 「双 daemon 并存(2112/25672)」= PyInstaller onefile 引导父子对,非单例失守(确定,今日实证)

- 2026-09-22 19:53 实盘:`deskpilot.exe --daemon` 两进程 27356/25024,`ParentProcessId(25024)=27356`
  (Win32_Process 实证)——父 = onefile 引导器(解包 _MEIPASS 后等待子进程),子 = 真 daemon;
  spec 无 COLLECT 节=onefile 形态(deskpilot.spec)。「其一疑似僵尸」即引导器,属设计形态。
- 单例机制未被突破:9420 监听、`owner.lock` 持锁、心跳写(pid 25024,10s 周期新鲜)
  三者唯一归属子进程(Get-NetTCPConnection + 心跳文件实证);今日日志无任何
  「daemon 单例退出/属主锁未获得」事件。
- 今日 19:53:34/40/45 三次顺序启动均走完全链(各自拿到锁、绑 9420),前两次静默退出
  (无遗嘱=被终止/控制台关闭,非代码路径退出)——顺序串行,无并发双属主。

### 4.3 estop-state.json「09-15 起不写」= 化石文件误读 + 现行无周期写设计,非缺陷(确定,今日实证)

- repo `audit/estop-state.json`(09-15 21:29, source=「服务启动」)是 **ISS-0084 锚点迁移前**
  的遗物:锚点迁移在 commit b875b03(09-16 09:24,属主面/邮箱迁 LOCALAPPDATA)之前,
  `FreezeNotifier` 锚 `policy.audit_dir`;迁移后该文件再无写手,时间戳定格。
- 现行状态文件 = `LOCALAPPDATA\DeskPilot\estop-state.json`,今日 19:53:45 被第三次启动
  正常重写(seq 216, source=「服务启动」)——实盘核验「现行代码还会写它」:**会**。
- 写触发点(ISS-0093 后,确定):冻结/解冻边沿 `on_state_change`(freeze_notify.py:68-83)、
  启动清理 `_start_estop_listeners`(main.py:233)、对账修复 `sync_local_with_shared_state`
  (main.py:193,50ms 甩角 tick 兼任)。**无任何周期性写 state 的机制**——不冻不写是预期行为。

### 4.4 分叉点 B(心跳间歇不写)根因结论

| # | 结论 | 置信度 | 证据 |
|---|------|--------|------|
| B-1 | **观测错位是重要成分**:旧属主(存活或僵死持锁)在场时,新 daemon 按设计 probe 9420(main.py:432)或抢锁 12 连败(:604-614)后退出 4,心跳面如实保留旧属主内容;09-18 的①(滞留 25392/0.3.7)与③(滞留源码形态 14808)均符合「旧属主内容被误读为不写」——③的 14808 若为存活源码属主,文件本就该显示它。叠加 §4.2 父子进程对(父进程被当作「活着的 daemon」),「daemon 在跑但心跳不写」的观测本身不成立 | 高置信 | 代码路径 + 今日同类误读实盘重演 |
| B-2 | **静默写失败是真缺陷面**:心跳写 `except Exception: pass` 全吞(ownership.py:134),冻结 exe 每次发布新构建=未签名低声誉二进制,杀软实时扫描/受控文件夹访问可持续拦截 `.tmp` 创建与 `os.replace` → 进程功能正常(①③同期「冻结触发正常」)但心跳从不落盘、零审计零 stderr——与 09-18 观测完全吻合;源码形态 python.exe 为签名受信二进制不受同等对待 → 形态分叉由此产生,**无需 PYZ 字节码分叉假说** | 高置信(机制确定;拦截触发待打包复现实证) | ownership.py:130-135 vs freeze_notify.py:142-168 防护不对称;ISS-0092 已实证本机 os.replace 瞬时失败 |
| B-3 | **并发 tmp 竞态(次要)**:daemon 复出/stdio 让位窗口(~10s)内两个 HeartbeatWriter 共用同一 `daemon-heartbeat.tmp` 文件名(ownership.py:120 `with_suffix(".tmp")`),`os.replace` 互踩丢拍,被 except 吞掉 → 间歇性丢拍 | 高置信(代码逻辑确定) | ownership.py:115-124 + 让位时序 ownership.py:312-321 |
| B-4 | 打包缓存污染假说(§1 同源嫌疑):B-1+B-2 已可完备解释行为分叉,该假说不必成立;干净构建复测仍建议作为廉价排除项 | 待打包复现实证 | — |
| B-5 | 跨会话双属主 latent 路径(顺带发现,非本单实证):`ThreadingHTTPServer` 未覆盖 `allow_reuse_address`(httpd.py:116),Windows 上 SO_REUSEADDR 允许不同会话(如计划任务/服务,LOCALAPPDATA 各异→锁文件各异)双绑 9420;同会话内 owner.lock 已封死该路径 | 待异机实证 | http.server 默认值 + Windows SO_REUSEADDR 语义 |
| B-6 | 运行期 audit_dir 锚定不一致(顺带发现,建议另立单):main.py:423 `AuditLogger(policy.audit_dir)` 吃配置原文 `./audit` 未走 `resolve_audit_dir`(audit_paths.py:13-26),实际锚 CWD——今日实证 dist daemon(CWD=仓库根)写 repo `audit/`(daemon.version 19:53、logs 落今日 jsonl),观测面文件散落 repo/dist/LOCALAPPDATA 三地,是历次「文件找不到/不写」误读的系统性诱因 | 确定 | main.py:423 + 今日文件时间戳实证 |

### 4.5 整改方案建议(SDD 级,不写码)

1. **根因 B-2 → 心跳写健壮性对齐 ISS-0092 ②**:`beat_once` 失败三段退避重试(0.05/0.15/0.45s),
   终败记审计「心跳写失败」——节流模式照 `_corner_loop`(main.py:194-206:连续失败只记首败、
   恢复另记一条),审计自身失败不上抛;心跳仍不得阻断主功能(观测面定位不变)。
   约束:重试只针对 OSError 写盘失败,不改变「抢锁失败停心跳」语义(ownership.py:254-257 保留——
   败者写心跳会污染 `is_daemon_alive` 判定,禁)。
2. **根因 B-3 → tmp 文件名按进程区分**(`daemon-heartbeat.{pid}.tmp`),消除复出窗口双写互踩;
   退出/换名后清孤儿 tmp(对齐 freeze_notify.py:153/167 的预清纪律)。
3. **根因 B-1 → 观测面消歧**:文档/验收用例明确「heartbeat 内容=当前属主,旧 pid≠不写」;
   验收脚本判活一律以 `ts` 新鲜度(is_daemon_alive 语义)而非 pid/version 字段为准;
   进程观测须区分 onefile 父子对(以 9420 持端者为准)。
4. **B-5 端口加固(次要)**:HTTPServer 子类 `allow_reuse_address = 0`(Windows),
   回归「9420 被占→审计+退出 4」路径(main.py:667-671)。
5. **测试设计要点**:①单测:`beat_once` 注入 OSError→重试 3 次→终败审计恰 1 条且线程存活
   (仿 ISS-0092 fg 系列);②双 HeartbeatWriter 同目录并发 beat 100 轮→无 .tmp 残留、
   无交叉内容;③集成:stdio 属主持锁时起 `--daemon`→退出码 4 + 审计「daemon 单例退出」+
   heartbeat 文件不被败者触碰;④打包验收:干净 workpath 全新构建 dist 形态,杀软实时扫描
   开启下连续 10 分钟采样 heartbeat mtime,10s±2s 全拍在案;同窗口 ProcMon 抓 `.tmp`/
   `os.replace` 结果码坐实 B-2 触发源。

### 4.6 待人类裁决 / 待异机·打包复现实证清单

- E-1 干净构建 + ProcMon 实证 B-2 拦截源(Defender Operational 日志 / 受控文件夹访问事件,
  09-18 09:19 与 10:47 窗口)。
- E-2 B-4 排除项:全新 workpath/distpath 重打包复测(原诊断方向②,保留)。
- E-3 B-5 跨会话双绑:计划任务会话 + 用户会话双起验证(如不做则转独立单)。
- E-4 B-6 audit_dir 锚定:另立单裁决(main.py:423 是否改走 resolve_audit_dir;影响面=全部
  观测面文件落点,涉 ISS-0010 锚定语义,超出本单边界)。
- E-5 整改方案 §4.5 的立项与排期裁决。

## 5. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-18 | 建单。升级验收实测证据(§1 分叉点 A/B)+同源嫌疑标注未坐实+诊断方向四条;安全边界衔接 ISS-0093 |
| v0.2 | 2026-09-22 | 诊断回填(§4):req 消费面(分叉点 A)随 ISS-0093 通道移除(commit 5c7c394)废止不再查;心跳全链测绘+「双 daemon」=onefile 父子对实证+estop-state 化石误读澄清+分叉点 B 根因四条(B-1 观测错位/B-2 静默写失败/B-3 tmp 竞态/B-4 构建污染降级为排除项)+整改方案与待实证清单 |
