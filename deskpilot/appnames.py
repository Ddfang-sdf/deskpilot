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
import shutil
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
    eng = _file_description(path) if path else None
    local = (_mui_description(path) if path else None) \
        or _appx_display_name(proc, eng)
    if local and eng and local.lower() != eng.lower():
        return f"{local}（{eng}）"
    return local or eng or proc


def _resolve_exe(proc: str) -> str | None:
    """进程名 → exe 全路径（PATH 优先，App Paths 注册表兜底）。"""
    p = shutil.which(proc)
    if p:
        return p
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


def _appx_display_name(proc: str, eng_desc: str | None) -> str | None:
    """UWP 应用显示名：两级匹配——① 清单 Executable 精确匹配；
    ② FileDescription 与包短名归一化恒等匹配（覆盖 calc.exe 这类
    遗留名 stub：其清单可执行名为 CalculatorApp.exe，精确匹配落空）。
    """
    key = proc.lower()
    if key in _APPX_CACHE:
        return _APPX_CACHE[key]
    result: str | None = None
    for full_name, short, exes, display in _package_index():
        if key in exes:
            result = _resolve_ms_resource(display, full_name) or display
            break
    if result is None and eng_desc:
        fd = _norm(eng_desc)
        if fd:
            for full_name, short, exes, display in _package_index():
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


_PKG_INDEX: list[tuple[str, str, frozenset, str]] | None = None


def _package_index() -> list[tuple[str, str, frozenset, str]]:
    """包清单索引（进程级只建一次）：[(包全名, 短名, 可执行名集, DisplayName)]。"""
    global _PKG_INDEX
    if _PKG_INDEX is None:
        idx = []
        for full_name, root in _iter_package_roots():
            manifest = root / "AppxManifest.xml"
            if not manifest.is_file():
                continue
            try:
                entries = _parse_manifest(
                    manifest.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            exes = frozenset(exe.lower() for exe, _d in entries if exe)
            display = next((d for _e, d in entries if d), "")
            if exes or display:
                idx.append((full_name, full_name.split("_")[0],
                            exes, display))
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


def _parse_manifest(xml_text: str) -> list[tuple[str, str]]:
    """解析 AppxManifest.xml：[(executable基名, DisplayName)]（命名空间无关）。

    DisplayName 优先取 Application 的 VisualElements，回退包 Properties。
    """
    root = ET.fromstring(xml_text)

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    pkg_display = ""
    apps: list[tuple[str, str]] = []
    for el in root.iter():
        name = local(el.tag)
        if name == "DisplayName" and not pkg_display and el.text:
            pkg_display = el.text.strip()
        elif name == "Application":
            exe = el.get("Executable", "")
            visual = ""
            for child in el.iter():
                if local(child.tag) == "VisualElements":
                    visual = child.get("DisplayName", "") or ""
                    break
            if exe:
                apps.append((Path(exe).name, visual))
    return [(exe, visual or pkg_display) for exe, visual in apps]


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

        sub = rf"\StringFileInfo\{lang:04x}{cpage:04x}\FileDescription"
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
