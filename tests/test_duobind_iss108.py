"""ISS-0108 9420 双绑潜伏修复测试(TC-108-01/02,问题单 §3 改法)。

背景:HTTPServer 默认 allow_reuse_address=1,Windows 下 SO_REUSEADDR
允许同址双绑(§3 会话内实证成功)——daemon 持 9420 后第三方进程
(含 SO_REUSEADDR)可影子绑定,双属主潜伏路径坐实。改法=监听 socket
置 SO_EXCLUSIVEADDRUSE(Windows;非 Windows 保持默认)。

层级:TC-108-01 集成(真 socket 零 mock);TC-108-02 形态(源码直读)。
入口(设计):HttpDaemon.start(改造后监听 socket)/httpd.py 源码。
断言出处:第二 socket bind 的 OSError.winerror 直出/源码文本检索直读。

P1 红态预期:TC-108-01 红(现状第二 bind 成功,DID NOT RAISE);
TC-108-02 红(源码无 SO_EXCLUSIVEADDRUSE 设置点)。
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestExclusiveAddrUse:
    """TC-108-01/02:独占绑定封死同址双绑;非 Windows 路径不受影响。"""

    def test_tc108_01_rebind_with_reuseaddr_rejected(self, ctx):
        """TC-108-01(集成,真 socket 零 mock):改造后 HttpDaemon 持临时
        端口监听 → 第二 socket 以 SO_REUSEADDR 绑同址 → 必须 OSError
        (独占绑定下 Windows 报 WSAEACCES 10013,实盘直读)。
        断言:异常 winerror 直出。红态:现状可双绑(DID NOT RAISE)。"""
        from deskpilot.httpd import HttpDaemon

        if sys.platform != "win32":
            pytest.skip("SO_EXCLUSIVEADDRUSE 为 Windows 语义")
        d = HttpDaemon(ctx, host="127.0.0.1", port=0)
        d.start()
        try:
            intruder = socket.socket()
            intruder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                with pytest.raises(OSError) as ei:
                    intruder.bind(("127.0.0.1", d.port))
                # 实证:独占绑定下同址再绑被拒,Windows 报 WSAEACCES(10013)
                assert ei.value.winerror == 10013, \
                    f"双绑拒绝码须为 WSAEACCES 10013(直出): {ei.value!r}"
            finally:
                intruder.close()
        finally:
            d.stop()

    def test_tc108_02_exclusive_guard_windows_only(self):
        """TC-108-02(形态):SO_EXCLUSIVEADDRUSE 设置点存在且收在
        sys.platform win32 分支内(非 Windows 平台语义不受影响)。
        断言:源码文本检索直读。红态:设置点缺失。"""
        src = (ROOT / "deskpilot" / "httpd.py").read_text(encoding="utf-8")
        assert "SO_EXCLUSIVEADDRUSE" in src, "独占绑定设置点缺失(直读)"
        lines = src.splitlines()
        for i, line in enumerate(lines):
            if "SO_EXCLUSIVEADDRUSE" not in line:
                continue
            # setsockopt 调用可跨行:回看窗口须同时见 setsockopt 与 win32 守卫
            window = "\n".join(lines[max(0, i - 5): i + 1])
            if "setsockopt" not in window:
                continue                        # docstring/注释提及,跳过
            assert 'sys.platform == "win32"' in window, \
                "SO_EXCLUSIVEADDRUSE 未收进 win32 平台分支(直读)"
            return
        raise AssertionError("SO_EXCLUSIVEADDRUSE 的 setsockopt 调用未找到(直读)")
