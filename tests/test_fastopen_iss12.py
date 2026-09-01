"""ISS-0012 管理窗口提速批次测试（TC-FAST-01~04,2026-09-01 评审通过）。

层级：端点=集成（真实 HTTP 响应体直出）；渲染/暖源=单元（替身/注入直出）。
入口（设计）：httpd GET /whitelist / whitelist_window.build_window(display_map) /
appnames.warm_caches。
"""

from __future__ import annotations

import json
import time
import urllib.request

import pytest
import yaml


class TestEndpointDisplayFields:
    """TC-FAST-01:GET /whitelist 每条带 display/desc 字段(集成,真实响应体直出)。"""

    @pytest.fixture
    def daemon(self, policy, bindings, approvals, estop, executor, audit_log,
               tmp_path):
        from deskpilot.enforcement import Enforcement
        from deskpilot.httpd import HttpDaemon
        from deskpilot.tools import ToolContext
        from deskpilot.whitelist_admin import WhitelistAdmin

        p = tmp_path / "policy.yml"
        p.write_text(yaml.safe_dump({"whitelist": [{"process": "notepad.exe"}]}),
                     encoding="utf-8")
        a = WhitelistAdmin(str(p), {"notepad.exe": "L2"})
        enf = Enforcement(policy, bindings, approvals, estop, executor,
                          audit_log, whitelist_admin=a)
        ctx = ToolContext(policy=policy, enforcement=enf, bindings=bindings,
                          executor=executor, audit=audit_log)
        d = HttpDaemon(ctx, port=0, whitelist_admin=a)
        d.start()
        yield d
        d.stop()

    def test_entries_have_display_and_desc(self, daemon):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{daemon.port}/whitelist", timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        item = body["data"]["static"][0]
        assert item["process"] == "notepad.exe"
        assert item["level"] == "L2"
        assert item["display"]                              # 非空显示名(直出)
        assert "desc" in item                               # 描述字段存在(直出)


class TestManagerZeroResolve:
    """TC-FAST-02/03:端点带 display_map 时管理窗口零解析且 ≤300ms 渲染。
    断言:appnames 调用计数与渲染耗时(直出)。"""

    def _fake_tk(self, monkeypatch, ww):
        class W:
            def __init__(self, *a, **k): pass
            def pack(self, *a, **k): pass
            def pack_forget(self): pass
            def bind(self, *a, **k): pass
            def bind_all(self, *a, **k): pass
            def config(self, *a, **k): pass
            def configure(self, *a, **k): pass
            def title(self, *a): pass
            def geometry(self, *a): pass
            def minsize(self, *a): pass
            def attributes(self, *a, **k): pass
            def after(self, *a, **k): return "a1"
            def create_window(self, *a, **k): return 1
            def itemconfig(self, *a, **k): pass
            def bbox(self, *a, **k): return (0, 0, 0, 0)
            def yview(self, *a, **k): pass
            def yview_scroll(self, *a, **k): pass
            def winfo_children(self): return []
            def destroy(self): pass
            def get(self): return ""
            def create_line(self, *a, **k): pass
            def create_oval(self, *a, **k): pass
            def create_rectangle(self, *a, **k): pass
            def delete(self, *a, **k): pass

        for cls in ("Toplevel", "Frame", "Canvas", "Scrollbar", "Label",
                    "Button", "Entry"):
            monkeypatch.setattr(ww.tk, cls, lambda *a, **k: W(*a, **k))

    def test_zero_appnames_calls_with_display_map(self, monkeypatch):
        """TC-FAST-02:display_map 存在时 app_display_name/app_description 零调用。"""
        import deskpilot.whitelist_window as ww
        import deskpilot.appnames as an
        calls = []
        monkeypatch.setattr(an, "app_display_name",
                            lambda *a, **k: calls.append("name") or "x")
        monkeypatch.setattr(an, "app_description",
                            lambda *a, **k: calls.append("desc") or "x")
        self._fake_tk(monkeypatch, ww)
        entries = {"static": {"notepad.exe": "L2"}, "session": {}}
        dmap = {"notepad.exe": ("记事本", "文本编辑器")}
        ww.build_window(object(), entries, on_remove=lambda p: None,
                        on_clear_session=lambda: None, display_map=dmap)
        assert calls == []                                  # 零解析(直出)

    def test_render_bounded_300ms(self, monkeypatch):
        """TC-FAST-03:display_map 注入下建窗渲染 ≤300ms。"""
        import deskpilot.whitelist_window as ww
        self._fake_tk(monkeypatch, ww)
        entries = {"static": {f"notepad.exe": "L2"}, "session": {}}
        dmap = {"notepad.exe": ("记事本", "文本编辑器")}
        t0 = time.monotonic()
        ww.build_window(object(), entries, on_remove=lambda p: None,
                        on_clear_session=lambda: None, display_map=dmap)
        assert time.monotonic() - t0 < 0.3                  # 上界(直出)


class TestParallelWarm:
    """TC-FAST-04:daemon 启动并行暖源,wall < 串行一半。
    断言:耗时(clock 直出)。"""

    def test_parallel_faster_than_serial(self, monkeypatch):
        from deskpilot import appnames
        for name in ("_package_index", "_startapps_map", "_start_menu_map",
                     "_uninstall_map"):
            monkeypatch.setattr(appnames, name,
                                lambda *a, _n=name, **k: time.sleep(0.1) or {})
        t0 = time.monotonic()
        appnames.warm_caches(parallel=True)
        elapsed = time.monotonic() - t0
        assert elapsed < 0.2                                # 4×0.1 并行≈0.1(直出)
