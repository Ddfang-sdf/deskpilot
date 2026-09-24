"""ISS-0073 入白审批证据链测试(TC-73-01~21,问题单 §5,五要素见各 docstring)。

层级:
- 单元(TestDescribe*):Enforcement.submit 公开入口;FakeExecutor 边界替身;
  可见性/采样两个读数原语打实例缝(真实桌面 Z 序不进单元层);显示名解析
  对 python.exe 的真 FileDescription 直读(不断言硬编码字符串)。
- 集成(TestRealWindow*):进程内自建 ctypes 顶层窗(注册专用窗类,用完
  DestroyWindow)+真 Executor/DesktopProbe;FakeApprover 仅作审批通道边界
  捕获(被测取证/描述链全真);真实窗口 Z 序/可见性/前台态为断言对象。

断言出处:image_path/description=FakeApprover 捕获入参直出;盘上 PNG=
Path.is_file/PIL 尺寸直读;窗口状态=IsWindowVisible/IsZoomed/
GetForegroundWindow 直读;显示名=appnames 直出;审计=read_audit JSONL 直读。

红态预期(现状):tc02(单点判据弃图)/tc03(伪归因在)/tc04(无显著无实拍
明示)/tc05(无 exe 路径)/tc05b(隐藏窗被还原)/tc05d(无窗口明细审计)/
tc06(无「已置前取证」报账)/tc11(置前失败与遮挡不可区分)/tc14~tc21
(软件级证据面缺失)红;tc01/tc05c/tc08/tc09/tc13 红期即绿(验证链/防回归钉)。
"""

from __future__ import annotations

import ctypes
import time
from pathlib import Path

import pytest

from deskpilot import errors  # noqa: F401
from deskpilot.approval import ApprovalManager
from deskpilot.binding import BindingManager
from deskpilot.enforcement import Enforcement
from deskpilot.estop import EstopMonitor
from deskpilot.models import OperationRequest
from deskpilot.secure_desktop import SecureDesktopGuard
from deskpilot.tools import ToolContext, attach

from deskpilot.audit_events import (
    EV_ENROLL_EVIDENCE_WINDOWS)
from .conftest import (FakeApprover, FakeClock, FakeExecutor, FakeProbe,
                       read_audit)

user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


# ---------- 进程内临时顶层窗(集成前提;用完销毁) ----------

class _WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", ctypes.c_void_p), ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p), ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p)]


_CLASS_NAME = "DeskPilotIss73TestWindow"
_registered = False


def _register_class() -> None:
    global _registered
    if _registered:
        return
    wc = _WNDCLASSW()
    wc.lpfnWndProc = ctypes.cast(user32.DefWindowProcW, ctypes.c_void_p)
    wc.hInstance = _kernel32.GetModuleHandleW(None)
    wc.lpszClassName = _CLASS_NAME
    user32.RegisterClassW(ctypes.byref(wc))     # 重复注册(1410)无害
    _registered = True


def _make_window(title: str, left: int, top: int, width: int, height: int,
                 *, topmost: bool = True, visible: bool = True,
                 zoomed: bool = False) -> int:
    """自建顶层窗(本进程=python.exe;默认 WS_EX_TOPMOST——发布门实证:
    用户桌面窗口(终端/浏览器)任意遮盖测试区会污染采样前提,测试窗
    置顶后前提与环境脱钩;遮挡片同为置顶且后建,仍压目标)。"""
    _register_class()
    exstyle = 0x00000008 if topmost else 0        # WS_EX_TOPMOST
    hwnd = user32.CreateWindowExW(
        exstyle, _CLASS_NAME, title, 0x00CF0000,  # WS_OVERLAPPEDWINDOW
        left, top, width, height, None, None,
        _kernel32.GetModuleHandleW(None), None)
    assert hwnd, "CreateWindowExW 失败"
    user32.ShowWindow(hwnd, 3 if zoomed else (5 if visible else 0))
    return hwnd


def _kill(hwnd: int) -> None:
    if hwnd:
        user32.DestroyWindow(hwnd)


