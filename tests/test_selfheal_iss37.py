"""ISS-0037 screenshot 感知自愈测试(TC-SV-01~06,问题单 §3)。

层级:单元(Executor 层打桩截图 I/O+注入假 OCR 引擎)+ 形态断言。
入口(设计):executor.screenshot(scope, rect, window, ocr) /
mcp_server.validate_call / TOOL_SCHEMAS / _check_type。
"""

from __future__ import annotations

import pytest

from deskpilot.executor import Executor
from deskpilot.errors import ExecutorError, InvalidParamsError


def _make(estop, tmp_path):
    """构造 Executor,打桩截图 I/O(真写 10x10 PNG 至 tmp)。"""
    import types

    from PIL import Image
    ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02)
    shot = tmp_path / "shot.png"
    Image.new("RGB", (10, 10), (255, 0, 0)).save(shot)
    region = {"left": 0, "top": 0, "width": 10, "height": 10}
    ex._resolve_region = types.MethodType(
        lambda self, scope, rect=None, window=None: region, ex)
    ex._save_shot = types.MethodType(
        lambda self, reg, tag: str(shot), ex)
    return ex


class TestVisionNote:
    """TC-SV-01~04:vision_note 降级指引与 ocr:true 语义。断言:返回 dict 直出。"""

    def test_sv01_vision_note_with_path(self, estop, tmp_path):
        ex = _make(estop, tmp_path)
        out = ex.screenshot("region", rect=[0, 0, 10, 10])
        assert isinstance(out["vision_note"], str)
        assert "ocr(source=" in out["vision_note"]          # 降级指引关键词
        assert out["path"] in out["vision_note"]           # 含实际路径(直出)

    def test_sv02_ocr_true_attaches_items(self, estop, tmp_path):
        ex = _make(estop, tmp_path)
        fake_items = [{"text": "X", "position": [0, 0, 2, 2]}]
        ex._ocr_engine = lambda img: fake_items             # 注入接缝
        out = ex.screenshot("region", rect=[0, 0, 10, 10], ocr=True)
        assert out["ocr_items"] == fake_items               # 引擎 items 直出

    def test_sv03_default_no_ocr_keys(self, estop, tmp_path):
        ex = _make(estop, tmp_path)
        out = ex.screenshot("region", rect=[0, 0, 10, 10])
        assert "ocr_items" not in out                       # 默认形态(直出)
        assert "ocr_error" not in out

    def test_sv04_ocr_failure_explicit_image_intact(self, estop, tmp_path):
        ex = _make(estop, tmp_path)

        def boom(img):
            raise ExecutorError("OCR_FAKE_FAIL", "假引擎失败")
        ex._ocr_engine = boom
        out = ex.screenshot("region", rect=[0, 0, 10, 10], ocr=True)
        assert out["path"] and out["width"] == 10           # 图像字段不受损
        assert out["ocr_error"]["code"] == "OCR_FAKE_FAIL"  # 显式错误(直出)
        assert "ocr_items" not in out                       # 禁止静默半成品


class TestSchemaBool:
    """TC-SV-05/06:ocr 参数 bool 严格校验与 schema 形态。断言:异常/形态直出。"""

    def test_sv05_bool_strict_rejects_int_and_str(self, policy):
        from deskpilot.mcp_server import validate_call
        assert validate_call("screenshot",
                             {"scope": "fullscreen", "ocr": True},
                             policy)["ocr"] is True
        for bad in (1, "yes"):
            with pytest.raises(InvalidParamsError):
                validate_call("screenshot",
                              {"scope": "fullscreen", "ocr": bad}, policy)

    def test_sv06_schema_shape_and_description(self):
        from deskpilot.mcp_server import TOOL_SCHEMAS
        schema = TOOL_SCHEMAS["screenshot"]
        assert schema["optional"]["ocr"] == ("bool",)       # 形态断言(直出)
        assert "图像不可见" in schema["description"]         # 降级指引入描述
