# AI Agent Installation Playbook (`AGENT_INSTALL.md`)

> **For AI Agents (Claude Code, OpenAI Codex, Antigravity, Cursor, Gemini CLI, OpenClaw, etc.)**:
> When a user asks you to install and set up **Super Workbench** on their machine, follow this exact checklist step by step. Do **not** guess credentials or bypass logins — instead, inspect their machine first and present a clear, minimal preparation checklist to the user.

---

## Step 1: Clone the Repository

If the repository is not already cloned locally, clone it to a clean directory of the user's choice (e.g. `~/SuperWorkbench` or `E:\SuperWorkbench`):

```bash
git clone https://github.com/ricardoashfordan-dot/SuperWorkbench.git
cd SuperWorkbench
```

Note: Super Workbench uses **Python 3.10+ standard library only**. Do **not** run `pip install` or `npm install`.

---

## Step 2: Run the Environment Doctor

Run the built-in diagnostic command to inspect Python, Git, Node (`npx`), local AI CLIs, and local Ollama:

```bash
python start.py --doctor --json
```

*(On macOS/Linux, use `python3` if `python` is not aliased.)*

---

## Step 3: Present a Clear "What You Need to Prepare" Checklist to the User

Read the JSON output from `--doctor` and clearly tell the user:
1. **What is already ready** on their machine (e.g., detected CLIs like `codex`, `claude`, `agy`, `gemini`, or local `Ollama` models).
2. **What they need to prepare** (only list what is missing or needed for their goal):
   - **If they want automated local file editing (Core Builder role)**:
     - Recommend installing & signing into **at least one** coding CLI they already subscribe to:
       - **OpenAI Codex CLI**: `npm install -g @openai/codex` → run `codex login` (uses ChatGPT Plus / Pro subscription)
       - **Claude Code CLI**: `npm install -g @anthropic-ai/claude-code` → run `claude` to sign in (uses Claude Pro / Max subscription)
       - **Gemini CLI**: `npm install -g @google/gemini-cli` → run `gemini` to sign in (free Google account tier available)
       - **Antigravity (`agy`)**: install Antigravity CLI and sign in
     - If the user asks you to install a CLI, run the official installer command, then **pause and ask the user to complete the browser/account sign-in themselves**.
   - **If they prefer API Keys or Free Local Models (Planner / Reviewer / Chat)**:
     - **Local Ollama (Free, 0 API bill)**: Download Ollama and run e.g. `ollama pull qwen2.5:14b`, then add it in `Settings → Engines & API → Local Ollama`.
     - **Cloud OpenAI-Compatible APIs (DeepSeek / OpenRouter / OpenAI / Kimi / SiliconFlow)**: Ask the user to prepare their `sk-...` API key and paste it directly inside Super Workbench's `Settings → Engines & API` UI (do **not** commit API keys to Git).
   - **Optional Tools**:
     - **Git**: Enables Live Git Diff and 1-click AI Commit in the Right Inspector.
     - **Node.js (`npx`)**: Enables stdio MCP servers (Playwright Browser, GitHub, Filesystem) in `Settings → MCP Tools`.

---

## Step 4: Verify Installation & Launch

Run the zero-dependency regression test suite to verify everything is healthy:

```bash
python -m unittest discover -s tests -v
```

Launch Super Workbench in **Desktop App Mode** (automatically opens a standalone frameless window with session-token authentication):
- **Windows (no black CMD window)**:
  1. Create a Desktop shortcut with the studio icon:
     ```bash
     python start.py --create-shortcut
     ```
  2. Launch via `Start-SuperWorkbench.cmd` or `pythonw start.py` (do **not** pass `--no-browser` if you want the desktop app window to open automatically).
- **macOS / Linux**: run `./start.sh` or `python3 start.py`.

Verify the local server is responding (note: all `/api/*` endpoints require the local session token in `.workbench/session.token` since v1.0.1; a bare request without the token intentionally returns HTTP `403`):
- Pass `X-Workbench-Token: <contents of .workbench/session.token>` when checking `http://127.0.0.1:8765/api/live` → should return HTTP `200`.

---

## Step 5: Hand Off to the User

Tell the user:
1. Where Super Workbench is installed and how to launch it next time (**double-click the Desktop `Super Workbench` shortcut** or `Start-SuperWorkbench.cmd` on Windows, or `./start.sh` on macOS/Linux).
2. **Do NOT give the user the bare URL `http://127.0.0.1:8765/`** — opening the bare URL without `?token=` will intentionally show HTTP `403` to protect local tools from untrusted browser tabs. Always let them open via the Desktop shortcut / `Start-SuperWorkbench.cmd`, or provide the full tokenized URL `http://127.0.0.1:8765/?token=<token>` (and remind them never to share the token).
3. In **`Settings → General`**, they can customize their display name, language (`简体中文 / English`), theme (`Obsidian Dark / Muse Light`), and approval gate.
4. In **`Settings → Roles & Engines`**, they can bind any detected CLI / API to each role and expand **Customize Role Name & System Prompt** to DIY their own specialist team!