# ---------- 装配 ----------

def _unit_rig(tmp_path, policy, audit_log, monkeypatch, *,
              windows=(), activate_ret=True, hits=5, visible=True,
              exe_path="__real__"):
    """单元装配:FakeExecutor 边界替身;_visibility_hits/_is_visible_hwnd
    两个读数原语打实例缝(单元层允许);exe_path 替身 appnames._resolve_exe。"""
    ex = FakeExecutor()
    ex.live_windows = list(windows)
    if activate_ret is not None:
        ex._activate_if_needed = lambda hwnd: activate_ret
    appr = FakeApprover()
    clock = FakeClock()
    bindings = BindingManager(FakeProbe(), policy.binding_ttl, clock)
    approvals = ApprovalManager(appr, policy.approval_ttl, clock)
    estop = EstopMonitor(policy.corner_hold_ms, clock, audit_log)
    enf = Enforcement(policy, bindings, approvals, estop, ex, audit_log)
    monkeypatch.setattr(enf, "_visibility_hits", lambda rect, hwnd: hits,
                        raising=False)   # P3 方法;红期不存在故 raising=False
    monkeypatch.setattr(enf, "_is_visible_hwnd", lambda hwnd: visible,
                        raising=False)   # 同上(单元层读数原语缝)
    if exe_path != "__real__":
        monkeypatch.setattr("deskpilot.appnames._resolve_exe",
                            lambda proc: exe_path)
    return enf, appr, ex


def _submit_attach(enf, proc="python.exe"):
    return enf.submit(OperationRequest("attach", {"process": proc}, None))


def _last_req(appr):
    assert appr.requests, "审批通道未收到请求"
    return appr.requests[-1]


def _real_ctx(tmp_path, policy, audit_log):
    """集成装配:真 Executor/DesktopProbe;FakeApprover 仅审批通道边界。"""
    from deskpilot.executor import DesktopProbe, Executor
    from deskpilot.audit import AuditLogger

    audit = AuditLogger(str(tmp_path / "audit"))
    estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit)
    ex = Executor(estop, str(tmp_path / "audit"), probe=DesktopProbe())
    clock = FakeClock()
    bindings = BindingManager(DesktopProbe(), policy.binding_ttl, clock)
    appr = FakeApprover()
    approvals = ApprovalManager(appr, policy.approval_ttl, clock)
    enf = Enforcement(policy, bindings, approvals, estop, ex, audit)
    ctx = ToolContext(policy=policy, enforcement=enf, bindings=bindings,
                      executor=ex, audit=audit,
                      secure_guard=SecureDesktopGuard(detector=lambda: False))
    return ctx, appr, ex


# ---------- 单元层:描述措辞与软件级证据 ----------

