"""ISS-0020 审批可读性测试（TC-READ-01~07,问题单 §4）。

层级：单元（conftest 装配/替身直出）。
入口（设计）：enforcement._describe / _capture_target / 审计事件。
"""

from __future__ import annotations


from deskpilot.audit_events import (
    EV_APPROVAL_SHOT_FAILED)

import pytest

from deskpilot.models import OperationRequest


def _describe(enforcement, tool, params, binding=None):
    return enforcement._describe(OperationRequest(tool, params, None), binding)


@pytest.fixture(autouse=True)
def _pin_zh(pin_zh_locale):
    """ISS-0111:本族断言中文语义面,显式钉 zh-CN 环境(CI en-US 面免疫)。"""


class TestContentHeadline:
    """TC-READ-01~05:内容进主标题;超长截断;坐标;key/launch 回归。
    断言:_describe 返回 headline/tech 文本(直出)。"""

    def test_read01_type_text_headline_has_text(self, enforcement):
        """TC-READ-01:type_text 主标题含命令文本。"""
        d = _describe(enforcement, "type_text",
                      {"text": "git push origin main"})
        headline = d.partition("\n---\n")[0]
        assert "git push origin main" in headline

    def test_read02_long_text_truncated(self, enforcement):
        """TC-READ-02:>60 字截断,以 … 结尾,标注总长。"""
        d = _describe(enforcement, "type_text", {"text": "x" * 100})
        headline = d.partition("\n---\n")[0]
        assert len(headline) <= 63 + 12 or "共" in headline
        assert "…" in headline
        assert "共 100 字" in headline

    def test_read03_set_clipboard_has_summary(self, enforcement):
        """TC-READ-03:set_clipboard 主标题含内容摘要与总长。"""
        d = _describe(enforcement, "set_clipboard",
                      {"text": "https://example.com/" + "a" * 80})
        headline = d.partition("\n---\n")[0]
        assert "https://example.com/" in headline
        assert "共" in headline

    def test_read04_click_has_coordinates(self, enforcement):
        """TC-READ-04:click 主标题含坐标。"""
        d = _describe(enforcement, "click", {"x": 1008, "y": 522})
        headline = d.partition("\n---\n")[0]
        assert "(1008, 522)" in headline

    def test_read05_key_launch_regression(self, enforcement):
        """TC-READ-05:key/launch 主标题语义回归。"""
        dk = _describe(enforcement, "key", {"key": "alt+f4"})
        assert "关闭窗口" in dk.partition("\n---\n")[0] or \
            "alt+f4" in dk.partition("\n---\n")[0]
        dl = _describe(enforcement, "launch_app", {"app": "calc.exe"})
        assert "启动应用" in dl.partition("\n---\n")[0]


