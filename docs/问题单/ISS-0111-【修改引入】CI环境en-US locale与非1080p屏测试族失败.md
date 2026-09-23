# ISS-0111:【修改引入】CI 环境(en-US locale+非 1920×1080 屏)测试族失败——REQ-007/ISS-0097 面从未上过 CI

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0111 |
| 标题 | v0.4.2(REQ-007 i18n+ISS-0096/0097 屏序/落位)未打 tag 未过 CI;ISS-0034 验收(PR #2 触发)暴露:CI 跑机 en-US locale + 非 1920×1080 屏下,中文文案钉/几何钉整族失败(test_enrollshot_iss73 中文断言族、test_whitelist_iss12 按钮文案+IndexError、test_primarydialog_iss97 几何 +1484+886 硬编码、test_approval_readability_iss20/test_enforcement/test_batch_iss19 文案) |
| 严重级 | **高**(发布面:CI 红=流水线断;ISS-0034 守卫验证被阻塞;修改引入类,先认账) |
| 状态 | 已关闭(CI 绿实证:run 35843107211 全步 ✓ 含 Verify policy sync;离场授权自决) |
| 提出 | 2026-09-23 PR #2 CI run 35839693194 实测失败清单 |

## 1. 根因(机制层)

- 测试断言把「zh-CN 文案」「1920×1080 主屏右下几何」当常量,而 CI 跑机是
  en-US+小屏:REQ-007 的「中文系统→中文,其余→英文」在 CI 上走英文面,
  中文断言全炸;ISS-0097 的主屏右下钉把 1920×1080 的 +1484+886 写成字面量;
- 本机全绿是因本机 zh-CN+1920×1080——ISS-0062 同族(环境假设),但发生在
  「CI 跑机与本机不同 locale/几何」这一未被 0062 覆盖的轴上。

## 2. 改法

- 文案族:断言前固定 locale(测试内 monkeypatch DESKPILOT_LOCALE=zh-CN 或
  双语断言二选一——按各钉原意,涉中文语义验证的钉显式钉 zh-CN 环境);
- 几何族:期望几何按实测 monitors 计算(toast_placement 同源),不写死
  +1484+886;
- IndexError 族(test_whitelist_iss12 undo 系):查明英文面控件枚举差(可能
  自绘钮 Name 为空面在英文布局下序位变化),按环境无关口径改取钮方式;
- 验收:本机全绿 + PR 重推 CI 绿(含 ISS-0034 守卫步骤执行)。

## 3. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-23 | 建单。CI 失败清单+根因(locale/几何两轴)+改法;授权自决进入修复 |
| v0.2 | 2026-09-23 | 修复落地,状态→已关闭(CI 绿实证)。逐族修法:①**文案族**(8 模块 34 用例:test_enrollshot_iss73/test_whitelist_iss12/test_approval_readability_iss20/test_batch_iss19/test_enforcement/test_sessionscope_iss43/test_tray_iss12e/test_whitelist_inplace_iss85)——conftest 增 `pin_zh_locale` 共享缝+各模块 autouse 钉 zh-CN(钉的即中文语义面;`_detect_locale` 每取词先读 env 覆盖通道,无需重载目录);②**IndexError 族**(undo 系)查明=同一 locale 根因(英文面按中文文案取钮取到空表→[0] 越界),随文案钉消,非自绘钮序位差;③**几何族**:pr03 期望几何改 `toast_placement(实测主屏)` 同源计算,弃写死 +1484+886(CI 实测 +588+526);④**产品面潜伏修 1 处**:whitelist_window._ManagerUI 的 `_SECTIONS`/`_EMPTY_TEXT` 类级 tr() 在 import 期固化(locale 晚于导入设置即文案锁死)——改惰性 property,使用点逐字节不动;⑤tc104_03:CI Server 系记事本无标签条形态,TabItem 前提转 envguard 显式 skip(ISS-0062 同族口径)。本机双层全绿:默认层 941 passed/30 skipped + `DESKPILOT_LOCALE=en` 强制层 941 passed/30 skipped;**CI run 35843107211 全步 ✓**(Run tests 7m41s 过 + **Verify policy sync 步执行且过**——ISS-0034 验收点) |