class TestDescribeHonesty:
    """TC-73-03/04/05b/06/11:措辞纠偏+诚实失败态+置前报账+成败区分。"""

    def test_tc03_no_pseudo_alarm_wording(self, tmp_path, policy, audit_log,
                                          monkeypatch):
        """TC-73-03:取证失败的描述不含伪归因「目标无法前置」。
        红态(现状):失败分支原文即「实拍存疑:目标无法前置,未截图」。"""
        enf, appr, _ex = _unit_rig(
            tmp_path, policy, audit_log, monkeypatch,
            windows=[{"hwnd": 998877, "title": "甲", "process": "python.exe",
                      "rect": [0, 0, 200, 200]}],
            hits=0)
        _submit_attach(enf)
        desc = _last_req(appr)["description"]
        assert "目标无法前置" not in desc         # 伪归因剔除(直出)

    def test_tc04_no_window_honest_statement(self, tmp_path, policy, audit_log,
                                             monkeypatch):
        """TC-73-04:反查不到窗口 → 以软件为主语如实陈述+「无实拍」显著明示。
        红态(现状):「未找到目标窗口,未截图」无显著无实拍标记。"""
        enf, appr, _ex = _unit_rig(tmp_path, policy, audit_log, monkeypatch,
                                   windows=[])
        _submit_attach(enf)
        desc = _last_req(appr)["description"]
        assert "未找到目标软件" in desc           # 软件为主语(直出)
        assert "本次无实拍" in desc               # 显著明示(直出)
        assert "目标无法前置" not in desc

    def test_tc05b_hidden_windows_not_presented(self, tmp_path, policy,
                                                audit_log, monkeypatch):
        """TC-73-05b(§2.1b D′):软件仅存隐藏窗 → 不取证不置前,描述如实
        陈述「无可见窗口」。红态(现状):ShowWindow 还原隐藏窗+「已还原窗口」。"""
        enf, appr, ex = _unit_rig(
            tmp_path, policy, audit_log, monkeypatch,
            windows=[{"hwnd": 998877, "title": "托盘窗", "process": "python.exe",
                      "rect": [0, 0, 200, 200]}],
            visible=False)
        _submit_attach(enf)
        desc = _last_req(appr)["description"]
        assert "无可见窗口" in desc               # 如实陈述(直出)
        assert "本次无实拍" in desc
        assert ex.approval_shot_rects == []     # 未取图(替身记录直出)

    def test_tc06_forefront_reported(self, tmp_path, policy, audit_log,
                                     monkeypatch):
        """TC-73-06(Q2 报账):置前取证成功 → 文案显式声明「已置前取证」。
        红态(现状):「已前置实拍」——无「取证」报账语。"""
        enf, appr, _ex = _unit_rig(
            tmp_path, policy, audit_log, monkeypatch,
            windows=[{"hwnd": 998877, "title": "甲", "process": "python.exe",
                      "rect": [0, 0, 200, 200]}],
            hits=5)
        _submit_attach(enf)
        desc = _last_req(appr)["description"]
        assert "已置前取证" in desc               # 报账语(直出)

    def test_tc11_activate_failure_distinguished(self, tmp_path, policy,
                                                 audit_log, monkeypatch):
        """TC-73-11(§2.5 E′):置前失败 ∧ 置前成功但被遮挡 → 两种描述
        互不相等且各含其状态词。红态(现状):返回值被丢弃,两句同为
        「目标无法前置」→ 相等立红。"""
        wins = [{"hwnd": 998877, "title": "甲", "process": "python.exe",
                 "rect": [0, 0, 200, 200]}]
        enf1, appr1, _ = _unit_rig(tmp_path, policy, audit_log, monkeypatch,
                                   windows=wins, activate_ret=False, hits=0)
        _submit_attach(enf1)
        d_fail = _last_req(appr1)["description"]
        enf2, appr2, _ = _unit_rig(tmp_path / "b", policy, audit_log,
                                   monkeypatch, windows=wins,
                                   activate_ret=True, hits=0)
        _submit_attach(enf2)
        d_occl = _last_req(appr2)["description"]
        assert d_fail != d_occl                   # 两态可区分(直出)
        assert "未能置前" in d_fail               # 置前未成功(直出)
        assert "遮挡" in d_occl                   # 置前成功但遮挡(直出)


