"""REQ-003 TC-INT-01/02/03 + TC-GOV-03b:真机终验收(集成,--run-integration)。

层级:**集成**(零替身;真 Executor + 真 HttpDaemon + 真桌面,经 urllib POST
`/call` 驱动;断言在响应体/PIL 像素/计时)。D-12 终裁后落地:出厂检测器
`cv-contour` 零权重,真机主链无需任何权重文件——此前「TC-INT-02 须真权重」
的阻塞面随 D-12 消解(侦察方案 v0.5)。

环境守卫:TC-INT-02/03 需要一个 **UIA 全盲** 的真实窗口。优先取西柚加速器
(seeyou.exe)或企业微信(wxwork.exe)的可见窗口;都没有则 pytest.skip
(集成用例的环境依赖,与 CT-12 同规)。

断言出处:响应体逐键 / 落盘 PNG 像素直读 / 调用计时;均为被调链路直接产出。
用例来源:测试设计 v0.5 §2 TC-INT-01/02/03、TC-GOV-03b;详设 §5.1/§5.3。
"""

from __future__ import annotations

from .envguard import env_skip

import json
import time
import urllib.request

import pytest
from PIL import Image

from deskpilot.models import TOOL_BUDGET_OVERRIDES


@pytest.mark.integration
class TestIntReq03:
    """真机终验收三链路 + 预算实测。"""

    def _server(self, tmp_path, audit_log):
        """真件装配(与 test_clicktarget_iss44 TC-CT-12 同款,零替身)。"""
        from deskpilot.approval import ApprovalManager
        from deskpilot.binding import BindingManager
        from deskpilot.enforcement import Enforcement
        from deskpilot.estop import EstopMonitor
        from deskpilot.executor import DesktopProbe, Executor
        from deskpilot.executor.detector import DetectorRegistry
        from deskpilot.httpd import HttpDaemon
        from deskpilot.tools import ToolContext
        from .conftest import FakeApprover, make_policy

        policy = make_policy(audit_dir=str(tmp_path / "audit"),
                             whitelist={"notepad.exe": "L2",
                                        "explorer.exe": "L2",
                                        "wxwork.exe": "L2",
                                        "mspaint.exe": "L2"})
        estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit_log)
        executor = Executor(estop, str(tmp_path / "audit"),
                            probe=DesktopProbe(), audit=audit_log)
        # D-12 终裁:CV 线零权重——注册表真工厂接线(与 main.py 同款装配)
        executor.detector_factory = (
            lambda: DetectorRegistry().build("cv-contour"))
        probe = DesktopProbe()
        bindings = BindingManager(probe, policy.binding_ttl, time.monotonic)
        approvals = ApprovalManager(FakeApprover(), policy.approval_ttl,
                                    time.monotonic)
        enforcement = Enforcement(policy, bindings, approvals, estop,
                                  executor, audit_log)
        ctx = ToolContext(policy=policy, enforcement=enforcement,
                          bindings=bindings, executor=executor,
                          audit=audit_log)
        d = HttpDaemon(ctx, port=0)
        d.start()
        return d

    @staticmethod
    def _call(d, tool, params, timeout=60):
        body = json.dumps({"tool": tool, "params": params}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{d.port}/call", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def _find(d, process):
        r = TestIntReq03._call(d, "find_window", {"process": process})
        return [w for w in r["data"]["windows"] if w["visible"]]

    def _blind_window(self, d):
        """找一个 UIA 全盲的可见窗口(西柚/企微);没有则跳过。"""
        for proc in ("seeyou.exe", "wxwork.exe"):
            wins = self._find(d, proc)
            # 全盲判据:元素树仅窗口自身 ± 壳节点(≤4 条)
            for w in wins:
                tree = self._call(d, "get_ui_tree",
                                  {"window": w["hwnd"]})["data"]["elements"]
                if len(tree) <= 4:
                    return w
        return None

    def test_int01_detect_false_zero_change(self, tmp_path, audit_log):
        """TC-INT-01:detect 缺省路径,返回结构 = 旧键集 ∪ {coord_space},
        条目字段与编号序与基线一致(现状五键,阅读顺序)。"""
        d = self._server(tmp_path, audit_log)
        try:
            wins = self._find(d, "explorer.exe")
            pm = [w for w in wins if w["title"] == "Program Manager"]
            if not pm:
                env_skip("Program Manager 不可见")
            r = self._call(d, "get_clickable_map",
                           {"window": pm[0]["hwnd"]})
            assert r["ok"], r.get("message")
            data = r["data"]
            # 顶层 = 旧三键 ∪ {coord_space}(DET-04/§5.1)
            assert set(data) == {"path", "count", "entries", "coord_space"}
            assert data["coord_space"] == "virtual_desktop"
            # 条目 = 六键(ISS-0066 ②设计授权:双写 som_id 与 id 同值,
            # id 标废弃日程;detect=false 不加 source/confidence 不动)
            for e in data["entries"]:
                assert set(e) == {"id", "som_id", "name", "control_type",
                                  "automation_id", "rect"}
                assert e["som_id"] == e["id"]
            assert [e["id"] for e in data["entries"]] == \
                list(range(1, len(data["entries"]) + 1))
        finally:
            d.stop()

    def test_int02_detect_true_main_chain(self, tmp_path, audit_log):
        """TC-INT-02:detect=true 主链——检测条目出现且 rect 与标注框像素一致。"""
        d = self._server(tmp_path, audit_log)
        try:
            w = self._blind_window(d)
            if w is None:
                env_skip("无 UIA 全盲窗口(seeyou.exe/wxwork.exe 未开,开窗后重跑本条)")
            r = self._call(d, "get_clickable_map",
                           {"window": w["hwnd"], "detect": True})
            assert r["ok"], r.get("message")
            data = r["data"]
            detect = [e for e in data["entries"] if e["source"] == "detect"]
            assert detect, "全盲窗口须有检测条目"
            # 每条检测条目:七键、三语义键恒 null、confidence 值域
            for e in detect:
                assert set(e) == {"id", "source", "name", "control_type",
                                  "automation_id", "rect", "confidence"}
                assert e["name"] is None and e["control_type"] is None
                assert e["automation_id"] is None
                assert 0.5 <= e["confidence"] <= 0.99
            # rect 与标注框像素位置一致:图内(扣原点)边界带上存在
            # outline 色 (255,60,60) 像素(与 TC-SOM-03 同口径)
            wl, wt = w["rect"][0], w["rect"][1]
            img = Image.open(data["path"]).convert("RGB")
            px = img.load()

            def outlined(rect):
                l, t, rr, b = (rect[0] - wl, rect[1] - wt,
                               rect[2] - wl, rect[3] - wt)
                band = 4
                for y in range(max(0, t - 1), min(img.size[1], b + 1)):
                    for x in range(max(0, l - 1), min(img.size[0], rr + 1)):
                        near = (x - l < band or rr - 1 - x < band
                                or y - t < band or b - 1 - y < band)
                        if near and px[x, y][:3] == (255, 60, 60):
                            return True
                return False
            unmatched = [e["id"] for e in detect if not outlined(e["rect"])]
            assert unmatched == [], f"检测条目 rect 与图上标注不一致: {unmatched}"
        finally:
            d.stop()

    def test_int03_detect_id_misuse_protection(self, tmp_path, audit_log):
        """TC-INT-03:detect 编号调 click_element → ELEMENT_UNSUPPORTED+指引,
        且目标窗口零点击副作用(分支②在 _element_root 之前返回)。"""
        d = self._server(tmp_path, audit_log)
        try:
            # 误用防护须 L2 白名单窗口:直指企微(seeyou 未入白,闸二会先拦,
            # 测不到诊断分支)
            wins = self._find(d, "wxwork.exe")
            if not wins:
                env_skip("企微未开(误用防护须 L2 白名单盲窗)")
            w = wins[0]
            tree = self._call(d, "get_ui_tree",
                              {"window": w["hwnd"]})["data"]["elements"]
            if len(tree) > 4:
                env_skip("企微窗口 UIA 非全盲(环境异常)")
            m = self._call(d, "get_clickable_map",
                           {"window": w["hwnd"], "detect": True})
            detect = [e for e in m["data"]["entries"]
                      if e["source"] == "detect"]
            if not detect:
                env_skip("全盲窗口无检测条目")
            a = self._call(d, "attach", {"hwnd": w["hwnd"]})
            token = a["data"]["token"]
            r = self._call(d, "click_element",
                           {"token": token, "som_id": detect[0]["id"]})
            assert not r["ok"]
            assert r["error_code"] == "ELEMENT_UNSUPPORTED"
            assert "detect" in r["message"] and "rect" in r["message"]
            # 零点击副作用的取证:窗口矩形与标题在误用尝试后不变
            w2 = [x for x in self._find(d, "wxwork.exe")
                  if x["hwnd"] == w["hwnd"]]
            assert w2 and w2[0]["rect"] == w["rect"]
        finally:
            d.stop()

    def test_gov03b_budget_measured(self, tmp_path, audit_log):
        """TC-GOV-03b【回填落地】:detect=true 真机调用计时,覆盖表数字须有
        ≥2× 余量(实测 × 2 ≤ 覆盖值)。R-04 数字见侦察方案 §5。"""
        d = self._server(tmp_path, audit_log)
        try:
            w = self._blind_window(d)
            if w is None:
                env_skip("无 UIA 全盲窗口")
            self._call(d, "get_clickable_map",
                       {"window": w["hwnd"], "detect": True})   # 预热(装填)
            t0 = time.perf_counter()
            r = self._call(d, "get_clickable_map",
                           {"window": w["hwnd"], "detect": True})
            elapsed = time.perf_counter() - t0
            assert r["ok"]
            budget = TOOL_BUDGET_OVERRIDES["get_clickable_map"]
            assert elapsed * 2 <= budget, \
                f"实测 {elapsed:.2f}s × 2 余量 > 覆盖值 {budget}s(禁猜测值)"
        finally:
            d.stop()
