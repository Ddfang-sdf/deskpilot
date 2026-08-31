"""ISS-0011 Release 自动化与安装指导测试（问题单 §4.1）。

层级：
- 发布工作流 = 集成（断言在落盘文件 .github/workflows/release.yml 解析结构，直出）；
- 发布说明渲染 = 单元（纯函数 render_notes 返回值，直出）；
- install.ps1 = 黑盒（powershell -File 命令行驱动；断言在退出码/落盘文件/替身 CLI 调用记录，均直出）。

入口（设计定义公开入口）：
- .github/workflows/release.yml（文件本身）
- scripts/render_release_notes.py: render_notes(template_path, version, sha256, changes)
- scripts/install.ps1 -LocalZip/-InstallDir/-Client/-WithDaemon/-AutoStart
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
RENDER_PY = ROOT / "scripts" / "render_release_notes.py"
INSTALL_PS1 = ROOT / "scripts" / "install.ps1"
TEMPLATE = ROOT / "release" / "RELEASE_NOTES.md"


def _load_render():
    """按文件路径加载 scripts/render_release_notes.py（scripts 非包）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("render_release_notes", RENDER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- B 发布工作流 ----------

class TestWorkflow:
    """场景:release.yml 存在、语法合法、触发器与步骤符合方案 B。
    断言:YAML 解析后的 dict 字段（直出）。"""

    def _data(self):
        assert WORKFLOW.exists(), ".github/workflows/release.yml 不存在"
        return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    def test_yaml_parses(self):
        data = self._data()
        assert isinstance(data, dict) and "jobs" in data

    def test_tag_trigger_and_pr_dryrun(self):
        """触发器:推 v* tag 触发正式发布;PR 触发干跑(约束:先干跑验证)。"""
        data = self._data()
        on = data.get("on", data.get(True))  # PyYAML 把 on 解析为 True
        assert "v*" in on["push"]["tags"]
        assert "pull_request" in on

    def test_build_steps_pinned(self):
        """构建与本地同规格:Python 3.13 + 同一 deskpilot.spec(方案约束)。"""
        data = self._data()
        steps = data["jobs"]["build"]["steps"]
        runs = "\n".join(s.get("run", "") for s in steps)
        assert "3.13" in json.dumps(steps)
        assert "pyinstaller deskpilot.spec" in runs
        assert "pip install -e . pyinstaller" in runs

    def test_package_triplet(self):
        """打包三件套:exe + policy.yml 进 zip,另产 SHA256(方案 B)。"""
        data = self._data()
        runs = "\n".join(s.get("run", "") for s in data["jobs"]["build"]["steps"])
        assert "policy.yml" in runs
        assert "Compress-Archive" in runs
        assert "Get-FileHash" in runs

    def test_release_only_on_tag(self):
        """release 创建步骤必须带 tag 守卫;正文经 render_release_notes 渲染(模板化)。"""
        data = self._data()
        steps = data["jobs"]["build"]["steps"]
        rel = [s for s in steps if "gh release create" in s.get("run", "")]
        assert len(rel) == 1
        assert "refs/tags/" in rel[0].get("if", "")
        runs = "\n".join(s.get("run", "") for s in steps)
        assert "render_release_notes.py" in runs


# ---------- B 发布说明渲染 ----------

class TestRenderNotes:
    """场景:模板渲染发布说明,三要素齐全、无占位残留、空输入 fail-closed。
    断言:render_notes 返回值字符串 / 抛出的异常（直出）。"""

    def test_render_contains_three_elements(self):
        m = _load_render()
        out = m.render_notes(TEMPLATE, version="0.3.1", sha256="a" * 64,
                             changes="- 条目甲\n- 条目乙")
        assert "0.3.1" in out                       # 要素1:版本号
        assert "a" * 64 in out                      # 要素2:SHA256 校验值
        assert "系统要求" in out                     # 要素3:最低系统要求

    def test_render_no_placeholder_left(self):
        m = _load_render()
        out = m.render_notes(TEMPLATE, version="0.3.1", sha256="b" * 64,
                             changes="- 条目")
        assert "{{" not in out and "}}" not in out

    def test_render_zip_name_derived(self):
        """zip 文件名按约定 deskpilot-v{version}-windows-x64.zip 派生并写入正文。"""
        m = _load_render()
        out = m.render_notes(TEMPLATE, version="0.3.1", sha256="c" * 64,
                             changes="- 条目")
        assert "deskpilot-v0.3.1-windows-x64.zip" in out

    def test_empty_version_fails(self):
        """fail-closed:版本号为空不允许出正文(约束:不允许空白正文上线)。"""
        m = _load_render()
        with pytest.raises(ValueError):
            m.render_notes(TEMPLATE, version="", sha256="d" * 64, changes="- 条目")

    def test_empty_sha256_fails(self):
        m = _load_render()
        with pytest.raises(ValueError):
            m.render_notes(TEMPLATE, version="0.3.1", sha256="", changes="- 条目")


# ---------- D install.ps1（黑盒）----------

def _make_zip(tmp_path: Path) -> Path:
    """造发行 zip 夹具:deskpilot.exe(伪)+ policy.yml。"""
    z = tmp_path / "deskpilot-v9.9.9-windows-x64.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("deskpilot.exe", b"MZ-fake-exe")
        f.writestr("policy.yml", "whitelist: []\n")
    return z


def _run_install(args: list[str], env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(INSTALL_PS1), *args],
        capture_output=True, text=True, errors="replace",
        env=env, timeout=120)


