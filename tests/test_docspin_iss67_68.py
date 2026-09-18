"""ISS-0067/0068 文档措辞钉(五要素见两单据)。

层级:单元(文本形态断言,零打桩)。
入口(设计):README.md / docs/INSTALL.md / docs/功能设计说明书.md 原文直读。
断言出处:文档原文文本直读(直出)。

红态预期(现状):p67a/p67b 含「首次运行自动生成」假措辞(ISS-0067);
p68 无 NO_BINDING 语义链(ISS-0068)。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestLazyCreateWording:
    """ISS-0067:policy.local.yml 惰性创建措辞(ISS-0031 语义:首写才落盘)。"""

    def test_p67a_readme_lazy_wording(self):
        """p67a:中文版不再称「首次运行自动生成」,改述「首次永久入白
        才创建,纯使用不产生」。REQ-006 适配(设计授权的结构变更):
        双语化后中文措辞在平行页 README.zh-CN.md(原 README.md 已成
        英文默认页,钉测试随之迁移)。红态:现文含假措辞。"""
        text = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        assert "首次运行自动生成" not in text          # 假措辞剔除(原文直读)
        assert "首次" in text and "永久入白" in text    # 惰性语义在

    def test_p67b_install_lazy_wording(self):
        """p67b:INSTALL.md 同口径。红态:现文含假措辞。"""
        text = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
        assert "首次运行自动生成" not in text
        assert "首次" in text and "永久入白" in text


class TestNoBindingSemanticChain:
    """ISS-0068:窗死返回码语义链文档化(NO_BINDING→重新 attach;
    attach 时窗死才 TARGET_NOT_FOUND)。"""

    def test_p68_semantic_chain_documented(self):
        """p68:功能设计说明书的原因码段含语义链明句(NO_BINDING=绑定无效
        (窗死/超时/未绑定)→重新 attach;窗死在 attach 路径才报
        TARGET_NOT_FOUND)。钉定语而非散词——散词在全文档他处存在
        (状态图/失败语义),不构成语义链。红态:链句不存在。"""
        text = (ROOT / "docs" / "功能设计说明书.md").read_text(
            encoding="utf-8")
        assert "窗死 → 绑定核销 → NO_BINDING" in text   # 链句直读
        assert "重新 attach" in text
        assert "TARGET_NOT_FOUND" in text
