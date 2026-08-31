"""发布说明渲染（ISS-0011 §3.2-B 公开入口）。

模板 release/RELEASE_NOTES.md 含占位符 {{VERSION}}/{{SHA256}}/{{ZIP_NAME}}/{{CHANGES}}。
fail-closed（约束：不允许空白正文上线）：
- version / sha256 为空 → ValueError
- 渲染后仍有 {{ }} 占位残留 → ValueError
- 渲染结果缺"系统要求"章节 → ValueError

CLI：python scripts/render_release_notes.py --version v0.3.1 --sha256 <hex> \
        [--changes-file release/CHANGES.md] [--output release-body.md]
"""

from __future__ import annotations

import argparse
from pathlib import Path

PLACEHOLDERS = ("{{VERSION}}", "{{SHA256}}", "{{ZIP_NAME}}", "{{CHANGES}}")

_DEFAULT_TEMPLATE = Path(__file__).resolve().parents[1] / "release" / "RELEASE_NOTES.md"


def render_notes(template_path, version: str, sha256: str, changes: str) -> str:
    """渲染发布说明正文（纯函数，SDD 公开入口）。

    template_path: 模板文件路径；version: 不带 v 前缀的版本号；
    sha256: zip 的 SHA256 十六进制串；changes: 变更摘要 Markdown 文本。
    返回渲染后的发布正文；空输入/占位残留/缺章节 → ValueError。
    """
    if not version or not version.strip():
        raise ValueError("version 为空，拒绝渲染发布正文（不允许空白正文上线）")
    if not sha256 or not sha256.strip():
        raise ValueError("sha256 为空，拒绝渲染发布正文（不允许空白正文上线）")
    text = Path(template_path).read_text(encoding="utf-8")
    out = (text
           .replace("{{VERSION}}", version.strip())
           .replace("{{SHA256}}", sha256.strip())
           .replace("{{ZIP_NAME}}", f"deskpilot-v{version.strip()}-windows-x64.zip")
           .replace("{{CHANGES}}", changes))
    if "{{" in out or "}}" in out:
        raise ValueError("模板占位符未全部渲染，拒绝产出")
    if "系统要求" not in out:
        raise ValueError("发布说明缺'系统要求'章节，拒绝产出")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="渲染 DeskPilot 发布说明")
    p.add_argument("--version", required=True, help="版本号，v 前缀自动去除")
    p.add_argument("--sha256", required=True, help="zip 的 SHA256（小写 hex）")
    p.add_argument("--changes-file", default=None,
                   help="变更摘要 Markdown 文件；缺省为占位说明")
    p.add_argument("--template", default=str(_DEFAULT_TEMPLATE))
    p.add_argument("--output", default=None, help="输出文件；缺省打印到 stdout")
    a = p.parse_args(argv)
    changes = (Path(a.changes_file).read_text(encoding="utf-8").strip()
               if a.changes_file else "- 变更明细见提交历史")
    body = render_notes(a.template, a.version.lstrip("vV"), a.sha256, changes)
    if a.output:
        Path(a.output).write_text(body, encoding="utf-8")
    else:
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
