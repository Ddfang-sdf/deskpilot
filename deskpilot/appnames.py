"""应用显示名解析（ISS-0012 整改项 F / F2 本地化 / F3 不自维护国际化）。

app_display_name：进程 → 用户可读显示名（纯函数），解析序：
① window_title 非空原样返回（attach 路径，最贴近实况）；
② 用户界面语言的 MUI 资源描述（如 zh-CN\\notepad.exe.mui 的"记事本"）；
③ UWP 包资源显示名（注册表包仓库 → AppxManifest.xml 按 Executable 匹配 →
   ms-resource 经 SHLoadIndirectString 按界面语言解析，与窗口标题同源）；
④ exe 版本信息 FileDescription（多为英文基名，如 "Windows Calculator"）；
⑤ 全部失败返回进程名本身（文案 fail-closed，不失信息）。
中文（②③）与英文基名（④）皆有且不同 → 中英并列「计算器（Windows Calculator）」。
显示名全部来自 OS/厂商数据，本模块不自维护任何翻译（F3，sdfang 批示）。
ctypes GetFileVersionInfoW / SHLoadIndirectString，零第三方依赖。
"""

from __future__ import annotations

import ctypes
import json
import shutil
import subprocess
import winreg
import xml.etree.ElementTree as ET
from ctypes import wintypes
from pathlib import Path

_version = ctypes.windll.version
_kernel32 = ctypes.windll.kernel32
_shlwapi = ctypes.windll.shlwapi

# AppX 解析缓存：进程名(小写) → 显示名（None 表示已查过未命中）
_APPX_CACHE: dict[str, str | None] = {}


def app_display_name(process: str, window_title: str = "") -> str:
    """ISS-0012 §6：进程 → 用户可读显示名（纯函数；本地化优先，中英并列）。"""
    if window_title:
        return window_title
    proc = str(process).strip()
    if not proc:
        return str(process)
    path = _resolve_exe(proc)
    eng = _file_string(path, "FileDescription") if path else None
    local = (_mui_description(path) if path else None) \
        or _name_from_startapps(proc, eng) \
        or _appx_display_name(proc, eng)
    if local and eng and local.lower() != eng.lower():
        return f"{local}（{eng}）"
    return local or eng or proc


def app_description(process: str) -> str:
    """ISS-0012 E2：进程 → 用户可读描述（悬浮/行内提示用）。

    源注册表按序命中：AppX Description → Uninstall DisplayName →
    版本信息组合 → 进程名（诚实回退，不编造）；全部来自 OS/厂商数据。
    """
    proc = str(process).strip()
    if not proc:
        return str(process)
    for src in _DESC_SOURCES:
        r = src(proc.lower())
        if r:
            return r
    return proc


def _resolve_exe(proc: str) -> str | None:
    """进程名 → exe 全路径：源注册表首命中（扩展=往 _SOURCES 注册一行）。"""
    return _first_hit(_SOURCES, str(proc).strip().lower())


def _first_hit(sources, proc):
    """按序调用各源，返回首个非空结果；后续源不再调用（短路）。"""
    for s in sources:
        r = s(proc)
        if r:
            return r
    return None


# ---------- exe 路径源（统一契约:(proc) -> path | None） ----------

def _from_running_process(proc: str) -> str | None:
    """运行进程枚举：基名匹配 → 全路径（应用要操作时多半在跑）。"""
    return _running_procs().get(proc)


