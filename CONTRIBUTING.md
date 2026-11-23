# Contributing to Super Workbench

Thank you for considering a contribution to **Super Workbench**!

## Core Design Rules

1. **Zero External Dependencies**: Backend modules in `workbench/` must use only the Python 3 standard library. The frontend stays a self-contained HTML/CSS/JS app with zero build step.
2. **Minimalist UX**: Follow the calm Obsidian Dark / Muse Paper Light aesthetic. Avoid cluttered forms, noisy popups, or unnecessary chrome. Hide beginner helper explanations inside collapsible `<details class="explain-fold">` elements.
3. **Zero Personal Path Hardcoding**: Never commit personal paths, usernames, API keys, or anything inside `.workbench/`.
4. **Safe CLI Invocation**: Never add sandbox-bypass or unrestricted execution flags to CLI adapters.

## Easy Ways to Contribute

### 1. Add a Built-In Starter Skill
Create a folder under `skills/<your-skill-id>/SKILL.md`:

```markdown
---
name: your-skill-id
description: One-sentence description shown in Settings and the / menu
---

Write clear, actionable instructions here.
```

### 2. Add an MCP One-Click Template
Add an entry to `MCP_TEMPLATES` in `workbench/mcp_manager.py` with `id`, `name`, `title`, `desc`, `transport` (`stdio` or `http`), and command/URL defaults.

### 3. Add a Workspace Preset
Add your directory initializer or asset scanner in `workbench/presets.py` and expose it in `workbench/server.py` (`_get_cached_ws_disk`).

## Local Verification Before PR

```bash
python -m unittest discover -s tests -v
```

Open `http://127.0.0.1:8765`, verify both Dark and Light themes (and Chinese / English UI), and ensure zero console errors.
