"""ISS-0091 click 像素兜底退化矩形守卫测试(TC-CG-01~04,问题单 §4 v0.1+v0.2 裁定)。

层级:TC-CG-01/02 单元(FakeElement 替身+pyautogui 记录器,允许打桩,
断言在异常码/记录器);TC-CG-03/04 集成(真 HttpDaemon+真记事本,禁桩,
断言在 HTTP 响应体/光标读数/estop-state.json 盘上文件——外表面直出)。
入口(设计):Executor.execute({"tool": "click_element", ...}) 公开入口 /
POST /call HTTP 面。

断言出处:错误码=ExecutorError 直出;零鼠标=pyautogui 记录器直出;
HTTP error_code=响应体直出;冻结状态=盘上 estop-state.json 直读。

P1 可编译性:ELEMENT_RECT_DEGENERATE 常量已随 P3 创建(errors.py);
P1 阶段本文件对该码用字符串字面量断言,现已升级为常量导入。

v0.2 裁定(Option A,已登记单据):退化 rect 元素不从候选中过滤——
Invoke-first 对折叠控件仍有效,过滤=过修回归;退化防护由①号守卫在
像素兜底时刻(唯一动鼠标处)fail-closed。故用例3 断言集合化为
{ELEMENT_RECT_DEGENERATE, ELEMENT_NOT_FOUND}:任一层显式拒绝皆可,
关键是不许静默成功点击。
"""

from __future__ import annotations

import json
import time
import urllib.request

import pytest

from deskpilot.errors import (ELEMENT_NOT_FOUND, ELEMENT_RECT_DEGENERATE,
                              WINDOW_OCCLUDED, ExecutorError)
from deskpilot.executor import Executor
from deskpilot.executor import core as core_mod

from .conftest import FIXTURE_HWND, FakeProbe
from .test_elements import FakeElement, make_callable_source
from .test_uia_com_iss16 import _close_all_and_wait


class _NoInvokeElement(FakeElement):
    """单元桩:Invoke 必炸 + 无 GetSelectionItemPattern(基类缺失→
    AttributeError 被 _invoke_element 二段 except Exception 吞)→
    逼出像素兜底路径(ISS-0091 缺陷机制的唯一动鼠标处)。"""

    def Invoke(self):
        raise RuntimeError("桩:不支持 Invoke(逼出像素兜底)")


class _Rec:
    def __init__(self):
        self.calls = []

    def fn(self, name):
        def f(*a, **k):
            self.calls.append((name, a, k))
        return f

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


def _exec(estop, tmp_path, monkeypatch):
    rec = _Rec()
    for fn in ("mouseDown", "mouseUp", "moveTo", "click", "hscroll", "scroll"):
        monkeypatch.setattr(core_mod.pyautogui, fn, rec.fn(fn))
    ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                  probe=FakeProbe())
    ex._check_occlusion = lambda *a, **k: None
    rec.calls.clear()                       # 清启动抬键清扫
    return ex, rec


class TestDegenerateRectGuard:
    """TC-CG-01/02:像素兜底退化守卫+校验链接入。断言:异常码/记录器直出。"""

    def _tree(self, rect):
        target = _NoInvokeElement(name="退化按钮", rect=rect)
        return FakeElement(children=[target]), target

    def test_cg01_degenerate_rect_rejected_zero_mouse(self, estop, tmp_path,
                                                      monkeypatch):
        """TC-CG-01:退化 rect(0,0,0,0)→ ELEMENT_RECT_DEGENERATE,零鼠标动作。

        红态(现状):兜底只挡 rect is None,(0,0,0,0) 非 None →
        中心 (0,0) → pixel_click 真实记录 click(0,0)(问题单 §1 机制);
        execute 成功返回 → DID NOT RAISE。
        守卫次序:退化判定必须在 _check_point 之前——否则 (0,0) 先吃
        OUT_OF_BOUNDS,错误码失真(AI 无法据码自愈)。
        """
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        tree, _ = self._tree((0, 0, 0, 0))
        ex._element_source = make_callable_source({FIXTURE_HWND: tree})
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "click_element",
                        "params": {"name": "退化按钮"},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == ELEMENT_RECT_DEGENERATE  # 异常码直出(errors 常量)
        assert rec.named("click") == []       # 零点击(记录器直出)
        assert rec.named("moveTo") == []      # 零移动(记录器直出)

    def test_cg02_fallback_passes_occlusion_chain(self, estop, tmp_path,
                                                  monkeypatch):
        """TC-CG-02:正常 rect 兜底必须过遮挡校验 → WINDOW_OCCLUDED 原样上抛。

        rect=(100,100,200,150)(v0.2 勘误:单据原文 (100,100,200,50)
        高度为负系笔误);中心 (150,125) ∈ FIXTURE_RECT(100,100,800,600),
        _check_point 放行,遮挡桩可达。
        红态(现状):兜底不调 _check_occlusion → 桩不触发 → 点击成功
        (DID NOT RAISE)。镜像 _click 的 ISS-0017 C 次序:
        check_point → 激活 → check_occlusion。
        """
        ex, rec = _exec(estop, tmp_path, monkeypatch)
        tree, _ = self._tree((100, 100, 200, 150))
        ex._element_source = make_callable_source({FIXTURE_HWND: tree})

        def _occluded(*a, **k):
            raise ExecutorError(WINDOW_OCCLUDED, "桩:落点被遮挡")

        ex._check_occlusion = _occluded
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "click_element",
                        "params": {"name": "退化按钮"},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == WINDOW_OCCLUDED   # 桩异常原样上抛(直出)
        assert rec.named("click") == []           # 拒绝即零点击(记录器直出)
        assert rec.named("moveTo") == []


