"""ISS-0096 屏号确定性重排测试(sc01~sc04,问题单 §4)。

层级:sc01~sc03 单元(mss 替身+_win32_info 缝替身,允许打桩,断言在
enum_monitors 返回清单直出);sc04 形态(注册表描述直读)。
入口(设计):monitors.enum_monitors(屏号唯一来源)/TOOL_SCHEMAS。

红态预期(现状):sc01~sc03 红(枚举序=OS 驱动序,主屏不优先);
sc04 红(描述无屏号语义)。
"""

from __future__ import annotations

import sys

import pytest

import deskpilot.monitors as mon
from deskpilot.mcp_server import TOOL_SCHEMAS


class _Sct:
    """mss 替身:MSS().monitors[0] 为虚拟聚合(跳过),后接物理屏。"""

    def __init__(self, mons):
        self.monitors = [None] + mons

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeMss:
    def __init__(self, mons):
        self._mons = mons

    def MSS(self):
        return _Sct(self._mons)


def _m(left, top, w, h):
    return {"left": left, "top": top, "width": w, "height": h}


def _info(*entries):
    """rect → (work_area, is_primary) 映射替身。"""
    return {rect: (wa, pri) for rect, wa, pri in entries}


class TestDeterministicScreenOrder:
    """sc01~sc03:主屏优先 + 其余从左到右(屏号语义可预知)。"""

    def test_sc01_primary_first(self, monkeypatch):
        """sc01(单元,本机事故镜像):mss 序=[右(非主),左(主)] →
        重排后 [0]=主屏(左)。红态:原样返回,[0]=右屏。"""
        right = (1920, -1, 3840, 1079)
        left = (0, 0, 1920, 1080)
        monkeypatch.setitem(sys.modules, "mss",
                            _FakeMss([_m(1920, -1, 1920, 1080),
                                      _m(0, 0, 1920, 1080)]))
        monkeypatch.setattr(mon, "_win32_info", lambda: _info(
            (right, right, False), (left, left, True)))
        mons = mon.enum_monitors()
        assert mons[0]["is_primary"] is True        # 主屏第一(直出)
        assert mons[0]["rect"] == left              # 左屏(主)在 0 号位
        assert mons[1]["rect"] == right

    def test_sc02_rest_left_to_right(self, monkeypatch):
        """sc02(单元):主屏居中(x=0)、左屏 x=-1920、右屏 x=1920,
        mss 序打乱 → 重排=[主屏, 左, 右](主屏优先+其余按左缘升序)。"""
        mid, left, right = (0, 0, 1920, 1080), (-1920, 0, 0, 1080), \
            (1920, 0, 3840, 1080)
        monkeypatch.setitem(sys.modules, "mss", _FakeMss(
            [_m(1920, 0, 1920, 1080), _m(0, 0, 1920, 1080),
             _m(-1920, 0, 1920, 1080)]))
        monkeypatch.setattr(mon, "_win32_info", lambda: _info(
            (mid, mid, True), (left, left, False), (right, right, False)))
        rects = [m["rect"] for m in mon.enum_monitors()]
        assert rects == [mid, left, right]          # 序直出

    def test_sc03_same_left_orders_by_top(self, monkeypatch):
        """sc03(单元):两非主屏同左缘(x=1920)不同上缘 → 上缘小者在前。"""
        pri = (0, 0, 1920, 1080)
        lo = (1920, 500, 3840, 1580)
        hi = (1920, 0, 3840, 1080)
        monkeypatch.setitem(sys.modules, "mss", _FakeMss(
            [_m(0, 0, 1920, 1080), _m(1920, 500, 1920, 1080),
             _m(1920, 0, 1920, 1080)]))
        monkeypatch.setattr(mon, "_win32_info", lambda: _info(
            (pri, pri, True), (lo, lo, False), (hi, hi, False)))
        rects = [m["rect"] for m in mon.enum_monitors()]
        assert rects == [pri, hi, lo]               # 同上缘升序(直出)


class TestDescriptionDeclaresOrder:
    """sc04:描述写明屏号语义(AI 不再靠猜)。"""

    def test_sc04_description_declares_primary_zero(self):
        """sc04(形态):screenshot 描述含「0=主屏」类屏号语义,≤200 闸门。
        红态(现状):只说「按屏号」,语义未声明。"""
        d = TOOL_SCHEMAS["screenshot"]["description"]
        assert "0=主屏" in d                        # 注册表直读
        assert len(d) <= 200