def _running_procs() -> dict:
    """运行进程基名(小写)→全路径（psapi EnumProcesses，进程级缓存一次）。"""
    if not hasattr(_running_procs, "_cache"):
        import ctypes
        from ctypes import wintypes
        out = {}
        psapi = ctypes.windll.psapi
        k32 = ctypes.windll.kernel32
        pids = (wintypes.DWORD * 1024)()
        needed = wintypes.DWORD()
        if psapi.EnumProcesses(pids, ctypes.sizeof(pids),
                               ctypes.byref(needed)):
            n = min(needed.value // 4, 1024)
            for i in range(n):
                h = k32.OpenProcess(0x1000, False, pids[i])
                if not h:
                    continue
                try:
                    buf = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(1024)
                    if k32.QueryFullProcessImageNameW(h, 0, buf,
                                                      ctypes.byref(size)):
                        p = buf.value
                        out[Path(p).name.lower()] = p
                finally:
                    k32.CloseHandle(h)
        _running_procs._cache = out
    return _running_procs._cache


def _from_path_env(proc: str) -> str | None:
    """PATH 环境变量解析。"""
    return shutil.which(proc)


def _from_app_paths(proc: str) -> str | None:
    """App Paths 注册表解析。"""
    try:
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{proc}") as k:
            v, _ = winreg.QueryValueEx(k, "")
            if v:
                return str(v)
    except OSError:
        pass
    return None


def _from_start_menu_lnk(proc: str) -> str | None:
    """开始菜单快捷方式：目标基名匹配 → 目标路径（进程级缓存映射）。"""
    return _start_menu_map().get(proc)


def _start_menu_map() -> dict:
    """开始菜单 .lnk 目标基名(小写)→目标路径（一次扫描缓存）。"""
    if not hasattr(_start_menu_map, "_cache"):
        import os
        m = {}
        try:
            from comtypes.client import CreateObject
            ws = CreateObject("WScript.Shell")
            dirs = [Path(os.environ.get("ProgramData", r"C:\ProgramData"))
                    / r"Microsoft\Windows\Start Menu\Programs",
                    Path(os.environ.get("APPDATA", ""))
                    / r"Microsoft\Windows\Start Menu\Programs"]
            for d in dirs:
                if not d.is_dir():
                    continue
                for lnk in d.rglob("*.lnk"):
                    try:
                        t = ws.CreateShortcut(str(lnk)).TargetPath
                        if t:
                            m.setdefault(Path(t).name.lower(), t)
                    except Exception:
                        continue
        except Exception:
            pass
        _start_menu_map._cache = m
    return _start_menu_map._cache


def _from_uninstall_icon(proc: str) -> str | None:
    """Uninstall 注册表 DisplayIcon 解析（基名匹配）。"""
    return _uninstall_map().get(proc, (None, None))[0]


def _uninstall_map() -> dict:
    """Uninstall 三 hive：exe 基名(小写)→(DisplayIcon 路径, DisplayName)。"""
    if not hasattr(_uninstall_map, "_cache"):
        import re
        m = {}
        hives = (
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        )
        for hive, sub in hives:
            try:
                with winreg.OpenKey(hive, sub) as k:
                    n = winreg.QueryInfoKey(k)[0]
                    for i in range(n):
                        try:
                            with winreg.OpenKey(k, winreg.EnumKey(k, i)) as app:
                                icon = _reg_str(app, "DisplayIcon")
                                name = _reg_str(app, "DisplayName")
                                if icon and ".exe" in icon.lower():
                                    p = icon.strip('"').split(",")[0]
                                    m.setdefault(Path(p).name.lower(),
                                                 (p, name or None))
                        except OSError:
                            continue
            except OSError:
                continue
        _uninstall_map._cache = m
    return _uninstall_map._cache


def _reg_str(key, name: str) -> str:
    try:
        v, _ = winreg.QueryValueEx(key, name)
        return str(v) if v else ""
    except OSError:
        return ""


# 源注册表（扩展点：新数据源=注册一行小纯函数；勿写 if 链）
_SOURCES = [_from_running_process, _from_path_env, _from_app_paths,
            _from_start_menu_lnk, _from_uninstall_icon]


# ---------- 描述源（统一契约:(proc) -> 描述 | None） ----------

def _desc_from_appx(proc: str) -> str | None:
    """AppX 清单 Description（含 stub 的 FD↔包短名恒等匹配）。"""
    for full, _short, exes, _disp, desc in _package_index():
        if proc in exes and desc:
            r = _resolve_ms_resource(desc, full) or desc
            if r:
                return r
    path = _resolve_exe(proc)
    eng = _file_string(path, "FileDescription") if path else None
    if eng:
        fd = _norm(eng)
        for full, short, _e, _d, desc in _package_index():
            cands = {_norm(short)}
            if "." in short:
                cands.add(_norm(short.split(".", 1)[1]))
            if fd in cands and desc:
                r = _resolve_ms_resource(desc, full) or desc
                if r:
                    return r
    return None


def _desc_from_uninstall_name(proc: str) -> str | None:
    """Uninstall DisplayName。"""
    return _uninstall_map().get(proc, (None, None))[1]


def _desc_from_version(proc: str) -> str | None:
    """版本信息组合：FileDescription · CompanyName。"""
    path = _resolve_exe(proc)
    if not path:
        return None
    eng = _file_string(path, "FileDescription")
    if not eng:
        return None
    company = _file_string(path, "CompanyName")
    return f"{eng} · {company}" if company else eng


_DESC_SOURCES = [_desc_from_appx, _desc_from_uninstall_name,
                 _desc_from_version]


# ---------- MUI（经典 Win32 本地化机制） ----------

def _mui_description(path: str) -> str | None:
    """读用户界面语言的 MUI 资源文件版本信息 FileDescription。

    <exe目录>\\<语言>\\<exe名>.mui；按 GetUserPreferredUILanguages 顺序尝试。
    """
    base = Path(path)
    for lang in _preferred_ui_languages():
        mui = base.parent / lang / (base.name + ".mui")
        if mui.is_file():
            desc = _file_description(str(mui))
            if desc:
                return desc
    return None


def _preferred_ui_languages() -> list[str]:
    """用户首选 UI 语言列表（如 ["zh-CN", "en-US"]）；失败回退 ["zh-CN"]。"""
    try:
        count = wintypes.ULONG(0)
        size = wintypes.ULONG(0)
        _kernel32.GetUserPreferredUILanguages(0x08, ctypes.byref(count),
                                              None, ctypes.byref(size))
        if not size.value:
            return ["zh-CN"]
        buf = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.GetUserPreferredUILanguages(
                0x08, ctypes.byref(count), buf, ctypes.byref(size)):
            return ["zh-CN"]
        langs = [s for s in buf.value.split("\x00") if s]
        return langs or ["zh-CN"]
    except Exception:
        return ["zh-CN"]


# ---------- UWP 包资源（F3：系统规范解析，不自维护翻译） ----------

_PACKAGE_KEYS = (
    (winreg.HKEY_CURRENT_USER,
     r"Software\Classes\Local Settings\Software\Microsoft\Windows"
     r"\CurrentVersion\AppModel\Repository\Packages"),
    (winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Appx"
     r"\PackageRepository\Packages"),
)


# ---------- shell 注册源（S1：UWP 本地化名称,中文优先） ----------

def _startapps_map() -> dict:
    """开始菜单注册应用快照：包族(名_哈希) → 本地化名（进程级一次性缓存）。

    数据来自 shell 注册源（Get-StartApps，与开始菜单同源，含本地化名称）；
    失败/超时（3s）返回空表，调用链自然降级（TC-SA-02/05）。
    """
    if not hasattr(_startapps_map, "_cache"):
        m: dict[str, str] = {}
        try:
            out = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command",
                 "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                 "Get-StartApps | ConvertTo-Json -Compress"],
                capture_output=True, timeout=3)
            if out.returncode == 0 and out.stdout.strip():
                data = json.loads(out.stdout.decode("utf-8", errors="replace"))
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    appid = str(item.get("AppID", ""))
                    name = str(item.get("Name", "")).strip()
                    fam = appid.split("!")[0]
                    if fam and name:
                        m.setdefault(fam, name)
        except Exception:
            pass
        _startapps_map._cache = m
    return _startapps_map._cache


