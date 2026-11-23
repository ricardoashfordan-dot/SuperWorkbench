# Super Workbench Roadmap

[English](README.md) · [简体中文](README_ZH.md) · [AI Install Guide](AGENT_INSTALL.md)

Super Workbench evolves around three core principles: **zero bloat**, **calm Muse/Codex minimalism**, and **local-first privacy**.

---

## v1.0 (Current Release)
- Zero-dependency Python 3 stdlib backend + modular zero-build frontend (`index.html` + `app.css` + `app.js`)
- Universal 3-role orchestration (`Planner` → `Builder` → `Reviewer`) with **collapsible DIY Role Name & Custom System Prompt** per slot
- Local CLI auto-discovery (`agy`, `codex`, `claude`, `gemini`, `dsh`) + OpenAI-compatible HTTP APIs & local Ollama
- 4-layer Skills (`SKILL.md`) engine + Visual Zero-JSON MCP Manager with 1-click CLI sync
- Multi-workspace & multi-thread conversations + 1-click Context Compaction
- 180ms in-place live streaming + GFM Markdown tables & links
- Right Inspector Drawer: Live Git Diff + AI Commit loop + AIGC Studio 5-stage Screening Room (Storyboard Gallery + HTTP 206 Range Video/Audio player)
- Desktop App Mode (`--app` standalone window, Studio Wing `.ico`, native OS folder picker, desktop notifications, global shortcuts, configurable background exit)
- Instant Chinese / English UI switch + Obsidian Dark / Muse Paper Light themes
- `python start.py --doctor` environment diagnostics & `AGENT_INSTALL.md` AI-guided installation SOP

---

## v1.1 — Custom Multi-Agent Roster (Dynamic N-Agent Teams)
- **Break the 3-slot limit**: Add, reorder, and save 4–8+ custom specialist agents per workspace (e.g., *Product Lead*, *Backend Engineer*, *UI Designer*, *Security Auditor*, *Storyboard Artist*, *Audio Editor*).
- **Dynamic Relay Rail & Composer Selector**: Adaptive vertical relay track and clean role switcher that scales smoothly beyond 3 agents without cluttering the canvas.
- **Shareable Team Presets**: Export/import a workspace's role roster + skills bundle as a single lightweight JSON preset.

---

## v2.0 — Autonomous Coordinator & Parallel DAG Swarm
- **Agent-Driven Task Decomposition**: A Lead Coordinator reads a high-level goal, dynamically selects or spawns specialist roles, and builds an inspectable execution plan.
- **Parallel Sub-Task Execution**: Run independent read/research/generation agents concurrently with workspace file-lock safety and live multi-lane progress tracking.
- **Optional Standalone Installers**: Lightweight native `.exe` / `.dmg` desktop packages via OS WebView2 / WebKit (no 200MB Electron bundle).
