"""ISS-0063 裁定项 C:工具元数据集合恒等钉(守卫钉,封 ISS-0040 类漂移)。

背景:同一工具元数据散 3 文件 5 处登记(TOOL_SCHEMAS/TOOL_LEVELS/
BINDING_REQUIRED_TOOLS/_L0_DIRECT/_L1_DIRECT);ISS-0040 前科=schema 增
类型而映射未同步,MCP list_tools 全量 KeyError。裁定 C:以集合恒等钉
封死「漏同步一处」类漂移(A 单源化挂起至下一新工具单顺手做)。

层级:形态(注册表直读,零执行)。
入口(出处):deskpilot/mcp_server.py TOOL_SCHEMAS;
deskpilot/models.py TOOL_LEVELS/BINDING_REQUIRED_TOOLS;
deskpilot/tools/__init__.py _L0_DIRECT/_L1_DIRECT。
断言出处:四处注册表 keys/集合直读比对,无中间转换。

红绿属性:**守卫钉,P1 即绿**(现状四表一致,属预期——钉的价值在
未来漂移时变红拦截,不在当前证明缺陷)。探测力实证(2026-09-22,
文件不留痕):临时从 TOOL_LEVELS 删一键→三条断言中 keys 恒等与
BINDING_REQUIRED⊆ 同步变红;还原即绿(见 ISS-0063 变更记录 v0.4)。
"""

from __future__ import annotations

from deskpilot.mcp_server import TOOL_SCHEMAS
from deskpilot.models import BINDING_REQUIRED_TOOLS, TOOL_LEVELS
from deskpilot.tools import _L0_DIRECT, _L1_DIRECT


class TestToolRegistrySetIdentity:
    """裁定 C 三条集合恒等(场景/前提/步骤/预期/断言见各函数)。"""

    def test_schemas_keys_equal_levels_keys(self):
        """TC-63-01(形态,裁定 C-1):keys(TOOL_SCHEMAS)==keys(TOOL_LEVELS)。
        场景:两表任一增删工具而另一表漏同步(schema 有级别无 → 路由
        按默认级放行;级别有 schema 无 → 调用面 KeyError,ISS-0040 同族)。
        前提:注册表静态直读。步骤:取两表 keys 集合比对。
        预期:恒等。断言:set 差集直读(双向)。"""
        schemas, levels = set(TOOL_SCHEMAS), set(TOOL_LEVELS)
        assert schemas - levels == set(), \
            f"schema 有而级别无(路由将按默认级放行): {schemas - levels}"
        assert levels - schemas == set(), \
            f"级别有而 schema 无(调用面缺声明): {levels - schemas}"

    def test_binding_required_subset_of_schemas(self):
        """TC-63-02(形态,裁定 C-2):BINDING_REQUIRED_TOOLS ⊆ TOOL_SCHEMAS。
        场景:绑定集登记了 schema 不存在的工具(闸一将对未知工具误要求
        绑定令牌/或新工具漏登记绑定要求而绕过闸一)。
        前提:注册表静态直读。步骤:集合包含判定。
        预期:子集成立。断言:差集直读。"""
        extra = BINDING_REQUIRED_TOOLS - set(TOOL_SCHEMAS)
        assert extra == set(), \
            f"绑定要求集含 schema 未登记工具: {extra}"

    def test_direct_routes_subset_of_schemas(self):
        """TC-63-03(形态,裁定 C-3):_L0_DIRECT/_L1_DIRECT ⊆ TOOL_SCHEMAS。
        场景:直调路由集登记了 schema 不存在的工具(直调绕过参数校验与
        强制层;或新工具误入直调集)。
        前提:注册表静态直读。步骤:两集分别做包含判定。
        预期:均为子集。断言:差集直读。"""
        schemas = set(TOOL_SCHEMAS)
        assert _L0_DIRECT - schemas == set(), \
            f"_L0_DIRECT 含 schema 未登记工具: {_L0_DIRECT - schemas}"
        assert _L1_DIRECT - schemas == set(), \
            f"_L1_DIRECT 含 schema 未登记工具: {_L1_DIRECT - schemas}"
