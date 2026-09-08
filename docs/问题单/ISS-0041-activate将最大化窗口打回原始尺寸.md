# ISS-0041：activate 将最大化窗口打回原始尺寸

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0041 |
| 标题 | activate 无条件 SW_RESTORE——最大化窗口被恢复为原始尺寸,用户手动最大化的状态被 AI 任意写操作意外撤销 |
| 严重级 | **中**(行为缺陷:用户可感知的窗口状态破坏;波及全部写路径,非安全面) |
| 状态 | **已修复**(先红后绿:5 红→全绿;真机终效应实证;全量回归 553+3 环境失败已证与本单无关) |
| 提出 | 2026-09-08(sdfang 质询 activate 是否会把最大化变半屏,代码取证确认) |

## 1. 认账

`executor/probe.py:106-115` 的 activate 无条件调用
`ShowWindow(hwnd, SW_RESTORE)`(`probe.py:16` 常量 9)。SW_RESTORE 的
微软官方语义:窗口处于**最小化或最大化**时,恢复其"原始尺寸与位置"——
即最大化窗口会被打回最大化之前的大小(如半屏)。

波及面:`executor/core.py:727-734` 的 `_activate_if_needed` 挂在全部写
操作(click/drag/type/key/drag/activate_window)上——只要最大化的目标
窗口不在前台,AI 的任何一次写入都会把它退出最大化。

**性质**:docstring 显示意图仅为"恢复最小化",实现时未考虑 SW_RESTORE
对最大化同样生效。属**实现遗漏**(探针落地起即存在),非修改引入,
不带【修改引入】前缀。

**用户场景实证链**:用户手动最大化绑定窗口 → 绑定不断(四校验无矩形
比对,binding.py:49-86)→ AI 下一次写操作 → SW_RESTORE → 最大化被
撤销。

## 2. 整改方案

| 项 | 内容 |
|----|------|
| A | activate 前置分支:`IsIconic`(最小化)才 SW_RESTORE;`IsZoomed`(最大化)用 SW_SHOWMAXIMIZED 或跳过 ShowWindow 只做前置;普通窗口不动 ShowWindow。最大化/普通窗口的尺寸状态零触碰 |
| B | 工具描述补充提示:窗口几何变化(最大化/缩放/移动)后,既有截图与坐标即作废,AI 应先重新感知再操作(判断归 AI,描述给指引) |

### 约束

- 最小化恢复语义不变(原意图保留);
- 前台附加线程技巧与 ≤3 次短退避重试(ISS-0017 A)不变;
- fail-closed 不变:激活失败仍返回 False,调用方必检;
- 测试设计(五要素)于评审通过后产出:核心用例——最大化窗口 activate
  后仍为最大化(先红后绿);最小化恢复回归不破坏。

## 3. 测试设计(五要素,2026-09-08)

### 实现契约(测试断言的目标形态)

`probe.activate(hwnd)`:行为不变式——窗口状态驱动 ShowWindow 命令:
- `IsIconic`(最小化)→ SW_RESTORE(9)(最小化恢复原意图;最小化的
  最大化窗恢复到最大化);
- `IsZoomed`(最大化)→ SW_SHOWMAXIMIZED(3)(激活且保持最大化);
- 其余 → SW_SHOW(5)(激活且按当前尺寸显示,不做任何恢复)。
签名、重试(≤3 次退避)、死窗 False、fail-closed 语义全部不变。
`activate_window` 描述增"窗口几何变化后先重新感知"指引。

层级:单元(probe.activate,fake user32/kernel32 调用记录直出)
+ 形态(描述)+ 集成(真机,--run-integration)。

| 用例 | 场景 | 前提 | 步骤 | 预期结果 | 断言代码 |
|------|------|------|------|----------|----------|
| TC-ACT-01 | **最大化窗不被打回**(判别性) | fake:IsWindow=T、IsIconic=F、IsZoomed=T;前台序列助激活成功 | `activate(hwnd)` | ShowWindow 记录:nCmdShow 全为 3,**无任何 9** | fake 调用记录直出 |
| TC-ACT-02 | 最小化恢复(回归) | IsIconic=T、IsZoomed=F | 同上 | ShowWindow 收到 9 | 直出 |
| TC-ACT-03 | 普通窗尺寸不动 | IsIconic=F、IsZoomed=F | 同上 | ShowWindow 收到 5,无 9 | 直出 |
| TC-ACT-04 | 最小化的最大化窗(边界) | IsIconic=T、IsZoomed=T | 同上 | 最小化优先:收到 9(恢复到最大化) | 直出 |
| TC-ACT-05 | 死窗不动 | IsWindow=F | 同上 | 返回 False;ShowWindow 零调用 | 直出 |
| TC-ACT-06 | 重试语义回归(ISS-0017 A) | IsZoomed=T;前台读数使前 2 轮失败、第 3 轮成功 | 同上 | 返回 True;ShowWindow 共 3 次且 nCmdShow 均为 3(每轮重试命令都正确) | 直出 |
| TC-ACT-07 | 描述指引(B 项,形态) | TOOL_SCHEMAS["activate_window"] | 读 description | 含"最大化/几何变化后重新感知"类关键词 | 形态断言直出 |
| TC-ACT-08 | **写路径真机终效应**(集成) | 真记事本经 ShowWindow(3) 最大化;真 Executor(真 probe)经 _dispatch 消费 | dispatch("activate_window") 触发 _activate_if_needed;**容忍业务结果**(CI 前台锁失败会抛 WINDOW_GONE,捕获后继续——ShowWindow 已在尝试中执行,窗口状态与前台成败无关;避开 click 的遮挡校验 CI 噪声) | `IsZoomed` 仍为 True(消费面终效应:最大化未被撤销) | user32.IsZoomed 真读直出 |
| TC-ACT-09 | 最小化恢复真机回归(集成) | 真记事本经 ShowWindow(6) 最小化;同上 | 同上(容忍业务结果) | `IsIconic` 变为 False(原意图未被破坏) | user32.IsIconic 真读直出 |