class TestSoftwareLevelEvidence:
    """TC-73-05/05c/05d/14~21:软件级定位底牌+显示名重排+自报标注+路径形态。"""

    def test_tc05_exe_path_and_proc_no_hwnd(self, tmp_path, policy, audit_log,
                                            monkeypatch):
        """TC-73-05(B):描述含 exe 路径与进程名;不含 hwnd 数值(窗口级
        标识不进人类裁决面)。红态(现状):无路径字段。"""
        enf, appr, _ex = _unit_rig(
            tmp_path, policy, audit_log, monkeypatch,
            windows=[{"hwnd": 998877, "title": "甲", "process": "python.exe",
                      "rect": [0, 0, 200, 200]}])
        _submit_attach(enf)
        desc = _last_req(appr)["description"]
        assert "python.exe" in desc               # 进程名(直出)
        assert "\\" in desc and "程序路径" in desc  # exe 路径字段(直出)
        assert "998877" not in desc               # hwnd 不入文案(反向断言)

    def test_tc05c_sibling_windows_not_listed(self, tmp_path, policy,
                                              audit_log, monkeypatch):
        """TC-73-05c(Q3):同进程多窗口(含隐藏/幽灵)不出清单——描述不含
        其他窗口标题。红期即绿(防回归钉:清单形态从未存在,保持不存在)。"""
        enf, appr, _ex = _unit_rig(
            tmp_path, policy, audit_log, monkeypatch,
            windows=[{"hwnd": 1, "title": "甲窗", "process": "python.exe",
                      "rect": [0, 0, 200, 200]},
                     {"hwnd": 2, "title": "乙窗隐藏", "process": "python.exe",
                      "rect": [0, 0, 200, 200]},
                     {"hwnd": 3, "title": "丙窗幽灵", "process": "python.exe",
                      "rect": [0, 0, 200, 200]}],
            hits=5)
        _submit_attach(enf)
        desc = _last_req(appr)["description"]
        assert "乙窗隐藏" not in desc             # 不列清单(反向断言直出)
        assert "丙窗幽灵" not in desc

    def test_tc05d_window_details_audit_only(self, tmp_path, policy,
                                             audit_log, monkeypatch):
        """TC-73-05d(§2.1b 审计/裁决分离):窗口级明细入审计 JSONL,
        不进弹窗描述。红态(现状):无「入白取证窗口明细」审计事件。"""
        enf, appr, _ex = _unit_rig(
            tmp_path, policy, audit_log, monkeypatch,
            windows=[{"hwnd": 1, "title": "甲窗", "process": "python.exe",
                      "rect": [0, 0, 200, 200]}],
            hits=5)
        _submit_attach(enf)
        events = [e.get("event") for e in read_audit(str(tmp_path / "audit"))]
        assert EV_ENROLL_EVIDENCE_WINDOWS in events       # 审计直读
        assert "hwnd" not in _last_req(appr)["description"]  # 弹窗不含(直出)

    def test_tc14_four_items_present(self, tmp_path, policy, audit_log,
                                     monkeypatch):
        """TC-73-14(§2.1b 主体归位):描述独立支撑「这是个什么软件」=
        显示名+来源+exe 路径+进程名四项齐全。红态(现状):无路径无标注。"""
        from deskpilot.appnames import _file_string, _resolve_exe
        fd = _file_string(_resolve_exe("python.exe"), "FileDescription")
        if not fd:
            pytest.skip("环境守卫:python.exe 无 FileDescription")
        enf, appr, _ex = _unit_rig(
            tmp_path, policy, audit_log, monkeypatch,
            windows=[{"hwnd": 1, "title": "某标题", "process": "python.exe",
                      "rect": [0, 0, 200, 200]}])
        _submit_attach(enf)
        desc = _last_req(appr)["description"]
        assert f"「{fd}」" in desc                # 显示名=FD(直读 FD 原文)
        assert "显示名来源" in desc               # 来源字段(直出)
        assert _resolve_exe("python.exe") in desc  # exe 全路径原文(直出)
        assert "python.exe" in desc               # 进程名(直出)

    def test_tc15_file_description_outranks_title(self, tmp_path, policy,
                                                  audit_log, monkeypatch):
        """TC-73-15(Q4 ③,红→绿):FD 与标题不同 → 显示名取 FD,
        来源=版本信息。红态(现状):标题优先(「某标题」上主标题)。"""
        from deskpilot.appnames import _file_string, _resolve_exe
        fd = _file_string(_resolve_exe("python.exe"), "FileDescription")
        if not fd or fd == "某标题":
            pytest.skip("环境守卫:python.exe FileDescription 不可用")
        enf, appr, _ex = _unit_rig(
            tmp_path, policy, audit_log, monkeypatch,
            windows=[{"hwnd": 1, "title": "某标题", "process": "python.exe",
                      "rect": [0, 0, 200, 200]}])
        _submit_attach(enf)
        desc = _last_req(appr)["description"]
        headline = desc.partition("\n---\n")[0]
        assert f"「{fd}」" in headline            # FD 上主标题(直出)
        assert "某标题" not in headline
        assert "显示名来源：版本信息" in desc      # 来源直出

    def test_tc16_self_report_annotation_title_kept(self, tmp_path, policy,
                                                    audit_log, monkeypatch):
        """TC-73-16(Q4 ②):自报来源诚实标注入描述;标题值仍出现
        (辅助线索,不得抹掉)。红态(现状):无标注语。"""
        enf, appr, _ex = _unit_rig(
            tmp_path, policy, audit_log, monkeypatch,
            windows=[{"hwnd": 1, "title": "某标题", "process": "python.exe",
                      "rect": [0, 0, 200, 200]}])
        _submit_attach(enf)
        desc = _last_req(appr)["description"]
        assert "自报" in desc or "未经系统核验" in desc   # 标注语(直出)
        assert "某标题" in desc                     # 标题仍在(反向不失信息)

    def test_tc17_no_fd_falls_back_to_title(self, tmp_path, policy, audit_log,
                                            monkeypatch):
        """TC-73-17(Q4 ③ 边界):无 FD 有标题 → 标题,来源如实标窗口标题。"""
        enf, appr, _ex = _unit_rig(
            tmp_path, policy, audit_log, monkeypatch,
            windows=[{"hwnd": 1, "title": "标题甲", "process": "no-such-xyz.exe",
                      "rect": [0, 0, 200, 200]}])
        _submit_attach(enf, proc="no-such-xyz.exe")
        desc = _last_req(appr)["description"]
        assert "「标题甲」" in desc
        assert "显示名来源：窗口标题" in desc
        assert "自报" in desc or "未经系统核验" in desc

    def test_tc18_nothing_falls_back_to_procname(self, tmp_path, policy,
                                                 audit_log, monkeypatch):
        """TC-73-18(Q4 ③ 边界):皆无 → 进程名兜底,来源如实标进程名。"""
        enf, appr, _ex = _unit_rig(tmp_path, policy, audit_log, monkeypatch,
                                   windows=[])
        _submit_attach(enf, proc="no-such-xyz.exe")
        desc = _last_req(appr)["description"]
        assert "「no-such-xyz.exe」" in desc
        assert "显示名来源：进程名" in desc

    def test_tc19_full_exe_path_verbatim(self, tmp_path, policy, audit_log,
                                         monkeypatch):
        """TC-73-19(T1):描述含 exe 全路径原文(非纯基名)。红态(现状):
        无路径字段。"""
        from deskpilot.appnames import _resolve_exe
        full = _resolve_exe("python.exe")
        if not full:
            pytest.skip("环境守卫:python.exe 路径不可解析")
        enf, appr, _ex = _unit_rig(tmp_path, policy, audit_log, monkeypatch,
                                   windows=[])
        _submit_attach(enf)
        desc = _last_req(appr)["description"]
        assert full in desc                       # 全路径原文(直出)
        import os
        assert os.path.dirname(full) in desc      # 目录部分在(非纯基名)

    def test_tc20_long_path_middle_elided(self, tmp_path, policy, audit_log,
                                          monkeypatch):
        """TC-73-20(T1 截断策略确定):超长路径中段省略——盘符前缀+文件名
        结尾保留,长度 ≤80(单行容量)。红态(现状):无路径字段。"""
        long_path = "C:\\" + "很长目录\\" * 12 + "seeyou.exe"
        enf, appr, _ex = _unit_rig(tmp_path, policy, audit_log, monkeypatch,
                                   windows=[], exe_path=long_path)
        _submit_attach(enf, proc="seeyou.exe")
        desc = _last_req(appr)["description"]
        marker = "程序路径："
        assert marker in desc
        seg = desc.split(marker, 1)[1].split("。", 1)[0]
        assert seg.startswith("C:\\")             # 盘符前缀保留(直出)
        assert seg.endswith(".exe")               # 文件名结尾保留(直出)
        assert len(seg) <= 80                     # 单行容量(直出)

    def test_tc21_path_unavailable_honest_blank(self, tmp_path, policy,
                                                audit_log, monkeypatch):
        """TC-73-21(T1 fail-closed):路径取不到 → 如实缺省「未取得」,
        不用进程名冒充路径。红态(现状):无路径字段。"""
        enf, appr, _ex = _unit_rig(tmp_path, policy, audit_log, monkeypatch,
                                   windows=[], exe_path=None)
        _submit_attach(enf, proc="no-such-xyz.exe")
        desc = _last_req(appr)["description"]
        assert "程序路径：未取得" in desc          # 如实缺省(直出)
        seg = desc.split("程序路径：", 1)[1].split("。", 1)[0]
        assert "\\" not in seg                    # 不冒充(反向断言)
        assert "no-such-xyz.exe" in desc          # 进程名仍单独在


