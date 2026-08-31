"""ISS-0013 生产弹窗全静默修复测试（问题单 §5.1 + 检查单 R1~R3）。

层级：单元（替身只允许在最末端可观察点：实例方法/窗口工厂/capsys，R2）。
五要素：各类 docstring 标注。
入口（§6/设计）：DialogService 默认装配 / 注入装配 / _dispatch 留痕 /
DialogRevokeChannel 真实装配接线。

红→绿：修复前默认构造的 DialogService 的 _factory 为 None，
_dispatch 调 NoneType 被静默吞掉（默认路径不触达任何工厂）。
"""

from __future__ import annotations

import time

import pytest

from deskpilot.dialog_service import DialogService
from deskpilot.whitelist_window import DialogRevokeChannel


class TestDefaultFactoryWired:
    """场景:R1/R3——生产默认构造(不注入工厂)必须触达真实默认工厂。
    断言:替身工厂收到的 (kind, payload)(直出);_factory 非 None(形态断言)。"""

    def test_default_construction_reaches_default_factory(self, monkeypatch):
        calls = []
        monkeypatch.setattr(DialogService, "_default_factory",
                            lambda self, kind, payload: calls.append(
                                (kind, payload)))
        ds = DialogService()                     # 生产默认装配:不注入工厂
        assert ds._factory is not None           # R3 形态断言(本缺陷根因点)
        ds._dispatch(("approval", {"description": "x"}, 0.0))
        assert calls == [("approval", {"description": "x"})]

    def test_injected_factory_not_overridden(self):
        """场景:注入 window_factory 时触达注入工厂而非默认(防 or 改坏注入语义)。
        断言:注入替身调用记录(直出)。"""
        calls = []
        ds = DialogService(window_factory=lambda kind, payload:
                           calls.append((kind, payload)))
        ds._dispatch(("freeze", {"audit_dir": "a"}, 0.0))
        assert calls == [("freeze", {"audit_dir": "a"})]


class TestSwallowLeavesTrace:
    """场景:通知层容错吞异常必须留痕(禁止吞错不留痕)。
    断言:capsys 捕获的 stderr 内容(直出);visible_latency 仍被设置(语义不变)。"""

    def test_dispatch_exception_prints_stderr(self, capsys):
        def boom(kind, payload):
            raise RuntimeError("工厂炸了")

        ds = DialogService(window_factory=boom)
        ds._dispatch(("approval", {}, 0.0))
        err = capsys.readouterr().err
        assert "工厂炸了" in err or "approval" in err
        assert ds.visible_latency_s >= 0.0       # 不阻断调用方语义不变


class TestRevokeChannelRealAssembly:
    """场景(R1/R2 自查补课):DialogRevokeChannel 配真实 DialogService,
    仅最末端 window_factory 记录 show 调用。
    断言:show 收到的 kind/payload(直出);超时默认 "keep"(fail-safe)。"""

    def test_request_dispatches_revoke_dialog(self, tmp_path):
        shown = []
        ds = DialogService(window_factory=lambda kind, payload:
                           shown.append((kind, payload)))
        ds.start()
        try:
            ch = DialogRevokeChannel(ds, timeout=0.5,
                                     result_root=str(tmp_path))
            r = ch.request("excel.exe")
        finally:
            ds.stop()
        assert shown and shown[0][0] == "revoke"
        assert shown[0][1]["process"] == "excel.exe"
        assert r == "keep"                        # 无人裁决超时按保留(fail-safe)
