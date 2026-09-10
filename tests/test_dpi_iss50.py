"""ISS-0050 DPI 感知形态可诊断单元测试。

入口:HttpDaemon /health(公开 HTTP 入口)、main._set_dpi_awareness /
main._startup_detail(模块级公开函数)。
断言值来源:HTTP 响应体字段、函数返回值——均直出,无中间转换。

测试设计(五要素):
- TC-50-01 场景=/health 暴露 dpi_mode;前提=临时端口 daemon 在线;
  步骤=GET /health;预期=200 且 dpi_mode ∈ {pmv2,v1,none};断言=响应体字段。
- TC-50-02 场景=V2 声明失败回退 V1;前提=替身 SetProcessDpiAwarenessContext
  返 0、SetProcessDPIAware 返 1;步骤=调 _set_dpi_awareness;预期=返回 "v1";
  断言=返回值直出。
- TC-50-03 场景=两级全败;前提=两级替身均抛 OSError;步骤=同上;
  预期=返回 "none";断言=返回值直出。
- TC-50-04 场景=启动审计明细含 DPI 形态;前提=模块已加载;
  步骤=_startup_detail("MCP stdio 就绪");预期=返回串含当前 _DPI_MODE;
  断言=返回值直出(与模块常量逐字比对)。
"""

from __future__ import annotations

import ctypes
import json
import urllib.request

import pytest

from deskpilot import main as main_mod
from deskpilot.httpd import HttpDaemon

# c_void_p.value 无符号回绕(ISS-0051 同形教训),替身比较同形化
_V1_VAL = ctypes.c_void_p(-2).value
_UNAWARE_VAL = ctypes.c_void_p(-1).value


class TestDpiModeDiagnosable:
    @pytest.fixture
    def daemon(self, ctx):
        d = HttpDaemon(ctx, host="127.0.0.1", port=0)
        d.start()
        yield d
        d.stop()

    def test_tc50_01_health_exposes_dpi_mode(self, daemon):
        with urllib.request.urlopen(f"http://127.0.0.1:{daemon.port}/health",
                                    timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200
        assert body["status"] == "ok"                      # 既有字段不动
        assert body["dpi_mode"] in ("pmv2", "pmv1", "v1", "unaware",
                                    "unknown")             # 新字段直出(查询制域)

    def test_tc50_02_fallback_v1(self, monkeypatch):
        """声明调用后查询=系统级上下文 → 如实报 v1(查询制)。"""
        monkeypatch.setattr(
            "ctypes.windll.user32.SetProcessDpiAwarenessContext",
            lambda *_a: 0)                                  # V2 声明失败
        monkeypatch.setattr(
            "ctypes.windll.user32.SetProcessDPIAware", lambda: 1)
        monkeypatch.setattr(
            "ctypes.windll.user32.GetThreadDpiAwarenessContext", lambda: 998)
        monkeypatch.setattr(
            "ctypes.windll.user32.AreDpiAwarenessContextsEqual",
            lambda a, b: getattr(b, "value", None) == _V1_VAL)  # 实为系统级
        assert main_mod._set_dpi_awareness() == "v1"

    def test_tc50_03_fallback_none(self, monkeypatch):
        """两级全败且查询=未感知上下文 → 如实报 unaware;查询本身失败 → unknown。"""
        def _boom(*_a):
            raise OSError("no dpi api")
        monkeypatch.setattr(
            "ctypes.windll.user32.SetProcessDpiAwarenessContext", _boom)
        monkeypatch.setattr(
            "ctypes.windll.user32.SetProcessDPIAware", _boom)
        monkeypatch.setattr(
            "ctypes.windll.user32.GetThreadDpiAwarenessContext", lambda: 997)
        monkeypatch.setattr(
            "ctypes.windll.user32.AreDpiAwarenessContextsEqual",
            lambda a, b: getattr(b, "value", None) == _UNAWARE_VAL)
        assert main_mod._set_dpi_awareness() == "unaware"
        monkeypatch.setattr(
            "ctypes.windll.user32.GetThreadDpiAwarenessContext", _boom)
        assert main_mod._set_dpi_awareness() == "unknown"

    def test_tc50_04_startup_detail_includes_mode(self):
        detail = main_mod._startup_detail("MCP stdio 就绪")
        assert "MCP stdio 就绪" in detail
        assert f"DPI={main_mod._DPI_MODE}" in detail
