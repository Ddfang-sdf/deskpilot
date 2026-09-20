"""ISS-0098 审批弹窗高度实测化测试(i08~i11,问题单 §4 骨架)。

层级:单元(Tk 替身,允许打桩);形态(源码行序直读)。
入口(设计):deskpilot.approval_dialog.build_window(公开构建入口)。
断言出处:geometry 调用序列直出(替身记账)/toast_placement 实收 height
直出(桩记录)/源码行序直读。

机制钉:窗高必须先排版(update_idletasks→winfo_reqheight)后落位;
静态估算(216+提示+缩略图)只做地板,不再封顶。红态预期(现状):
i08/i09 红——无 reqheight 咨询,geometry 只有估算高一次;i10 红——
源码无 update_idletasks。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

DESC_LONG = ("AI requests to operate a new app: \"字符映射表\"\n---\n" +
             "Process charmap.exe is not locally authorized yet. " * 12)


class _Recorder:
    """Tk 替身:几何/测量调用记账。winfo_reqheight 由测试注入。"""

    reqheight_value = 0

    def __init__(self, *a, **k):
        self._text = k.get("text", a[2] if len(a) > 2 else "")

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name == "winfo_reqheight":
            return lambda: type(self).reqheight_value
        if name in ("winfo_screenwidth", "winfo_screenheight"):
            return lambda: 1920 if name == "winfo_screenwidth" else 1080
        if name == "geometry":
            return self._geometry
        if name == "update_idletasks":
            return lambda: type(self).calls.append(("update_idletasks", None))
        if name == "after":
            return lambda *a, **k: None       # 不跑 tick/slide 调度
        return lambda *a, **k: None

    calls: list = []

    def _geometry(self, spec: str):
        type(self).calls.append(("geometry", spec))

    def configure(self, **k):
        if "text" in k:
            self._text = k["text"]

    config = configure


@pytest.fixture
def tk_stub(monkeypatch):
    """替身装配:全 widget 类替换 + 记账复位;返回记账列表。"""
    import deskpilot.approval_dialog as ad
    _Recorder.calls = []
    _Recorder.reqheight_value = 0
    for cls in ("Toplevel", "Frame", "Label", "Button", "Canvas"):
        monkeypatch.setattr(ad.tk, cls, _Recorder)
    return _Recorder.calls


class TestMeasuredHeightPlacement:
    """i08/i09:实测高进几何与落位;静态估算只做地板。"""

    def _build(self, monkeypatch, reqh: int):
        import deskpilot.approval_dialog as ad
        _Recorder.reqheight_value = reqh
        seen = {}
        real_tp = ad._toast_placement

        def spy(screen, width, height):
            seen["height"] = height
            return real_tp(screen, width, height)

        monkeypatch.setattr(ad, "_toast_placement", spy)
        monkeypatch.setenv("DESKPILOT_LOCALE", "en")
        ad.build_window(object(), DESC_LONG, str(ROOT / "r.txt"), 5,
                        enroll="charmap.exe")
        return seen

    def test_i08_long_content_measured_height_applied(self, tk_stub,
                                                      monkeypatch):
        """i08:英文长文(替身 reqheight=600)→ 窗高按 600 重设重落位。"""
        seen = self._build(monkeypatch, 600)
        assert seen["height"] == 600                    # 落位实收(直出)
        geos = [s for kind, s in tk_stub if kind == "geometry"]
        assert "480x600+1424+1080" in geos              # 重设入几何(直出)

    def test_i09_short_content_floor_no_collapse(self, tk_stub, monkeypatch):
        """i09:短正文(reqheight=100 < 地板 216)→ 窗高=地板 216,且
        测量确已发生(reqheight 被咨询过)。"""
        seen = self._build(monkeypatch, 100)
        assert seen["height"] == 216                    # 地板守住(直出)
        assert ("update_idletasks", None) in tk_stub    # 测量发生(直出)


class TestMeasureBeforeSlideSourceOrder:
    """i10(形态):源码行序——测量(update_idletasks)在滑入(slide)之前。"""

    def test_i10_measure_precedes_slide_in_source(self):
        """i10:build_window 源码内 update_idletasks() 出现于 slide(
        定义之前(先排版后量尺再滑入);静态估算行不得是唯一 geometry
        尺寸来源。"""
        src = (ROOT / "deskpilot" / "approval_dialog.py").read_text(
            encoding="utf-8")
        body = src[src.index("def build_window"):]
        measure = body.find("update_idletasks()")
        slide = body.find("def slide(")
        assert measure != -1, "无 update_idletasks 实测——估算仍封顶"
        assert measure < slide, "实测晚于滑入——重设会被人看见"
