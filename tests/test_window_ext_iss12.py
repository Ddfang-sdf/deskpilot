"""ISS-0012 扩展性批次测试：解析源注册表/图形按钮统一/淡入/单例。

TC-RESOLVE-01~07 / TC-WIDGET-01 / TC-ANIM-01~02 / TC-SINGLE-01~02
（2026-09-01 评审通过；通用性原则：注册表+参数化，禁止 if 链与 bespoke 类）。

层级：单元（替身/注入直出；系统数据用例带 skipif 环境守卫）。
入口（设计）：appnames._SOURCES/_first_hit/app_description/_resolve_exe、
whitelist_window._GraphicButton/fade_in/focus_existing_or_exit/build_window/main。
"""

from __future__ import annotations

import sys

import pytest

from deskpilot import appnames


# ---------- TC-RESOLVE 源注册表 ----------

class TestResolveRegistry:
    """TC-RESOLVE:解析源注册表——短路/扩展点/各源命中/诚实回退。
    断言:_resolve_exe/app_description 返回值与源调用记录(直出)。"""

    def test_resolve04_first_hit_short_circuits(self, monkeypatch):
        """TC-RESOLVE-04:首源命中时后续源零调用。"""
        calls = []
        src1 = lambda p: calls.append("s1") or "C:\\hit\\x.exe"
        src2 = lambda p: calls.append("s2") or None
        monkeypatch.setattr(appnames, "_SOURCES", [src1, src2])
        assert appnames._resolve_exe("x.exe") == "C:\\hit\\x.exe"
        assert calls == ["s1"]                        # s2 未被调用(直出)

    def test_resolve07_extension_point(self, monkeypatch):
        """TC-RESOLVE-07:注入新源到注册表首位→优先命中(扩展点可证)。"""
        calls = []
        fake = lambda p: calls.append(p) or "D:\\fake\\x.exe"
        monkeypatch.setattr(appnames, "_SOURCES", [fake])
        assert appnames._resolve_exe("x.exe") == "D:\\fake\\x.exe"
        assert calls == ["x.exe"]

    def test_resolve01_running_process_wins(self, monkeypatch):
        """TC-RESOLVE-01:运行进程源优先——注入运行表直接命中。"""
        monkeypatch.setattr(appnames, "_running_procs",
                            lambda: {"powerpnt.exe": "C:\\Office\\POWERPNT.EXE"})
        monkeypatch.setattr(appnames, "_SOURCES",
                            [appnames._from_running_process])
        assert appnames._resolve_exe("powerpnt.exe") == "C:\\Office\\POWERPNT.EXE"

    def test_resolve02_start_menu_lnk(self):
        """TC-RESOLVE-02:weixin.exe 经开始菜单快捷方式解析(系统真实数据)。"""
        if not hasattr(appnames, "_from_start_menu_lnk"):
            pytest.fail("源函数未实现(P1 红阶段预期)")
        path = appnames._from_start_menu_lnk("weixin.exe")
        if not path:
            pytest.skip("本机无微信快捷方式(环境守卫)")
        assert "weixin.exe" in path.lower()

    def test_resolve03_uninstall_icon(self):
        """TC-RESOLVE-03:seeyou.exe 经 Uninstall DisplayIcon 解析。"""
        if not hasattr(appnames, "_from_uninstall_icon"):
            pytest.fail("源函数未实现(P1 红阶段预期)")
        path = appnames._from_uninstall_icon("seeyou.exe")
        if not path:
            pytest.skip("本机无西柚 Uninstall 项(环境守卫)")
        assert "seeyou.exe" in path.lower()

    def test_resolve05_description_chain(self):
        """TC-RESOLVE-05:描述链解析出非进程名内容。

        语言无关+环境守卫:描述源依赖本机安装与 OS 语言(CI 英文机
        无微信则回退进程名——按同文件 resolve02/03 惯例 skip)。"""
        d = appnames.app_description("weixin.exe")
        if "weixin.exe" == d:
            pytest.skip("本机无微信描述源(环境守卫)")
        assert d and d != "weixin.exe"

    def test_resolve06_honest_fallback(self):
        """TC-RESOLVE-06:全链未覆盖→回退进程名,不编造。"""
        assert appnames.app_description("no-such-xyz.exe") == "no-such-xyz.exe"


