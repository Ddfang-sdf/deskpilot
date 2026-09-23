# ISS-0110:【修改引入】test_freezesingle_iss46 隔离被 ISS-0064 重构打破——真属主锁在场时甩角陷阱炸全量

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0110 |
| 标题 | ISS-0064 S5(OwnershipRuntime 收口)后,`_main_stubs` 装配的 tc46 系列在**真 daemon 持 owner.lock** 的环境下:`RoleSupervisor.start()` 撞真锁连败 12 次,落进重试循环的 `time.sleep`(main.py:725)→ 触发 `_main_stubs` 的 KeyboardInterrupt 陷阱(test_freezesingle_iss46.py:74)→ BaseException 穿透 pytest 逐用例捕获,**全量套件中断**(实测 46/184/254/291/334 不等位置断,exit=2) |
| 严重级 | **高**(测试基座:全量套件在本机常态(daemon 在线)必炸;修改引入类,先认账) |
| 状态 | 已关闭(2026-09-23 修复+三道验证;离场授权自决) |
| 提出 | 2026-09-23 最终回归四次中断取证(/tmp/pytest_full.log 全栈) |

## 1. 实证链(全部直读)

- 中断栈:`_stage_ownership`(main.py:725)`time.sleep(min(1.0*(_att+1),2.0))` → 陷阱;触发条件=supervisor.start() 连败=真锁被持;
- 对照:重构前同场景绿(历史 900+ 绿含 daemon 在线期);重构后 `rt._shared_dir` 指向真实 LOCALAPPDATA 共享目录(装配段未把共享目录纳入 `_main_stubs` 的 tmp 隔离);
- 暴露面:任何「真锁在场」的环境(本机常态),CI 无锁不炸——正是 ISS-0062 的环境假设同族。

## 2. 根因(机制层)

`_main_stubs` 的 tmp 隔离覆盖了策略/审计/探活/HTTP/托盘,但 ISS-0064 把共享目录
解析收进装配段后,`OwnershipRuntime._shared_dir` 不再经被 stub 的缝——测试里的
RoleSupervisor 直接抢**真锁**。陷阱的原设计语义(防 main 走进常驻循环挂死)
依然正确;被打破的是隔离缝本身。

## 3. 改法(缝合义修复,不动产品行为)

- 测试侧(首选):`_main_stubs` 增补共享目录缝重定向(将装配段的 shared_dir 来源
  stub 到 tmp)——恢复「全隔离」原语义;
- 若产品侧缝更可取(如 shared_dir 改为可注入),按最小改动评估,但不得为测试
  改产品语义;
- 测试设计:TC-110-01(回归形态):真锁占位(临时目录起真 RoleSupervisor 持锁)+
  tc46_01/02 重跑→绿(不再触陷阱);断言=rc 直出+审计事件直读。
- 交叉面:trap 语义保持(真走进常驻循环仍炸);其余 _main_stubs 消费文件
  (test_estop_reset/test_tray_iss12e 等)全绿回归。

## 4. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-23 | 建单。四次中断取证+根因(隔离缝被重构绕过)+改法;授权自决按缝合义修复 |
| v0.2 | 2026-09-23 | 修复落地,状态→已关闭。**根因确认(git 对照实证,修正 v0.1 归因)**:失效缝=装配段 `_stage_dialogs` 的 shared_dir 来源(main.py `os.environ.get("LOCALAPPDATA") or home → DeskPilot`),`_main_stubs` 的 tmp 隔离从未覆盖它;但 12 连败重试循环+真锁竞争并非 ISS-0064 S5 引入——逐提交实盘:4f25ce0(ISS-0064 前)/ce28bba(S5 前)在真锁占位下同炸(tc46_02 触 KeyboardInterrupt 陷阱),b875b03~1(ISS-0084 前)全绿。**真正引入点=b875b03(ISS-0084 属主族落地,daemon 分支新增 RoleSupervisor 12 次持锁重试)**;ISS-0064 仅搬移代码,历史「daemon 在线也绿」系当时在线 daemon 为 ISS-0084 前构建不持 owner.lock(环境相依,ISS-0062 同族)。**修法(§3 首选,测试侧+零行为变化产品缝)**:main.py 提取模块级 `_resolve_shared_dir()`(表达式逐字搬移);`_main_stubs` 增补 `monkeypatch.setattr(m, "_resolve_shared_dir", lambda: str(tmp_path/"shared"))`;新增 TC-110-01(回归形态:真 RoleSupervisor 占位锁持锁下 tc46_01/02 场景重跑,rc 4+审计事件直读)——先红(未修时触陷阱 KeyboardInterrupt,直读)后绿。S7 装配钉(test_main_assembly_iss64)同缝自愈。**三道验证**:①daemon 在线持锁 `pytest test_freezesingle_iss46 test_estop_reset test_tray_iss12e` = 14 passed;②daemon 在线持锁全量 = 939 passed/30 skipped(exit 0);③daemon 离线全量 = 939 passed/30 skipped(exit 0)。trap 语义保持(未动) |
