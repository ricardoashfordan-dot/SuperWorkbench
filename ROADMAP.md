# Super Workbench Roadmap

[English](README.md) · [简体中文](README_ZH.md) · [AI Install Guide](AGENT_INSTALL.md) · [Changelog](CHANGELOG.md)

Super Workbench evolves around three core principles: **zero bloat**, **calm Muse/Codex minimalism**, and **local-first privacy**.

---

## v1.0 & v1.1 (Current Release)
- Zero-dependency Python 3.10+ stdlib backend + modular zero-build frontend (`index.html` + `app.css` + `app.js`)
- Local API security hardening: session token, `HttpOnly; SameSite=Strict` cookie bootstrap, Host/Origin validation, and GitHub Actions 3-OS/Python CI matrix + stdlib-only AST guard
- **Per-workspace independent role rosters** with **5 smart scene presets** (Coding, Video/Vibe, 3D Art & Modeling, Paper & Study, Security Audit), engine capability profiles, model-short avatars (zero fake uninstalled defaults), guided opt-in skill recommendations, and portable JSON preset export/import
- **Skill Ecosystem Phase 1**: 9 built-in `SKILL.md` packs, category/tag search, read-only local discovery across 5 CLIs (`codex`, `agy`, `gemini`, `claude`, `dsh`), hardened GitHub preview-before-import, and 1-click export
- Visual Zero-JSON MCP Manager (Playwright, GitHub, Figma, ComfyUI, Blender 3D, Filesystem) with 1-click CLI sync
- Per-workspace isolated chat history with file locks, atomic writes, monotonic unique IDs, CLI role persona injection, and bounded thread context memory
- Right Inspector Drawer: Live Git Diff + AI Commit loop + AIGC Studio 5-stage Screening Room (Storyboard Gallery + HTTP 206 Range Video/Audio player)
- Desktop App Mode (`--app` standalone window, `python start.py --create-shortcut`, Studio Wing `.ico`, native OS folder picker, desktop notifications)
- Instant Chinese / English UI switch + Obsidian Dark / Muse Paper Light themes + `python start.py --doctor` diagnostics

---

## v1.2 — Ecosystem Polish & Dynamic N-Agent Roster
- **MCP Self-Check & More Templates**: One-click connectivity test button, `fetch` / `context7` presets, and Gemini CLI sync.
- **Optional System Proxy for Remote Skill Import**: User opt-in setting for environments requiring a local proxy to reach GitHub.
- **Sharded Workspace Message Storage**: Partition chat history per workspace (or add in-memory cache) for fast polling at 10,000+ messages.
- **Break the 3-Slot Limit**: Add, reorder, and save 4–8+ custom specialist agents per workspace with an adaptive vertical relay track.

---

## v2.0 — Autonomous Coordinator, Parallel Swarm & Plugin Workspaces
- **Agent-Driven Task Decomposition**: A Lead Coordinator reads a high-level goal, dynamically selects or spawns specialist roles, and builds an inspectable execution plan.
- **Parallel Sub-Task Execution**: Run independent read/research/generation agents concurrently with workspace file-lock safety and live multi-lane progress tracking.
- **Pluggable Workspace Presets & Community Index**: Extract specialized workspace presets (Godot, AIGC, 3D Art, Research) into pluggable modules and add a curated community skill/roster index.
- **Optional Standalone Installers & OS Secret Storage**: Lightweight native `.exe` / `.dmg` desktop packages via OS WebView2 / WebKit + OS keyring/DPAPI secret storage.
