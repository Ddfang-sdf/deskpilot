"""REQ-007 界面英文版(i18n)测试(i01~i06,需求单 §7 骨架)。

层级:i01/i06 形态(源码/目录直读);i02/i03/i04/i05 单元(Tk 替身/桩,
允许打桩)。入口(设计):deskpilot.i18n.tr / CATALOG / _detect_locale;
四类弹窗 build_*;enforcement._describe_enroll。
断言出处:目录直读/返回值直出/替身 widget 文本直出/描述字符串直出。

红态预期(现状):全红——i18n 模块不存在(ImportError 系列)。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestCatalogIntegrity:
    """i01/i06:目录完备性——代码取词键 ⊆ 目录,zh-CN/en 键集相等。"""

    def test_i01_catalog_dual_language_complete(self):
        """i01:配置文件 i18n.yml 每键 en/zh-CN 双语文本全非空,且代码内
        tr() 调用的键全部已登记(防漏译)。"""
        from deskpilot import i18n

        catalog = i18n._load_catalog()
        for key, pair in catalog.items():
            assert pair.get("en", ""), f"缺 en(基线): {key}"
            assert pair.get("zh-CN", ""), f"缺 zh-CN: {key}"
        keys = set(catalog)
        for mod in ("approval_dialog.py", "freeze_dialog.py",
                    "whitelist_window.py", "tray.py", "enforcement.py",
                    "approval_ui.py"):
            src = (ROOT / "deskpilot" / mod).read_text(encoding="utf-8")
            used = set(re.findall(r'tr\("([a-z0-9_.+]+)"', src))
            missing = used - keys
            assert not missing, f"{mod} 未登记键: {missing}"


class TestLocaleResolution:
    """i02/i03:语言解析——环境变量优先,默认中文;缺键回退+审计。"""

    def test_i02_env_override_wins(self, monkeypatch):
        """i02:DESKPILOT_LOCALE 优先;en 为默认(未知语言回退 en)。"""
        from deskpilot import i18n
        monkeypatch.setenv("DESKPILOT_LOCALE", "en")
        assert i18n.tr("approval.btn.approve_once") == "Approve"
        monkeypatch.setenv("DESKPILOT_LOCALE", "zh-CN")
        assert i18n.tr("approval.btn.approve_once") == "批准一次"
        monkeypatch.setenv("DESKPILOT_LOCALE", "fr")   # 未知语言 → en 默认
        assert i18n.tr("approval.btn.approve_once") == "Approve"

    def test_i03_missing_key_fallback_audited(self, monkeypatch):
        """i03:取未登记键 → 回退中文文本(键本身)且记审计「i18n 缺键」
        (fail-closed,不静默)。"""
        from deskpilot import i18n

        events = []
        monkeypatch.setattr(i18n, "_AUDIT_SINK",
                            lambda e, d="": events.append(e))
        monkeypatch.setenv("DESKPILOT_LOCALE", "en")
        out = i18n.tr("no.such.key")
        assert out == "no.such.key"               # 键本身兜底(直出)
        assert "i18n 缺键" in events              # 审计留痕(直出)


class TestDialogBilingual:
    """i04:四类弹窗按语言渲染(Tk 替身,同 test_monitors_iss7 形态)。"""

    def _stub_tk(self, monkeypatch, mod):
        """ISS-0059 步骤11:__getattr__ 沉默替身收编 tests/faketk.install
        (screen=(1920,1080) 按原校准值;cget/text 观测归库面,断言零改动)。"""
        from .faketk import install
        return install(monkeypatch, mod.tk, screen=(1920, 1080))

    def test_i04_approval_dialog_bilingual(self, monkeypatch, tmp_path):
        """i04a:审批弹窗标题/按钮随 DESKPILOT_LOCALE 切换。"""
        import deskpilot.approval_dialog as ad
        from deskpilot import i18n  # noqa: F401  (注册触发 tr 使用面)
        rec = self._stub_tk(monkeypatch, ad)
        monkeypatch.setenv("DESKPILOT_LOCALE", "en")
        seen = rec.button_texts
        ad.build_window(object(), "测试描述", str(tmp_path / "r.txt"), 5)
        assert "Approve" in seen and "Deny" in seen   # 按钮英文(直出)
        monkeypatch.setenv("DESKPILOT_LOCALE", "zh-CN")
        seen.clear()
        ad.build_window(object(), "测试描述", str(tmp_path / "r.txt"), 5)
        assert "批准一次" in seen and "拒绝" in seen

    def test_i04_revoke_confirm_bilingual(self, monkeypatch, tmp_path):
        """i04b:撤回确认窗标题文案随语言切换(移出/保留按钮)。"""
        import deskpilot.whitelist_window as ww
        rec = self._stub_tk(monkeypatch, ww)
        monkeypatch.setenv("DESKPILOT_LOCALE", "en")
        seen = rec.button_texts
        ww.build_revoke_confirm(object(), "x.exe",
                                str(tmp_path / "r.result"), 15)
        assert "Remove" in seen and "Keep" in seen
        monkeypatch.setenv("DESKPILOT_LOCALE", "zh-CN")
        seen.clear()
        ww.build_revoke_confirm(object(), "x.exe",
                                str(tmp_path / "r.result"), 15)
        assert "移出" in seen and "保留" in seen


class TestEnforcementBilingual:
    """i05:enforcement 动态描述模板双语言(槽位注入正确)。"""

    def test_i05_enroll_description_bilingual(self, policy, bindings,
                                              approvals, estop, executor,
                                              audit_log, tmp_path,
                                              monkeypatch):
        """i05:_describe_enroll 在 en 下为英文骨架(自报标注/程序路径),
        zh 下为中文;进程名/路径槽不译。"""
        from deskpilot.enforcement import Enforcement
        from deskpilot.models import OperationRequest
        monkeypatch.setenv("DESKPILOT_LOCALE", "en")
        enf = Enforcement(policy, bindings, approvals, estop, executor,
                          audit_log)
        req = OperationRequest("attach", {"process": "no-such-xyz.exe"}, None)
        desc = enf._describe_enroll(req, None, "no-such-xyz.exe")
        assert "self-reported" in desc and "unverified" in desc
        assert "no-such-xyz.exe" in desc
        assert not re.search(r"[一-鿿]", desc), desc
        monkeypatch.setenv("DESKPILOT_LOCALE", "zh-CN")
        desc2 = enf._describe_enroll(req, None, "no-such-xyz.exe")
        assert "自报" in desc2 and "未经系统核验" in desc2


class TestCatalogPathFrozenForm:
    """i07:冻结形态目录路径=_MEIPASS/deskpilot/i18n.yml(素材实拍实证:
    错写根目录会整窗显示键名)——路径逻辑钉。"""

    def test_i07_catalog_path_frozen_layout(self, monkeypatch, tmp_path):
        """i07:模拟冻结形态(设 _MEIPASS)→ 目录路径指到
        _MEIPASS/deskpilot/i18n.yml;源码形态指包目录。"""
        from deskpilot import i18n
        monkeypatch.setattr(i18n.sys, "_MEIPASS", str(tmp_path),
                            raising=False)
        p = i18n._catalog_path()
        assert p == tmp_path / "deskpilot" / "i18n.yml"   # 直出
        monkeypatch.delattr(i18n.sys, "_MEIPASS")
        p2 = i18n._catalog_path()
        assert p2.name == "i18n.yml" and p2.is_file()      # 源码直读在盘


class TestNoResidualChineseInEnMode:
    """i06(形态):en 模式下四类弹窗渲染树不得残留中文。"""

    def test_i06_six_surfaces_use_tr(self):
        """i06:六面源码不再出现裸中文 UI 字面量(取词必经 tr();
        抽查:四个弹窗文件内无 text="...中文..." 形态)。
        ISS-0099:邻近词表扩三通道——text= / set_state( / .title(,
        防运行时改文案通道漏网(「更多 N 项」事件)。"""
        import io
        cjk = re.compile(r'"[^"\n]*[一-鿿][^"\n]*"')
        channels = ("text=", "set_state(", ".title(")
        for mod in ("approval_dialog.py", "freeze_dialog.py",
                    "whitelist_window.py"):
            src = io.open(ROOT / "deskpilot" / mod,
                          encoding="utf-8").read()
            hits = []
            for h in cjk.findall(src):
                pos = src.find(h)
                ctx = src[max(0, pos - 16):pos + len(h)]
                if any(ch in ctx for ch in channels):
                    hits.append(h)
            assert not hits, f"{mod} 残留裸中文 UI 字面量: {hits[:4]}"

    def test_i06b_more_collapse_keys_slot_injection(self, monkeypatch):
        """w02:wl.more/wl.collapse 槽位注入双语直出(ISS-0099)。"""
        from deskpilot import i18n
        monkeypatch.setenv("DESKPILOT_LOCALE", "en")
        assert i18n.tr("wl.more", n=3) == "More 3 items"
        assert i18n.tr("wl.collapse") == "Collapse"
        monkeypatch.setenv("DESKPILOT_LOCALE", "zh-CN")
        assert i18n.tr("wl.more", n=3) == "更多 3 项"
        assert i18n.tr("wl.collapse") == "收起"

    def test_i06c_more_collapse_call_sites_use_tr(self):
        """w03:「更多/收起」调用点走 tr 取词,不再裸写字面量(源码直读)。"""
        src = (ROOT / "deskpilot" / "whitelist_window.py").read_text(
            encoding="utf-8")
        assert 'set_state(tr("wl.collapse")' in src
        assert 'set_state(tr("wl.more", n=rest)' in src
        assert 'set_state("收起"' not in src
        assert 'set_state(f"更多' not in src