class TestInstallLayout:
    """场景:就地 zip 解压落位;缺 zip fail-closed;同参数连跑幂等。
    断言:退出码 + 落盘文件清单与字节内容（直出）。"""

    def test_install_local_zip_layout(self, tmp_path):
        z = _make_zip(tmp_path)
        d = tmp_path / "installed"
        r = _run_install(["-LocalZip", str(z), "-InstallDir", str(d), "-Client", "none"])
        assert r.returncode == 0, r.stdout + r.stderr
        assert (d / "deskpilot.exe").read_bytes() == b"MZ-fake-exe"
        assert (d / "policy.yml").read_text() == "whitelist: []\n"

    def test_install_idempotent(self, tmp_path):
        """同参数连跑两次:退出码均 0,目录文件清单与内容哈希一致(§4.1 幂等)。"""
        import hashlib
        z = _make_zip(tmp_path)
        d = tmp_path / "installed"
        args = ["-LocalZip", str(z), "-InstallDir", str(d), "-Client", "none"]
        r1 = _run_install(args)
        snap1 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(d.iterdir())}
        r2 = _run_install(args)
        snap2 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(d.iterdir())}
        assert r1.returncode == 0 and r2.returncode == 0
        assert snap1 == snap2

    def test_missing_zip_fails_closed(self, tmp_path):
        r = _run_install(["-LocalZip", str(tmp_path / "nope.zip"),
                          "-InstallDir", str(tmp_path / "d"), "-Client", "none"])
        assert r.returncode != 0


@pytest.fixture
def claude_stub(tmp_path):
    """替身 claude.cmd:记录全部调用到日志文件;mcp get 返 1(未注册)。

    黑盒替身——不 import 源码,经 PATH 前置让被测脚本调用;
    断言在调用记录文件(直出)。
    """
    stub_dir = tmp_path / "stubbin"
    stub_dir.mkdir()
    log = tmp_path / "claude_calls.log"
    (stub_dir / "claude.cmd").write_text(
        "@echo off\r\n"
        f'echo %* >> "{log}"\r\n'
        'if "%1"=="mcp" if "%2"=="get" exit /b 1\r\n'
        "exit /b 0\r\n",
        encoding="ascii")
    return stub_dir, log


