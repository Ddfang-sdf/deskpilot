<p align="center">
  <img src="assets/logo-dp.png" alt="DeskPilot" width="128">
</p>

<h1 align="center">DeskPilot</h1>

<p align="center">
  <strong>Let AI operate your Windows desktop — safely.</strong><br>
  WeChat, Excel, legacy ERPs, internal systems… if it has no API, DeskPilot lets AI drive it anyway.
</p>

<p align="center">
  <a href="https://github.com/Ddfang-sdf/deskpilot/releases"><img src="https://img.shields.io/github/v/release/Ddfang-sdf/deskpilot" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Ddfang-sdf/deskpilot" alt="License"></a>
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4" alt="Platform">
  <img src="https://img.shields.io/badge/MCP-stdio-6E56CF" alt="MCP">
  <img src="https://img.shields.io/badge/tests-209%20passed-2DA44E" alt="Tests">
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> ·
  <a href="docs/DESIGN.md">Design Docs</a> ·
  <a href="https://github.com/Ddfang-sdf/deskpilot/releases">Releases</a> ·
  <a href="README.md">中文</a>
</p>

<p align="center">
  <img src="assets/demo.gif" alt="DeskPilot live demo: AI types into Notepad via MCP → closing the window triggers local approval → executes only after the human approves" width="880"><br>
  <em>Live demo: AI types via MCP → requests a dangerous op (close window) → local approval toast with a live thumbnail of the target → executes only after the human approves</em>
</p>

---

## Safety you can see

Dangerous operations require your explicit approval — the AI requests, the program prompts, and nothing executes until you click. The AI never sees a token it could reuse to bypass you:

<p align="center">
  <img src="assets/screenshot-approval-toast.png" alt="Local approval for dangerous operations" width="520"><br>
  <em>Dangerous ops (e.g. closing a window): local approval toast with a live thumbnail of the target window and a countdown — auto-denied on timeout</em>
</p>

If anything feels wrong, hit <code>Ctrl+Shift+F12</code> to freeze all write operations instantly (or flick your mouse into the top-left corner and hold). The freeze tells you itself — no more discovering a silent AI hours later:

<p align="center">
  <img src="assets/screenshot-freeze-card.png" alt="Emergency-stop freeze notification" width="440"><br>
  <em>Freeze notification: unfreeze now / remind me later — and it dismisses itself when you unfreeze via hotkey</em>
</p>

<!-- Demo GIF: assets/demo.gif (live recording: typing into Notepad → alt+f4 triggers approval → approved → executed). See release/RELEASE_NOTES.md for how to re-record. -->

## Why DeskPilot

- 🛡️ **Safety by enforcement, not by prompt** — every click and keystroke passes a hard verification layer (binding check / process whitelist / key permit / local approval for dangerous ops — four fail-closed gates). Approval belongs to the human at the keyboard, period.
- 🔌 **Plug & play** — standard MCP (stdio). Works with Claude Code, Claude Desktop, Cursor, and any MCP client.
- 👁️ **No vision model required** — screen content is translated into an element list plus text (UIA tree + OCR dual channel), so text-only models can drive the UI.
- 🛑 **Emergency stop with feedback** — hotkey or corner-flick freezes all writes; a toast confirms the freeze and offers one-click unfreeze.
- 📼 **Full audit trail** — automatic before/after screenshots plus JSONL audit logs for every action.

## 🚀 Quick Start

**Step 1: Download.** Grab the latest `deskpilot-vX.Y.Z-windows-x64.zip` from [Releases](https://github.com/Ddfang-sdf/deskpilot/releases) and extract to a fixed folder, e.g. `C:\tools\deskpilot\`.

> ⚠️ Keep `policy.yml` and `deskpilot.exe` in the **same folder** — the security policy is loaded from beside the exe.

**Step 2: Hook up your AI client.**

Claude Code (CLI):

```powershell
claude mcp add deskpilot -- "C:\tools\deskpilot\deskpilot.exe"
```

Claude Desktop — edit `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "deskpilot": { "command": "C:\\tools\\deskpilot\\deskpilot.exe" }
  }
}
```

Cursor — edit `%USERPROFILE%\.cursor\mcp.json` (or use Settings → MCP), same content. Any MCP client that supports stdio works: point `command` at `deskpilot.exe`.

**Step 3: Restart the client and verify.** Tell your AI: "**take a screenshot with deskpilot**". If a screenshot comes back, you're set.

## How it works

```
AI client ──MCP(stdio)──▶ deskpilot ──4 fail-closed gates──▶ Windows desktop
                              │
                              ├─ dangerous op → local approval toast (executes only if you approve)
                              ├─ emergency stop → freeze notification card (one-click unfreeze)
                              └─ everything → screenshot + JSONL audit trail
```

23 MCP tools (screenshot / OCR / element tree / click / type / window management…). The full security model, gate internals, and protocol design live in [docs/](docs/DESIGN.md) (Chinese).

## Security notes

- By default only whitelisted everyday apps (Notepad, Paint, Explorer, PowerPoint) are operable; everything else is unreachable. Edit `policy.yml` beside the exe to extend the list.
- Dangerous operations (closing windows, deletion, etc.) always require local approval and are auto-denied on timeout. Approval tokens never pass through the AI.
- Freeze everything anytime with **`Ctrl+Shift+F12`**; resume with `Ctrl+Shift+F11` — or flick the mouse into the top-left corner and hold to freeze.

## Develop from source

```powershell
git clone https://github.com/Ddfang-sdf/deskpilot.git
cd deskpilot
pip install -e .
python -m deskpilot
```

Requires Windows 10/11 + Python ≥ 3.12. Run tests: `python -m pytest tests/ -q` (209 cases). Build the exe yourself: `pip install pyinstaller && pyinstaller deskpilot.spec`.

## Roadmap

- [x] M1 security core: four-gate enforcement layer, audit trail, emergency stop
- [x] M2 element-level operations: UIA-first, zero pixel-coordinate clicking/typing
- [x] M3 SoM annotated screenshots + local approval channel
- [x] Human-aware freeze: notification card, synchronous approve-then-execute
- [ ] Multi-monitor support
- [ ] One-click setup wizards for more clients

## Contributing

Issues and PRs are welcome. For security-related changes, please update the design docs in `docs/` together with the code — in this project, design documents are reviewed in the same repo as the code.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Ddfang-sdf/deskpilot&type=Date)](https://star-history.com/#Ddfang-sdf/deskpilot&Date)

## License

MIT