### 交叉面清单(§2.1)

| 触及对象 | 其他写入者/读取者 | 覆盖 |
|---------|-----------------|------|
| probe.activate | core._activate_if_needed(全部写路径);test_elevation_iss17 既有 activate 用例 | TC-ACT-01~06 + 既有回归(见 R4) |
| _SW_RESTORE 常量 | 修复后仍服务 IsIconic 分支 | 无删除 |
| activate_window 描述 | validate/_list 描述面;desc05(≤200 字)/bound05 质量线 | TC-ACT-07+回归 |
| 真机记事本设施 | test_uia_com_iss16 开闭设施复用(generality) | TC-ACT-08 |

### 装配守门五条(R1~R5)

R1 装配矩阵:单元×7 + 形态×1 + 集成×2(--run-integration 门槛,CI 全量);
无真机装配放宽;TC-ACT-08/09 不断言前台成功(CI 无交互桌面适配,
不断言≠放宽——断言目标本为窗口状态)。
R2 mock 边界:替身仅 user32/kernel32 OS 接口层;被测 activate 本体真实
执行(禁止替身被测方法)。
R3 形态断言:TC-ACT-07。
R4 路径变迁表:①probe.activate 签名不变、行为变化=ShowWindow 命令按
窗口状态选择;唯一生产调用方 core._activate_if_needed 不变;②**既有
test_elevation_iss17 两 activate 用例必须更新**(2026-09-08 复审纠正):
修复后 activate 新调 IsIconic/IsZoomed 两 OS 接口,既有两例未替身——
靠假 hwnd 上真实调用恰返回 0 侥幸通过,违反密封原则;更新=显式替身
IsIconic/IsZoomed(断言不变,非放宽,属增强确定性的合法重指);
③描述改写保持 ≤200 字质量线;④全量排查(2026-09-08):conftest
FakeExecutor._activate_if_needed(独立替身契约)、iss20 审批窗自身
SW_RESTORE(enforcement 路径,非 probe.activate)、iss35 整方法替身
(绕过 probe)——三处均不受影响,无需更新。
R5 终效应断言:TC-ACT-08(写路径真机 IsZoomed=True,消费面终效应);
TC-ACT-01 为其单元级行为代理(命令不含 9 且为 3);TC-ACT-09 为原意图
(最小化恢复)的真机回归。

### 设计默认(非决策点,评审可推翻)

- 状态判定 IsIconic 优先于 IsZoomed(最小化的最大化窗恢复到最大化,
  符合用户预期);
- 普通窗用 SW_SHOW(5)而非 SW_SHOWNORMAL(1)——后者同样触发"恢复
  原始尺寸",会复现同类副作用。

## 4. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-08 | 建单(sdfang 质询取证:SW_RESTORE 语义+全写路径波及面),待评审 |
| v0.2 | 2026-09-08 | 测试设计定稿:TC-ACT-01~08(单元/形态/集成),实现契约(状态驱动 ShowWindow)+交叉面+装配守门五条随单 |
| v0.3 | 2026-09-08 | sdfang 复审纠正("历史用例不需要补充回归?"):①既有两例"兼容无需改"判定有误——修复引入 IsIconic/IsZoomed 新 OS 调用,既有两例靠假 hwnd 侥幸通过,必须显式替身(密封性,R4 更新);②TC-ACT-08 升级为写路径(消费面)真机终效应;③新增 TC-ACT-09 最小化恢复真机回归。用例 8→9 条 |
| v0.4 | 2026-09-08 | SDD 完成:P1 红(01/03/06/07/08 五红,02/04/05/09 四绿守卫)→P3 绿(28 目标全过;真机 08/09 实证);全量回归 553 过,3 例失败经 git stash 对照实证为环境(本机记事本会话污染),与本单无关。随 v0.3.5 替换发布(不升版本号,sdfang 裁定) |
