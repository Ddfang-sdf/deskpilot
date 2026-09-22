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


@pytest.fixture
def tk_stub(monkeypatch):
    """替身装配(ISS-0059 步骤14):_Recorder 类属性记账收编
    tests/faketk.install——实例 recorder+fixture 复位,消除借前序
    残留风险(ISS-0026 教训);观测口:geometries/idletasks/reqheight。"""
    import deskpilot.approval_dialog as ad
    from .faketk import install
    return install(monkeypatch, ad.tk, screen=(1920, 1080))


class TestMeasuredHeightPlacement:
    """i08/i09:实测高进几何与落位;静态估算只做地板。"""

    def _build(self, monkeypatch, tk_stub, reqh: int):
        import deskpilot.approval_dialog as ad
        tk_stub.reqheight = reqh
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
        seen = self._build(monkeypatch, tk_stub, 600)
        assert seen["height"] == 600                    # 落位实收(直出)
        geos = tk_stub.geometries                       # 几何记录(直出)
        assert "480x600+1424+1080" in geos              # 重设入几何(直出)

    def test_i09_short_content_floor_no_collapse(self, tk_stub, monkeypatch):
        """i09:短正文(reqheight=100 < 地板 216)→ 窗高=地板 216,且
        测量确已发生(reqheight 被咨询过)。"""
        seen = self._build(monkeypatch, tk_stub, 100)
        assert seen["height"] == 216                    # 地板守住(直出)
        assert tk_stub.idletasks >= 1                   # 测量发生(直出)


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