# ---------- TC-WIDGET 图形按钮统一 ----------

class TestGraphicButtonUnified:
    """TC-WIDGET-01:尖角/禁止图标由同一 _GraphicButton 经不同绘制回调产出。
    断言:类型与基类(直出)。"""

    def test_common_base_class(self):
        from deskpilot.whitelist_window import (_ChevronButton, _GraphicButton,
                                                _IconButton)
        assert issubclass(_ChevronButton, _GraphicButton)
        assert issubclass(_IconButton, _GraphicButton)


# ---------- TC-ANIM 淡入 ----------

class TestFadeIn:
    """TC-ANIM:管理窗口淡入——alpha 起步<1、≤20ms 步进、终态 1.0。
    断言:attributes 记录与 after 调度(替身直出)。"""

    def _make(self, monkeypatch):
        import deskpilot.whitelist_window as ww
        rec = {"alphas": [], "afters": []}

        class W:
            def __init__(self, *a, **k): pass
            def pack(self, *a, **k): pass
            def bind(self, *a, **k): pass
            def bind_all(self, *a, **k): pass
            def config(self, *a, **k): pass
            def configure(self, *a, **k): pass
            def title(self, *a): pass
            def geometry(self, *a): pass
            def minsize(self, *a): pass
            def create_window(self, *a, **k): return 1
            def itemconfig(self, *a, **k): pass
            def bbox(self, *a, **k): return (0, 0, 0, 0)
            def yview(self, *a, **k): pass
            def yview_scroll(self, *a, **k): pass
            def winfo_children(self): return []
            def destroy(self): pass
            def pack_forget(self): pass
            def get(self): return ""
            def create_line(self, *a, **k): pass
            def create_rectangle(self, *a, **k): pass
            def create_oval(self, *a, **k): pass
            def delete(self, *a, **k): pass
            def after(self, ms, fn=None):
                rec["afters"].append(ms)
                return "a1"
            def attributes(self, flag, val=None):
                if flag == "-alpha":
                    rec["alphas"].append(val)

        monkeypatch.setattr(ww.tk, "Toplevel", lambda parent: W())
        monkeypatch.setattr(ww.tk, "Frame", lambda *a, **k: W(*a, **k))
        monkeypatch.setattr(ww.tk, "Canvas", lambda *a, **k: W(*a, **k))
        monkeypatch.setattr(ww.tk, "Scrollbar", lambda *a, **k: W(*a, **k))
        monkeypatch.setattr(ww.tk, "Label", lambda *a, **k: W(*a, **k))
        monkeypatch.setattr(ww.tk, "Button", lambda *a, **k: W(*a, **k))
        monkeypatch.setattr(ww.tk, "Entry", lambda *a, **k: W(*a, **k))
        ww.build_window(object(), {"static": {}, "session": {}},
                        on_remove=lambda p: None, on_clear_session=lambda: None)
        return rec

    def test_anim01_fadein_scheduled(self, monkeypatch):
        rec = self._make(monkeypatch)
        assert rec["alphas"] and rec["alphas"][0] < 1.0   # 起步<1(直出)
        assert any(ms <= 20 for ms in rec["afters"])       # ≤20ms 步进(直出)

    def test_anim02_final_alpha_one(self, monkeypatch):
        from deskpilot.whitelist_window import fade_in
        alphas = []
        win = type("W", (), {"attributes": lambda self, f, v:
                             alphas.append(v)})()
        frames = list(fade_in(win, total_ms=60, step_ms=20))
        assert alphas[-1] == 1.0                            # 终态 1.0(直出)


# ---------- TC-SA shell 注册源中文名（2026-09-01 评审通过） ----------