class TestRegisterClient:
    """场景:-Client 注册到各客户端;注册命令与手工 claude mcp add 等价;幂等。
    断言:替身调用记录 / 落盘 JSON 配置（直出）。"""

    def test_register_claude_code(self, tmp_path, claude_stub):
        stub_dir, log = claude_stub
        z = _make_zip(tmp_path)
        d = tmp_path / "installed"
        env = {"PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}"}
        r = _run_install(["-LocalZip", str(z), "-InstallDir", str(d),
                          "-Client", "claude-code"], env)
        assert r.returncode == 0, r.stdout + r.stderr
        calls = log.read_text(encoding="utf-8", errors="replace")
        exe = str(d / "deskpilot.exe")
        assert re.search(rf"mcp add deskpilot -- .*{re.escape(exe)}", calls)

    def test_register_claude_code_idempotent(self, tmp_path, claude_stub):
        """连跑两次:每次先 remove 后 add(同一组手工命令),不堆积重复注册。"""
        stub_dir, log = claude_stub
        z = _make_zip(tmp_path)
        d = tmp_path / "installed"
        env = {"PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}"}
        args = ["-LocalZip", str(z), "-InstallDir", str(d), "-Client", "claude-code"]
        r1 = _run_install(args, env)
        r2 = _run_install(args, env)
        assert r1.returncode == 0 and r2.returncode == 0
        calls = log.read_text(encoding="utf-8", errors="replace")
        assert calls.count("mcp add deskpilot") == 2
        assert calls.count("mcp remove deskpilot") == 2

    def test_register_cursor_json(self, tmp_path):
        """cursor:写 %USERPROFILE%\\.cursor\\mcp.json(env 重定向,不碰真实配置)。"""
        z = _make_zip(tmp_path)
        d = tmp_path / "installed"
        home = tmp_path / "home"
        env = {"USERPROFILE": str(home)}
        r = _run_install(["-LocalZip", str(z), "-InstallDir", str(d),
                          "-Client", "cursor"], env)
        assert r.returncode == 0, r.stdout + r.stderr
        cfg = json.loads((home / ".cursor" / "mcp.json").read_text(encoding="utf-8-sig"))
        assert cfg["mcpServers"]["deskpilot"]["command"] == str(d / "deskpilot.exe")

    def test_register_cursor_idempotent_single_key(self, tmp_path):
        """cursor 连跑两次:mcpServers 下 deskpilot 仍只有一个键。"""
        z = _make_zip(tmp_path)
        d = tmp_path / "installed"
        home = tmp_path / "home"
        env = {"USERPROFILE": str(home)}
        args = ["-LocalZip", str(z), "-InstallDir", str(d), "-Client", "cursor"]
        _run_install(args, env)
        _run_install(args, env)
        cfg = json.loads((home / ".cursor" / "mcp.json").read_text(encoding="utf-8-sig"))
        assert list(cfg["mcpServers"]).count("deskpilot") == 1

    def test_register_claude_desktop_preserves_existing(self, tmp_path):
        """claude-desktop:合并进 claude_desktop_config.json,已有 server 不丢。"""
        z = _make_zip(tmp_path)
        d = tmp_path / "installed"
        appdata = tmp_path / "appdata"
        cfg_dir = appdata / "Claude"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "claude_desktop_config.json").write_text(
            json.dumps({"mcpServers": {"other": {"command": "x.exe"}}}),
            encoding="utf-8")
        env = {"APPDATA": str(appdata)}
        r = _run_install(["-LocalZip", str(z), "-InstallDir", str(d),
                          "-Client", "claude-desktop"], env)
        assert r.returncode == 0, r.stdout + r.stderr
        cfg = json.loads((cfg_dir / "claude_desktop_config.json")
                         .read_text(encoding="utf-8-sig"))
        assert cfg["mcpServers"]["other"]["command"] == "x.exe"
        assert cfg["mcpServers"]["deskpilot"]["command"] == str(d / "deskpilot.exe")

    def test_client_none_writes_no_config(self, tmp_path):
        """-Client none:不写任何客户端配置(fail-closed 默认,不碰用户环境)。"""
        z = _make_zip(tmp_path)
        d = tmp_path / "installed"
        home = tmp_path / "home"
        appdata = tmp_path / "appdata"
        env = {"USERPROFILE": str(home), "APPDATA": str(appdata)}
        r = _run_install(["-LocalZip", str(z), "-InstallDir", str(d),
                          "-Client", "none"], env)
        assert r.returncode == 0
        assert not (home / ".cursor" / "mcp.json").exists()
        assert not (appdata / "Claude" / "claude_desktop_config.json").exists()
