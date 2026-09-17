"""ISS-0052 daemon 瞬态 500 诊断修复测试(t52a/t52b,单据 §2 约束:裸 500 必须结构化)。

层级:单元(monkeypatch urllib/pyautogui 接缝,允许打桩)。
入口(设计):httpd.remote_call(瘦代理客户端面)/Executor.move(L1 公开入口)。
断言出处:返回字典/异常码直出。

诊断结论(证据分级,单据 v0.2):
- 实证:handler :331 的 500 带结构化 JSON 体,但 remote_call 把 HTTPError
  (OSError 子类)吞进 RuntimeError「无法连接」——错误体被丢弃且误归因
  (服务明明连得上)。「裸 500」观感=客户端侧吞掉错误体。
- 代码实证的候选机制:Executor.move 的 pyautogui.moveTo 无 FAILSAFE 收敛
  (兄弟路径 click/key/type/drag 全有,:905/:959/:1075/:1104/execute :148)
  ——光标压角时首调 move 必 500;与 09-10 现场(ISS-0049 甩角实测期间)
  吻合但不完全坐实(「立即重试即恢复」要求光标已离角)。

红态预期(现状):t52a HTTPError→RuntimeError 立红;t52b FailSafeException
裸逃(非 ExecutorError)立红;t52c 连接真失败仍 RuntimeError(红期即绿钉)。
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from deskpilot.errors import EMERGENCY_STOP, ExecutorError
from deskpilot.executor.core import Executor
from deskpilot.httpd import remote_call

from .conftest import FakeProbe


class TestRemoteCallStructuredError:
    """t52a/t52c:500 结构化错误体须原样送达 AI(不得吞进 RuntimeError)。"""

    def test_t52a_http_500_body_parsed(self, monkeypatch):
        """t52a:服务端 500 + 结构化 JSON 体 → remote_call 返回该字典
        (ok=False/error_code 保留),不抛 RuntimeError。
        红态(现状):HTTPError 被 OSError 分支吞 → RuntimeError「无法连接」
        (误归因+错误码丢失)。"""
        body = json.dumps({"ok": False, "error_code": "INTERNAL_ERROR",
                           "message": "服务内部异常: boom", "data": None},
                          ensure_ascii=False).encode("utf-8")

        def _raise_500(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 500, "Internal Server Error", None,
                io.BytesIO(body))

        monkeypatch.setattr("deskpilot.httpd.urllib.request.urlopen",
                            _raise_500)
        out = remote_call("move", {"x": 1, "y": 2}, "http://127.0.0.1:1", 5)
        assert out["ok"] is False               # 结构体直出
        assert out["error_code"] == "INTERNAL_ERROR"
        assert "boom" in out["message"]         # 服务端消息不丢

    def test_t52c_connection_failure_still_runtime_error(self, monkeypatch):
        """t52c(钉):真连接失败(OSError)仍显式 RuntimeError「无法连接」
        (禁止静默成功语义不变)。红期即绿。"""
        def _refused(req, timeout=None):
            raise OSError("连接被拒绝")

        monkeypatch.setattr("deskpilot.httpd.urllib.request.urlopen",
                            _refused)
        with pytest.raises(RuntimeError) as ei:
            remote_call("move", {"x": 1, "y": 2}, "http://127.0.0.1:1", 5)
        assert "无法连接" in str(ei.value)      # 误归因面不变(直出)


class TestMoveFailSafeConverged:
    """t52b:move 路径 pyautogui FAILSAFE 收敛为 EMERGENCY_STOP(兄弟对齐)。"""

    def test_t52b_move_failsafe_maps_emergency_stop(self, estop, tmp_path,
                                                    monkeypatch):
        """t52b(单元):光标压角时 moveTo 抛 FailSafeException →
        ExecutorError(EMERGENCY_STOP)(不再裸逃成 500)。
        红态(现状):move 裸调 pyautogui.moveTo(core.py:298-301),
        FailSafeException 非 ExecutorError → 沿 _run_sensing 外逃。"""
        import pyautogui

        def _boom(*a, **k):
            raise pyautogui.FailSafeException("光标压角")

        monkeypatch.setattr(pyautogui, "moveTo", _boom)
        ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                      probe=FakeProbe())
        with pytest.raises(ExecutorError) as ei:
            ex.move(300, 300)
        assert ei.value.code == EMERGENCY_STOP   # 异常码直出
