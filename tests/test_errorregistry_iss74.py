"""ISS-0074 错误码登记册与实现一致性钉(五要素见单据)。

层级:单元(文本/注册表直出,零打桩)。
入口(设计):deskpilot.errors 常量集 ↔ docs/详细设计说明书.md 附录 A
错误码表首列——两侧直读比对。
断言出处:errors.py 大写字符串常量(dir 直出);附录 A 表格首列(原文直读)。

红态预期(现状):附录 A 缺 7 码(ELEMENT_RECT_DEGENERATE/ELEVATION_REQUIRED/
WINDOW_OCCLUDED/OCR_TEXT_NOT_FOUND/OCR_AMBIGUOUS/TOOL_TIMEOUT/SECURE_DESKTOP)
→ 集合差非空立红。
"""

from __future__ import annotations

import re
from pathlib import Path

import deskpilot.errors as errors_mod

ROOT = Path(__file__).resolve().parent.parent


def _impl_codes() -> set[str]:
    """实现侧:errors.py 大写字符串常量集(直出)。"""
    return {name for name in dir(errors_mod)
            if name.isupper()
            and isinstance(getattr(errors_mod, name), str)}


def _registry_codes() -> set[str]:
    """文档侧:附录 A 表格首列码集(原文直读)。"""
    text = (ROOT / "docs" / "详细设计说明书.md").read_text(encoding="utf-8")
    m = re.search(r"## 附录 A 错误码一览\n(.*?)\n## ", text, re.DOTALL)
    assert m, "附录 A 章节未找到"
    codes = set()
    for line in m.group(1).splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) >= 3 and re.fullmatch(r"[A-Z][A-Z0-9_]+",
                                            cells[1] if cells[0] == "" else
                                            cells[0]):
            codes.add(cells[1] if cells[0] == "" else cells[0])
    return codes


class TestErrorRegistryNoDrift:
    """ISS-0074:登记册↔实现零漂移(漂移=少登记/多登记皆红)。"""

    def test_registry_matches_errors_py(self):
        """两侧集合精确相等(实现新码未登记 / 登记册幽灵码皆立红)。"""
        impl = _impl_codes()
        reg = _registry_codes()
        assert reg - impl == set(), f"登记册幽灵码(实现无): {reg - impl}"
        assert impl - reg == set(), f"未登记码(附录 A 缺): {impl - reg}"

    def test_registry_count_single_sourced(self):
        """附录 A 头部的计数声明与 errors.py 实有数一致(计数单源化,
        不再散落多处互相矛盾)。"""
        text = (ROOT / "docs" / "详细设计说明书.md").read_text(
            encoding="utf-8")
        m = re.search(r"附录 A[^\n]*共 (\d+) 码", text)
        assert m, "附录 A 头部缺计数声明"
        assert int(m.group(1)) == len(_impl_codes())   # 直读比对
