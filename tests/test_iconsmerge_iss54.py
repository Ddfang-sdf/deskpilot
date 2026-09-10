"""ISS-0054 图标三源装配按名归并单元测试(TC-54-01~04,问题单 §2 方向①)。

层级:单元(装配器四接缝替身:_FakeUia/_FakeListView/_FakeShellView/_FakeLocator)。
入口(设计):DesktopIconAssembler.assemble(公开入口)。
断言值来源:assemble 返回项 / ExecutorError.code 与消息——直出。

语义钉(方向① 按名归并):
- source 归并键=规范化名称(UIA 显示名 ↔ PIDL 文件名,剥 .lnk/.url、小写);
- LVIR 图形矩形仍索引对齐(与 UIA 同视图同源,序天然一致);
- 虚拟项(回收站)source 恒 null;实体项无匹配来源 → fail-closed;
- 重名歧义(多图标同名且有来源候选)→ fail-closed 附指引;
- 三路计数不一致仍拒(既有诚实钉不动)。

测试设计(五要素):
- TC-54-01 场景=枚举序分叉(核心:实机 2026-09-10 形态);前提=UIA
  [回收站,微信]、ShellView [微信.lnk, None](序不一致);步骤=assemble;
  预期=微信得 source、回收站 null、图形矩形按 UIA 序;断言=返回项直出。
- TC-54-02 场景=重名歧义;前提=UIA 两个「微信」+来源含 微信.lnk;
  预期=INTERNAL_ERROR 且消息含「重名」;断言=code+消息直出。
- TC-54-03 场景=实体项无匹配来源;前提=UIA [微信]、ShellView [None];
  预期=INTERNAL_ERROR 含「无匹配来源」(旧码会静默错配 None——假绿防线);
  断言=code+消息直出。
- TC-54-04 场景=扩展名显示形态;前提=UIA 显示名带 .lnk;
  预期=仍按名归并成功;断言=返回项 source 直出。
"""

from __future__ import annotations

import pytest

from deskpilot.errors import INTERNAL_ERROR, ExecutorError

from .test_desktop_icons_req02 import (CELL_A, CELL_B, G_A, G_B,
                                       _FakeListView, _FakeShellView,
                                       _FakeUia, _assembler)


class TestAssembleByName:
    def test_tc54_01_order_divergence_merges_by_name(self):
        """UIA 序 [回收站,微信] × PIDL 序 [微信, None]——实机分叉形态。"""
        a = _assembler(_FakeUia([("回收站", CELL_A), ("微信", CELL_B)]),
                       _FakeListView([G_A, G_B]),
                       _FakeShellView([r"C:\D\微信.lnk", None]))
        items = a.assemble()
        assert items[0] == {"display": "回收站", "source": None,
                            "graphic_rect": G_A, "cell_rect": CELL_A}
        assert items[1] == {"display": "微信", "source": r"C:\D\微信.lnk",
                            "graphic_rect": G_B, "cell_rect": CELL_B}

    def test_tc54_02_duplicate_names_fail_closed(self):
        a = _assembler(_FakeUia([("微信", CELL_A), ("微信", CELL_B)]),
                       _FakeListView([G_A, G_B]),
                       _FakeShellView([r"C:\D\微信.lnk", None]))
        with pytest.raises(ExecutorError) as ei:
            a.assemble()
        assert ei.value.code == INTERNAL_ERROR
        assert "重名" in str(ei.value)

    def test_tc54_03_real_item_without_source_fails(self):
        a = _assembler(_FakeUia([("微信", CELL_A)]),
                       _FakeListView([G_A]),
                       _FakeShellView([None]))
        with pytest.raises(ExecutorError) as ei:
            a.assemble()
        assert ei.value.code == INTERNAL_ERROR
        assert "无匹配来源" in str(ei.value)

    def test_tc54_04_extension_visible_form_still_merges(self):
        """Explorer 开"显示扩展名"时 UIA 名带 .lnk——双剥后仍归并。"""
        a = _assembler(_FakeUia([("微信.lnk", CELL_A), ("回收站", CELL_B)]),
                       _FakeListView([G_A, G_B]),
                       _FakeShellView([r"C:\D\微信.lnk", None]))
        items = a.assemble()
        assert items[0]["source"] == r"C:\D\微信.lnk"
        assert items[1]["source"] is None
