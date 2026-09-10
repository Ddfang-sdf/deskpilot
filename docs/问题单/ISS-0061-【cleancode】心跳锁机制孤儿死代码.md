# ISS-0061:【cleancode】freeze_notify 心跳锁机制成孤儿——LOCK_FILE/LOCK_MAX_AGE 死代码

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0061 |
| 标题 | freeze_notify.py:27-28 `LOCK_FILE = "estop-dialog.lock"` / `LOCK_MAX_AGE = 3.0` 无任何消费点(全库 grep 零命中);dist/audit/ 下残留 8 月 29 日的 estop-dialog.lock 实体文件——机制已废,尸体还在 |
| 严重级 | 低(死代码;误导后来者以为弹窗去重靠它) |
| 状态 | 建单待排期 |
| 提出 | 2026-09-10(cleancode 审查;ISS-0046 B 把弹窗互斥收口到命名互斥体后,心跳锁机制整体孤儿化) |

## 现象与证据

- freeze_notify.py:27-28 两常量零消费点;
- dist/audit/estop-dialog.lock 残留(2026-08-29,机制生前最后一口气);
- ISS-0006 时代设计是"心跳锁文件判弹窗存活";ISS-0046 B(今天)把跨进程
  单例收口到 `Local\DeskPilotFreezeDialog` 命名互斥体,锁文件路径彻底退场。

## 方向

删常量+删残留文件+ISS-0006/文档中心跳锁描述核对(若文档还写着锁文件
机制,同步改为互斥体叙述)。约束:互斥体路径(ISS-0046 B)为用例钉住,
不动。
