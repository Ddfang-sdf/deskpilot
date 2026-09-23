# ISS-0108:【待诊断】Windows 跨会话双绑 9420 潜伏路径——allow_reuse_address 未覆盖

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0108 |
| 标题 | `httpd.py:116` HTTPServer 未显式 `allow_reuse_address = 0`(Windows 默认语义下,计划任务会话+用户会话可能存在双绑 9420 的潜伏路径);同会话内已被 owner.lock 封死,跨会话属「理论上可双属主」面(ISS-0094 §4.4 B-5 转出) |
| 严重级 | **低-中**(潜伏;同会话已有 owner.lock 防线) |
| 状态 | 已关闭(2026-09-23 验收;离场授权自决) |
| 提出 | ISS-0094 诊断 §4.4 B-5 |

## 1. 验证设计(先实证,不改码)

- 计划任务会话(任务计划程序,登录时运行)+ 用户会话各起一个 `dist/deskpilot.exe --daemon`,观测:①9420 归属;②owner.lock 竞争结果;③是否出现双属主双心跳;
- 若双绑实证:改法=httpd 显式 `allow_reuse_address = 0` + 回归「9420 被占→审计+退出 4」(main.py:667-671);
- 若不能双绑(Windows 端口独占语义):单据直接关闭,结论入档。

## 2. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-22 | 立单(ISS-0094 E-3 转出)。验证设计先行 |

## 3. 实证(2026-09-23,升级定案)

- 会话内实证:daemon 持 9420 监听时,第三方进程以 SO_REUSEADDR 绑定同址**成功**(Python 复现,直读)——httpd 未显式关 allow_reuse_address,Windows 下 SO_REUSEADDR 允许同址双绑,双属主/影子服务潜伏路径坐实(不限跨会话);
-  SYSTEM 计划任务跨会话实测因权限拒绝(未提权 shell),跨会话面留痕,但会话内实证已足以定案;
- 改法:daemon 监听 socket 设置 SO_EXCLUSIVEADDRUSE(Windows;非 Windows 平台保持默认),回归「9420 被占→审计+退出 4」路径。

## 4. 变更记录(续)

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.2 | 2026-09-23 | 会话内双绑实证成功(潜伏升级);批准 SO_EXCLUSIVEADDRUSE 修复(离场授权自决);待开发 |
| v0.3 | 2026-09-23 | 修复落地(SDD 全程),状态→已关闭。**实现**:httpd.py:32 新增 `_DaemonHTTPServer(ThreadingHTTPServer)`——win32 下 `server_bind` 先清 `allow_reuse_address=0` 再 `setsockopt(SO_EXCLUSIVEADDRUSE)`(bind 之前,两标志互斥),非 Windows 分支不进、默认语义不动;`start()` 换用该类(httpd.py:132)。**先红后绿证据**:TC-108-01 红=DID NOT RAISE(现状 SO_REUSEADDR 双绑成功,直读),TC-108-02 红=设置点缺失;实现后转绿。**实证偏差登记**:独占绑定下同址再绑的拒绝码实盘=**WSAEACCES 10013**(非任务书预估的 WSAEADDRINUSE 10048)——TC-108-01 断言按实盘钉 10013,语义(必拒)不变。**回归面**:tc46 系列(9420 被占→审计+rc 4)绿不回退;全量 941 passed/30 skipped(daemon 在线,基线 939+本单 2 钉)。注:本机当前在线 dist daemon 为修复前构建,源码修复未重打包(打包属发布流程,不在本单) |