@pytest.mark.integration
class TestDegenerateRectRealNotepad:
    """TC-CG-03/04:真 daemon+真记事本(iss21 装配先例)。禁桩;
    断言全在系统外表面:HTTP 响应体/get_cursor 读数/盘上 estop-state.json。"""

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
        assert new, "记事本窗口未出现"
        return proc, new

    def _make_daemon(self, policy, audit_log, tmp_path):
        """完整装配(iss21 同构)+FreezeNotifier 材料化 estop-state.json
        (镜像 main.py:183 启动写 frozen:false;spawn 置 no-op——测试期间
        绝不弹窗)。"""
        from deskpilot.approval import ApprovalManager
        from deskpilot.binding import BindingManager
        from deskpilot.enforcement import Enforcement
        from deskpilot.executor import DesktopProbe, Executor
        from deskpilot.estop import EstopMonitor
        from deskpilot.freeze_notify import FreezeNotifier
        from deskpilot.httpd import HttpDaemon
        from deskpilot.tools import ToolContext
        from .conftest import FakeApprover, FakeClock

        audit_dir = tmp_path / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        notifier = FreezeNotifier(str(audit_dir), spawn=lambda *a, **k: None)
        notifier.on_state_change(False, "测试启动")
        probe = DesktopProbe()
        estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit_log,
                             on_state_change=notifier.on_state_change)
        executor = Executor(estop, str(audit_dir), probe=probe)
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
        return d, audit_dir

    def _call(self, port, tool, params, timeout=60):
        body = json.dumps({"tool": tool, "params": params}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/call",
                                     data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _attach(self, port, hwnd):
        a = self._call(port, "attach", {"hwnd": hwnd})
        assert a["ok"] is True, a
        return a["data"]["token"]

    def _cursor(self, port):
        c = self._call(port, "get_cursor", {})
        assert c["ok"] is True, c
        return (c["data"]["x"], c["data"]["y"])

    def test_cg03_real_degenerate_element_rejected(self, policy, audit_log,
                                                   tmp_path):
        """TC-CG-03:真实窗口退化 rect 元素点击 → 显式拒绝+光标零移动+不发生冻结。

        红态(现状):兜底 pixel_click(退化中心) 真实动鼠标——(0,0,0,0)
        中心=(0,0) 屏幕原点,恰为甩角判定点,可诱发冻结(问题单 §1)。
        环境自适应(iss21 ct07/iss44 ct12 同款):扫 get_ui_tree 退化
        rect 候选;具 Invoke/Select 模式的候选经非鼠标通道合法成功
        (ok=True)→ 换下一个;无可复现候选 → 环境守卫 skip。
        """
        proc, new = self._spawn_notepad()
        try:
            d, audit_dir = self._make_daemon(policy, audit_log, tmp_path)
            try:
                hwnd = new[0]["hwnd"]
                token = self._attach(d.port, hwnd)
                tree = self._call(d.port, "get_ui_tree", {"window": token})
                assert tree["ok"] is True, tree
                cands = []
                for el in tree["data"]["elements"]:
                    r = el.get("rect")
                    if r is None:
                        continue
                    if (r[2] - r[0]) <= 0 or (r[3] - r[1]) <= 0:
                        if el.get("name") or el.get("automation_id"):
                            cands.append(el)
                if not cands:
                    pytest.skip("环境守卫:真实记事本窗口无退化矩形元素")
                c0 = self._cursor(d.port)
                errored = None
                for el in cands[:10]:
                    ca = self._cursor(d.port)
                    params = {"token": token}
                    if el["name"]:
                        params["name"] = el["name"]
                    else:
                        params["automation_id"] = el["automation_id"]
                    r2 = self._call(d.port, "click_element", params)
                    cb = self._cursor(d.port)
                    assert cb == ca, (
                        f"点击退化元素 {el} 后光标移动 {ca}→{cb} → "
                        "疑似像素兜底误点(ISS-0091 缺陷机制)")
                    if not r2["ok"]:
                        errored = r2
                        break
                    # ok=True:元素具 Invoke/Select 模式,非鼠标通道合法成功
                if errored is None:
                    pytest.skip("环境守卫:退化元素均被 Invoke/Select 模式承接,"
                                "无法复现像素兜底")
                # v0.2 裁定:任一层显式拒绝皆可,不许静默成功点击
                assert errored["error_code"] in {
                    ELEMENT_RECT_DEGENERATE,   # ①退化守卫(像素兜底时刻)
                    ELEMENT_NOT_FOUND,         # ③可见性过滤层(Offscreen 时)
                }, errored
                c1 = self._cursor(d.port)
                assert c1 == c0                  # 全程光标零移动(读数直出)
                state = json.loads(
                    (audit_dir / "estop-state.json").read_text(
                        encoding="utf-8"))
                assert state["frozen"] is False  # 不误触冻结(盘上文件直读)
            finally:
                d.stop()
        finally:
            proc.terminate()
            closed = _close_all_and_wait([w["hwnd"] for w in new])
        assert closed is True, "测试残留记事本窗口(未保存关窗失败)"

    def test_cg04_normal_element_still_clickable(self, policy, audit_log,
                                                 tmp_path):
        """TC-CG-04(防过修对照):同窗正常 rect 元素仍能成功点击。

        修复前后皆绿(本用例不红)——守护 P3 的守卫/校验链不把正常
        Invoke-first/兜底路径一并打死(问题单 §4 用例4)。
        环境自适应:仅选可寻址(name/automation_id 非空)、非退化、
        interactable、完全落在窗口 rect 内、且非 Button/MenuItem
        (规避关闭/菜单语义→防未保存对话框)的控件;Edit/Document
        大面积控件优先(点击=无害聚焦)。全军覆没→断言失败(过修红)。
        """
        proc, new = self._spawn_notepad()
        try:
            d, audit_dir = self._make_daemon(policy, audit_log, tmp_path)
            try:
                hwnd = new[0]["hwnd"]
                wr = new[0]["rect"]
                token = self._attach(d.port, hwnd)
                tree = self._call(d.port, "get_ui_tree", {"window": token})
                assert tree["ok"] is True, tree

                def _addressable(el):
                    r = el.get("rect")
                    ct = el.get("control_type") or ""
                    return (bool(el.get("name") or el.get("automation_id"))
                            and r is not None
                            and (r[2] - r[0]) > 0 and (r[3] - r[1]) > 0
                            and el.get("interactable")
                            and wr[0] <= r[0] and r[2] <= wr[2]
                            and wr[1] <= r[1] and r[3] <= wr[3]
                            and ct not in ("ButtonControl", "MenuItemControl"))

                cands = [el for el in tree["data"]["elements"]
                         if _addressable(el)]
                if not cands:
                    pytest.skip("环境守卫:窗口内无可点正常元素")
                cands.sort(key=lambda el: 0 if any(
                    t in (el.get("control_type") or "")
                    for t in ("Edit", "Document")) else 1)
                clicked = None
                last = None
                for el in cands[:10]:
                    params = {"token": token}
                    if el["name"]:
                        params["name"] = el["name"]
                    else:
                        params["automation_id"] = el["automation_id"]
                    r2 = self._call(d.port, "click_element", params)
                    last = r2
                    if r2["ok"]:
                        clicked = r2
                        break
                    # 非 ok:可能同名歧义(ELEMENT_NOT_FOUND)→ 换下一个候选
                assert clicked is not None, (
                    f"正常元素全部被拒 → 疑似过修(ISS-0091 整改①③"
                    f"把正常路径打死):最后响应={last}")
                assert clicked["ok"] is True               # 响应体直出
                assert clicked["data"]["status"] == "ok"   # 数据段直出
            finally:
                d.stop()
        finally:
            proc.terminate()
            closed = _close_all_and_wait([w["hwnd"] for w in new])
        assert closed is True, "测试残留记事本窗口(未保存关窗失败)"
