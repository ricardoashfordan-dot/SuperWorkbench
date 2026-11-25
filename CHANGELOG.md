# Changelog

All notable changes to **Super Workbench** are documented in this file.

---

## [1.1.0] - 2026-11-25

### Highlights
- **Per-Workspace Independent Role Rosters & 5 Smart Scenes** (#7):
  - Each workspace now maintains its own isolated role bindings (Planner / Builder / Reviewer) without overwriting other workspaces, while supporting global default inheritance and one-click reset.
  - Added a 1-click **Workspace Roster Popover** beside the composer with 5 built-in scene presets: **Coding**, **Video / Vibe Creation**, **3D Art & Modeling**, **Paper & Deep Study**, and **Security Audit**.
  - Added engine capability profiles (`strength_zh` / `strength_en` / `capabilities`), guided opt-in skill recommendations (never silently auto-enabled), and portable JSON preset export/import.
- **Honest Defaults & Model-Short Avatars** (#3, #7):
  - Never fakes uninstalled `AGY` / `CDX` / `DSH` bindings when those CLIs are not installed; gracefully falls back to available CLIs or custom API/Ollama engines, or displays neutral `Unset` / `未配`.
  - Replaced hardcoded engine initials on the vertical relay rail, composer pills, and chat cards with dynamic 2–4 character **model abbreviations** (`GPT`, `CLD`, `GEM`, `DS`, `DSR`, `QWN`, `KMI`, `DSH`, etc.).
- **Skill Ecosystem Phase 1** (#6, #7):
  - Expanded built-in skills from 3 to **9**: `aigc-storyboard`, `art-3d-pipeline`, `bug-triage`, `code-review-strict`, `deep-research`, `doc-writer`, `git-commit-release`, `paper-study`, and `security-audit`.
  - Added `category` & `tags` metadata, live search & tag filtering, read-only local discovery for `~/.gemini/skills` and `~/.dsh/skills`, 1-click `SKILL.md` export, and hardened **Import from GitHub** with mandatory full-text preview before install (HTTPS allowlist, safe redirect validation, 8s deadline, 128 KB streaming cap, path-traversal & symlink defenses).
- **3D Art & Modeling Starter** (#7):
  - Added `skills/art-3d-pipeline/SKILL.md` and the **Blender 3D Modeling Bridge** (`uvx blender-mcp`) template in `Settings → MCP Tools`.
- **CLI Persona Injection, Thread Context & Workspace Chat History** (#5, #8):
  - All 6 CLI transports (`agy`, `codex`, `claude`, `gemini`, `dsh`, `custom-cli`) now receive configured role `system_prompt` and bounded per-thread conversation context.
  - Hardened `custom-cli` template argument splitting before `{cwd}` / `{prompt}` substitution.
  - Replaced the global 400-message cap with cross-platform file-locked, atomic writes and monotonic `.sequence.json` IDs, strictly isolated per `workspace_id`.
- **Accurate Reviewer & Godot Quality Gates** (#4):
  - Reviewer pipeline accurately separates success, failure, exception, and user cancellation (`130`).
  - Workspace-scoped Godot self-check and real evidence parsing (`desktop.json`, report latency, and `*smoke*.json` `movement_ms`/`jump_ms`).
- **Adapter Hardening, Diagnostics & Onboarding** (#1, #2, #3):
  - Added GitHub Actions 3-environment CI matrix (Ubuntu 3.10 / 3.12, Windows 3.12) and zero-dependency stdlib AST guard (`scripts/check_stdlib_only.py`).
  - Added defensive Codex model discovery tagging (`discovered` / `fallback`), `--doctor` CLI version probes with 3s timeouts, and `COMPATIBILITY.md`.
  - Added `python start.py --create-shortcut` (Windows Desktop shortcut), synced `AGENT_INSTALL.md` with session-token auth, and removed stale HTML placeholders.

---

## [1.0.1] - 2026-11-23

- **Local API Security Hardening**: Added local session-token auth (`.workbench/session.token` + `HttpOnly; SameSite=Strict` cookie bootstrap + `X-Workbench-Token`), strict `Host` validation (DNS rebinding defense), and cross-site `Origin` validation.

---

## [1.0.0] - 2026-11-23

- Initial open-source release: zero-dependency Python 3.10+ stdlib backend, modular dual-theme UI (Obsidian Dark ⇄ Muse Paper Light), Desktop App Mode (`--app`), 3-role orchestration, Skills & Visual MCP Manager, Live Git Diff + AI Commit, and AIGC Studio Screening Room.
