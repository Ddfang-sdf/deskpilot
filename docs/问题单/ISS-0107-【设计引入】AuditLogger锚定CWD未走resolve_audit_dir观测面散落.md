# ISS-0107:【设计引入】AuditLogger 锚定 CWD 未走 resolve_audit_dir——观测面文件散落三地

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0107 |
| 标题 | `main.py:423` `AuditLogger(policy.audit_dir)` 吃配置原文(相对串 `./audit`),实际锚定进程 CWD;dist daemon 从仓库根启动写 repo audit/、从开始菜单启动写 exe 目录、计划任务启动写 system32——观测面文件落点随启动方式漂移,历次「心跳不写」「文件找不到」误读的系统性诱因(ISS-0094 §4.4 B-6 转出) |
| 严重级 | **中**(观测面一致性;非安全缺陷) |
| 状态 | **已关闭**(2026-09-23 裁定:sdfang 离场授权自决,取②不改代码、文档化启动契约——理由见 §4) |
| 提出 | ISS-0094 诊断 §4.4 B-6 |

## 1. 实证

- `main.py:423` AuditLogger 直吃 `policy.audit_dir` 原文;同文件 :467 AuditPaths、:505 Executor 同样直吃——**只有策略迁移路径(main.py:383-388)走 `resolve_audit_dir`**;
- `audit_paths.py:13-26` resolve_audit_dir 语义:相对路径源码形态锚 policy 所在目录、冻结形态锚 exe 目录——main 主路径未复用;
- 2026-09-22 实盘:dist daemon(cwd=repo)写 repo audit/,与 ISS-0084 锚定 LOCALAPPDATA 的 estop/属主面形成「两地三处」观测面。

## 2. 影响面(裁决须答)

- 改走 resolve_audit_dir 后:**冻结形态审计目录从 CWD 变为 exe 目录**——既有部署的 audit/ 累积数据、手工测试文档引用路径、ISS-0010 清理(janitor)锚点、CI artifact 路径全部连带;
- 不改:CWD 依赖继续,文档须明示「从何处启动 daemon」是运维契约。

## 3. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-22 | 立单(ISS-0094 E-4 转出)。实证+影响面两问 |

## 4. 裁定(2026-09-23,sdfang 离场留言授权自决,记录在案)

**取②:不改代码,文档化启动契约**。理由:①改走 resolve_audit_dir 会把冻结形态观测面从 CWD 迁到 exe 目录——既有部署的 audit 累积数据、CI artifact、手工测试引用全部连带漂移,风险大于收益;②CWD 依赖本身可文档化为运维契约(「从安装/仓库根启动 daemon」);③真正的观测错位已被 ISS-0094 心跳健壮性+观测消歧(判活以 ts 新鲜度)覆盖。启动契约已随 ISS-0094 v0.4 落入 INSTALL.md 故障排查表。

## 5. 变更记录(续)

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.2 | 2026-09-23 | 裁定关单:取②不改代码,启动契约文档化(理由三条) |
