"""界面文案翻译器（REQ-007 国际化 v1）。

**文案单源在配置文件 `deskpilot/i18n.yml`**（en 默认基线 + zh-CN 翻译；
新增/修改界面文案一律改该文件，禁止散落双语字面量进代码——
sdfang 2026-09-20 裁定：不搞散弹式修改，配置集中管理，默认英文）。

本模块只做翻译:
- `tr(key, **fmt)`:按语言取词并做格式槽替换(槽内容如进程名/路径不译);
- 语言解析序:环境变量 `DESKPILOT_LOCALE`(测试/素材生成强制开关) >
  **OS 系统语言**(GetUserPreferredUILanguages:中文 → zh-CN,其余 →
  en 默认) > en 兜底;
- fail-closed:缺键先回退 en 基线;en 也缺 → 返回键本身;均记审计
  「i18n 缺键」(每键一次,不静默)。

范围(v1):人类可见 UI(弹窗/托盘/气泡/动态描述模板)。不进:MCP 错误
消息、审计事件名、错误码名、文件协议名。
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

_DEFAULT_LANG = "en"            # 默认语言(sdfang 裁定:默认是英文)
_LOCALE_CACHE: str | None = None
_CATALOG_CACHE: dict[str, dict[str, str]] | None = None


# ---------- 目录加载(配置文件) ----------

def _catalog_path() -> Path:
    """i18n.yml 位置:源码=包目录;冻结(onefile)=_MEIPASS 解包目录。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "i18n.yml"


def _load_catalog() -> dict[str, dict[str, str]]:
    """读 i18n.yml 为 {key: {lang: text}};文件缺失/非法 → 空目录
    (取词侧全部按缺键回退+审计,fail-closed)。"""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE
    out: dict[str, dict[str, str]] = {}
    try:
        import yaml
        raw = yaml.safe_load(_catalog_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for lang, table in raw.items():
                if isinstance(table, dict):
                    for key, text in table.items():
                        out.setdefault(str(key), {})[str(lang)] = str(text)
    except Exception:
        pass                        # 加载失败=空目录,取词全走缺键兜底
    _CATALOG_CACHE = out
    return out


def reload_catalog() -> None:
    """测试/调试缝:强制重载配置文件与语言缓存。"""
    global _CATALOG_CACHE, _LOCALE_CACHE
    _CATALOG_CACHE = None
    _LOCALE_CACHE = None


# ---------- 语言解析(按系统语言) ----------

def _detect_locale() -> str:
    """语言解析:DESKPILOT_LOCALE 优先;否则按 OS 系统语言
    (中文 → zh-CN;其余 → en 默认)。"""
    override = (os.environ.get("DESKPILOT_LOCALE") or "").strip().lower()
    if override:
        return "zh-CN" if override.startswith("zh") else _DEFAULT_LANG
    global _LOCALE_CACHE
    if _LOCALE_CACHE is None:
        _LOCALE_CACHE = "zh-CN" if _os_ui_is_chinese() else _DEFAULT_LANG
    return _LOCALE_CACHE


def _os_ui_is_chinese() -> bool:
    """OS 首选界面语言含中文?失败按 False(回默认英文,不猜)。

    探测镜像 appnames 的 MUI 通道(GetUserPreferredUILanguages)。
    """
    try:
        k32 = ctypes.windll.kernel32
        count = wintypes.ULONG(0)
        size = wintypes.ULONG(0)
        if not k32.GetUserPreferredUILanguages(0x08, ctypes.byref(count),
                                               None, ctypes.byref(size)):
            return False
        if not size.value:
            return False
        buf = ctypes.create_unicode_buffer(size.value)
        if not k32.GetUserPreferredUILanguages(0x08, ctypes.byref(count),
                                               buf, ctypes.byref(size)):
            return False
        langs = [s.lower() for s in buf.value.split("\x00") if s]
        return any(s.startswith("zh") for s in langs)
    except Exception:
        return False


# ---------- 审计留痕(缺键) ----------

_AUDIT_SINK = None            # 测试替身缝:lambda event, detail=""
_missing_reported: set[str] = set()


def _audit_missing(key: str) -> None:
    if _AUDIT_SINK is None or key in _missing_reported:
        return
    _missing_reported.add(key)
    try:
        _AUDIT_SINK("i18n 缺键", key)
    except Exception:
        pass


def set_audit_sink(sink) -> None:
    """装配侧挂审计(生产:AuditLogger.record_event;测试:记录替身)。"""
    global _AUDIT_SINK
    _AUDIT_SINK = sink


# ---------- 取词 ----------

def tr(name: str, **fmt) -> str:
    """按当前语言取词;**fmt 为格式槽(槽内容不译)。

    解析:目录键 → 当前语言 → en 基线 → 键本身;后两级各记一次
    「i18n 缺键」审计(fail-closed,不静默)。
    形参名用 name 不用 key——格式槽里可能有 key= 之类
    (enf.head.tech.key 的按键槽),撞名即 TypeError。
    """
    table = _load_catalog().get(name)
    if table is None:
        _audit_missing(name)
        return name
    lang = _detect_locale()
    text = table.get(lang)
    if not text:
        text = table.get(_DEFAULT_LANG, "")
        _audit_missing(name)
    if not text:
        return name
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError, ValueError):
            return text            # 槽缺失按原文(不炸调用方)
    return text