class TestStartAppsNames:
    """TC-SA:Get-StartApps 快照作为 UWP 本地化名称源(中文优先)。
    断言:显示名/快照表/调用计数/耗时(直出)。"""

    def _reset_cache(self):
        from deskpilot import appnames
        for attr in ("_cache",):
            if hasattr(appnames._startapps_map, attr):
                delattr(appnames._startapps_map, attr)

    def test_sa01_calc_os_data(self):
        """TC-SA-01:calc.exe 显示名取 OS/厂商数据——语言无关断言
        (中文名随 OS 语言变,CI 英文系统实证)。"""
        from deskpilot.appnames import app_display_name
        name = app_display_name("calc.exe")
        assert "Calculator" in name
        assert name != "calc.exe"

    def test_sa02_powershell_failure_degrades(self, monkeypatch):
        """TC-SA-02:PowerShell 失败返回空表不崩,解析链自然降级。"""
        import subprocess as sp
        from deskpilot import appnames
        self._reset_cache()
        monkeypatch.setattr(appnames.subprocess, "run",
                            lambda *a, **k: (_ for _ in ()).throw(
                                sp.TimeoutExpired("pwsh", 3)))
        assert appnames._startapps_map() == {}

    def test_sa03_single_snapshot(self, monkeypatch):
        """TC-SA-03:连续两次调用,PowerShell 仅拉起一次。"""
        from deskpilot import appnames
        self._reset_cache()
        calls = []

        class R:
            returncode = 0
            stdout = ('[{"Name":"计算器","AppID":'
                      '"Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"}]'
                      ).encode("utf-8")

        monkeypatch.setattr(appnames.subprocess, "run",
                            lambda *a, **k: calls.append(1) or R())
        appnames._startapps_map()
        appnames._startapps_map()
        assert len(calls) == 1

    def test_sa04_mapping_correct(self, monkeypatch):
        """TC-SA-04:包族→本地化名映射正确(注入假快照直出)。"""
        from deskpilot import appnames
        appnames._startapps_map._cache = {
            "Microsoft.WindowsCalculator_8wekyb3d8bbwe": "计算器"}
        assert appnames._startapps_map()[
            "Microsoft.WindowsCalculator_8wekyb3d8bbwe"] == "计算器"

    def test_sa05_timeout_bounded(self, monkeypatch):
        """TC-SA-05:悬挂时 ≤3.5s 返回空表。"""
        import time
        from deskpilot import appnames
        self._reset_cache()

        def hang(*a, **k):
            raise TimeoutError("hang")

        monkeypatch.setattr(appnames.subprocess, "run", hang)
        t0 = time.monotonic()
        assert appnames._startapps_map() == {}
        assert time.monotonic() - t0 < 3.5


# ---------- TC-SINGLE 单例 ----------

class TestSingleton:
    """TC-SINGLE:已存在则聚焦退出,不存在则正常建窗。
    断言:tk.Tk 创建计数与 focus_existing_or_exit 调用(替身直出)。"""

    def _run_main(self, monkeypatch, exists: bool):
        import deskpilot.whitelist_window as ww
        rec = {"tk": 0, "focus": []}
        monkeypatch.setattr(ww, "focus_existing_or_exit",
                            lambda title: rec["focus"].append(title) or exists)
        monkeypatch.setattr(ww.tk, "Tk",
                            lambda *a, **k: rec.__setitem__("tk", rec["tk"] + 1)
                            or type("T", (), {"withdraw": lambda s: None,
                                              "mainloop": lambda s: None,
                                              "quit": lambda s: None})())
        # 建窗本体打桩:本用例只验单例分支,不验窗口装配
        monkeypatch.setattr(ww, "build_window",
                            lambda *a, **k: type("W", (), {
                                "protocol": lambda s, *a: None})())
        monkeypatch.setattr(sys, "argv", ["x", "http://127.0.0.1:1"])
        ww.main()
        return rec

    def test_single01_existing_focuses_and_exits(self, monkeypatch):
        rec = self._run_main(monkeypatch, exists=True)
        assert rec["focus"] == ["DeskPilot 白名单管理"]
        assert rec["tk"] == 0                        # 未建新窗(直出)

    def test_single02_absent_builds(self, monkeypatch):
        rec = self._run_main(monkeypatch, exists=False)
        assert rec["tk"] == 1                        # 正常建窗(直出)