class TestCaptureReverseLookup:
    """TC-READ-06/07:无绑定按进程反查实拍;取图失败留痕。
    断言:返回路径/调用记录/审计事件(直出)。

    实拍契约(用户钦定四步):找到窗口→前置→验证无遮挡→才截图;
    任一步失败不给错图,底注明示(fail-closed)。"""

    def test_read06_reverse_lookup_returns_shot(self, enforcement, executor,
                                                monkeypatch):
        """TC-READ-06:反查命中可见窗 → 先置前后截图(顺序直出),返回实拍路径。
        ISS-0073 适配:可见性改 IsWindowVisible 实测,假 hwnd 须打缝
        (单元层读数原语;真实可见性由 test_enrollshot_iss73 集成层覆盖)。"""
        import deskpilot.enforcement as enf_mod
        executor.live_windows = [{"hwnd": 424242, "title": "目标",
                                  "process": "x.exe", "rect": (0, 0, 100, 100),
                                  "visible": True}]
        monkeypatch.setattr(enforcement, "_is_visible_hwnd",
                            lambda hwnd: True)            # 假 hwnd 可见性缝
        monkeypatch.setattr(enf_mod.ctypes.windll.user32, "WindowFromPoint",
                            lambda pt: 424242)            # 采样点顶层=目标
        orig_shot = executor.capture_approval_shot

        def shot(rect):
            # 截图被调时前置必须已发生(顺序断言,直出 fake 记录)
            assert executor.activate_calls == [424242]
            return orig_shot(rect)
        monkeypatch.setattr(executor, "capture_approval_shot", shot)
        p = enforcement._capture_target(
            None, OperationRequest("attach", {"process": "x.exe"}, None))
        assert p == executor.approval_shot_path
        assert executor.approval_shot_rects == [(0, 0, 100, 100)]
        # ISS-0073 E(设计授权契约变更):报账措辞「已前置实拍」→「已置前取证」
        # +五点采样命中数标注(Q1③);前置先于截图的顺序断言不变(上行)
        assert "已置前取证" in enforcement._capture_note
        assert "可见性采样 5/5" in enforcement._capture_note

    def test_read06b_hidden_window_restored_then_shot(self, enforcement,
                                                      executor, monkeypatch):
        """TC-READ-06b(ISS-0073 D′ 反转重写):隐藏窗候选**不再还原**——
        人类看不到的窗不进人类裁决面(Q3 定案,原「还原再拍」行为被显式
        撤销);如实陈述「无可见窗口」+不给图。本用例由「还原+前置+拍」
        反转为「不还原/不前置/不拍」,钉死 D′ 防复活。"""
        import deskpilot.enforcement as enf_mod
        calls = []
        monkeypatch.setattr(enforcement, "_is_visible_hwnd",
                            lambda hwnd: False)           # 隐藏前提(假 hwnd 缝)
        monkeypatch.setattr(enf_mod.ctypes.windll.user32, "ShowWindow",
                            lambda h, s: calls.append((h, s)))
        executor.live_windows = [{"hwnd": 424242, "title": "目标",
                                  "process": "x.exe",
                                  "rect": (10, 10, 200, 200),
                                  "visible": False}]
        p = enforcement._capture_target(
            None, OperationRequest("attach", {"process": "x.exe"}, None))
        assert calls == []                                # 零还原(直出)
        assert executor.activate_calls == []              # 零前置(直出)
        assert executor.approval_shot_rects == []         # 零取图(直出)
        assert p is None                                  # 不给图(直出)
        assert "无可见窗口" in enforcement._capture_note  # 如实陈述(直出)

    def test_read06c_never_foreground_no_image(self, enforcement,
                                               executor, monkeypatch):
        """TC-READ-06c:两次后置前采样归属全败 → 不截图,返回 None+如实
        遮挡陈述。ISS-0073 C/Q1(设计授权契约变更):伪归因「目标无法前置」
        族措辞退役,改「被遮挡+采样命中数+本次无实拍」如实陈述。"""
        import deskpilot.enforcement as enf_mod
        executor.live_windows = [{"hwnd": 424242, "title": "目标",
                                  "process": "x.exe",
                                  "rect": (10, 10, 210, 210),
                                  "visible": True}]
        monkeypatch.setattr(enforcement, "_is_visible_hwnd",
                            lambda hwnd: True)            # 假 hwnd 可见性缝
        monkeypatch.setattr(enf_mod.ctypes.windll.user32, "WindowFromPoint",
                            lambda pt: 999999)            # 恒为他人
        monkeypatch.setattr(enf_mod.ctypes.windll.user32, "IsChild",
                            lambda h, t: False)
        p = enforcement._capture_target(
            None, OperationRequest("attach", {"process": "x.exe"}, None))
        assert executor.activate_calls == [424242, 424242]  # 重试一次(直出)
        assert executor.approval_shot_rects == []         # 从未截图(直出)
        assert p is None                                  # 不给错图(直出)
        assert "遮挡" in enforcement._capture_note        # 如实遮挡态(直出)
        assert "本次无实拍" in enforcement._capture_note  # 显著明示(直出)

    def test_read06d_no_candidate_no_fullscreen(self, enforcement, executor):
        """TC-READ-06d:反查不到窗口 → None+明示,禁止全屏退化误导。
        ISS-0073 C′(设计授权):措辞主体归位软件(「目标窗口」→「目标软件」)。"""
        executor.live_windows = []                        # 进程无窗口
        p = enforcement._capture_target(
            None, OperationRequest("attach", {"process": "x.exe"}, None))
        assert p is None
        assert executor.approval_shot_rects == []         # 无全屏退化(直出)
        assert "未找到目标软件" in enforcement._capture_note

    def test_read07_capture_failure_audited(self, enforcement, executor,
                                            audit_log, tmp_path):
        """TC-READ-07:取图异常 → 返回 None,且审计含「审批取图失败」事件。"""
        import json
        import time
        executor.approval_shot_error = True
        from .conftest import FIXTURE_HWND
        p = enforcement._capture_target(
            type("B", (), {"window_rect": (0, 0, 100, 100)})())
        assert p is None
        day = time.strftime("%Y%m%d")
        log = tmp_path / "audit" / "logs" / f"audit-{day}.jsonl"
        text = log.read_text(encoding="utf-8") if log.exists() else ""
        assert EV_APPROVAL_SHOT_FAILED in text
