"""ISS-0020 审批可读性测试（TC-READ-01~07,问题单 §4）。

层级：单元（conftest 装配/替身直出）。
入口（设计）：enforcement._describe / _capture_target / 审计事件。
"""

from __future__ import annotations

from deskpilot.models import OperationRequest


def _describe(enforcement, tool, params, binding=None):
    return enforcement._describe(OperationRequest(tool, params, None), binding)


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
        """TC-READ-06:反查命中可见窗 → 先前置后截图(顺序直出),返回实拍路径。"""
        import deskpilot.enforcement as enf_mod
        executor.live_windows = [{"hwnd": 424242, "title": "目标",
                                  "process": "x.exe", "rect": (0, 0, 100, 100),
                                  "visible": True}]
        monkeypatch.setattr(enf_mod.ctypes.windll.user32, "WindowFromPoint",
                            lambda pt: 424242)            # 中心点顶层=目标
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
        assert "已前置实拍" in enforcement._capture_note

    def test_read06b_hidden_window_restored_then_shot(self, enforcement,
                                                      executor, monkeypatch):
        """TC-READ-06b:候选隐藏时先 SW_RESTORE 还原,再前置+校验+拍。"""
        import deskpilot.enforcement as enf_mod
        calls = []
        monkeypatch.setattr(enf_mod.ctypes.windll.user32, "ShowWindow",
                            lambda h, s: calls.append((h, s)))
        monkeypatch.setattr(enf_mod.ctypes.windll.user32, "WindowFromPoint",
                            lambda pt: 424242)
        executor.live_windows = [{"hwnd": 424242, "title": "目标",
                                  "process": "x.exe",
                                  "rect": (10, 10, 200, 200),
                                  "visible": False}]
        p = enforcement._capture_target(
            None, OperationRequest("attach", {"process": "x.exe"}, None))
        assert calls == [(424242, 9)]                     # 还原(直出)
        assert executor.activate_calls == [424242]        # 前置(直出)
        assert p == executor.approval_shot_path           # 拍到目标而非全屏
        assert "已还原窗口" in enforcement._capture_note
        assert "已前置实拍" in enforcement._capture_note

    def test_read06c_never_foreground_no_image(self, enforcement,
                                               executor, monkeypatch):
        """TC-READ-06c:两次前置后中心点仍为他人 → 不截图,返回 None+存疑。"""
        import deskpilot.enforcement as enf_mod
        executor.live_windows = [{"hwnd": 424242, "title": "目标",
                                  "process": "x.exe",
                                  "rect": (10, 10, 210, 210),
                                  "visible": True}]
        monkeypatch.setattr(enf_mod.ctypes.windll.user32, "WindowFromPoint",
                            lambda pt: 999999)            # 恒为他人
        monkeypatch.setattr(enf_mod.ctypes.windll.user32, "IsChild",
                            lambda h, t: False)
        p = enforcement._capture_target(
            None, OperationRequest("attach", {"process": "x.exe"}, None))
        assert executor.activate_calls == [424242, 424242]  # 重试一次(直出)
        assert executor.approval_shot_rects == []         # 从未截图(直出)
        assert p is None                                  # 不给错图(直出)
        assert "存疑" in enforcement._capture_note        # 不静默(直出)

    def test_read06d_no_candidate_no_fullscreen(self, enforcement, executor):
        """TC-READ-06d:反查不到窗口 → None+明示,禁止全屏退化误导。"""
        executor.live_windows = []                        # 进程无窗口
        p = enforcement._capture_target(
            None, OperationRequest("attach", {"process": "x.exe"}, None))
        assert p is None
        assert executor.approval_shot_rects == []         # 无全屏退化(直出)
        assert "未找到目标窗口" in enforcement._capture_note

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
        assert "审批取图失败" in text
