"""ISS-0100 type_text 通道废止+读回校验修真测试(TC-100-01~09,问题单 §6 表)。

背景:纯 ASCII 逐键路径被中文 IME 吞改(demo 录制实证),读回校验对无
ValuePattern 目标静默跳过仍报 ok:sdfang 裁定 A+C——逐键路径废止全量
走剪贴板桥;读回修真(三级通道序+比对失败 TYPE_MISMATCH+通道全灭
READBACK_UNAVAILABLE fail-closed)。

层级分布(§6 表逐行落码):
- 单元:TC-100-01/02/03/04/07(替身/桩允许,照 test_textchannel_iss35 风格:
  Executor.__new__ 取方法,pyautogui/pyperclip/_read_edit_value 桩;
  TC-100-03/07 另加 UIA 替身节点)
- 形态:TC-100-05/06/09(源码直读检索,无执行)
- 集成:TC-100-08(@pytest.mark.integration,真 daemon 临时端口+真记事本,
  环境守卫照 iss21 先例:真 daemon(9420) 在线或记事本拉不起即 skip)

入口(设计):Executor._type_text(剪贴板桥)/Executor._read_edit_value
(三级通道序)/errors.py 常量/core.py·mcp_server.py 源码/POST /call type_text。
断言出处:桩调用记录直出/返回值与异常 code 属性直出/源码文本检索直读/
HTTP 响应体 data.note 直出——均直出,无中间转换。

替身缝约定(P3 实现须按此缝,否则属实现偏离设计):UIA 替身节点暴露
GetValuePattern()/GetTextPattern()(uiautomation 便捷口惯例),
TextPattern 经 DocumentRange().GetText(-1) 取全文。

P1 红态预期:TC-100-01/02/03/04/06/07/09 红(未实现行为:逐键分支未删/
新码未换/TextPattern·选读通道未接/引导语未改);TC-100-05 绿(P1 空壳
常量已加);TC-100-08 环境守卫 skip(真 daemon 在线)。
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import pytest

from deskpilot.errors import (READBACK_UNAVAILABLE, TYPE_MISMATCH,
                              ExecutorError)

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "deskpilot"


def _read_src(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def _bridge_executor(monkeypatch, readback):
    """_type_text 桥测试替身装配(iss35 风格):activate 恒真;读回按
    readback 队列出值(空则恒 'stale');pyautogui/pyperclip/time 全桩。
    返回 (ex, rec):rec 记录 copy/write/hotkey 调用序列(直出断言用)。"""
    import deskpilot.executor.core as core
    from deskpilot.executor import Executor

    ex = Executor.__new__(Executor)              # 不经 __init__,仅取方法
    monkeypatch.setattr(ex, "_activate_if_needed", lambda hwnd: True)
    monkeypatch.setattr(
        ex, "_read_edit_value",
        lambda hwnd: readback.pop(0) if readback else "stale")
    rec = {"copy": [], "write": [], "hotkey": []}
    monkeypatch.setattr(core.pyperclip, "copy",
                        lambda t: rec["copy"].append(t))
    monkeypatch.setattr(core.pyperclip, "paste", lambda: "old")
    monkeypatch.setattr(core.pyautogui, "hotkey",
                        lambda *a, **k: rec["hotkey"].append(a))
    monkeypatch.setattr(core.pyautogui, "write",
                        lambda *a, **k: rec["write"].append(a))
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    return ex, rec


class _UiaNode:
    """UIA 替身节点:ControlTypeName 可配;ValuePattern/TextPattern 行为可配。

    TC-100-03:ValuePattern 抛异常、TextPattern.DocumentRange().GetText(-1)
    给值;TC-100-07:两路均无值(抛异常),仅存在 Edit 控件供选读通道。
    """

    def __init__(self, type_name: str, *, value_error: bool = True,
                 text_pattern_value=None):
        self.ControlTypeName = type_name
        self._value_error = value_error
        self._text_pattern_value = text_pattern_value

    def GetValuePattern(self):
        if self._value_error:
            raise Exception("替身:无 ValuePattern")
        return None

    def GetTextPattern(self):
        if self._text_pattern_value is None:
            raise Exception("替身:无 TextPattern")

        class _TP:
            def DocumentRange(self_):
                class _Range:
                    def GetText(self__, n):
                        assert n == -1        # 取全文(直出)
                        return self._text_pattern_value
                return _Range()
        return _TP()


def _uia_executor(monkeypatch, nodes):
    """真实 _read_edit_value 的 UIA 替身装配:ControlFromHandle 桩 +
    _iter_controls 桩给出 nodes(其余 UIA 不触)。"""
    import deskpilot.executor.core as core
    from deskpilot.executor import Executor

    ex = Executor.__new__(Executor)
    monkeypatch.setattr(core.uiautomation, "ControlFromHandle",
                        lambda hwnd: object())
    monkeypatch.setattr(ex, "_iter_controls",
                        lambda root, depth=0: iter(list(nodes)))
    return ex


# ---------- TC-100-01/02/04/07 单元:_type_text 桥与读回 ----------

class TestTypeTextBridge:
    """TC-100-01/02(单元,§5.1/§5.2):纯 ASCII 全量走桥;比对失败报新码。"""

    def test_tc100_01_pure_ascii_goes_clipboard_bridge(self, monkeypatch):
        """TC-100-01(单元,A):_type_text(text="Hello ASCII") →
        pyperclip.copy 被调;pyautogui.write 零调用;返回 mode="clipboard"。
        断言:桩调用记录直出;返回值直出。
        红态:现状 ASCII 走逐键分支(write 被调,mode="keyboard")。"""
        ex, rec = _bridge_executor(monkeypatch, ["Hello ASCII"])
        r = ex._type_text("Hello ASCII", 42)
        assert rec["copy"] and rec["copy"][0] == "Hello ASCII"   # 桥写(桩记录)
        assert rec["write"] == [], \
            "ASCII 逐键路径已废止,pyautogui.write 不得再被调(桩记录直出)"
        assert r["mode"] == "clipboard"          # 返回值直出

    def test_tc100_02_mismatch_raises_type_mismatch(self, monkeypatch):
        """TC-100-02(单元,C):读回恒不含请求文本 → 重试耗尽抛
        ExecutorError,code==TYPE_MISMATCH。
        断言:异常对象 code 属性直出。
        红态:现状抛 INTERNAL_ERROR 泛码。"""
        ex, rec = _bridge_executor(monkeypatch, [])   # 恒 'stale' 不命中
        with pytest.raises(ExecutorError) as ei:
            ex._type_text("中文请求文本", 42)
        assert ei.value.code == TYPE_MISMATCH, \
            f"比对失败须报 TYPE_MISMATCH,实得 {ei.value.code}"
        assert len(rec["hotkey"]) == 2           # 重贴至上限语义不动(桩记录)


class TestReadbackChannels:
    """TC-100-03/04/07(单元,§5.2):读回三级通道序与 fail-closed。"""

    def test_tc100_03_textpattern_channel_reads_full_text(self, monkeypatch):
        """TC-100-03(单元,C②):UIA 替身——ValuePattern 抛异常、
        TextPattern.DocumentRange().GetText(-1) 给值 → _read_edit_value
        返回 TextPattern 文本(非 None)。
        断言:返回值直出。
        红态:现状仅 ValuePattern 一路,异常即 None。"""
        node = _UiaNode("Document", value_error=True,
                        text_pattern_value="记事本全文内容")
        ex = _uia_executor(monkeypatch, [node])
        r = ex._read_edit_value(42)
        assert r == "记事本全文内容"              # 返回值直出(TextPattern 通道)

    def test_tc100_04_all_channels_dead_fails_closed(self, monkeypatch):
        """TC-100-04(单元,C fail-closed):目标无 Edit/Document(读回
        三通道全灭,替身 _read_edit_value 恒 None) → _type_text 抛
        ExecutorError code==READBACK_UNAVAILABLE,不再 ok:true+note 放行;
        finally 剪贴板还原(old_clip)不受影响。
        断言:异常 code 直出;pyperclip 桩还原调用记录直出。
        红态:现状 note「读回校验不可用」仍返回 status=ok(DID NOT RAISE)。"""
        ex, rec = _bridge_executor(monkeypatch, [None, None, None])
        monkeypatch.setattr(ex, "_read_edit_value", lambda hwnd: None)
        with pytest.raises(ExecutorError) as ei:
            ex._type_text("中文", 42)
        assert ei.value.code == READBACK_UNAVAILABLE, \
            f"读回通道全灭须 fail-closed READBACK_UNAVAILABLE,实得 {ei.value.code}"
        assert rec["copy"][0] == "中文"          # 请求文本曾入桥(桩记录)
        assert rec["copy"][-1] == "old", \
            "old_clip 还原语义不变(桩还原调用记录直出)"

    def test_tc100_07_selection_channel_third_level(self, monkeypatch):
        """TC-100-07(单元,C③):ValuePattern/TextPattern 均无值但存在
        Edit 控件 → 选读通道 ctrl+a/ctrl+c 触发,读剪贴板比对命中 →
        ok+note「读回校验一致」;finally 剪贴板还原。
        前提:真实 _read_edit_value+_type_text 全链,UIA/剪贴板/键盘桩;
        pyperclip.paste 首返 old(old_clip 暂存),其后返最后 copy 值
        (选读读到的是请求文本)。
        断言:桩热键调用序列直出(含 ctrl+a/ctrl+c 序);返回值直出;
        桩还原调用记录直出。
        红态:现状无第三级通道,ValuePattern 异常即 None → note 不可用,
        ctrl+a/ctrl+c 零调用。"""
        import deskpilot.executor.core as core

        text = "中文选读命中"
        node = _UiaNode("Edit", value_error=True, text_pattern_value=None)
        ex = _uia_executor(monkeypatch, [node])
        monkeypatch.setattr(ex, "_activate_if_needed", lambda hwnd: True)
        copies: list[str] = []
        hotkeys: list[tuple] = []

        def _paste():
            return copies[-1] if copies else "old"   # 首调(old_clip)→old

        monkeypatch.setattr(core.pyperclip, "copy", lambda t: copies.append(t))
        monkeypatch.setattr(core.pyperclip, "paste", _paste)
        monkeypatch.setattr(core.pyautogui, "hotkey",
                            lambda *a, **k: hotkeys.append(a))
        monkeypatch.setattr(core.time, "sleep", lambda s: None)

        r = ex._type_text(text, 42)
        assert ("ctrl", "a") in hotkeys and ("ctrl", "c") in hotkeys, \
            f"选读通道未触发(热键序列直出): {hotkeys}"
        assert hotkeys.index(("ctrl", "a")) < hotkeys.index(("ctrl", "c"))
        assert r["status"] == "ok"               # 返回值直出
        assert r["note"] == "读回校验一致"
        assert copies[-1] == "old", \
            "选读覆盖剪贴板后仍须还原 old_clip(桩还原记录直出)"


# ---------- TC-100-05/06/09 形态钉:源码直读 ----------

class TestSourcePins:
    """TC-100-05/06/09(形态):源码文本检索,无执行。"""

    def test_tc100_05_new_codes_registered(self):
        """TC-100-05(形态,§5.2):errors.py 含 TYPE_MISMATCH、
        READBACK_UNAVAILABLE 常量(附录 A 一致性由 iss74 既有钉守)。
        断言:源码文本检索直读。绿态:P1 空壳常量已加。"""
        src = _read_src("errors.py")
        assert 'TYPE_MISMATCH = "TYPE_MISMATCH"' in src
        assert 'READBACK_UNAVAILABLE = "READBACK_UNAVAILABLE"' in src

    def test_tc100_06_keystroke_branch_gone(self):
        """TC-100-06(形态,§5.1):core.py 无 pyautogui.write;
        docstring 无「ASCII 逐键」。
        断言:源码文本检索直读。红态:core.py:1179/1183 现状命中。"""
        src = _read_src("executor/core.py")
        assert "pyautogui.write" not in src, \
            "ASCII 逐键分支未删(pyautogui.write 仍在 core.py)"
        assert "ASCII 逐键" not in src, \
            "_type_text docstring 仍自述「ASCII 逐键」"

    def test_tc100_09_guidance_wording_aligned(self):
        """TC-100-09(形态,§5.1 文案):type_element 引导语无「键盘路径」
        (core.py ELEMENT_UNSUPPORTED 引导句);mcp_server.py 无「键盘路径」;
        type_text 描述 ≤200(ISS-0015 闸门既有钉守,此处顺带形态确认)。
        断言:源码文本检索直读。红态:core.py:969 现状命中。"""
        core_src = _read_src("executor/core.py")
        assert "请改用 type_text 走键盘路径输入" not in core_src, \
            "type_element 引导语仍指「键盘路径」(应指剪贴板路径)"
        mcp_src = _read_src("mcp_server.py")
        assert "键盘路径" not in mcp_src
        from deskpilot.mcp_server import TOOL_SCHEMAS
        assert len(TOOL_SCHEMAS["type_text"]["description"]) <= 200


# ---------- TC-100-08 集成:真记事本读回真实发生 ----------

@pytest.mark.integration
class TestNotepadReadbackIntegration:
    """TC-100-08(集成,§3.2:零打桩,断言在 HTTP 响应体外表面)。

    场景:真 Win11 记事本(无 ValuePattern) attach+type_text 纯 ASCII
    魔法串 → ok True 且 note=「读回校验一致」(TextPattern/选读通道实盘)。
    前提:真 daemon(9420) 在线则 skip(不起临时服务打扰真服务,
    同 fg05/TC-93-12 守卫);记事本拉不起亦 skip(环境缺,非产品红)。
    断言:响应体 ok/data.note 直出。
    红态:现状 note=「读回校验不可用(目标无 UIA 值模式)」仍 ok:true
    ——红在读回通道未修真。
    """

    def _spawn_notepad(self):
        import subprocess

        from deskpilot.executor import DesktopProbe

        def mains():
            return [w for w in DesktopProbe().find_windows(
                process="notepad.exe", include_hidden=True)
                if w.get("title")
                and (w["rect"][2] - w["rect"][0]) > 100
                and (w["rect"][3] - w["rect"][1]) > 100]

        before = {w["hwnd"] for w in mains()}
        proc = subprocess.Popen(["notepad.exe"])
        time.sleep(3.0)
        new = [w for w in mains() if w["hwnd"] not in before]
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

    def test_tc100_08_notepad_readback_actually_happens(self, policy,
                                                        audit_log, tmp_path):
        from deskpilot.httpd import DEFAULT_HOST, DEFAULT_PORT, probe_daemon

        from .test_uia_com_iss16 import _close_all_and_wait

        if probe_daemon(DEFAULT_HOST, DEFAULT_PORT):
            pytest.skip("环境守卫:真实 daemon 在线,不打扰真服务")
        proc, new = self._spawn_notepad()
        if not new:
            proc.terminate()
            pytest.skip("环境守卫:记事本窗口未出现(无可用记事本环境)")
        try:
            d = self._make_daemon(policy, audit_log, tmp_path)
            try:
                a = self._call(d.port, "attach",
                               {"hwnd": new[0]["hwnd"]})
                assert a["ok"] is True, a.get("message")
                token = a["data"]["token"]
                magic = f"dp100magic{int(time.time()) % 100000}"   # 纯 ASCII
                t = self._call(d.port, "type_text",
                               {"token": token, "text": magic})
                assert t["ok"] is True, t.get("message")       # 响应体直出
                assert t["data"]["note"] == "读回校验一致", \
                    f"读回须真实发生(TextPattern/选读通道),实得 note=" \
                    f"{t['data'].get('note')!r}"
            finally:
                d.stop()
        finally:
            proc.terminate()
            closed = _close_all_and_wait([w["hwnd"] for w in new])
        assert closed is True, "测试残留记事本窗口(未保存关窗失败)"
