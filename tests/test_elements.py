"""M2 元素级操作单元测试（详细设计 §9.2 uia 子模块 / §14.7 / TDS TC-N-L2-03~05、
TC-E-TGT-04~07）。

入口：工具层公开入口（tools.call_tool 经强制层路由）与执行层公开入口
（Executor.execute）。断言值来源：ToolResult / 指令记录 / 元素替身调用记录。
元素替身实现设计文档定义的公开观测字段（§12.5：name/control_type/automation_id/
rect/interactable）。
"""

from __future__ import annotations

import pytest

from deskpilot import errors, tools
from deskpilot.errors import ExecutorError
from deskpilot.executor.core import Executor

from .conftest import (FIXTURE_HWND, FIXTURE_HWND_B, FIXTURE_RECT, FakeClock,
                       FakeProbe)


# ---------- 元素替身（测试布置，非业务代码） ----------

class FakeRect:
    """UIA 矩形替身（uiautomation.Rect 的属性形态）。"""

    def __init__(self, rect):
        self.left, self.top, self.right, self.bottom = rect


class FakeElement:
    """UIA 控件替身：公开字段与设计文档 §12.5 一致。"""

    def __init__(self, name="", automation_id="", control_type="Button",
                 enabled=True, children=None, *, invokable=True, setable=True,
                 value="", rect=None):
        self.Name = name
        self.AutomationId = automation_id
        self.ControlTypeName = control_type
        self.IsEnabled = enabled
        self._children = list(children or [])
        self._invokable = invokable
        self._setable = setable
        self.value = value
        self.rect = rect
        self.BoundingRectangle = FakeRect(rect) if rect is not None else None
        self.invoked = 0
        self.set_values: list[str] = []

    def GetChildren(self):
        return self._children

    def Invoke(self):
        self.invoked += 1

    def SetValue(self, text: str):
        self.set_values.append(text)
        self.value = text

    def GetValuePattern(self):
        """ValuePattern 语义：不支持设值的控件取模式即失败。"""
        if not self._setable:
            raise RuntimeError("no ValuePattern")
        return self


class MutableSource:
    """可按时钟翻转内容的元素源（wait_for_element 用）。

    根控件始终存在（窗口活着就有树）；目标元素在时钟越过 appear_at 后加入子树。
    """

    def __init__(self, clock: FakeClock, appear_at: float, target: FakeElement):
        self.root = FakeElement(children=[])
        self.clock = clock
        self.appear_at = appear_at
        self.target = target
        self.calls = 0

    def __call__(self, hwnd: int):
        self.calls += 1
        if self.clock() >= self.appear_at and self.target not in self.root._children:
            self.root._children.append(self.target)
        return self.root


# ---------- 闸路由（工具层 → 强制层，FakeExecutor 已放行路径） ----------

class TestElementGate:
    def test_click_element_no_binding(self, ctx):
        r = tools.call_tool(ctx, "click_element", {"token": "nope", "name": "保存"})
        assert r.ok is False
        assert r.error_code == errors.NO_BINDING

    def test_type_element_no_binding(self, ctx):
        r = tools.call_tool(ctx, "type_element",
                            {"token": "nope", "name": "编辑", "text": "x"})
        assert r.ok is False
        assert r.error_code == errors.NO_BINDING

    def test_wait_for_element_no_binding(self, ctx):
        r = tools.call_tool(ctx, "wait_for_element",
                            {"token": "nope", "name": "编辑"})
        assert r.ok is False
        assert r.error_code == errors.NO_BINDING

    def test_click_element_missing_locator(self, ctx, bound_record):
        """三选一必填：name / automation_id / som_id 全缺 → INVALID_PARAMS。"""
        r = tools.call_tool(ctx, "click_element", {"token": bound_record.token})
        assert r.ok is False
        assert r.error_code == errors.INVALID_PARAMS

    def test_type_element_missing_locator(self, ctx, bound_record):
        r = tools.call_tool(ctx, "type_element",
                            {"token": bound_record.token, "text": "x"})
        assert r.ok is False
        assert r.error_code == errors.INVALID_PARAMS

    def test_type_element_text_over_limit(self, ctx, bound_record):
        """文本超 input_max_chars → INVALID_PARAMS（执行层零接触）。"""
        too_long = "x" * (ctx.policy.input_max_chars + 1)
        r = tools.call_tool(ctx, "type_element",
                            {"token": bound_record.token, "name": "编辑",
                             "text": too_long})
        assert r.ok is False
        assert r.error_code == errors.INVALID_PARAMS

    def test_click_element_allowed_instruction(self, ctx, bound_record, executor):
        """放行：指令含工具名、定位参数与绑定句柄。"""
        r = tools.call_tool(ctx, "click_element",
                            {"token": bound_record.token, "name": "保存"})
        assert r.ok is True
        ins = executor.instructions[0]
        assert ins["tool"] == "click_element"
        assert ins["params"]["name"] == "保存"
        assert ins["binding_hwnd"] == FIXTURE_HWND

    def test_executor_element_error_propagates(self, ctx, bound_record, executor):
        """执行层元素错误码原样回传（ELEMENT_* 拒绝路径）。"""
        executor.error = ExecutorError(errors.ELEMENT_DISABLED, "元素禁用")
        r = tools.call_tool(ctx, "click_element",
                            {"token": bound_record.token, "name": "保存"})
        assert r.ok is False
        assert r.error_code == errors.ELEMENT_DISABLED