def _name_from_startapps(proc: str, eng: str | None) -> str | None:
    """proc → 包族（清单 exe 匹配；stub 走 FD 恒等）→ 本地化名。"""
    fam = _package_family_of(proc, eng)
    return _startapps_map().get(fam) if fam else None


def _package_family_of(proc: str, eng: str | None) -> str | None:
    """proc → 包族名（Name_PublisherHash 形，与 AppID 族对齐）。"""
    for full, _short, exes, _d, _desc in _package_index():
        if proc in exes:
            return _family_of(full)
    if eng:
        fd = _norm(eng)
        for full, short, _e, _d, _desc in _package_index():
            cands = {_norm(short)}
            if "." in short:
                cands.add(_norm(short.split(".", 1)[1]))
            if fd in cands:
                return _family_of(full)
    return None


def _family_of(full_name: str) -> str:
    """包全名(Microsoft.X_1.2.3.4_x64__hash)→族名(Microsoft.X_hash)。"""
    parts = full_name.split("_")
    if len(parts) >= 2:
        return f"{parts[0]}_{parts[-1]}"
    return full_name


def _appx_display_name(proc: str, eng_desc: str | None) -> str | None:
    """UWP 应用显示名：两级匹配——① 清单 Executable 精确匹配；
    ② FileDescription 与包短名归一化恒等匹配（覆盖 calc.exe 这类
    遗留名 stub：其清单可执行名为 CalculatorApp.exe，精确匹配落空）。
    """
    key = proc.lower()
    if key in _APPX_CACHE:
        return _APPX_CACHE[key]
    result: str | None = None
    for full_name, short, exes, display, _desc in _package_index():
        if key in exes:
            result = _resolve_ms_resource(display, full_name) or display
            break
    if result is None and eng_desc:
        fd = _norm(eng_desc)
        if fd:
            for full_name, short, exes, display, _desc in _package_index():
                cands = {_norm(short)}
                if "." in short:            # 去厂商前缀形:WindowsCalculator
                    cands.add(_norm(short.split(".", 1)[1]))
                if fd in cands:
                    result = _resolve_ms_resource(display, full_name) or display
                    break
    _APPX_CACHE[key] = result
    return result


