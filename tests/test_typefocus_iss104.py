"""ISS-0104 type_text 粘贴前 SetFocus 测试(TC-104-01~03,问题单 §6 表)。

背景:_type_text 只置前窗口,不保证键盘焦点在编辑控件上;Win11 记事本
多标签形态焦点可在标签条,ctrl+v 粘贴落空(W6 实盘:读回 fail-closed
如实拦下,但写操作本身失败)。裁定改法 A:粘贴前对首个 Edit/Document
控件 UIA SetFocus(复用 _iter_controls+_EDIT_TYPE_NAMES 枚举;无编辑
控件/聚焦失败不阻断,交读回兜底)。

层级分布(§6 表逐行落码):
- 单元:TC-104-01/02(UIA 替身节点带 SetFocus 记录桩;桥替身照
  test_typeguard_iss100 风格——pyperclip/pyautogui/time 桩,
  focus/hotkey 统一时序记录同一 list)
- 集成:TC-104-03(@pytest.mark.integration,真 daemon 临时端口+真记事本;
  环境守卫:真 daemon(9420) 在线 skip+ISS104_FORCE_E2E 逃逸口先例;
  记事本拉不起 skip)

入口(设计):Executor._type_text(粘贴序列)/POST /call type_text。
断言出处:统一调用序列桩记录直出(focus 序位 < hotkey 序位)/桩零调用
记录直出/异常 code 属性直出/HTTP 响应体 ok·data.note 直出——均直出,
无中间转换。

P1 红态预期:TC-104-01 红(现状粘贴序列无 SetFocus 步,桩零记录);
TC-104-02 绿(行为保持面——无编辑控件不聚焦不崩+READBACK_UNAVAILABLE
兜底均系既有行为,P1 即绿属正确落点,设计「行为与现版一致」本意);
TC-104-03 红(W6 正向路径:聚焦前提缺失,真机 READBACK_UNAVAILABLE/
TYPE_MISMATCH,逃逸口实证)。
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

import pytest

from deskpilot.errors import READBACK_UNAVAILABLE, ExecutorError
from deskpilot.executor.core import Executor


class _FocusNode:
    """UIA 替身节点:ControlTypeName 可配;SetFocus 调用记入统一时序。"""

    def __init__(self, type_name: str, seq: list):
        self.ControlTypeName = type_name
        self._seq = seq

    def SetFocus(self):
        self._seq.append(("focus",))
        return True


def _focus_bridge_executor(monkeypatch, nodes, readback, seq):
    """_type_text 桥+聚焦缝替身装配(iss100 风格):activate 恒真;
    _iter_controls 桩给出 nodes;读回替身=readback 值;pyperclip/
    pyautogui/time 全桩,hotkey 记入统一时序 seq。"""
    import deskpilot.executor.core as core

    ex = Executor.__new__(Executor)              # 不经 __init__,仅取方法
    monkeypatch.setattr(ex, "_activate_if_needed", lambda hwnd: True)
    monkeypatch.setattr(ex, "_read_edit_value", lambda hwnd: readback)
    monkeypatch.setattr(ex, "_iter_controls",
                        lambda root, depth=0: iter(list(nodes)))
    monkeypatch.setattr(core.uiautomation, "ControlFromHandle",
                        lambda hwnd: object())
    monkeypatch.setattr(core.pyperclip, "copy", lambda t: None)
    monkeypatch.setattr(core.pyperclip, "paste", lambda: "old")
    monkeypatch.setattr(core.pyautogui, "hotkey",
                        lambda *a, **k: seq.append(("hotkey",) + a))
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    return ex


class TestFocusBeforePaste:
    """TC-104-01/02(单元,§5):粘贴前聚焦/无编辑控件不聚焦不崩。"""

    def test_tc104_01_setfocus_first_edit_before_paste(self, monkeypatch):
        """TC-104-01(单元,改法 A):UIA 替身首个 Edit 节点带 SetFocus
        记录桩;读回替身命中 → _type_text(text) → SetFocus 被调一次且
        序位先于 ("ctrl","v")。
        断言:统一调用序列桩记录直出(focus 序位 < hotkey 序位)。
        红态:现状粘贴序列无 SetFocus 步(桩零记录,序位查找失败)。"""
        seq: list[tuple] = []
        text = "聚焦测试文本"
        edit = _FocusNode("Edit", seq)
        ex = _focus_bridge_executor(monkeypatch, [edit], text, seq)
        r = ex._type_text(text, 42)
        assert r["note"] == "读回校验一致"        # 链路前提:读回命中(返回值直出)
        focus_at = [i for i, e in enumerate(seq) if e == ("focus",)]
        assert len(focus_at) == 1, \
            f"SetFocus 须被调恰好一次(序列直出): {seq}"
        paste_at = seq.index(("hotkey", "ctrl", "v"))
        assert focus_at[0] < paste_at, \
            f"SetFocus 须先于 ctrl+v(序位直出): {seq}"

    def test_tc104_02_no_edit_control_no_focus_no_crash(self, monkeypatch):
        """TC-104-02(单元,§5 行为保持面):树内零 Edit/Document(仅 Pane
        节点,带 SetFocus 记录桩) → SetFocus 零调用;流程照常进粘贴+
        读回兜底(读回替身 None → READBACK_UNAVAILABLE,与 TC-100-04 同形态)。
        断言:桩零调用记录直出;异常 code 直出。
        P1 即绿(正确落点):不聚焦+不崩+读回兜底均系既有行为——设计
        「行为与现版一致,READBACK_UNAVAILABLE 面不回退」本意即保持。"""
        seq: list[tuple] = []
        pane = _FocusNode("Pane", seq)           # 非编辑控件,带记录桩
        ex = _focus_bridge_executor(monkeypatch, [pane], None, seq)
        with pytest.raises(ExecutorError) as ei:
            ex._type_text("中文", 42)
        assert ei.value.code == READBACK_UNAVAILABLE   # 异常 code 直出
        assert ("focus",) not in seq, \
            f"无编辑控件不得 SetFocus(桩零调用直出): {seq}"
        assert ("hotkey", "ctrl", "v") in seq, \
            f"流程须照常进粘贴(序列直出): {seq}"


# ---------- TC-104-03 集成:真记事本(焦点在标签条)全链 ----------

@pytest.mark.integration
class TestNotepadFocusIntegration:
    """TC-104-03(集成,§3.2:零打桩,断言在 HTTP 响应体外表面)。

    场景:真 Win11 记事本(多标签,程序化置前后焦点可在标签条)
    attach+type_text 魔法串 → ok 且 note=「读回校验一致」
    (W6 正向路径补验)。
    前提:真 daemon(9420) 在线 skip(+ISS104_FORCE_E2E 逃逸口,
    ISS-93/101 先例);记事本拉不起 skip。
    断言:响应体 ok/data.note 直出。
    红态:现状粘贴前无聚焦步,真机 READBACK_UNAVAILABLE/TYPE_MISMATCH
    (W6 事故链复现)。
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

    def _seed_doc_and_focus_tab(self, hwnd: int) -> None:
        """前提建立(设计场景「焦点在标签条」+ W6 现场=文档非空):
        ①外部驱动置前+SetFocus Document 粘贴种子文本(编辑焦点下
        粘贴必达,2026-09-22 探针实证);②SetFocus TabItem 把焦点移出
        编辑区(此后 ctrl+v 粘贴落空,探针实证 content 不变)。
        全部外部驱动(同 ct08 SetCursorPos 先例),被测链(daemon 侧
        type_text/读回)全真。"""
        import pyautogui
        import pyperclip
        import uiautomation as uia

        from deskpilot.executor import DesktopProbe
        DesktopProbe().activate(hwnd)
        time.sleep(0.3)
        root = uia.ControlFromHandle(hwnd)
        doc = tab = None

        def walk(c, d=0):
            nonlocal doc, tab
            if c is None or d > 14:
                return
            try:
                tn = c.ControlTypeName
            except Exception:
                tn = ""
            if doc is None and tn in ("DocumentControl", "EditControl"):
                doc = c
            elif tab is None and tn == "TabItemControl":
                tab = c
            try:
                ch = c.GetChildren()
            except Exception:
                return
            for x in ch:
                walk(x, d + 1)

        walk(root)
        assert doc is not None, "前提失败:未找到编辑控件"
        assert tab is not None, "前提失败:未找到 TabItem(非多标签形态?)"
        doc.SetFocus()
        time.sleep(0.2)
        pyperclip.copy("dp104seed种子")
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.8)
        content = doc.GetTextPattern().DocumentRange.GetText(-1)
        assert "dp104seed种子" in content, \
            f"前提失败:种子未落入(编辑焦点下粘贴应必达): {content!r}"
        tab.SetFocus()
        time.sleep(0.3)

    def test_tc104_03_notepad_focused_paste_readback(self, policy, audit_log,
                                                     tmp_path):
        from .envguard import (dismiss_xaml_save_prompt, env_skip,
                           real_daemon_online)
        from .test_uia_com_iss16 import _close_all_and_wait

        if os.environ.get("ISS104_FORCE_E2E") != "1" and \
                real_daemon_online():
            env_skip("真实 daemon 在线,不打扰真服务")
        proc, new = self._spawn_notepad()
        if not new:
            proc.terminate()
            env_skip("记事本窗口未出现(无可用记事本环境)")
        try:
            d = self._make_daemon(policy, audit_log, tmp_path)
            try:
                a = self._call(d.port, "attach",
                               {"hwnd": new[0]["hwnd"]})
                assert a["ok"] is True, a.get("message")
                token = a["data"]["token"]
                # 场景前提:文档非空(W6 现场)+焦点在标签条
                self._seed_doc_and_focus_tab(new[0]["hwnd"])
                magic = f"dp104focus{int(time.time()) % 100000}"  # 纯 ASCII
                t = self._call(d.port, "type_text",
                               {"token": token, "text": magic})
                assert t["ok"] is True, t.get("message")     # 响应体直出
                assert t["data"]["note"] == "读回校验一致", \
                    f"粘贴须真实落入编辑控件(聚焦前提),实得 note=" \
                    f"{t['data'].get('note')!r}"
            finally:
                d.stop()
        finally:
            # 自动保存浸泡(2026-09-22 授权修正,对齐 ct08 自然浸泡语义):
            # Store 记事本未保存 '*' 需数秒自动保存方消退;未消退即
            # WM_CLOSE 会弹 XAML 内嵌保存提示(非经典 #32770,
            # _close_all_and_wait 的「不保存」处置不覆盖)模态阻塞关窗——
            # 浸泡是唯一稳定出口。
            time.sleep(8.0)
            proc.terminate()
            # 二次裁决方案①:XAML「不保存」消除(本机实证 '*' 永不消退,
            # 浸泡不足以让提示不出现,须主动消除;详见函数 docstring)
            dismiss_xaml_save_prompt([w["hwnd"] for w in new])
            closed = _close_all_and_wait([w["hwnd"] for w in new])
        assert closed is True, "测试残留记事本窗口(关窗失败)"
