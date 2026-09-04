"""ISS-0021 click_text 测试(TC-CT-01~08,问题单 §4/§5 v0.2 评审通过)。

层级:TC-CT-01~06 单元(resolve_click 纯函数,合成 items,断言全在返回值);
TC-CT-07/08 集成(真 HttpDaemon+真记事本+真 OCR,断言在 HTTP 响应体/落点)。
入口(设计):executor.textclick.resolve_click / screenshot data / POST /call click_text。

设计修正(v0.2 实施细化,已记录):index 默认 None=未指定——否则
"多命中未指定→OCR_AMBIGUOUS"分支永不可达(默认 0 与显式 0 不可分)。
"""

from __future__ import annotations

import json
import time
import urllib.request

import pytest

from deskpilot import errors
from deskpilot.executor.textclick import resolve_click

from .test_uia_com_iss16 import _close_all_and_wait

RECT = (1000, 1000, 1800, 1600)          # 绑定窗 rect 800×600
ITEMS = [{"text": "保存文档", "position": [100, 50, 160, 80]}]


class TestResolveClickUnit:
    """TC-CT-01~06:OCR items→点击坐标/失败分类(返回值直出)。"""

    def test_ct01_single_hit_coordinates(self):
        """TC-CT-01:单命中 → 框中心+rect 偏移(scale 1:1)。"""
        status, payload = resolve_click(ITEMS, "保存", "contains", None,
                                        800, 600, RECT)
        assert status == "ok"
        assert payload["point"] == (1130, 1065)        # (1000+130, 1000+65)
        assert payload["matched"] == "保存文档"

    def test_ct02_scale_mapping(self):
        """TC-CT-02:图像 400×300、rect 800×600(scale=2) → 坐标翻倍。"""
        items = [{"text": "保存", "position": [50, 25, 80, 40]}]
        status, payload = resolve_click(items, "保存", "contains", None,
                                        400, 300, RECT)
        assert status == "ok"
        assert payload["point"] == (1000 + 130, 1000 + 64)   # 中心(65,32)×2

    def test_ct03_not_found_fail_closed(self):
        """TC-CT-03:无命中 → not_found + OCR 文本摘要。"""
        status, payload = resolve_click(ITEMS, "不存在词", "contains", None,
                                        800, 600, RECT)
        assert status == "not_found"
        assert "保存文档" in payload                     # 摘要含可见文本

    def test_ct04_ambiguous_then_index(self):
        """TC-CT-04:多命中未指定 → ambiguous+坐标列;指定 index=1 → 第二处。"""
        items = [{"text": "保存", "position": [0, 0, 10, 10]},
                 {"text": "另存", "position": [100, 100, 110, 110]},
                 {"text": "保存为", "position": [200, 200, 210, 210]}]
        status, payload = resolve_click(items, "保存", "contains", None,
                                        800, 600, RECT)
        assert status == "ambiguous"
        assert len(payload) == 2                         # 两处"保存*"(含/另存?)
        status2, payload2 = resolve_click(items, "保存", "contains", 1,
                                          800, 600, RECT)
        assert status2 == "ok"
        # index=1 命中第二处(200,200,210,210)中心(205,205),scale 1:1:
        assert payload2["point"] == (1000 + 205, 1000 + 205)

    def test_ct05_empty_text_invalid(self):
        """TC-CT-05:空文本 → invalid(不放行)。"""
        status, _ = resolve_click(ITEMS, "", "contains", None, 800, 600, RECT)
        assert status == "invalid"

    def test_ct06_out_of_window_rejected(self):
        """TC-CT-06:OCR 框越出图像边界(数据异常) → out_of_window。"""
        items = [{"text": "保存", "position": [790, 590, 900, 700]}]
        status, _ = resolve_click(items, "保存", "contains", None,
                                  800, 600, RECT)
        assert status == "out_of_window"


