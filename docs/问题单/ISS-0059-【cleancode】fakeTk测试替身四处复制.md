# ISS-0059:【cleancode】fake-Tk 测试替身四处复制

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0059 |
| 标题 | 同一套 Tk 替身(W 基类 pack/place/bind/config/geometry… + Button/Label 记录器)在 test_batch_iss19 / test_sessionscope_iss43 / test_whitelist_iss12 / test_monitors_iss7 四个文件各抄一份;弹窗 API 增参数时四处同步,今天 ISS-0043/0053 已复制到第四份 |
| 严重级 | 低(测试可维护性) |
| 状态 | 方案已设计,待 sdfang 评审排期(2026-09-22 方案落档,见下「整改方案」) |
| 提出 | 2026-09-10(cleancode 审查;grep winfo_screenwidth 四文件实证) |

## 现象与证据

四份同形 W/Btn/Lbl 替身类(grep `winfo_screenwidth` 命中四测试文件),
细节已开始漂移(有的收 text、有的收 command、有的都不收)。
今天写 TC-43 时我又复制了一份(自证其害)。

## 方向

收编 `tests/faketk.py`(单一替身库:W/Btn/Lbl/Toplevel 工厂+文本与命令
记录),四文件改导入;断言形态不变。约束:四个套件转绿即验收。

## 评估记录(2026-09-17)

| 项 | 内容 |
|----|------|
| 现状核对 | 仍成立且+1:今日 ISS-0071 的 test_dialoggeo_iss71.py 又新增一份 Tk 替身(认账:当时按 test_fastopen_iss12 先例就地复制)——共 5 处 |
| 处置 | **保留排期**。建议:conftest 提供共享 fakeTk 工厂(记 geometry/title 等通用观测口),五个测试文件逐批收敛;顺带做,不独立占用窗口 |

## 整改方案(2026-09-22 设计)

### 现状核验(2026-09-22 复核,行号实证)

问题单原述「四处」+ 评估记录「共 5 处」均已过时:grep `class W:` /
`winfo_screenwidth` / `setattr(*.tk, "Toplevel"` 三路交叉实证,现状为
**16 份替身体、分布 11 个测试文件**,问题单低估约 3 倍。另纠正任务面
一处前提:test_freeze_singleton.py 实无 Tk 替身(纯函数+子进程单测,
tests/test_freeze_singleton.py:1-69 通篇无 tk 补丁),不纳入本单。

| # | 位置 | 方言 | 观测口(记录什么) |
|---|------|------|------------------|
| 1 | tests/test_batch_iss19.py:107 | 显式方法表 W+Btn | buttons(text/command) |
| 2 | tests/test_sessionscope_iss43.py:27 | 显式 W+Lbl | labels 文本 |
| 3 | tests/test_whitelist_iss12.py:276 | 显式 W(geo 记录)+Btn | clicks |
| 4 | tests/test_whitelist_iss12.py:480 | 管理窗口大 W(Canvas/Entry 面)+Btn/Lbl/Top(:516-529) | buttons/labels/tops |
| 5 | tests/test_whitelist_iss12.py:692 | 显式 W+Btn | buttons |
| 6 | tests/test_whitelist_iss12.py:743 | 同 #3(geo+clicks) | clicks |
| 7 | tests/test_whitelist_iss12.py:831 | W(after/destroy 记账)+Lbl/Btn | rec 字典 |
| 8 | tests/test_monitors_iss7.py:85 FakeWin + :134 _FakeWidget | 显式 | geo |
| 9 | tests/test_dialoggeo_iss71.py:67 | `__getattr__` 沉默+geometry 记录 | rec |
| 10 | tests/test_fastopen_iss12.py:67 | 显式大 W(Canvas 面) | — |
| 11 | tests/test_estopreset_iss93.py:57 _TkRig | `__getattr__`+buttons/after_queue | rig |
| 12 | tests/test_i18n_req07.py:74 | `__getattr__`+cget/text | texts |
| 13 | tests/test_freeze_dialog_iss103.py:57 | `__getattr__`+place 记录 | places |
| 14 | tests/test_whitelist_inplace_iss85.py:39 | #4 的复制+Top destroy/protocol 扩展(:79-88) | rec |
| 15 | tests/test_window_ext_iss12.py:107 | 显式大 W(Canvas 面) | — |
| 16 | tests/test_approval_dialog_iss98.py:27 _Recorder | `__getattr__` 记账(类属性 calls, :50) | calls |

基线实测(2026-09-22,`.venv` 全量默认层):**900 passed, 28 skipped**
(928 collected,212.58s),与任务单所述基线一致。

### 根因(机制层)

1. **替身没有单一来源,先例即规范**。tk widget 类以模块全局 `tk`
   (=tkinter 本体)暴露,测试只能 monkeypatch 就地装配;仓库从未提供
   共享替身库,每写一个弹窗用例,最便宜的局部动作就是照抄上一份
   (问题单与 ISS-0071 评估两次自证「按先例就地复制」)。复制是结构
   缺口下的理性选择,不是个人习惯问题——不收编单一来源,第 17 份
   只是时间问题。
