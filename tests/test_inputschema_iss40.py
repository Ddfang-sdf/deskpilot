"""ISS-0040【修改引入】list_tools 工具清单构建回归测试。

ISS-0037 增 screenshot.ocr=("bool",) 后 _input_schema type_map 缺
"bool" 映射 → list_tools 全量抛 KeyError → MCP 客户端 "tools fetch
failed"。TC-SC-01~02:inputSchema 构建对全部工具零异常 + bool 映射
形态。层级:单元(形态直出)。
"""

from __future__ import annotations

from deskpilot.mcp_server import TOOL_SCHEMAS, _input_schema


class TestInputSchemaBuild:
    """TC-SC:全部工具 inputSchema 构建零异常(判别性:type_map 缺键即红)。"""

    def test_sc01_all_tools_build(self):
        for name, schema in TOOL_SCHEMAS.items():
            out = _input_schema(schema)          # 任一缺键即 KeyError(直出)
            assert out["type"] == "object", name

    def test_sc02_bool_maps_to_boolean(self):
        out = _input_schema(TOOL_SCHEMAS["screenshot"])
        assert out["properties"]["ocr"] == {"type": "boolean"}
