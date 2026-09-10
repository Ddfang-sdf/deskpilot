# ISS-0051:【打包/源码同病】PMV2 声明 ctypes 封送溢出被吞——DPI 感知从未真正是 PMV2

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0051 |
| 标题 | main.py:25 `SetProcessDpiAwarenessContext(ctypes.c_void_p(-4).value)`:.value 把句柄拆包成 64 位巨无符号整数,无 argtypes 时 ctypes 按 c_int 封送溢出抛 ArgumentError,被 try/except 回退吞掉 → PMV2 声明自 ISS-0007 D 起从未成功,进程实际锁在 V1(系统级);混合 DPI 双屏副屏位图拉伸风险一直在场 |
| 严重级 | **高**(安全声明静默失效:设计承诺 PMV2,实盘一直是 V1;源码形态与打包形态同病——隔离实验实证的同根) |
| 状态 | **已修复(19 过+活实证:重打包后 /health dpi_mode=pmv2,2026-09-10)** |
| 提出 | 2026-09-10(ISS-0050 可诊断首轮活实证钓出 /health dpi_mode=v1;隔离实验:裸 python 同调用即 OverflowError,与清单无关——清单假设被证据推翻) |

## 1. 根因(机制层,隔离实验链)

| 实验 | 结果 | 结论 |
|------|------|------|
| /health(新 exe) | dpi_mode=v1 | 打包形态 PMV2 失效 |
| 源码形态 import main → _DPI_MODE | 同为 v1 | 非清单问题,与打包无关 |
| 裸 python 同调用(c_void_p(-4).value) | **OverflowError: int too long to convert** | 真凶:封送溢出被 except 吞 |
| 改传 c_void_p(-4) 对象 | 返回 1,查询确认 PMV2 | 修法验证成立 |

教训链:调用成败记账法 + 静默回退 = 声明失效两年无人知(ISS-0050 的
可诊断缺口放大了它;两份病根是同一份"静默")。

## 2. 整改方案

| 项 | 内容 |
|----|------|
| A | 修封送:`SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))` 传对象不拆 .value |
| B | 回报改**查询制**:声明后一律 GetThreadDpiAwarenessContext + AreDpiAwarenessContextsEqual 查真实上下文(原始句柄含标志位——实证 PMV2 原值 34,禁止直比数值);回报域 pmv2/pmv1/v1/unaware/unknown。清单预设、调用被拒、封送异常任何组合都说实话 |

### 约束

- 声明顺序不变(先 PMV2 尝试,败则系统级);只修封送与回报;
- 测试设计(五要素):TC-51-01 子进程真调用回归钉(import deskpilot.main
  打印 _DPI_MODE 必为 pmv2,真 Win32 无替身——封送 bug 的诚实回归);
  TC-51-02 查询制如实(替身 setter 全败+查询返 PMV2 上下文 → 报 pmv2,
  清单预设场景重演);TC-50-02/03 随查询制改写;TC-51-03 活实证
  (重打包 /health dpi_mode=pmv2,记批次 H)。

## 3. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-10 | 建单(四连隔离实验实证 ctypes 封送溢出被吞;清单假设推翻记录)+修复+用例 |
| v0.2 | 2026-09-10 | P3 绿:传参改 c_void_p 对象+回报查询制(_query_dpi_mode);TC-51-01/02+TC-50 改写+ISS-0007 三用例迁移共 19 过;测试替身同踩 value 无符号回绕坑(同形化修正)——再次印证封送语义反直觉 |
