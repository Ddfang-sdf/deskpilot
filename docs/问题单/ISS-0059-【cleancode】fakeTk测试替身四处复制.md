# ISS-0059:【cleancode】fake-Tk 测试替身四处复制

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0059 |
| 标题 | 同一套 Tk 替身(W 基类 pack/place/bind/config/geometry… + Button/Label 记录器)在 test_batch_iss19 / test_sessionscope_iss43 / test_whitelist_iss12 / test_monitors_iss7 四个文件各抄一份;弹窗 API 增参数时四处同步,今天 ISS-0043/0053 已复制到第四份 |
| 严重级 | 低(测试可维护性) |
| 状态 | 建单待排期 |
| 提出 | 2026-09-10(cleancode 审查;grep winfo_screenwidth 四文件实证) |

## 现象与证据

四份同形 W/Btn/Lbl 替身类(grep `winfo_screenwidth` 命中四测试文件),
细节已开始漂移(有的收 text、有的收 command、有的都不收)。
今天写 TC-43 时我又复制了一份(自证其害)。

## 方向

收编 `tests/faketk.py`(单一替身库:W/Btn/Lbl/Toplevel 工厂+文本与命令
记录),四文件改导入;断言形态不变。约束:四个套件转绿即验收。