def _norm(s: str) -> str:
    """归一化：小写、仅留字母数字（包名/FileDescription 恒等比较用）。"""
    return "".join(c for c in s.lower() if c.isalnum())


_PKG_INDEX: list[tuple[str, str, frozenset, str, str]] | None = None


def _package_index() -> list[tuple[str, str, frozenset, str, str]]:
    """包清单索引（进程级只建一次）：
    [(包全名, 短名, 可执行名集, DisplayName, Description)]。"""
    global _PKG_INDEX
    if _PKG_INDEX is None:
        idx = []
        for full_name, root in _iter_package_roots():
            manifest = root / "AppxManifest.xml"
            if not manifest.is_file():
                continue
            try:
                entries, pkg_desc = _parse_manifest(
                    manifest.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            exes = frozenset(exe.lower() for exe, _d in entries if exe)
            display = next((d for _e, d in entries if d), "")
            if exes or display:
                idx.append((full_name, full_name.split("_")[0],
                            exes, display, pkg_desc))
        _PKG_INDEX = idx
    return _PKG_INDEX


def _iter_package_roots() -> list[tuple[str, Path]]:
    """枚举包仓库注册表，产出 (包全名, 包根目录) 列表（只读一次并缓存）。"""
    if not hasattr(_iter_package_roots, "_cache"):
        out: list[tuple[str, Path]] = []
        for hive, sub in _PACKAGE_KEYS:
            try:
                with winreg.OpenKey(hive, sub) as k:
                    n = winreg.QueryInfoKey(k)[0]
                    for i in range(n):
                        full = winreg.EnumKey(k, i)
                        root = _read_package_root(k, full)
                        if root:
                            out.append((full, root))
            except OSError:
                continue
        _iter_package_roots._cache = out
    return _iter_package_roots._cache


def _read_package_root(packages_key, full_name: str) -> Path | None:
    try:
        with winreg.OpenKey(packages_key, full_name) as k:
            for value_name in ("PackageRootFolder", "Path"):
                try:
                    v, _ = winreg.QueryValueEx(k, value_name)
                    if v and Path(str(v)).is_dir():
                        return Path(str(v))
                except OSError:
                    continue
    except OSError:
        pass
    return None


def _parse_manifest(xml_text: str) -> tuple[list[tuple[str, str]], str]:
    """解析 AppxManifest.xml：([(executable基名, DisplayName)], 包级 Description)。

    DisplayName 优先取 Application 的 VisualElements，回退包 Properties；
    Description 取包 Properties（ms-resource 本地化引用或字面量）。
    """
    root = ET.fromstring(xml_text)

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    pkg_display = ""
    pkg_desc = ""
    apps: list[tuple[str, str]] = []
    for el in root.iter():
        name = local(el.tag)
        if name == "DisplayName" and not pkg_display and el.text:
            pkg_display = el.text.strip()
        elif name == "Description" and not pkg_desc and el.text:
            pkg_desc = el.text.strip()
        elif name == "Application":
            exe = el.get("Executable", "")
            visual = ""
            for child in el.iter():
                if local(child.tag) == "VisualElements":
                    visual = child.get("DisplayName", "") or ""
                    break
            if exe:
                apps.append((Path(exe).name, visual))
    return [(exe, visual or pkg_display) for exe, visual in apps], pkg_desc


def _resolve_ms_resource(display: str, package_full_name: str) -> str | None:
    """ms-resource: 引用经 SHLoadIndirectString 按界面语言解析（与窗口标题同源）。"""
    if not display.startswith("ms-resource:"):
        return display or None
    if display.startswith("ms-resource://"):
        ref = display[len("ms-resource://"):]
    else:
        tail = display[len("ms-resource:"):]
        pkg_short = package_full_name.split("_")[0]
        ref = tail if tail.startswith("Resources/") \
            else f"{pkg_short}/Resources/{tail}"
    indirect = f"@{{{package_full_name}? ms-resource://{ref}}}"
    buf = ctypes.create_unicode_buffer(512)
    hr = _shlwapi.SHLoadIndirectString(indirect, buf, 512, None)
    if hr == 0 and buf.value.strip():
        return buf.value.strip()
    return None


# ---------- 版本信息 ----------

def _file_description(path: str) -> str | None:
    """读 exe 版本信息 FileDescription（首个翻译对）；失败返回 None。"""
    return _file_string(path, "FileDescription")


def _file_string(path: str, key: str) -> str | None:
    """读 exe 版本信息指定字符串（FileDescription/CompanyName 等，首个翻译对）。"""
    try:
        size = _version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not _version.GetFileVersionInfoW(path, 0, size, buf):
            return None

        trans = ctypes.c_void_p()
        tlen = wintypes.UINT()
        if not _version.VerQueryValueW(buf, r"\VarFileInfo\Translation",
                                       ctypes.byref(trans), ctypes.byref(tlen)):
            return None
        if not trans.value or tlen.value < 4:
            return None
        raw = ctypes.string_at(trans.value, 4)
        lang = int.from_bytes(raw[:2], "little")
        cpage = int.from_bytes(raw[2:], "little")

        sub = rf"\StringFileInfo\{lang:04x}{cpage:04x}\{key}"
        val = ctypes.c_void_p()
        vlen = wintypes.UINT()
        if not _version.VerQueryValueW(buf, sub, ctypes.byref(val),
                                       ctypes.byref(vlen)):
            return None
        if not val.value:
            return None
        s = ctypes.wstring_at(val.value).strip()
        return s or None
    except Exception:
        return None
