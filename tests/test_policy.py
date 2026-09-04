"""策略管理（policy.load_policy）单元测试。

覆盖：TC-S-POL-01/02/03、DDS §5.12、附录B-1 关联（input_max_chars 默认值）。
断言值来源：load_policy 返回值（Policy 对象）与 PolicyError 异常。
"""

from __future__ import annotations

import pytest
import yaml

from deskpilot.errors import PolicyError
from deskpilot.policy import load_policy

from .conftest import policy_yaml_dict


def _write(tmp_path, content: dict) -> str:
    p = tmp_path / "policy.yml"
    p.write_text(yaml.safe_dump(content, allow_unicode=True), encoding="utf-8")
    return str(p)


class TestLoadValid:
    def test_load_valid_policy(self, tmp_path):
        """TC-N-MAIN-01 前置 + DDS §5.12：合法策略加载成功，可选节取默认值。"""
        path = _write(tmp_path, policy_yaml_dict(str(tmp_path / "audit")))
        policy = load_policy(path)

        assert policy.whitelist["notepad.exe"] == "L2"       # 默认上限 L2
        assert policy.whitelist["explorer.exe"] == "L1"      # 显式上限 L1
        assert "cmd.exe" in policy.terminal_apps
        assert "enter" in policy.l2_keys and "alt+f4" in policy.l3_keys
        # 可选节缺省默认值（DDS §5.9）
        assert policy.input_max_chars == 65536
        assert policy.l0_during_freeze is True
        assert policy.corner_hold_ms == 1000        # ISS-0028 默认阈值
        assert policy.input_scenario_keys == frozenset({"backspace"})
        assert policy.input_control_types == frozenset({"Edit", "Document"})
        assert policy.binding_ttl == 600.0

    def test_process_name_normalized_lowercase(self, tmp_path):
        """TC-S-WL-04：进程名大小写归一，不绕过、不误伤。"""
        content = policy_yaml_dict(str(tmp_path / "audit"))
        content["whitelist"] = [{"process": "NOTEPAD.EXE"}]
        policy = load_policy(_write(tmp_path, content))
        assert "notepad.exe" in policy.whitelist

    def test_custom_limits_and_estop(self, tmp_path):
        """limits / estop 节显式配置时按配置加载。"""
        content = policy_yaml_dict(str(tmp_path / "audit"))
        content["limits"] = {"input_max_chars": 100}
        content["estop"] = {"l0_during_freeze": False, "corner_hold_ms": 500}
        policy = load_policy(_write(tmp_path, content))
        assert policy.input_max_chars == 100
        assert policy.l0_during_freeze is False
        assert policy.corner_hold_ms == 500


class TestRefuseInvalid:
    """TC-S-POL-03：缺失/非法策略拒绝启动。"""

    def test_missing_file_refused(self, tmp_path):
        with pytest.raises(PolicyError):
            load_policy(str(tmp_path / "no_such_policy.yml"))

    def test_missing_section_refused(self, tmp_path):
        content = policy_yaml_dict(str(tmp_path / "audit"))
        del content["keys"]                       # 缺必填节
        with pytest.raises(PolicyError):
            load_policy(_write(tmp_path, content))

    def test_illegal_value_refused(self, tmp_path):
        content = policy_yaml_dict(str(tmp_path / "audit"))
        content["timeouts"]["binding_ttl"] = -5   # 非法值（非正数）
        with pytest.raises(PolicyError):
            load_policy(_write(tmp_path, content))

    def test_illegal_level_refused(self, tmp_path):
        content = policy_yaml_dict(str(tmp_path / "audit"))
        content["whitelist"] = [{"process": "notepad.exe", "max_level": "L9"}]
        with pytest.raises(PolicyError):
            load_policy(_write(tmp_path, content))


class TestImmutability:
    """TC-S-POL-01/02 本质：已加载策略运行期不可变（INV-9）。"""

    def test_policy_immutable(self, tmp_path):
        policy = load_policy(_write(tmp_path, policy_yaml_dict(str(tmp_path / "audit"))))
        with pytest.raises(Exception):
            policy.whitelist["evil.exe"] = "L2"      # 映射不可写
        with pytest.raises(Exception):
            policy.binding_ttl = 1                   # 冻结对象不可赋值
        assert "evil.exe" not in policy.whitelist
        assert policy.binding_ttl == 600.0
