"""ISS-0023 TOOL_TIMEOUT 重试指引测试(TC-RT-01~03,问题单 §4/§5 v0.2 评审通过)。

层级:TC-RT-01/02 单元(tool_timeout_payload 返回 dict 直出);
TC-RT-03 集成(真 HttpDaemon+慢 probe 接缝制造真实超时,断言在 HTTP 响应体)。
入口(设计):httpd.tool_timeout_payload(level) / 真 POST /call。
"""

from __future__ import annotations

import json
import time
import urllib.request

import pytest

from deskpilot import errors
from deskpilot.httpd import tool_timeout_payload


class TestPayloadUnit:
    """TC-RT-01/02:重试元数据按级别差异化(返回 dict 直出)。"""

    def test_rt01_budget_level_metadata(self):
        """TC-RT-01:L2 预算超时 → 500ms/3 次,四要素齐。"""
        p = tool_timeout_payload("L2")
        assert p["ok"] is False
        assert p["error_code"] == errors.TOOL_TIMEOUT
        assert p["data"]["retry_after_ms"] == 500
        assert p["data"]["retry_max"] == 3
        assert p["message"].startswith("处理中")          # 前缀兼容(直出)

    def test_rt02_l3_differentiated(self):
        """TC-RT-02:L3(审批挂起语义) → 2000ms,message 带指引短语。"""
        p = tool_timeout_payload("L3")
        assert p["data"]["retry_after_ms"] == 2000
        assert p["data"]["retry_max"] == 3
        assert "2000" in p["message"]
        assert "最多 3 次" in p["message"]


@pytest.mark.integration
class TestRealTimeoutIntegration:
    """TC-RT-03:真 daemon+慢 probe 真超时 → HTTP 响应体同形(外表面直出)。"""

    def test_rt03_real_daemon_timeout_shape(self, policy, audit_log, tmp_path):
        from deskpilot.executor import Executor
        from deskpilot.estop import EstopMonitor
        from deskpilot.httpd import HttpDaemon
        from deskpilot.tools import ToolContext

        class SlowProbe:
            def find_windows(self, **kw):
                time.sleep(6.0)                       # > L0 预算 5s
                return []

        estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit_log)
        executor = Executor(estop, str(tmp_path / "audit"), probe=SlowProbe())
        ctx = ToolContext(policy=policy, enforcement=None, bindings=None,
                          executor=executor, audit=audit_log)
        d = HttpDaemon(ctx, port=0)
        d.start()
        try:
            for _ in range(50):
                try:
                    with urllib.request.urlopen(
                            f"http://127.0.0.1:{d.port}/health",
                            timeout=0.5):
                        break
                except OSError:
                    time.sleep(0.1)
            body = json.dumps({"tool": "find_window",
                               "params": {"process": "x.exe"}}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{d.port}/call", data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                r = json.loads(resp.read().decode("utf-8"))
            assert r["ok"] is False
            assert r["error_code"] == errors.TOOL_TIMEOUT
            assert r["data"]["retry_after_ms"] == 500      # L0 走默认档(直出)
            assert r["data"]["retry_max"] == 3
            assert "最多 3 次" in r["message"]
        finally:
            d.stop()
