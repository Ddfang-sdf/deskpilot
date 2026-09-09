# ISS-0042：【AI友好】遮挡错误不点名遮挡者

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0042 |
| 标题 | WINDOW_OCCLUDED 错误只说"落点被其他窗口遮挡",不说是谁——AI 必须自行侦查 WindowFromPoint 才能定位遮挡者,可诊断性不足 |
| 严重级 | **中**(AI 易用性;sdfang 裁定:"出问题了,让 AI 用户自己去调查,就挺不可取") |
| 状态 | **已修复**(先红后绿:TC-OC-01/02 红→绿;既有遮挡回归兼容;全量 584 过) |
| 提出 | 2026-09-08(手工实测实证:元气桌面 kdesk64.exe 全屏层触发遮挡闸,AI 需多轮侦查才定位到进程名) |

## 1. 背景（实证）

2026-09-08 手工实测中,桌面 click 被 WINDOW_OCCLUDED 拦停。错误信息:
"落点被其他窗口遮挡,请先前置目标窗口"——**无遮挡者身份**。AI 为定位
是谁,需自行对多个点位做 WindowFromPoint+进程路径反查（本例为
`C:\Program Files (x86)\cmcm\kdesk\kdesk64.exe` 元气桌面,两轮侦查）。

机制:遮挡层分两类——透明层(WS_EX_TRANSPARENT,WindowFromPoint 跳过,
天然不触发)与命中可见层(真吃点击)。闸对后者的拦截是正确的,但
错误信息没把"谁挡的"交给 AI——而 _check_occlusion 在判定时**已经持有**
该窗口句柄,进程名/标题/类名都在手边,只是没放进 message。

## 2. 整改方案

| 项 | 内容 |
|----|------|
| A | `_check_occlusion` 的 WINDOW_OCCLUDED message 附遮挡者:`process(进程名)+title(标题)`,如"落点被 kdesk64.exe(元气桌面)遮挡,请先前置目标窗口或请人类处理遮挡程序" |
| B | 桌面助手类常见遮挡的处置指引入错误或文档(退出/最小化遮挡程序;感知类工具 list_desktop_icons 不受影响) |

### 约束

- 判定逻辑不变(只改信息载荷);fail-closed 语义不变;
- 测试设计(五要素)于评审通过后产出:核心用例——替身顶层窗,断言
  message 含其进程名与标题(直出)。

## 3. 测试设计(五要素,2026-09-08)

层级:单元(executor._check_occlusion;_occlusion_user32 与 probe 接缝替身)。

| 用例 | 场景 | 前提 | 步骤 | 预期结果 | 断言代码 |
|------|------|------|------|----------|----------|
| TC-OC-01 | 遮挡者进程+标题入 message | 替身 user32:WindowFromPoint=他窗、IsChild=False、GetWindowTextLengthW>0、GetWindowTextW 填"元气桌面";probe.process_of="kdesk64.exe" | _check_occlusion(绑定窗,x,y) | WINDOW_OCCLUDED;message 含 "kdesk64.exe" 与 "元气桌面" | 异常码+message 直出 |
| TC-OC-02 | 无标题遮挡者只带进程 | GetWindowTextLengthW=0;proc="kdesk64.exe" | 同上 | message 含 "kdesk64.exe 遮挡"且无空括号残留 | message 直出 |
| TC-OC-03 | 放行回归 | 落点=绑定窗/子窗(既有 test_elevation_iss17 两用例) | 既有用例 | 不抛异常,行为不变 | 既有回归 |

### 装配守门五条

R1 装配矩阵:全单元,无放宽;R2 mock 边界:替身仅 user32/probe 接缝,
被测 _check_occlusion 真实;R3 形态:TC-OC-02 格式断言;R4 路径变迁:
仅 message 载荷变化,既有"遮挡"关键词保留(既有两用例兼容);
R5 终效应:TC-OC-01(AI 一轮拿到遮挡者身份,零侦查)。

## 4. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-08 | 建单(手工实测实证+sdfang 裁定易用性问题),待评审 |
| v0.2 | 2026-09-08 | 测试设计定稿(sdfang 令"解决一下"=审核通过,直接 SDD):TC-OC-01~03 |
| v0.3 | 2026-09-08 | SDD 完成:P1 红(01/02)→P3 绿(10 过,含既有遮挡回归兼容);message 现附遮挡者进程名+标题("落点被 kdesk64.exe(元气桌面)遮挡…");全量 584 过 |
