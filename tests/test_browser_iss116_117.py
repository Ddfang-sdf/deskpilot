"""ISS-0116/0117 回归钉(browser_get_rect 坐标系与遮挡自检)。

TC-116-01:render_origin 取渲染件子窗口原点(非顶层窗口原点);
TC-116-02:渲染件缺失 → WINDOW_GONE fail-closed(不退回窗口原点);
TC-117-01:occluder 缝判同根(None)→ occluded=false、top_element 空;
TC-117-02:occluder 缝判异根(标题)→ occluded=true、rect 照给;
TC-117-03:occluder 缝收到目标 hwnd(UIA=int;CDP=注册表实例 hwnd)。
"""

from __future__ import annotations

import pytest

from deskpilot.errors import ExecutorError, WINDOW_GONE


class _Probe016:
    """DesktopProbe 替身:顶层窗与渲染件矩形刻意分离,钉死取值来源。"""

    def __init__(self, child=(100, 200, 900, 800)):
        self._child = child
        self.calls: list[tuple] = []

    def rect_of(self, hwnd):
        self.calls.append(("rect_of", hwnd))
        return (10, 20, 910, 900)            # 顶层窗原点(10,20)≠渲染件

    def child_rect_by_class(self, hwnd, class_name):
        self.calls.append(("child_rect_by_class", hwnd, class_name))
        return self._child


class TestIss116RenderOrigin:
    def test_tc01_origin_from_render_widget(self):
        """TC-116-01:render_origin() = 渲染件子窗口矩形原点(100,200),
        不得取顶层窗口原点(10,20);类名须为 Chrome_RenderWidgetHostHWND。
        红态:生产仍取 probe.rect_of 顶层窗原点。"""
        from deskpilot.browser.cdp import CdpChannel
        probe = _Probe016()
        ch = CdpChannel({"hwnd": 4242, "port": 1, "ws_path": "/x"},
                        probe=probe)
        assert ch.render_origin() == (100, 200), \
            f"渲染件原点(直出): {ch.render_origin()}"
        assert ("child_rect_by_class", 4242,
                "Chrome_RenderWidgetHostHWND") in probe.calls, \
            f"渲染件类名直查(直出): {probe.calls}"

    def test_tc02_widget_missing_fail_closed(self):
        """TC-116-02:渲染件子窗口缺失 → WINDOW_GONE fail-closed,
        绝不 silently 退回顶层窗口原点(那是 ISS-0116 病根)。
        红态:生产无此判定,直接返回窗口原点。"""
        from deskpilot.browser.cdp import CdpChannel
        ch = CdpChannel({"hwnd": 4242, "port": 1, "ws_path": "/x"},
                        probe=_Probe016(child=None))
        with pytest.raises(ExecutorError) as ei:
            ch.render_origin()
        assert ei.value.code == WINDOW_GONE, \
            f"code(直出): {ei.value.code}"


class TestIss117Occluder:
    def test_tc01_same_root_unoccluded(self):
        """TC-117-01:occluder 缝判同根(返 None)→ occluded=false、
        top_element 空串、rect 照给。红态:现缝 topmost 按标题比元素名,
        自家渲染件恒判遮挡。"""
        from deskpilot.browser.rect import browser_get_rect
        uia = _UiaDouble(rect=(10, 20, 110, 60))
        out = browser_get_rect(4242, name="登录", uia=uia,
                               occluder=lambda point, tgt: None)
        assert out["occluded"] is False, \
            f"occluded(直出): {out.get('occluded')}"
        assert out["top_element"] == "", \
            f"top_element(直出): {out.get('top_element')!r}"
        assert out["rect"] == [10, 20, 110, 60]

    def test_tc02_other_root_occluded(self):
        """TC-117-02:occluder 缝判异根(返遮挡者标题)→ occluded=true、
        top_element=遮挡者、rect 照给(判断归 AI)。红态:同 TC-117-01。"""
        from deskpilot.browser.rect import browser_get_rect
        out = browser_get_rect(
            4242, name="登录", uia=_UiaDouble(rect=(10, 20, 110, 60)),
            occluder=lambda point, tgt: "钉钉升级提示")
        assert out["occluded"] is True, \
            f"occluded(直出): {out.get('occluded')}"
        assert out["top_element"] == "钉钉升级提示", \
            f"top_element(直出): {out.get('top_element')!r}"
        assert out["rect"] == [10, 20, 110, 60], \
            f"遮挡时 rect 照给(直出): {out.get('rect')}"

    def test_tc03_target_hwnd_handed_to_occluder(self):
        """TC-117-03:遮挡判定须拿到目标 hwnd 做根归属比对——
        UIA 路由=传入窗口句柄本身;CDP 路由=注册表实例的 hwnd。
        红态:现缝只收 point,无 target 概念。"""
        from deskpilot.browser.rect import browser_get_rect
        seen: list = []
        browser_get_rect(4242, name="登录",
                         uia=_UiaDouble(rect=(10, 20, 110, 60)),
                         occluder=lambda point, tgt: seen.append(tgt) or None)
        assert seen == [4242], f"UIA 路由 target hwnd(直出): {seen}"

        seen.clear()
        browser_get_rect(777, name="登录",
                         cdp=_CdpDouble(box={"left": 1, "top": 2,
                                             "right": 5, "bottom": 6},
                                        origin=(10, 10), dpr=1.0),
                         occluder=lambda point, tgt: seen.append(tgt) or None)
        assert seen == [777], f"CDP 路由 target hwnd(直出): {seen}"


class _UiaDouble:
    """UIA 通道替身(最小面:rect_of/snapshot)。"""

    def __init__(self, rect=(10, 20, 110, 60)):
        self._rect = rect

    def snapshot(self, target):
        return {"elements": [], "meta": {}}

    def rect_of(self, target, name=None, control_type=None, index=None):
        return self._rect


class _CdpDouble:
    """CDP 通道替身(最小面:三因子定值)。"""

    def __init__(self, *, box, origin, dpr):
        self._box, self._origin, self._dpr = box, origin, dpr

    def snapshot(self, target):
        return {"elements": [], "meta": {}}

    def element_box(self, name=None, control_type=None, index=None):
        return self._box

    def render_origin(self):
        return self._origin

    def dpr(self):
        return self._dpr