# ---------- 集成层:真实窗口取证链 ----------

class TestRealWindowCapture:
    """TC-73-01/02/07/09/10/12/13:真窗口 Z 序/可见性/几何下的取证行为。"""

    def test_tc01_visible_unoccluded_shot(self, tmp_path, policy, audit_log):
        """TC-73-01(集成):可见未遮挡 → image_path 非空且文件存在。
        红期即绿(验证链:修复前后都应出图)。TC-73-07 同案断言受管目录前缀。"""
        ctx, appr, _ex = _real_ctx(tmp_path, policy, audit_log)
        hwnd = _make_window("ISS73-TC01", 300, 300, 420, 320)
        try:
            time.sleep(0.3)                     # 窗口管理器就位
            r = attach(ctx, hwnd=hwnd)
            assert r.ok is False                # 未入白→审批拒绝(deny)
            req = _last_req(appr)
            assert req["image_path"]            # 捕获入参直出
            p = Path(req["image_path"])
            assert p.is_file()                  # 盘上 PNG 直读
            assert str(p).startswith(str(tmp_path / "audit"))  # TC-73-07
            assert "shots" in str(p)
        finally:
            _kill(hwnd)

    def test_tc02_partial_occlusion_still_shots(self, tmp_path, policy,
                                                audit_log):
        """TC-73-02(Q1 五点采样,现场复现):中心被压、四角可见 → 仍出图。
        红态(现状):中心单点判据零容忍 → 两次重试弃图,image_path=None。
        遮挡片 49×49(短边 <50):恰好压采样点又不入取证候选池
        (生产语义:微小窗不作软件证据面),目标仍是 onscreen[0]。"""
        ctx, appr, _ex = _real_ctx(tmp_path, policy, audit_log)
        # 目标置顶(对抗环境:用户 Chrome 置顶窗实测覆盖底角);遮挡片同置顶
        # 且后建→压中心不动。诚实注记:置前取证(Q2)可能重排置顶组,
        # 本用例断言「部分遮挡不吞图」的终效应;过半判据的零命中边界由
        # tc09 守住(目标不置顶,激活不翻身)
        target = _make_window("ISS73-TC02", 300, 300, 420, 320, topmost=True)
        # 中心点 (510,460);topmost 遮挡片只压中心(激活目标后仍压顶)
        occ = _make_window("ISS73-TC02-OCC", 486, 436, 49, 49, topmost=True)
        try:
            time.sleep(0.3)
            r = attach(ctx, hwnd=target)
            assert r.ok is False
            req = _last_req(appr)
            assert req["image_path"], "部分遮挡应出图(五点过半)"
            assert Path(req["image_path"]).is_file()
        finally:
            _kill(occ)
            _kill(target)

    def test_tc09_full_occlusion_no_shot(self, tmp_path, policy, audit_log):
        """TC-73-09(fail-closed 守住):五点归属全败 → 仍不给图,
        描述明示无实拍。红期行为面即绿(不出图禁令钉);「本次无实拍」
        明示措辞为新增断言(红驱动)。
        前提构造:五片 49×49 topmost 遮挡片各压一个采样点(四角内缩
        max(4,边长/8)+中心,与判据公式同前提;遮挡片因微小尺寸不入
        取证候选池)。"""
        ctx, appr, _ex = _real_ctx(tmp_path, policy, audit_log)
        # 目标不置顶(同 tc02:置顶会在置前取证时压过遮挡片,毁掉五点全败前提)
        target = _make_window("ISS73-TC09", 300, 300, 420, 320, topmost=False)
        # 采样点:中心(510,460);四角内缩 ix=52/iy=40 → (352,340)(668,340)
        # (352,580)(668,580)
        pts = [(510, 460), (352, 340), (668, 340), (352, 580), (668, 580)]
        occs = [_make_window(f"ISS73-TC09-OCC{i}", x - 24, y - 24, 49, 49,
                             topmost=True) for i, (x, y) in enumerate(pts)]
        try:
            time.sleep(0.3)
            r = attach(ctx, hwnd=target)
            assert r.ok is False
            req = _last_req(appr)
            assert req["image_path"] is None    # 完全遮挡不出图(直出)
            assert "本次无实拍" in req["description"]
        finally:
            for o in occs:
                _kill(o)
            _kill(target)

    def test_tc10_hidden_only_never_restored(self, tmp_path, policy,
                                             audit_log):
        """TC-73-10(§2.1b D′,防回归):软件窗口最小化到托盘(西柚现场形态:
        可见标志真但矩形在屏外 -32000)→ 不还原/不置前/不截图;
        IsIconic 仍真、前台窗不变。红态(现状):ShowWindow(9) 还原
        → IsIconic 变假立红。
        前提注:SW_HIDE 隐藏窗在 attach 的 find 阶段即不可见(默认不含
        隐藏窗),生产上触发该分支的真实形态=最小化(单据 §1 西柚案)。"""
        ctx, appr, _ex = _real_ctx(tmp_path, policy, audit_log)
        hwnd = _make_window("ISS73-TC10", 300, 300, 420, 320)
        try:
            time.sleep(0.2)
            user32.ShowWindow(hwnd, 6)          # SW_MINIMIZE(最小化=托盘形态)
            time.sleep(0.2)
            assert user32.IsIconic(hwnd) != 0   # 前提:已最小化(直读)
            fg_before = user32.GetForegroundWindow()
            r = attach(ctx, hwnd=hwnd)
            assert r.ok is False
            req = _last_req(appr)
            assert req["image_path"] is None    # 不取证(直出)
            assert "无可见窗口" in req["description"]
            assert user32.IsIconic(hwnd) != 0   # 未被拽回(系统态直读)
            assert user32.GetForegroundWindow() == fg_before  # 前台未变
        finally:
            _kill(hwnd)

    def test_tc12_zoomed_window_not_restored(self, tmp_path, policy,
                                             audit_log, monkeypatch):
        """TC-73-12(§2.5 E″):executor 缺 _activate_if_needed(遗留分支)
        时兜底激活走状态自适应——最大化窗 IsZoomed 仍真,不被 SW_RESTORE
        打回。红态(现状):兜底硬编码 ShowWindow(hwnd,9) → 最大化被打回。
        装配注:executor 边界替身缺该方法=用例前提(单据 §2.5);窗口为真
        ctypes 最大化窗(IsZoomed 为系统态直读,不可替身)。"""
        class _BareExec:
            """缺 _activate_if_needed 的最小执行层替身(用例前提)。"""
            def __init__(self, windows):
                self._w = windows
                self.shots = []
            def find_windows(self, **_k):
                return list(self._w)
            def capture_approval_shot(self, rect):
                self.shots.append(rect)
                return "shot.png"

        hwnd = _make_window("ISS73-TC12", 100, 100, 500, 400, zoomed=True)
        try:
            time.sleep(0.3)
            assert user32.IsZoomed(hwnd) != 0     # 前提:已最大化(直读)
            wins = [{"hwnd": hwnd, "title": "ISS73-TC12",
                     "process": "python.exe",
                     "rect": list(_window_rect(hwnd))}]
            ex = _BareExec(wins)
            appr = FakeApprover()
            clock = FakeClock()
            bindings = BindingManager(FakeProbe(), policy.binding_ttl, clock)
            approvals = ApprovalManager(appr, policy.approval_ttl, clock)
            estop = EstopMonitor(policy.corner_hold_ms, clock, audit_log)
            enf = Enforcement(policy, bindings, approvals, estop, ex,
                              audit_log)
            _submit_attach(enf)
            assert user32.IsZoomed(hwnd) != 0   # 最大化未被打回(直读)
        finally:
            _kill(hwnd)

    def test_tc13_second_screen_shot(self, tmp_path, policy, audit_log):
        """TC-73-13(集成):副屏目标取到副屏画面——PNG 尺寸与 find_windows
        所报 rect 一致(非主屏错位图)。环境守卫:单屏机 skip。
        红期即绿(虚拟坐标系既有能力钉)。

        ISS-0113 ②(环境不变量改造):几何断言改经
        executor.capture_approval_shot(rect) 直取——enforcement 链末端
        同一生产函数(mss 虚拟坐标实拍,无前台置前/五点采样门控);
        钉语义(副屏取图几何)零削减,摘除对实时桌面 z-order 的依赖
        (ISS-0062 v0.5⑧ 实测敏感:另一置顶窗/前台竞争盖住采样点即
        hits<3 无图而红);attach 拒绝链保留(环境无关),前台/采样
        链路的覆盖在 tc01。"""
        from deskpilot.monitors import enum_monitors
        mons = enum_monitors()
        if len(mons) < 2:
            pytest.skip("环境守卫:单屏机无副屏")
        sec = mons[1]["rect"]
        ctx, appr, ex = _real_ctx(tmp_path, policy, audit_log)
        hwnd = _make_window("ISS73-TC13", sec[0] + 60, sec[1] + 60, 400, 300)
        try:
            time.sleep(0.3)
            r = attach(ctx, hwnd=hwnd)
            assert r.ok is False                # 未入白→审批拒绝(环境无关)
            from PIL import Image
            from deskpilot.executor import DesktopProbe
            w = [w for w in DesktopProbe().find_windows(hwnd=hwnd)
                 if w["hwnd"] == hwnd][0]
            rw = w["rect"][2] - w["rect"][0]
            rh = w["rect"][3] - w["rect"][1]
            shot = ex.capture_approval_shot(w["rect"])  # 链末端同一生产函数
            assert Image.open(shot).size == (rw, rh)    # 副屏几何直读
        finally:
            _kill(hwnd)


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


class TestBoundPathRegression:
    """TC-73-08:有绑定 L3 审批取证不回退(防过修钉)。"""

    def test_tc08_bound_l3_capture_unchanged(self, tmp_path, policy,
                                             audit_log, monkeypatch):
        """TC-73-08(单元钉):绑定路径取图=binding.window_rect 直拍,
        不经反查/采样。红期即绿(既有语义钉)。"""
        ex = FakeExecutor()
        appr = FakeApprover()
        appr.decision = "approve"
        clock = FakeClock()
        probe = FakeProbe()
        bindings = BindingManager(probe, policy.binding_ttl, clock)
        approvals = ApprovalManager(appr, policy.approval_ttl, clock)
        estop = EstopMonitor(policy.corner_hold_ms, clock, audit_log)
        enf = Enforcement(policy, bindings, approvals, estop, ex, audit_log)
        from .conftest import FIXTURE_HWND, FIXTURE_RECT
        rec = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        d = enf.submit(OperationRequest(
            "key", {"key": "delete"}, rec.token))   # delete=L3 受控键
        assert d.allowed is True                  # 批准后放行(直出)
        assert ex.approval_shot_rects == [tuple(FIXTURE_RECT)]  # 绑定矩形直拍
