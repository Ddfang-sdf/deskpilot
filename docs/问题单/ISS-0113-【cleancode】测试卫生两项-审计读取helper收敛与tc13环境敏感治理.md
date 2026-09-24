# ISS-0113:【cleancode】测试卫生两项——审计读取 helper 收敛 + tc13 环境敏感红治理

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0113 |
| 标题 | ①读审计 helper 4 份复制(conftest read_audit + 3 处 `_audit_events` 私有副本,ISS-0060 裁决⑤遗留)收敛单点;②test_enrollshot_iss73 tc13 环境敏感红(ISS-0062 v0.5⑧ 登记另案:真实窗口前台竞争)治理 |
| 严重级 | 低(测试面整洁/基座稳定;非产品缺陷) |
| 状态 | 已关闭(2026-09-24 两项修复落地;sdfang 离场授权自决) |
| 提出 | 2026-09-24 卫生级三项任务包(①ISS-0060 裁决⑤遗留;②ISS-0062 v0.5⑧ 相邻发现转案) |

## 1. 现状与根因

### ① read_audit 四份复制

- conftest.py `read_audit`(dict 通道,logs/ 口径)之外,三个文件各带私有副本:
  test_audit_retention_iss31 / test_guardfix_iss34(原文子串通道,同形两份)、
  test_mouse_req01(dict 通道,`**/*.jsonl` 递归形——AuditLogger 落盘恒在
  logs/ 下(audit.py:_write_line),递归与 logs/ 口径等价,属无谓分叉);
- 伤害:读取口径四处各自演化,改审计落盘形态要扫全库。

### ② tc13 环境敏感红(诊断结论)

- tc13 断言链:`attach → enforcement._capture_target → _shot_verified`
  ——实拍被「前台置前 + 五点可辨认度采样(≥3 才出图)」门控;真实桌面上
  另一置顶窗/前台竞争盖住采样点时 hits<3 → `image_path` 空 →
  `assert req["image_path"]` 红(ISS-0062 v0.5⑧ 实测,stash 对照=既有);
- **本钉的语义面**=「副屏虚拟坐标取图几何正确(PNG 尺寸==find_windows
  rect,非主屏错位图)」,前台/采样门控是该面的**附带路径**(主屏同链
  覆盖在 tc01)——敏感机制=附带路径依赖实时桌面 z-order,非钉本身脆;
- 与 tc10 不同处:tc10 钉的是隐藏窗语义(采样面本体),tc13 钉几何,
  故不照搬 tc10 处理。

## 2. 改法

- ①conftest 拆 `read_audit_text`(原文通道,文件读取唯一实现)+
  `read_audit`(dict 通道,复用前者);三副本删除,调用点切共享缝
  (子串断言语义逐字保持);
- ②环境不变量改造:tc13 保留 attach 拒绝链(环境无关),几何断言改经
  `executor.capture_approval_shot(rect)` 直取(=链末端同一生产函数,
  mss 虚拟坐标实拍,无前台/采样门控)——钉语义零削减,前台竞争面摘除;
  前台/采样链路由 tc01 等主屏用例继续覆盖。

## 3. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-24 | 立单(卫生级三项任务包①②合并)。现状+根因(tc13 敏感机制诊断:附带路径前台/采样门控依赖实时桌面 z-order)+改法 |
| v0.2 | 2026-09-24 | 两项修复落地,状态→已关闭。①conftest 拆 read_audit_text/read_audit(文件读取单源),三处私有副本删除、调用点切共享缝(断言语义逐字保持;影响面 46 passed);②tc13 环境不变量改造:几何断言改经 executor.capture_approval_shot(rect) 直取(链末端同一生产函数),attach 拒绝链保留,前台/采样面摘除——钉语义零削减,tc13 ×3 连跑绿+全文件 23 passed。无放宽登记项(①②均为等价或增强语义重构) |