# ---------- 执行层 UIA 定位驱动（真 Executor + 注入元素源） ----------

@pytest.fixture
def fake_probe():
    p = FakeProbe()
    p.rects = {FIXTURE_HWND: FIXTURE_RECT}
    return p


@pytest.fixture
def real_executor(estop, tmp_path, clock, fake_probe, monkeypatch):
    ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                  wait_timeout_max=5.0, clock=clock, probe=fake_probe)
    # 遮挡校验打桩:其落点判定打的是真实屏幕,桌面窗口状态会把单测变环境
    # 依赖(随机序 CI 实证:被前台窗口遮挡即红)——本组用例的被测对象是
    # 元素定位/调用,遮挡语义由 click 系专测覆盖
    monkeypatch.setattr(ex, "_check_occlusion", lambda hwnd, x, y: None)
    return ex


def make_callable_source(elements: dict[int, FakeElement | None]):
    def source(hwnd: int):
        return elements.get(hwnd)
    return source


class TestElementDriver:
    def test_unique_match_invoked(self, real_executor, clock):
        """TC-N-L2-03：唯一匹配 → Invoke，返回被点元素摘要。"""
        btn = FakeElement(name="保存", automation_id="save-btn")
        real_executor._element_source = make_callable_source(
            {FIXTURE_HWND: FakeElement(children=[btn])})
        r = real_executor.execute(
            {"tool": "click_element", "params": {"name": "保存"},
             "binding_hwnd": FIXTURE_HWND})
        assert r["status"] == "ok"
        assert btn.invoked == 1
        assert r["element"]["name"] == "保存"
        assert r["element"]["automation_id"] == "save-btn"

    def test_automation_id_lookup(self, real_executor):
        btn = FakeElement(name="", automation_id="ok-btn")
        real_executor._element_source = make_callable_source(
            {FIXTURE_HWND: FakeElement(children=[btn])})
        r = real_executor.execute(
            {"tool": "click_element", "params": {"automation_id": "ok-btn"},
             "binding_hwnd": FIXTURE_HWND})
        assert r["status"] == "ok"
        assert btn.invoked == 1

    def test_not_found_with_candidates(self, real_executor):
        """TC-E-TGT-04：未找到 → ELEMENT_NOT_FOUND，附候选元素列表。"""
        tree = FakeElement(children=[
            FakeElement(name="文件"), FakeElement(name="编辑"),
            FakeElement(name="视图")])
        real_executor._element_source = make_callable_source(
            {FIXTURE_HWND: tree})
        with pytest.raises(ExecutorError) as ei:
            real_executor.execute(
                {"tool": "click_element", "params": {"name": "不存在按钮"},
                 "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == errors.ELEMENT_NOT_FOUND
        assert "文件" in ei.value.message and "编辑" in ei.value.message

    def test_ambiguous_with_candidates(self, real_executor):
        """TC-E-TGT-05：多匹配 → ELEMENT_AMBIGUOUS，附候选列表。"""
        tree = FakeElement(children=[
            FakeElement(name="保存", rect=(110, 110, 160, 140)),
            FakeElement(name="保存", rect=(200, 110, 250, 140))])
        real_executor._element_source = make_callable_source(
            {FIXTURE_HWND: tree})
        with pytest.raises(ExecutorError) as ei:
            real_executor.execute(
                {"tool": "click_element", "params": {"name": "保存"},
                 "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == errors.ELEMENT_AMBIGUOUS
        assert "保存" in ei.value.message

    def test_disabled_rejected(self, real_executor):
        """TC-E-TGT-06：禁用元素 → ELEMENT_DISABLED，不调用 Invoke。"""
        btn = FakeElement(name="灰态按钮", enabled=False)
        real_executor._element_source = make_callable_source(
            {FIXTURE_HWND: FakeElement(children=[btn])})
        with pytest.raises(ExecutorError) as ei:
            real_executor.execute(
                {"tool": "click_element", "params": {"name": "灰态按钮"},
                 "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == errors.ELEMENT_DISABLED
        assert btn.invoked == 0

    def test_type_element_setvalue(self, real_executor):
        """TC-N-L2-05：唯一匹配编辑控件 → SetValue 设值。"""
        edit = FakeElement(name="编辑区", control_type="Edit",
                           automation_id="editor")
        real_executor._element_source = make_callable_source(
            {FIXTURE_HWND: FakeElement(children=[edit])})
        r = real_executor.execute(
            {"tool": "type_element", "params": {"name": "编辑区", "text": "Hello"},
             "binding_hwnd": FIXTURE_HWND})
        assert r["status"] == "ok"
        assert edit.set_values == ["Hello"]
        assert edit.value == "Hello"

    def test_type_element_unsupported(self, real_executor):
        """TC-E-TGT-07：不支持设值 → ELEMENT_UNSUPPORTED，引导改用 type_text。"""
        label = FakeElement(name="只读标签", control_type="Text", setable=False)
        real_executor._element_source = make_callable_source(
            {FIXTURE_HWND: FakeElement(children=[label])})
        with pytest.raises(ExecutorError) as ei:
            real_executor.execute(
                {"tool": "type_element",
                 "params": {"name": "只读标签", "text": "x"},
                 "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == errors.ELEMENT_UNSUPPORTED
        assert "type_text" in ei.value.message


# ---------- 等待轮询（wait_for_element，§13.6） ----------

class TestWaitElement:
    def _run_wait(self, ex, params):
        """在后台推进时钟的线程中执行等待调用，返回结果或异常。"""
        import threading
        outcome: dict = {}

        def advance():
            import time as _t
            for _ in range(120):
                _t.sleep(0.01)
                ex._clock.advance(0.01)

        t = threading.Thread(target=advance, daemon=True)
        t.start()
        try:
            outcome["result"] = ex.execute(params)
        except ExecutorError as e:
            outcome["error"] = e
        t.join(timeout=5)
        return outcome

    def test_appears_within_timeout(self, estop, tmp_path, clock, fake_probe):
        """目标晚于调用出现 → 命中返回元素信息（含控制类型与自动化标识）。"""
        target = FakeElement(name="保存对话框", control_type="Window",
                             automation_id="dlg")
        src = MutableSource(clock, appear_at=clock.t + 0.15, target=target)
        ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                      wait_timeout_max=5.0, clock=clock, probe=fake_probe,
                      element_source=src)
        outcome = self._run_wait(
            ex, {"tool": "wait_for_element",
                 "params": {"name": "保存对话框", "timeout": 2.0},
                 "binding_hwnd": FIXTURE_HWND})
        assert "error" not in outcome
        r = outcome["result"]
        assert r["status"] == "ok"
        assert r["element"]["name"] == "保存对话框"
        assert r["element"]["control_type"] == "Window"

    def test_timeout(self, estop, tmp_path, clock, fake_probe):
        """超时 → TIMEOUT，附最后探测状态。"""
        src = MutableSource(clock, appear_at=clock.t + 9999.0,
                            target=FakeElement(name="永不出现"))
        ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                      wait_timeout_max=5.0, clock=clock, probe=fake_probe,
                      element_source=src)
        outcome = self._run_wait(
            ex, {"tool": "wait_for_element",
                 "params": {"name": "永不出现", "timeout": 0.3},
                 "binding_hwnd": FIXTURE_HWND})
        assert "error" in outcome
        assert outcome["error"].code == errors.TIMEOUT
        assert "永不出现" in outcome["error"].message
        assert src.calls >= 2


class TestActivationFailClosed:
    """实盘事故回归：前置失败时写路径必须中止，禁止向失焦窗口开火。"""

    def _executor(self, estop, tmp_path, clock, probe):
        return Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                        wait_timeout_max=5.0, clock=clock, probe=probe)

    def _blocked(self, fake_probe):
        """让绑定窗口不在前台且前置必然失败。"""
        fake_probe.foreground = FIXTURE_HWND_B
        fake_probe.activate_result = False

    def test_type_text_aborts_when_activate_fails(self, estop, tmp_path,
                                                  clock, fake_probe):
        self._blocked(fake_probe)
        ex = self._executor(estop, tmp_path, clock, fake_probe)
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "type_text", "params": {"text": "x"},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == errors.WINDOW_GONE
        assert "防误射" in ei.value.message

    def test_key_aborts_when_activate_fails(self, estop, tmp_path,
                                            clock, fake_probe):
        self._blocked(fake_probe)
        ex = self._executor(estop, tmp_path, clock, fake_probe)
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "key", "params": {"key": "ctrl+z"},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == errors.WINDOW_GONE

    def test_click_aborts_when_activate_fails(self, estop, tmp_path,
                                              clock, fake_probe):
        self._blocked(fake_probe)
        ex = self._executor(estop, tmp_path, clock, fake_probe)
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "click", "params": {"x": 300, "y": 300},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == errors.WINDOW_GONE


class TestInvokeFallback:
    """元素激活三级回退：Invoke → SelectionItem → 像素点击（实盘 Paint 回归）。"""

    def _executor(self, estop, tmp_path, clock, probe):
        return Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                        wait_timeout_max=5.0, clock=clock, probe=probe)

    def test_selection_pattern_fallback(self, estop, tmp_path, clock, fake_probe):
        """无 Invoke 的列表项 → SelectionItem.Select 命中。"""
        class Selectable(FakeElement):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.selected = 0

            def Invoke(self):
                raise RuntimeError("no invoke")

            def GetSelectionItemPattern(self):
                return self

            def Select(self):
                self.selected += 1

        item = Selectable(name="矩形")
        ex = self._executor(estop, tmp_path, clock, fake_probe)
        ex._element_source = lambda hwnd: FakeElement(children=[item])
        r = ex.execute({"tool": "click_element", "params": {"name": "矩形"},
                        "binding_hwnd": FIXTURE_HWND})
        assert r["status"] == "ok"
        assert item.selected == 1

    def test_pixel_fallback(self, estop, tmp_path, clock, fake_probe, monkeypatch):
        """既无 Invoke 也无选择模式 → 元素中心像素点击兜底。

        ISS-0025 E 实证修复:原实现手工 `FakeElement.Invoke = fake_invoke`
        后 `del FakeElement.Invoke`——del 删掉的是类字典里的原始方法本身,
        该测试跑过即永久摧毁 Invoke,随机序下先跑会炸掉后序用例;
        改用 monkeypatch 自动还原(顺序依赖治理)。
        """
        item = FakeElement(name="形状项", invokable=False, rect=(110, 110, 160, 140))
        clicked = []

        def fake_invoke(self):
            raise RuntimeError("no invoke")

        monkeypatch.setattr(FakeElement, "Invoke", fake_invoke)
        ex = self._executor(estop, tmp_path, clock, fake_probe)
        ex._element_source = lambda hwnd: FakeElement(children=[item])
        ex._pixel_click = lambda x, y: clicked.append((x, y))
        r = ex.execute({"tool": "click_element", "params": {"name": "形状项"},
                        "binding_hwnd": FIXTURE_HWND})
        assert r["status"] == "ok"
        assert clicked == [(135, 125)]


class TestGhostDedup:
    """WinUI 幽灵重复（同名同型同矩形）应视为同一元素。"""

    def _executor(self, estop, tmp_path, clock, probe):
        return Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                        wait_timeout_max=5.0, clock=clock, probe=probe)

    def test_identical_duplicates_resolve_unique(self, estop, tmp_path, clock,
                                                 fake_probe):
        rect = (110, 110, 160, 140)
        ghost1 = FakeElement(name="编辑框", control_type="Edit", rect=rect)
        ghost2 = FakeElement(name="编辑框", control_type="Edit", rect=rect)
        ex = self._executor(estop, tmp_path, clock, fake_probe)
        ex._element_source = lambda hwnd: FakeElement(
            children=[ghost1, ghost2])
        r = ex.execute({"tool": "type_element",
                        "params": {"name": "编辑框", "text": "Hello"},
                        "binding_hwnd": FIXTURE_HWND})
        assert r["status"] == "ok"
        assert ghost1.set_values == ["Hello"]
        assert ghost2.set_values == []

    def test_distinct_same_name_still_ambiguous(self, estop, tmp_path, clock,
                                                fake_probe):
        a = FakeElement(name="保存", rect=(110, 110, 160, 140))
        b = FakeElement(name="保存", rect=(200, 110, 250, 140))
        ex = self._executor(estop, tmp_path, clock, fake_probe)
        ex._element_source = lambda hwnd: FakeElement(children=[a, b])
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "click_element", "params": {"name": "保存"},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == errors.ELEMENT_AMBIGUOUS


class TestValuePatternNone:
    """uiautomation 对无 ValuePattern 控件返回 None → 必须按不支持处理。"""

    def _executor(self, estop, tmp_path, clock, probe):
        return Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                        wait_timeout_max=5.0, clock=clock, probe=probe)

    def test_none_pattern_is_unsupported(self, estop, tmp_path, clock,
                                         fake_probe):
        edit = FakeElement(name="编辑框", control_type="Edit",
                           rect=(110, 110, 160, 140))
        edit.GetValuePattern = lambda: None      # 实盘 Paint 行为
        ex = self._executor(estop, tmp_path, clock, fake_probe)
        ex._element_source = lambda hwnd: FakeElement(children=[edit])
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "type_element",
                        "params": {"name": "编辑框", "text": "x"},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == errors.ELEMENT_UNSUPPORTED
        assert "type_text" in ei.value.message
