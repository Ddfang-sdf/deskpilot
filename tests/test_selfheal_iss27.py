"""ISS-0027 AI 可自愈错误规范测试(TC-ECHO-01~03 / TC-FUZZ-01~04,
问题单 §4/§5 v0.2 评审通过)。

层级:回显=单元(_check_type/Decision 直出);近邻建议=单元(纯函数直出);
TC-FUZZ-03=单元(Decision 形态);TC-FUZZ-04=集成(真 daemon+真 OCR)。
入口(设计):mcp_server._check_type / textclick.suggest_similar /
executor._click_text not_found 分支。
"""

from __future__ import annotations

import pytest

from deskpilot import errors
from deskpilot.errors import ExecutorError, InvalidParamsError
from deskpilot.executor.textclick import suggest_similar


class TestParamEcho:
    """TC-ECHO-01/02:参数错误回显服务端收到的值(直出)。"""

    def test_echo01_overlong_text_echoed(self, policy):
        """TC-ECHO-01:超长文本错误含「收到:」与截断后的参数值。"""
        from deskpilot.mcp_server import _check_type
        text = "收到我" + "x" * 70000
        with pytest.raises(InvalidParamsError) as ei:
            _check_type("text", text, ("text",), policy)
        msg = str(ei.value)
        assert "收到:" in msg
        assert "收到我" in msg                          # 首段可辨识(直出)

    def test_echo02_truncation_discipline(self, policy):
        """TC-ECHO-02:5000 字回显值段截断至 60 字,总长 ≤400。

        校准:项目既有截断惯例为「前60字…(共 N 字)」,尾注计在值段外。
        """
        from deskpilot.mcp_server import _check_type
        text = "A" * 70000                              # > 65536 上限
        with pytest.raises(InvalidParamsError) as ei:
            _check_type("text", text, ("text",), policy)
        msg = str(ei.value)
        assert len(msg) <= 400
        value_part = msg.split("收到:")[1].strip().split("…")[0]
        assert len(value_part) == 60                    # 值段截断(直出)
        assert "共 70000 字" in msg                     # 总长尾注(直出)

    def test_echo03_key_unknown_regression(self, enforcement, bound_record):
        """TC-ECHO-03:KEY_UNKNOWN 既有回显不回归(ISS-0022 行为)。"""
        from deskpilot.models import OperationRequest
        d = enforcement.submit(OperationRequest(
            "key", {"key": "ctrl+shift+f99"}, bound_record.token))
        assert d.reason_code == errors.KEY_UNKNOWN
        assert "本次未发送任何按键" in d.message
        assert "ctrl+c" in d.message


class TestFuzzySuggest:
    """TC-FUZZ-01/02:近邻建议纯函数(返回值直出)。"""

    ITEMS = [{"text": "保存文档", "position": [0, 0, 10, 10]},
             {"text": "保序文挡", "position": [0, 0, 10, 10]},
             {"text": "另存为", "position": [0, 0, 10, 10]},
             {"text": "完全无关内容甲乙丙", "position": [0, 0, 10, 10]}]

    def test_fuzz01_no_similar_returns_empty(self):
        assert suggest_similar(self.ITEMS, "xyzzy") == []

    def test_fuzz02_sorted_truncated(self):
        out = suggest_similar(self.ITEMS, "保存文档", limit=3)
        assert len(out) <= 3
        assert out[0] == "保存文档"                     # 最相似居首(直出)
        assert "完全无关内容甲乙丙" not in out          # 低 ratio 剔除(直出)


class TestSuggestionNoPayload:
    """TC-FUZZ-03:OCR 未命中错误经 Decision 映射,data 无载荷(形态)。"""

    def test_fuzz03_decision_data_none(self, enforcement, bound_record,
                                       executor):
        from deskpilot.models import OperationRequest
        executor.error = ExecutorError(
            errors.OCR_TEXT_NOT_FOUND,
            "未找到文字: 保存。相似文本: 保序文挡")
        d = enforcement.submit(OperationRequest(
            "click_text", {"token": bound_record.token, "text": "保存"},
            bound_record.token))
        assert d.reason_code == errors.OCR_TEXT_NOT_FOUND
        assert d.data is None                           # 建议无载荷(直出)
        assert "相似文本" in d.message


@pytest.mark.integration
class TestFuzzyRealOcr:
    """TC-FUZZ-04:真链差一字查询 → not_found 且带相似建议(响应体直出)。"""

    def test_fuzz04_real_ocr_suggestion(self, policy, audit_log, tmp_path):
        import time
        from .test_clicktext_iss21 import TestClickTextIntegration

        tc = TestClickTextIntegration()
        proc, new = tc._spawn_notepad()
        try:
            def real_ocr():
                from rapidocr_onnxruntime import RapidOCR
                from deskpilot.main import _build_ocr_engine
                return _build_ocr_engine(RapidOCR())

            d = tc._make_daemon(policy, audit_log, tmp_path,
                                ocr_factory=real_ocr)
            try:
                a = tc._call(d.port, "attach", {"hwnd": new[0]["hwnd"]})
                assert a["ok"] is True, a.get("message")
                token = a["data"]["token"]
                magic = f"dp相似串{int(time.time()) % 100000}"
                t = tc._call(d.port, "type_text",
                             {"token": token, "text": magic})
                assert t["ok"] is True, t.get("message")
                time.sleep(0.5)
                r = tc._call(d.port, "click_text",
                             {"token": token, "text": magic[:-1] + "X",
                              "index": 0}, timeout=120)
                assert r["ok"] is False
                assert r["error_code"] == errors.OCR_TEXT_NOT_FOUND
                assert r["data"] is None                # 无载荷(直出)
                assert "相似文本" in r["message"]       # 建议呈现(直出)
            finally:
                d.stop()
        finally:
            proc.terminate()
            from .test_uia_com_iss16 import _close_all_and_wait
            _close_all_and_wait([w["hwnd"] for w in new])
