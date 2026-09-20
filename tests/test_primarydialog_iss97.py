"""ISS-0097 弹窗一律主屏右下角测试(pr01~pr04,问题单 §4)。

层级:单元(纯函数/桩;允许打桩)。
入口(设计):approval_ui._screen_of_target / freeze_notify._mouse_screen /
whitelist_window._resolve_geo / DialogRevokeChannel.request——弹窗落位决议面。
断言出处:返回值/载荷直出;几何字符串直出。

红态预期(现状):pr01/pr02 红(跟随目标屏/鼠标屏,传副屏得副屏);
pr03 红(_resolve_geo 跟 target_screen);pr04 红(通道载荷带 target_screen)。
"""

from __future__ import annotations

import deskpilot.whitelist_window as ww
from deskpilot.monitors import toast_placement

SECOND = {"rect": (1920, -1, 3840, 1079),
          "work_area": (1920, -1, 3840, 1031), "is_primary": False}
PRIMARY = {"rect": (0, 0, 1920, 1080), "work_area": (0, 0, 1920, 1080),
           "is_primary": True}


def _primary():
    from deskpilot.monitors import enum_monitors
    mons = enum_monitors()
    return next((m for m in mons if m.get("is_primary")),
                mons[0] if mons else None)


class TestApprovalAlwaysPrimary:
    """pr01/pr02:审批/冻结的落屏决议恒主屏(裁定:不额外判断)。"""

    def test_pr01_approval_ignores_target_screen(self):
        """pr01:_screen_of_target 传副屏矩形也恒返主屏。
        红态(现状):screen_of_rect 命中副屏 → 返回副屏。"""
        from deskpilot.approval_ui import TkApprovalChannel
        mon = TkApprovalChannel._screen_of_target(
            (2000, 100, 3600, 900))            # 副屏上的矩形
        assert mon is not None
        assert mon["is_primary"] is True        # 恒主屏(直出)

    def test_pr02_freeze_ignores_mouse_screen(self, monkeypatch):
        """pr02:_mouse_screen 即使鼠标在副屏也恒主屏。
        红态(现状):返回鼠标所在屏。"""
        import pyautogui

        class _Pos:
            x, y = 3000, 500                    # 副屏上的鼠标

        monkeypatch.setattr(pyautogui, "position", lambda: _Pos())
        from deskpilot.freeze_notify import FreezeNotifier
        mon = FreezeNotifier._mouse_screen()    # 类静态方法(公开面)
        assert mon is not None
        assert mon["is_primary"] is True        # 恒主屏(直出)


class TestWhitelistAlwaysPrimary:
    """pr03/pr04:白名单浮窗恒主屏右下;通道不再携带屏解析。"""

    def test_pr03_resolve_geo_ignores_target_screen(self):
        """pr03:_resolve_geo(target_screen=副屏) 仍给主屏右下几何。
        红态(现状):按副屏算。"""
        geo = ww._resolve_geo(420, 130, SECOND)
        exp_x, _ys, exp_y = toast_placement(PRIMARY, 420, 130)
        assert geo == f"420x130+{exp_x}+{exp_y}"  # 主屏公式值(直出)
        bad_x, _b, bad_y = toast_placement(SECOND, 420, 130)
        assert geo != f"420x130+{bad_x}+{bad_y}"  # 不是副屏

    def test_pr04_channel_carries_no_screen(self, tmp_path):
        """pr04:撤回通道载荷不再带 target_screen(裁定:不额外判断)。
        红态(现状):载荷带 target_screen 键。"""
        class _DS:
            def __init__(self):
                self.shows = []

            def show(self, kind, payload):
                self.shows.append((kind, payload))

        ds = _DS()
        ch = ww.DialogRevokeChannel(ds, timeout=0.2,
                                    result_root=str(tmp_path))
        r = ch.request("x.exe")
        assert r == "keep"                        # 超时默认保留(既有语义)
        _kind, payload = ds.shows[0]
        assert "target_screen" not in payload     # 载荷无屏字段(直出)
