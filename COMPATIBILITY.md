# CLI Compatibility Matrix

This table records the exact local CLI versions last verified against **Super Workbench**, along with how each engine's model list is populated. Run `python start.py --doctor` on your own machine to inspect live installed versions and model sources.

| Engine | Verified CLI version | Last verified | Model source | Notes |
| :--- | :--- | :---: | :---: | :--- |
| **Antigravity (`agy`)** | `1.5.14` | `2026-11-23` | `fallback` | No local model cache file; `agy models` performs a slow network RPC (>3s), so built-in `DEFAULT_AGY_OPTIONS` is used. |
| **OpenAI Codex (`codex`)** | `codex-cli 0.171.0` | `2026-11-23` | `discovered` | Live discovery from `~/.codex/models_cache.json` with defensive parsing and automatic fallback to `FALLBACK_CODEX_OPTIONS`. |
| **Claude Code (`claude`)** | not installed on maintainer machine | `2026-11-23` | `fallback` | Uses built-in `DEFAULT_CLAUDE_OPTIONS`; no documented local models cache file. |
| **Gemini CLI (`gemini`)** | not installed on maintainer machine | `2026-11-23` | `fallback` | Uses built-in `DEFAULT_GEMINI_OPTIONS`; no documented local models cache file. |
| **DSH (`dsh`)** | `0.1.5-rc.2` | `2026-11-23` | `n/a` | Headless verification/gate runner; does not select an LLM model. |

## Model Source Legend
- **`discovered`**: Read dynamically from a local cache/config file maintained by the CLI itself.
- **`fallback`**: Built-in curated list in `workbench/adapters.py` (marked with `# Last verified: YYYY-MM-DD`). You can always type any custom model ID in `Settings → Roles & Engines` or connect an OpenAI-compatible API / local Ollama model.
- **`n/a`**: Engine does not use a model list.