@pytest.mark.integration
class TestClickTextIntegration:
    """TC-CT-07/08:真 daemon+真记事本。断言:HTTP 响应体(外表面直出)。"""

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

    def _make_daemon(self, policy, audit_log, tmp_path, ocr_factory=None):
        from deskpilot.approval import ApprovalManager
        from deskpilot.binding import BindingManager
        from deskpilot.enforcement import Enforcement
        from deskpilot.executor import DesktopProbe, Executor
        from deskpilot.estop import EstopMonitor
        from deskpilot.httpd import HttpDaemon
        from deskpilot.tools import ToolContext
        from .conftest import FakeApprover, FakeClock

        probe = DesktopProbe()
        estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit_log)
        executor = Executor(estop, str(tmp_path / "audit"), probe=probe)
        if ocr_factory is not None:
            executor.ocr_factory = ocr_factory
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

    def test_ct07_screenshot_coord_metadata(self, policy, audit_log, tmp_path):
        """TC-CT-07:screenshot scope=window 带坐标系元数据且数值自洽。"""
        proc, new = self._spawn_notepad()
        try:
            d = self._make_daemon(policy, audit_log, tmp_path)
            try:
                r = self._call(d.port, "screenshot",
                               {"scope": "window", "window": new[0]["hwnd"]})
                assert r["ok"] is True
                data = r["data"]
                for k in ("width", "height", "virtual_rect",
                          "scale_x", "scale_y"):
                    assert k in data, k
                vr = data["virtual_rect"]
                assert abs(data["scale_x"] * data["width"]
                           - (vr[2] - vr[0])) <= 1       # 数值自洽(直出)
                assert abs(data["scale_y"] * data["height"]
                           - (vr[3] - vr[1])) <= 1
            finally:
                d.stop()
        finally:
            proc.terminate()
            closed = _close_all_and_wait([w["hwnd"] for w in new])
        # 卫生断言(泄漏即红):打字类测试同样零残留
        assert closed is True, "测试残留记事本窗口(未保存关窗失败)"

    def test_ct08_real_ocr_click(self, policy, audit_log, tmp_path):
        """TC-CT-08:真 OCR 点击独特字符串 → ok 且落点在窗口 rect 内。"""
        proc, new = self._spawn_notepad()
        try:
            def real_ocr():
                from rapidocr_onnxruntime import RapidOCR
                from deskpilot.main import _build_ocr_engine
                return _build_ocr_engine(RapidOCR())

            d = self._make_daemon(policy, audit_log, tmp_path,
                                  ocr_factory=real_ocr)
            try:
                a = self._call(d.port, "attach",
                               {"hwnd": new[0]["hwnd"]})   # 按句柄(进程多窗)
                assert a["ok"] is True, a.get("message")
                token = a["data"]["token"]
                # 会话恢复会带回历史运行键入的内容(Store 记事本特性),
                # 魔法串逐次唯一;type_text 双贴缺陷已由 ISS-0035 修复
                # (读回轮询确认)——同串必须唯一,多命中(AMBIGUOUS)即红:
                # 本用例兼任双贴回归探测器。ctrl+end+\r\n 让魔法串独占
                # 行(恢复文档可能把历次串拼成巨行,吞并 OCR 条目)
                k = self._call(d.port, "key",
                               {"token": token, "key": "ctrl+end"})
                assert k["ok"] is True, k.get("message")
                magic = f"dp测试串{int(time.time()) % 100000}"
                t = self._call(d.port, "type_text",
                               {"token": token, "text": "\r\n" + magic})
                assert t["ok"] is True, t.get("message")
                time.sleep(0.5)
                c = self._call(d.port, "click_text",
                               {"token": token, "text": magic}, timeout=120)
                assert c["ok"] is True, c.get("message")
                tx, ty = c["data"]["target"]
                rect = new[0]["rect"]
                assert rect[0] <= tx <= rect[2]          # 落点在窗内(直出)
                assert rect[1] <= ty <= rect[3]
            finally:
                d.stop()
        finally:
            proc.terminate()
            closed = _close_all_and_wait([w["hwnd"] for w in new])
        # 卫生断言(泄漏即红):打字类测试同样零残留
        assert closed is True, "测试残留记事本窗口(未保存关窗失败)"
