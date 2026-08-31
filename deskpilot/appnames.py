"""应用显示名解析（ISS-0012 整改项 F）。

app_display_name：进程 → 用户可读显示名（纯函数），三级解析序：
① window_title 非空原样返回（attach 路径，最贴近实况）；
② 按进程名解析 exe 全路径（PATH / App Paths），读版本信息 FileDescription
   （ctypes GetFileVersionInfoW + VerQueryValueW，零第三方依赖）；
③ 全部失败返回进程名本身（文案 fail-closed，不失信息）。
"""

from __future__ import annotations

import ctypes
import shutil
import winreg
from ctypes import wintypes

_version = ctypes.windll.version


def app_display_name(process: str, window_title: str = "") -> str:
    """ISS-0012 §6：进程 → 用户可读显示名（纯函数，三级解析序）。"""
    if window_title:
        return window_title
    proc = str(process).strip()
    if not proc:
        return str(process)
    path = _resolve_exe(proc)
    if path:
        desc = _file_description(path)
        if desc:
            return desc
    return proc


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
