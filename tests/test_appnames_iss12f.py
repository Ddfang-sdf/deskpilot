"""ISS-0012 整改项 F：弹窗应用显示名测试（问题单 §4.1/§6）。

层级：单元（纯函数返回值直出；FileDescription 用例断言系统真实版本信息）。
五要素：各类 docstring 标注。
入口（§6）：appnames.app_display_name / enforcement._describe_enroll。
"""

from __future__ import annotations

import time

from .conftest import make_policy  # noqa: F401  （保留 conftest 装配一致性）


class TestAppDisplayName:
    """场景:进程→用户可读显示名,三级解析序(窗口标题/FileDescription/回退)。
    断言:app_display_name 返回字符串(直出)。"""

    def test_window_title_wins(self):
        from deskpilot.appnames import app_display_name
        assert app_display_name("whatever.exe", "无标题 - 记事本") == "无标题 - 记事本"

    def test_file_description_for_calc(self):
        """calc.exe 显示名取 OS/厂商数据(F2)——语言无关断言:
        英文名在任意语言系统均存在,中文名随 OS 语言变(CI 英文系统实证)。"""
        from deskpilot.appnames import app_display_name
        name = app_display_name("calc.exe")
        assert "Calculator" in name
        assert name != "calc.exe"                      # 非裸进程名回退(直出)

    def test_unknown_process_falls_back(self):
        from deskpilot.appnames import app_display_name
        assert app_display_name("no-such-app-xyz.exe") == "no-such-app-xyz.exe"

    def test_empty_title_goes_to_parse(self):
        from deskpilot.appnames import app_display_name
        name = app_display_name("calc.exe", "")
        assert "Calculator" in name
        assert name != "calc.exe"

    def test_parse_time_bounded(self):
        """冷扫描(清双缓存)<2s;缓存命中 <100ms(F3 时限)。"""
        from deskpilot import appnames
        appnames._APPX_CACHE.clear()
        appnames._PKG_INDEX = None
        t0 = time.monotonic()
        appnames.app_display_name("calc.exe")
        assert time.monotonic() - t0 < 2.0
        t1 = time.monotonic()
        appnames.app_display_name("calc.exe")
        assert time.monotonic() - t1 < 0.1


class TestAppDescription:
    """场景(E2):进程→用户可读描述(悬浮提示),全部来自 OS/厂商数据。
    断言:app_description 返回字符串(直出)。"""

    def test_calc_description_from_os(self):
        from deskpilot.appnames import app_description
        d = app_description("calc.exe")
        assert d and ("计算" in d or "Calculator" in d)

    def test_unknown_process_falls_back(self):
        from deskpilot.appnames import app_description
        assert app_description("no-such-xyz.exe") == "no-such-xyz.exe"


class TestEnrollDescription:
    """场景:入白审批描述两段式——主标题显示名、底注进程名。
    断言:_describe_enroll 返回字符串(直出)。"""

    def test_launch_enroll_uses_display_name(self, policy, bindings, approvals,
                                             estop, executor, audit_log,
                                             tmp_path):
        import yaml
        from deskpilot.enforcement import Enforcement
        from deskpilot.models import OperationRequest
        from deskpilot.whitelist_admin import WhitelistAdmin

        p = tmp_path / "policy.yml"
        p.write_text(yaml.safe_dump({"whitelist": [{"process": "notepad.exe"}]}),
                     encoding="utf-8")
        admin = WhitelistAdmin(str(p), {"notepad.exe": "L2"})
        enf = Enforcement(policy, bindings, approvals, estop, executor,
                          audit_log, whitelist_admin=admin)
        req = OperationRequest("launch_app", {"app": "calc.exe"}, None)
        desc = enf._describe_enroll(req, None, "calc.exe")
        headline, _, detail = desc.partition("\n---\n")
        assert ("Calculator" in headline) or ("计算器" in headline)
        assert "calc.exe" in detail

    def test_attach_enroll_uses_window_title(self, policy, bindings, approvals,
                                             estop, executor, audit_log,
                                             tmp_path):
        import yaml
        from deskpilot.enforcement import Enforcement
        from deskpilot.models import OperationRequest
        from deskpilot.whitelist_admin import WhitelistAdmin

        p = tmp_path / "policy.yml"
        p.write_text(yaml.safe_dump({"whitelist": [{"process": "notepad.exe"}]}),
                     encoding="utf-8")
        admin = WhitelistAdmin(str(p), {"notepad.exe": "L2"})
        enf = Enforcement(policy, bindings, approvals, estop, executor,
                          audit_log, whitelist_admin=admin)
        rec = bindings.create(998877, "evil.exe", (0, 0, 100, 100),
                              window_title="机密文档 - 编辑器")
        req = OperationRequest("attach", {"process": "evil.exe"}, None)
        desc = enf._describe_enroll(req, rec, "evil.exe")
        headline, _, detail = desc.partition("\n---\n")
        assert "机密文档 - 编辑器" in headline
        assert "evil.exe" in detail
