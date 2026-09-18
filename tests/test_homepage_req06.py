"""REQ-006 主页双语化钉测试(hp01~hp06,需求单 §2 R1~R7)。

层级:形态(仓库文件直读,零打桩)。
入口(设计):README.md / README.zh-CN.md / assets/ 盘上文件。
断言出处:文件文本/存在性/PIL 尺寸直读。

红态预期(现状):hp01 红(README.md 现为中文默认);hp02 红(zh-CN 不存在);
hp06 红(README_EN.md 仍在且被引用);hp03/hp04/hp05 红期即绿
(资产/徽章/配置块现状钉——重构后不得丢)。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_CJK = re.compile(r"[一-鿿]")


class TestBilingualHomepage:
    """R1/R2:英文默认页 + 中文平行页互链。"""

    def test_hp01_readme_is_english_default(self):
        """hp01(R1):README.md 为英文默认页——标语行无中文,且顶部含
        到中文版的切换链接。红态:现为中文默认。"""
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "README.zh-CN.md" in text          # 互链存在(直读)
        # 标语行(首个 <strong>)不含中文=英文默认页
        m = re.search(r"<strong>(.*?)</strong>", text, re.DOTALL)
        assert m, "缺标语行"
        assert not _CJK.search(m.group(1)), "默认页标语须为英文"

    def test_hp02_chinese_parallel_page_exists(self):
        """hp02(R2):README.zh-CN.md 存在、正文为中文、互链回英文页。"""
        p = ROOT / "README.zh-CN.md"
        assert p.is_file()
        text = p.read_text(encoding="utf-8")
        assert _CJK.search(text)                  # 中文内容在
        assert 'href="README.md"' in text         # 互链回英文默认页(直读)


class TestAssetsAndBadges:
    """R3/R4/R5:hero/截图资产在盘上、徽章行、快速上手配置块。"""

    def test_hp03_referenced_assets_exist(self):
        """hp03(R3):README.md 引用的 assets/ 图像全部存在且 PIL 可读。
        红期即绿(资产现状钉——重构不许丢图)。"""
        from PIL import Image
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        refs = re.findall(r'src="(assets/[^"]+)"', text)
        assert refs, "主页未引用任何 assets 图像"
        for ref in refs:
            f = ROOT / ref
            assert f.is_file(), f"引用丢失: {ref}"
            with Image.open(f) as im:
                assert im.size[0] > 0 and im.size[1] > 0

    def test_hp04_badges_row_present(self):
        """hp04(R4):徽章行含 release/license/platform/CI 状态徽章。
        红期即绿(徽章现状钉)。"""
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "img.shields.io/github/v/release" in text
        assert "img.shields.io/github/license" in text
        assert "platform-Windows" in text
        assert "github/actions/workflow/status" in text  # CI 状态徽章(动态)

    def test_hp05_quickstart_mcp_config_present(self):
        """hp05(R5):快速上手含 MCP 接入配置(claude mcp add 或
        claude_desktop_config.json 片段)。红期即绿。"""
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        assert ("claude mcp add" in text) or \
               ("claude_desktop_config.json" in text)


class TestNoStaleEnglishPage:
    """R1 附属:旧 README_EN.md 平行页已收编,全库无悬挂引用。"""

    def test_hp06_no_stale_readme_en(self):
        """hp06:README_EN.md 已删除(内容并入英文默认页),且全库
        无活引用(历史单据的追溯性提及除外——问题单/手工记录不改写)。
        红态(现状):README_EN.md 仍在。"""
        assert not (ROOT / "README_EN.md").exists()
        # 活文档面(README/INSTALL/DESIGN 等)不得再引用旧名
        for f in (ROOT / "docs").glob("*.md"):
            if f.name.startswith("手工测试记录"):
                continue                       # 追溯记录不改写
            assert "README_EN.md" not in f.read_text(encoding="utf-8"), \
                f"悬挂引用: {f.name}"
