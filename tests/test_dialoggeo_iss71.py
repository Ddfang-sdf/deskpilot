"""ISS-0071 白名单浮窗统一落位几何测试(TC-71-01~06 落地映射,g01~g08)。

层级:全部单元(Tk 替身先例 test_fastopen_iss12;纯函数直出;形态扫描)。
入口(设计):monitors.toast_placement(统一落位单源)/
whitelist_window._resolve_geo(白名单浮窗几何决策)/build_revoke_confirm/
build_enroll_confirm/build_enroll_notice(建窗公开入口)/DialogRevokeChannel.request
(通道装配面)。

断言出处:落位三元组=函数返回值直出;geometry 字符串=Tk 替身记录直出;
通道 payload=假 DialogService 捕获直出;形态=源码文本直读。

TC 映射:g01/g02/g03=TC-71-01/02/04(纯函数);g04/g05=TC-71-01/03(建窗
几何行为);g06=TC-71-06(形态扫描);g07=主屏回退(单据 §3 不能定位退主屏);
g08=通道把被裁决对象所在屏送进弹窗载荷(§3 跟随语义的数据源)。
TC-71-05(审批/冻结像素不动)由 test_m3.py 既有精确值钉+全量回归覆盖。

红态预期(现状):g04/g05 TypeError(builders 无 target_screen 形参);
g06 winfo_screenwidth 仍在;g08 TypeError(channel 无 resolve_screen 形参);
g01/g02/g03/g07 红期即绿(新公共 helper 的数学契约钉)。
"""

from __future__ import annotations

import pytest

from deskpilot.monitors import toast_placement

import deskpilot.whitelist_window as ww

SECOND = {"rect": (1920, -1, 3840, 1079), "work_area": (1920, -1, 3840, 1031),
          "is_primary": False}
PRIMARY = {"rect": (0, 0, 1920, 1080), "work_area": (0, 0, 1920, 1080),
           "is_primary": True}


class TestToastPlacementHome:
    """g01~g03:统一落位纯函数契约(目标屏右下角;负坐标/非原点布局正确)。"""

    def test_g01_single_screen_right_bottom(self):
        """g01(TC-71-01):单屏 → 主屏右下角,与审批弹窗同公式。
        红期即绿(helper 数学钉)。"""
        x, y_start, y_final = toast_placement(PRIMARY, 420, 130)
        assert (x, y_final) == (1920 - 420 - 16, 1080 - 130 - 48 - 16)
        assert y_start == 1080                  # 滑入起点在底缘外侧

    def test_g02_second_screen_follow(self):
        """g02(TC-71-02):目标屏=副屏 → 落副屏右下角(窗口矩形⊆副屏)。
        红期即绿(helper 数学钉)。"""
        x, _ys, y_final = toast_placement(SECOND, 420, 130)
        assert (x, y_final) == (3840 - 420 - 16, 1031 - 130 - 48 - 16)
        assert 1920 <= x and x + 420 <= 3840    # 横含副屏内(直出)
        assert -1 <= y_final and y_final + 130 <= 1079

    def test_g03_negative_coord_screen(self):
        """g03(TC-71-04):主屏非原点/负坐标屏(副屏在主屏左侧)——
        按屏矩形算,不吃 winfo 主屏宽度公式的亏。红期即绿。"""
        left = {"rect": (-1920, 0, 0, 1080), "work_area": (-1920, 0, 0, 1080)}
        x, _ys, y_final = toast_placement(left, 420, 130)
        assert (x, y_final) == (0 - 420 - 16, 1080 - 130 - 48 - 16)
        assert -1920 <= x and x + 420 <= 0      # 横含左屏内(直出)


class TestBuilderGeometry:
    """g04/g05:两个白名单浮窗建窗走统一落位(Tk 替身记录 geometry)。"""

    def _stub_tk(self, monkeypatch, rec):
        class W:
            def __init__(self, *a, **k): pass
            def geometry(self, s): rec.append(s)

            def __getattr__(self, name):
                if name.startswith("__"):
                    raise AttributeError(name)
                return lambda *a, **k: None   # 其余 Tk 方法全沉默替身

        for cls in ("Toplevel", "Frame", "Label", "Button"):
            monkeypatch.setattr(ww.tk, cls, W)

    def test_g04_revoke_confirm_follows_target_screen(self, monkeypatch,
                                                      tmp_path):
        """g04(TC-71-01/02 行为面):撤回确认窗(人类裁决面)落目标屏右下。
        红态(现状):build_revoke_confirm 无 target_screen 形参 → TypeError;
        且公式为主屏右上角硬编码。"""
        rec: list[str] = []
        self._stub_tk(monkeypatch, rec)
        ww.build_revoke_confirm(object(), "x.exe", tmp_path / "r.result", 15,
                                target_screen=SECOND)
        assert rec[-1] == "420x130+3404+837"    # 替身记录直出(副屏右下)

    def test_g05_enroll_notice_same_anchor(self, monkeypatch):
        """g05(TC-71-03):入白回执 toast 与确认窗同屏同锚点(右下角)。
        红态(现状):无 target_screen 形参+主屏右上角硬编码。"""
        rec: list[str] = []
        self._stub_tk(monkeypatch, rec)
        ww.build_enroll_notice(object(), "x.exe", on_undo=lambda: None,
                               target_screen=SECOND)
        assert rec[-1] == "420x48+3404+919"     # 替身记录直出(副屏右下)


class TestFallbackAndForm:
    """g06/g07:主屏回退(不能定位时)+ 形态扫描(winfo 公式清零)。"""

    def test_g06_no_winfo_screenwidth_placement(self):
        """g06(TC-71-06,形态):whitelist_window 不再用 winfo_screenwidth
        做落位计算。红态(现状):两处硬编码仍在(:566/:642)。"""
        from pathlib import Path
        src = (Path(ww.__file__)).read_text(encoding="utf-8")
        assert "winfo_screenwidth" not in src   # 源码文本直读

    def test_g07_none_screen_falls_back_to_primary(self, monkeypatch):
        """g07(§3 回退语义):不能定位被裁决对象 → 主屏右下角
        (is_primary 优先,非列表首项碰巧)。红期即绿(helper 钉)。"""
        fake = [dict(SECOND), dict(PRIMARY)]    # 主屏不在首项
        monkeypatch.setattr(ww, "enum_monitors", lambda: fake)
        assert ww._resolve_geo(420, 130, None) == "420x130+1484+886"


class TestChannelCarriesScreen:
    """g08:撤回通道把「被裁决对象所在屏」解析进弹窗载荷。"""

    def test_g08_channel_resolves_target_screen(self, tmp_path):
        """g08(单元,§3 跟随语义数据源):DialogRevokeChannel 装配
        resolve_screen 后,show 载荷带 target_screen;解析失败回 None
        (builder 端退主屏)。超时默认保留语义不变(既有)。
        红态(现状):channel 无 resolve_screen 形参 → TypeError。"""
        class _DS:
            def __init__(self): self.shows = []
            def show(self, kind, payload): self.shows.append((kind, payload))

        ds = _DS()
        ch = ww.DialogRevokeChannel(ds, timeout=0.2,
                                    result_root=str(tmp_path),
                                    resolve_screen=lambda proc: SECOND)
        r = ch.request("x.exe")
        assert r == "keep"                      # 超时默认保留(既有语义直出)
        kind, payload = ds.shows[0]
        assert kind == "revoke"
        assert payload["target_screen"] == SECOND   # 载荷直出