2. **两种替身方言并存、各自漂移、无人仲裁**。显式方法表方言
   (#1-#8/#10/#15:未列方法→AttributeError,响)与 `__getattr__`
   沉默方言(#9/#11-#14/#16:任意未知方法→None lambda,默)并存;
   同方言内部也在漂——屏幕常量 2560×1440(#1-#7)vs 1920×1080
   (#9/#11-#13/#16)、after 返回值 None / "a1" / 入队三种形态、
   观测口各记各的(text/command/geo/place/afters 互不约束)。弹窗
   API 每增一个 Tk 调用,需同步的份数随复制次数线性增长,形成
   正反馈。
3. **沉默方言与 fail-closed 纪律相悖**。`__getattr__` 吞掉一切未知
   调用,被测代码新增 Tk 交互时替身静默放行,测试可能假绿——与
   SDD-开发流程 §5「安全路径 fail-closed」冲突,属复制漂移积累的
   隐性语义回退,整改应借机收紧而非照单保留。

### 改法(小步快走,每步独立验证、独立提交)

约定:产品代码零改动;除步骤 1(新库)与步骤 2(守卫)外全部为
测试内纯重构——断言形态、断言值、用例数量不变。

- **步骤 1(新增文件,有测试面)**:新建 `tests/faketk.py` 单一替身库:
  - `FakeWidget` 显式方法面 = 16 份替身的方法并集(pack/place/grid/
    pack_forget/bind/bind_all/config/configure/focus_set/title/
    overrideredirect/attributes/geometry/minsize/protocol/after/
    destroy/update_idletasks/winfo_*/yview*/create_*/itemconfig/
    bbox/delete/get/set/cget);未列方法 → AttributeError
    (fail-closed,废止 `__getattr__` 沉默方言)。
  - 内建观测口:text/command 记录、geometry 记录、place 记录、
    after 队列(记录 (ms,fn) 并返回令牌,提供 pump)、destroy 计数;
    屏幕尺寸参数化(`screen=(w,h)`,默认 2560×1440,迁移时按各
    测试原校准值传,不动断言值)。
  - `install(monkeypatch, tk_module, screen=…, reqheight=…)` 工厂:
    一次替换 Toplevel/Frame/Label/Button/Canvas/Scrollbar/Entry,
    返回 recorder。
  - 同步新建 `tests/test_faketk.py` 钉库契约(用例表见「测试设计
    要点」),P1 先红(库不存在)、P3 实现转绿。
- **步骤 2(新增守卫用例,先红)**:`tests/test_faketk.py` 内形态用例
  TC-FAKETK-GUARD:源码扫描 tests/ 下除 faketk.py 与白名单外,禁止
  出现本地替身类定义(`class W:`/`FakeWin`/`_Recorder`/`_TkRig` 等)
  与就地 `setattr(*.tk, "Toplevel"` 补丁。提交时红(16 份在册),
  随迁移逐个转绿——本单「先红后绿」由守卫承担,且永久防复发。
- **步骤 3-13(每步=一个测试文件,纯重构)**:逐文件迁移到
  `from .faketk import install`,删除本地替身体;断言代码零改动
  (仅装配段替换)。顺序(先难后易,最大文件先验证库表达力):
  1. test_whitelist_iss12.py(5 份替身 #3-#7,同文件一次收编)
  2. test_whitelist_inplace_iss85.py(#14)
  3. test_fastopen_iss12.py(#10)
  4. test_window_ext_iss12.py(#15)
  5. test_batch_iss19.py(#1)
  6. test_sessionscope_iss43.py(#2)
  7. test_monitors_iss7.py(#8)
  8. test_dialoggeo_iss71.py(#9)
  9. test_i18n_req07.py(#12)
  10. test_freeze_dialog_iss103.py(#13)
  11. test_estopreset_iss93.py(#11,after 泵语义迁入库)
  12. test_approval_dialog_iss98.py(#16,类属性 calls 改实例
      recorder+fixture 复位,消除借前序残留风险)
- **步骤 14(收尾)**:守卫全绿确认 + 全量基线复核 + 本单状态流转。

每步验证纪律:迁移文件单跑绿 **且** 全量套件绿,双跑缺一不可
(ISS-0026 教训:单跑/全量顺序依赖可致借残留假绿)。

行为面标注:步骤 3-13 均为纯重构(既有钉全绿即证)。有行为面的
仅两处:① `__getattr__` 沉默方言废止改显式面——属测试基础设施的
fail-closed 收紧(非产品语义),若某用例暗中依赖沉默放行,迁移当场
转红,处置=补库方法面并在提交信息登记,不许回退成沉默面;
② 步骤 1/2 的新库钉与守卫为先红后绿新用例。

### 约束

- 产品代码零改动;fail-closed 语义不回退(本单反向收紧:沉默替身
  改显式面)。
- 全量基线(默认层 900 passed / 28 skipped)保持绿;断言形态、断言
  值、用例数不变;任何断言放宽走 SDD 测试放宽双闸门,本单不预期
  触发。

### 测试设计要点

步骤 1 新库钉(tests/test_faketk.py,层级=[单元],替身库自测允许
打桩):

| 用例编号 | 测试场景 | 测试前提 | 测试步骤 | 测试预期结果 | 断言代码(断什么/由什么直出) |
|---------|---------|---------|---------|-------------|---------------------------|
| TC-FAKETK-01 | 按钮文本/命令记录 | install 已装配 | 1. 经替身构造 Button(text="x", command=f) | recorder 收录该按钮 | `rec.buttons[0].text == "x"`、`rec.buttons[0].command is f`(替身记录直出) |
| TC-FAKETK-02 | geometry 记录 | 同上 | 1. 替身窗 `geometry("1x1+2+3")` | 几何记录末项为该串 | `rec.geometries[-1] == "1x1+2+3"`(直出) |
| TC-FAKETK-03 | after 入队可泵 | 同上 | 1. `after(10, f)` 2. pump | f 恰执行一次 | 标志位计数 == 1(直出) |
| TC-FAKETK-04 | 未知方法 fail-closed | 同上 | 1. 调替身未定义方法 | 抛 AttributeError | `pytest.raises(AttributeError)`(异常直出) |
| TC-FAKETK-GUARD | 替身唯一来源(形态) | 仓库现状 | 1. 扫描 tests/*.py 本地替身定义与就地 Toplevel 补丁 | 白名单外零命中 | 命中清单 == [](源码直读) |

步骤 3-13(纯重构):不设新用例,既有钉全绿即证;红线=迁移文件
单跑 + 全量双绿。

交叉面清单(SDD §2.1):

| 触及对象 | 其他写入者/读取者 | 覆盖用例 | 或豁免理由 |
|---------|-----------------|---------|-----------|
| tkinter 模块属性(Toplevel/Frame/Label/Button/Canvas/Scrollbar/Entry) | 全部弹窗测试的 monkeypatch 写入;`ad.tk`/`ww.tk` 与 tkinter 为同一模块对象 | 各迁移文件既有用例 | — |
| after 调度语义 | test_estopreset_iss93.py:102 pump_to_shown(16 帧);test_whitelist_iss12.py:853 返回 "a1";test_approval_dialog_iss98.py:47 静默 None | 迁移后既有用例 | 库统一「入队+返回令牌+泵接口」,三形态归一 |
| 屏幕常量 2560×1440 / 1920×1080 | 几何断言校准值(test_dialoggeo_iss71.py:90 等实测由 enum_monitors 桩决定,不吃 winfo) | 既有几何断言 | `install(screen=…)` 按原值传参,断言值不动 |
| `_Recorder.calls` 类属性(test_approval_dialog_iss98.py:50) | 类级跨用例状态,借前序残留风险 | 迁移为实例 recorder+fixture 复位后既有用例 | ISS-0026 教训,借机消除 |
| test_estopreset_iss93.py:487-521 真 Tk E2E(TC-93-12) | 真实 tkinter 线程,非替身 | 既有环境守卫 skip | 豁免:非替身,守卫白名单;守卫只禁本地替身定义/就地补丁,不禁止 import tkinter |

### 工作量粗估

14 步(1 库+1 守卫+11 文件迁移+1 收尾),受影响文件 ~14:
tests/faketk.py、tests/test_faketk.py 新增;11 个既有测试文件各改
一处装配段;本问题单文档。净删 ~600 行重复、增 ~200 行库+钉。
单人日 0.5-1 天;每步独立提交、可独立回滚。

### 风险点

1. 沉默方言废止的连锁红:某用例若依赖 `__getattr__` 吞掉的未列
   Tk 方法,迁移即红——处置=补库方法面并登记,属预期内收紧代价,
   不许回退沉默面。
2. test_whitelist_iss12 同文件 5 份替身,单步爆炸半径最大,放迁移
   序列首位验证库表达力;库面不足先扩库再继续。
3. 测试间顺序依赖:装配段改写后单跑+全量双验证,缺一不提交。
4. 守卫误伤:真 Tk E2E(TC-93-12)与 faketk.py 自身需白名单。

### 待人类裁决

1. 落位形态:`tests/faketk.py` 显式 import(本方案默认,合问题单
   「方向」原话)vs conftest fixture 注入(2026-09-17 评估记录
   建议)——二选一或并存,请拍板。
2. 是否认可借机废止 `__getattr__` 沉默替身、统一显式方法面
   (fail-closed 收紧,可能伴随步骤内补面小迭代)。
3. 屏幕常量是否借机统一默认值(本方案:保留参数化、按各测试原
   校准值传参,不动断言值)。

## 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-22 | 整改方案落档:现状复核为 16 份替身/11 文件(原述 5 处低估);根因写到机制层(无单一来源+双方言漂移+沉默方言悖 fail-closed);14 步小步快走(tests/faketk.py 单一替身库 + 先红守卫 TC-FAKETK-GUARD + 11 文件逐文件纯重构迁移);基线 900 passed 保持绿;状态转「方案已设计,待 sdfang 评审排期」 |
