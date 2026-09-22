"""ISS-0101 set_window_rect 窗口几何摆放原语测试(TC-101-01~08,问题单 §5 表)。

背景:演示编导/多窗协同需要把目标窗摆到指定位置,MCP 无窗口几何写入
原语,AI 只能裸写 Win32 MoveWindow 绕行(2026-09-21 sdfang 怒批事件缺口
之一)。设计=物理层原语(SW_RESTORE+MoveWindow,返回新 rect)+L2 闸门+
绑定进程窗限定(不收 hwnd=结构性跨窗限定)+判断归 AI。

层级分布(§5 表逐行落码):
- 形态:TC-101-01/05/07/08(注册表/i18n.yml 直读)
- 单元:TC-101-02/03/04(user32 替身照 test_activate_iss41 接缝形态——
  monkeypatch probe 模块 user32;Executor 真装配,经 execute 全链驱动)
- 集成:TC-101-06(@pytest.mark.integration,真 daemon 临时端口+真记事本,
  环境守卫:真 daemon(9420) 在线 skip;记事本拉不起 skip——参照
  test_typeguard_iss100 TC-100-08 先例)

入口(设计):TOOL_SCHEMAS/TOOL_LEVELS/BINDING_REQUIRED_TOOLS 注册表、
Executor.execute(set_window_rect)、i18n.yml enf.act.* 键、
POST /call set_window_rect。
断言出处:替身调用序列直出/异常 code 属性直出/返回值 rect 直出/
注册表与 YAML 解析直读/HTTP 响应体直出——均直出,无中间转换。

替身缝约定(P3 实现须按此缝):MoveWindow/ShowWindow 经 probe 模块 user32
接缝(设计 §4.2「probe.py 增 MoveWindow ctypes 接缝,同 iss41 先例」);
返回形态钉为 {"rect": list(rect_of(hwnd))}(设计「返回新 rect 直出」
的落形,上报裁决点)。

P1 红态预期:TC-101-02/03/06 红(_dispatch 无 set_window_rect 分支,
INTERNAL_ERROR 未接线);TC-101-01/05/07/08 绿(P1 空壳声明已落);
TC-101-04 预期偏差见函数 docstring(死窗统一检查为既有机制)。
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

import pytest
import yaml

from deskpilot.errors import INVALID_PARAMS, WINDOW_GONE, ExecutorError
from deskpilot.executor.core import Executor
from deskpilot.mcp_server import TOOL_SCHEMAS
from deskpilot.models import BINDING_REQUIRED_TOOLS, TOOL_LEVELS

from .conftest import FIXTURE_HWND, FakeProbe

SW_RESTORE = 9
TOOL = "set_window_rect"


def _wingeo_exec(monkeypatch, estop, tmp_path, clock, alive=True):
    """真 Executor + probe user32 替身(iss41 接缝形态)。

    返回 (ex, seq):seq 为 ("show",hwnd,cmd)/("move",hwnd,x,y,w,h,repaint)
    统一时序记录(直出断言用)。"""
    from deskpilot.executor import probe as probe_mod

    seq: list[tuple] = []

    def _show(h, s):
        seq.append(("show", h, s))
        return True

    def _move(h, x, y, w, hh, repaint):
        seq.append(("move", h, x, y, w, hh, repaint))
        return True

    monkeypatch.setattr(probe_mod.user32, "ShowWindow", _show)
    monkeypatch.setattr(probe_mod.user32, "MoveWindow", _move)
    probe = FakeProbe()
    probe.alive[FIXTURE_HWND] = alive
    ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                  wait_timeout_max=5.0, clock=clock, probe=probe)
    return ex, seq


# ---------- TC-101-01/05/07/08 形态钉:注册面直读 ----------

class TestRegistryShape:
    """TC-101-01/05/07/08(形态):注册面三处一致/跨窗限定/i18n 双键/计数。"""

    def test_tc101_01_registration_three_places_consistent(self):
        """TC-101-01(形态,§4.1 ①②③):TOOL_SCHEMAS/TOOL_LEVELS/
        BINDING_REQUIRED_TOOLS 三处均含 set_window_rect;级别 L2;
        required=token+rect(rect 型);描述 ≤200 含领域词。
        断言:注册表直读。绿态:P1 空壳声明已落。"""
        schema = TOOL_SCHEMAS[TOOL]
        assert schema["required"]["token"] == ("str",)
        assert schema["required"]["rect"] == ("rect",)     # rect 四元型先例
        assert TOOL_LEVELS[TOOL] == "L2"
        assert TOOL in BINDING_REQUIRED_TOOLS
        d = schema["description"]
        assert len(d) <= 200
        assert any(w in d for w in ("Windows", "窗口", "桌面"))

    def test_tc101_05_no_hwnd_param_structural_binding_scope(self):
        """TC-101-05(形态,§4.1):schema required/optional 无 hwnd 参数
        (仅 token+rect)——hwnd 由闸一从绑定记录取出,结构上只能摆绑定的
        那个窗=「不得跨绑定」的最顺落位。
        断言:注册表直读(闸一绑定链由既有 NO_BINDING 钉回归覆盖)。
        绿态:P1 空壳声明已落。"""
        schema = TOOL_SCHEMAS[TOOL]
        assert set(schema["required"]) == {"token", "rect"}
        assert "hwnd" not in schema["required"]
        assert "hwnd" not in schema["optional"]

    def test_tc101_07_i18n_approval_text_bilingual(self):
        """TC-101-07(形态,§4.1 ⑥):i18n.yml 增 enf.act.set_window_rect
        双语键(en/zh 非空;REQ-007 设计义务)。
        断言:YAML 解析直读。绿态:P1 空壳声明已落。"""
        from pathlib import Path
        doc = yaml.safe_load((Path(__file__).resolve().parent.parent
                              / "deskpilot" / "i18n.yml")
                             .read_text(encoding="utf-8"))
        en = doc["en"].get("enf.act.set_window_rect", "")
        zh = doc["zh-CN"].get("enf.act.set_window_rect", "")
        assert isinstance(en, str) and en.strip(), "en 键缺失或为空(直读)"
        assert isinstance(zh, str) and zh.strip(), "zh-CN 键缺失或为空(直读)"

    def test_tc101_08_tool_count_thirty(self):
        """TC-101-08(形态,§4.3):len(TOOL_SCHEMAS)==30(29+本单新工具)。
        断言:注册表直读。绿态:P1 空壳声明已落。"""
        assert len(TOOL_SCHEMAS) == 30


# ---------- TC-101-02/03/04 单元:执行链(经 execute 全链) ----------

class TestSetWindowRectExec:
    """TC-101-02/03/04(单元,§4.2):动作序/几何非法/死窗。"""

    def test_tc101_02_action_sequence_and_return(self, estop, tmp_path,
                                                 clock, monkeypatch):
        """TC-101-02(单元):execute set_window_rect(rect=[100,100,700,600])
        → ShowWindow(SW_RESTORE=9) 先于 MoveWindow(恒定先发,最大化/最小化
        先还原防打回);MoveWindow 收 (hwnd,100,100,600,500,True)
        (r-l=600,b-t=500);返回 {"rect": rect_of(hwnd) 直出}。
        断言:替身调用序列直出;返回值=rect_of 直出。
        红态:_dispatch 无分支(ExecutorError 工具未接线)。"""
        ex, seq = _wingeo_exec(monkeypatch, estop, tmp_path, clock)
        r = ex.execute({"tool": TOOL,
                        "params": {"rect": [100, 100, 700, 600]},
                        "binding_hwnd": FIXTURE_HWND})
        assert [s[0] for s in seq] == ["show", "move"], \
            f"动作序须 ShowWindow 先于 MoveWindow(序列直出): {seq}"
        assert seq[0] == ("show", FIXTURE_HWND, SW_RESTORE)
        assert seq[1] == ("move", FIXTURE_HWND, 100, 100, 600, 500, True), \
            f"MoveWindow 参数须为 (hwnd,l,t,r-l,b-t,True): {seq[1]}"
        assert r["rect"] == list(ex._probe.rect_of(FIXTURE_HWND)), \
            "返回新 rect 须为 rect_of 直出(与 GetWindowRect 同口径)"

    def test_tc101_03_degenerate_geometry_fail_closed(self, estop, tmp_path,
                                                      clock, monkeypatch):
        """TC-101-03(单元,§4.2):rect=[700,100,100,600](r<l) 与
        [100,600,700,100](b<t) → ExecutorError INVALID_PARAMS;user32 零调用。
        断言:异常 code 直出;替身零调用记录。
        红态:无分支(INTERNAL_ERROR≠INVALID_PARAMS)。"""
        ex, seq = _wingeo_exec(monkeypatch, estop, tmp_path, clock)
        for bad in ([700, 100, 100, 600], [100, 600, 700, 100]):
            with pytest.raises(ExecutorError) as ei:
                ex.execute({"tool": TOOL, "params": {"rect": bad},
                            "binding_hwnd": FIXTURE_HWND})
            assert ei.value.code == INVALID_PARAMS, \
                f"几何非法须 INVALID_PARAMS,实得 {ei.value.code}"
        assert seq == [], f"几何非法零 user32 调用(序列直出): {seq}"

    def test_tc101_04_dead_window_window_gone(self, estop, tmp_path, clock,
                                              monkeypatch):
        """TC-101-04(单元,§4.2):hwnd_alive 替身 False → WINDOW_GONE;
        user32 零调用。断言:异常 code 直出。
        P1 预期偏差(上报):死窗统一检查为 _dispatch 既有机制(core.py 入口
        统一判定,§6 交叉面「机制复用不改」)——本条 P1 即绿属正确落点
        (新工具自动继承既有死窗闸),非未实现行为;设计本意即复用。"""
        ex, seq = _wingeo_exec(monkeypatch, estop, tmp_path, clock,
                               alive=False)
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": TOOL, "params": {"rect": [100, 100, 700, 600]},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == WINDOW_GONE      # 异常 code 直出
        assert seq == [], "死窗零 user32 调用(序列直出)"


# ---------- TC-101-06 集成:真记事本摆放读回 ----------

@pytest.mark.integration
class TestSetWindowRectIntegration:
    """TC-101-06(集成,§3.2:零打桩,断言在 HTTP 响应体/读回矩形外表面)。

    场景:真记事本 attach → set_window_rect [100,100,700,600] → 返回 rect
    与 find_window 读回矩形同口径一致(GetWindowRect 同口径)。
    前提:真 daemon(9420) 在线 skip(不打扰真服务,同 TC-100-08 守卫);
    记事本拉不起 skip(环境缺,非产品红)。
    断言:响应体 ok/data.rect 直出;find_window rect 直读对照。
    红态:_dispatch 无分支 → INTERNAL_ERROR,ok False。
    """

    def _spawn_notepad(self):
        """ISS-0062 步骤 A:内联窗口枚举收敛 envguard.notepad_mains(纯重构)。"""
        import subprocess

        from .envguard import notepad_mains

        before = {w["hwnd"] for w in notepad_mains()}
        proc = subprocess.Popen(["notepad.exe"])
        time.sleep(3.0)
        new = [w for w in notepad_mains() if w["hwnd"] not in before]
        return proc, new

    def _make_daemon(self, policy, audit_log, tmp_path):
        from deskpilot.approval import ApprovalManager
        from deskpilot.binding import BindingManager
        from deskpilot.enforcement import Enforcement
        from deskpilot.estop import EstopMonitor
        from deskpilot.executor import DesktopProbe, Executor
        from deskpilot.httpd import HttpDaemon
        from deskpilot.tools import ToolContext

        from .conftest import FakeApprover, FakeClock

        probe = DesktopProbe()
        estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit_log)
        executor = Executor(estop, str(tmp_path / "audit"), probe=probe)
        clock = FakeClock()
        bindings = BindingManager(probe, policy.binding_ttl, clock)
        approvals = ApprovalManager(FakeApprover(), policy.approval_ttl, clock)
        enforcement = Enforcement(policy, bindings, approvals, estop,
                                  executor, audit_log)
        ctx = ToolContext(policy=policy, enforcement=enforcement,
                          bindings=bindings, executor=executor,
                          audit=audit_log)
        d = HttpDaemon(ctx, port=0)
        d.start()
        for _ in range(50):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{d.port}/health", timeout=0.5):
                    break
            except OSError:
                time.sleep(0.1)
        return d

    def _call(self, port, tool, params, timeout=60):
        body = json.dumps({"tool": tool, "params": params}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/call",
                                     data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_tc101_06_notepad_move_and_readback(self, policy, audit_log,
                                                tmp_path):
        from .envguard import env_skip, real_daemon_online
        from .test_uia_com_iss16 import _close_all_and_wait

        if os.environ.get("ISS101_FORCE_E2E") != "1" and \
                real_daemon_online():
            env_skip("真实 daemon 在线,不打扰真服务")
        proc, new = self._spawn_notepad()
        if not new:
            proc.terminate()
            env_skip("记事本窗口未出现(无可用记事本环境)")
        try:
            d = self._make_daemon(policy, audit_log, tmp_path)
            try:
                hwnd = new[0]["hwnd"]
                a = self._call(d.port, "attach", {"hwnd": hwnd})
                assert a["ok"] is True, a.get("message")
                token = a["data"]["token"]
                r = self._call(d.port, TOOL,
                               {"token": token, "rect": [100, 100, 700, 600]})
                assert r["ok"] is True, r.get("message")      # 响应体直出
                f = self._call(d.port, "find_window", {"hwnd": hwnd})
                win = [w for w in f["data"]["windows"]
                       if w["hwnd"] == hwnd][0]
                assert list(r["data"]["rect"]) == list(win["rect"]), \
                    "返回 rect 与 find_window 读回矩形须同口径一致" \
                    "(GetWindowRect 同口径,直读对照)"
            finally:
                d.stop()
        finally:
            proc.terminate()
            closed = _close_all_and_wait([w["hwnd"] for w in new])
        assert closed is True, "测试残留记事本窗口(关窗失败)"
