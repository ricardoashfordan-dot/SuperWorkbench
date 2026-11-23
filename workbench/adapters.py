import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import config

_CLI_CACHE: dict = {"ts": 0.0, "data": None}
MAX_DISCOVERED_MODELS = 50
MAX_MODEL_ID_LEN = 120
MAX_CACHE_BYTES = 2 * 1024 * 1024

# Last verified: 2026-11-23
DEFAULT_AGY_OPTIONS = [
    {"id": "gemini-4-neon-high", "label": "Gemini 4 Neon (High)"},
    {"id": "gemini-4-neon-xhigh", "label": "Gemini 4 Neon (XHigh)"},
    {"id": "gemini-4-neon-medium", "label": "Gemini 4 Neon (Medium)"},
    {"id": "gemini-4-argon-high", "label": "Gemini 4 Argon (High)"},
    {"id": "gemini-4-hydrogen-high", "label": "Gemini 4 Hydrogen (High)"},
    {"id": "gemini-3.8-flash-high", "label": "Gemini 3.8 Flash (High · Fast)"},
    {"id": "claude-opus-5-5-high", "label": "Claude Opus 5.5 (High)"},
    {"id": "claude-sonnet-5-5-high", "label": "Claude Sonnet 5.5 (High)"},
    {"id": "gpt-oss-120b-medium", "label": "GPT-OSS 120B (Medium)"},
]

# Last verified: 2026-11-23
FALLBACK_CODEX_OPTIONS = [
    {"id": "gpt-6.2-sol", "label": "gpt-6.2-sol"},
    {"id": "gpt-6.2-astra", "label": "gpt-6.2-astra"},
    {"id": "gpt-6.1-sol", "label": "gpt-6.1-sol"},
    {"id": "o3", "label": "o3"},
    {"id": "o4-mini", "label": "o4-mini"},
]

# Last verified: 2026-11-23
DEFAULT_CLAUDE_OPTIONS = [
    {"id": "claude-sonnet-4-5", "label": "Claude Sonnet 4.5"},
    {"id": "claude-opus-4-5", "label": "Claude Opus 4.5"},
]

# Last verified: 2026-11-23
DEFAULT_GEMINI_OPTIONS = [
    {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
    {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
]

SLOT_ALIASES = {
    "agy": "planner",
    "planner": "planner",
    "codex": "builder",
    "builder": "builder",
    "dsh": "reviewer",
    "reviewer": "reviewer",
}


def normalize_slot(name: str) -> str:
    return SLOT_ALIASES.get(str(name or "").lower(), "planner")


def _effective_home() -> Path:
    env_home = os.environ.get("HOME")
    if env_home:
        return Path(env_home)
    return Path.home()


def discover_codex_models_with_source() -> tuple[list[dict], str]:
    """Read Codex CLI's local models cache defensively; return (options, 'discovered'|'fallback')."""
    cache = _effective_home() / ".codex" / "models_cache.json"
    if not cache.exists() or not cache.is_file():
        return list(FALLBACK_CODEX_OPTIONS), "fallback"
    try:
        # defensive: cap file size before reading so a corrupted/oversized vendor cache cannot exhaust memory
        if cache.stat().st_size > MAX_CACHE_BYTES:
            return list(FALLBACK_CODEX_OPTIONS), "fallback"
        # defensive: this file is vendor-controlled — never trust its JSON shape, fall back on any error
        data = json.loads(cache.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return list(FALLBACK_CODEX_OPTIONS), "fallback"
        raw_models = data.get("models")
        if not isinstance(raw_models, list):
            return list(FALLBACK_CODEX_OPTIONS), "fallback"

        out, seen = [], set()
        for m in raw_models:
            if not isinstance(m, dict):
                continue
            slug = m.get("slug") or m.get("id")
            if not isinstance(slug, str):
                continue
            slug = slug.strip()[:MAX_MODEL_ID_LEN]
            if not slug or slug in seen or slug == "codex-auto-review":
                continue
            seen.add(slug)
            out.append({"id": slug, "label": slug})
            if len(out) >= MAX_DISCOVERED_MODELS:
                break
        if out:
            return out, "discovered"
        return list(FALLBACK_CODEX_OPTIONS), "fallback"
    except Exception:
        return list(FALLBACK_CODEX_OPTIONS), "fallback"


def discover_codex_models() -> list[dict]:
    options, _ = discover_codex_models_with_source()
    return options


def discover_engine_models(engine_id: str) -> tuple[list[dict], str]:
    """Return (model_options, source) where source is 'discovered', 'fallback', or 'n/a'."""
    if engine_id == "codex":
        return discover_codex_models_with_source()
    if engine_id == "agy":
        # agy has no documented local cache file and `agy models` performs a slow network RPC (>3s)
        return list(DEFAULT_AGY_OPTIONS), "fallback"
    if engine_id == "claude":
        return list(DEFAULT_CLAUDE_OPTIONS), "fallback"
    if engine_id == "gemini":
        return list(DEFAULT_GEMINI_OPTIONS), "fallback"
    if engine_id == "dsh":
        return [{"id": "headless", "label": "headless (default)"}], "n/a"
    return [], "n/a"


def default_model_settings() -> dict:
    codex_opts, codex_src = discover_engine_models("codex")
    agy_opts, agy_src = discover_engine_models("agy")
    _, claude_src = discover_engine_models("claude")
    _, gemini_src = discover_engine_models("gemini")
    default_codex = codex_opts[0]["id"] if codex_opts else "gpt-6.2-sol"
    return {
        "agy_model": "gemini-4-neon-high",
        "codex_model": default_codex,
        "codex_effort": "high",
        "agy_options": agy_opts,
        "codex_options": codex_opts,
        "effort_options": ["low", "medium", "high", "xhigh"],
        "model_sources": {
            "agy": agy_src,
            "codex": codex_src,
            "claude": claude_src,
            "gemini": gemini_src,
            "dsh": "n/a",
        },
    }


def load_model_settings() -> dict:
    defaults = default_model_settings()
    if not config.MODELS_PATH.exists():
        save_model_settings(defaults)
        return defaults
    saved = config.read_json(config.MODELS_PATH, {})
    merged = dict(defaults)
    for k in ("agy_model", "codex_model", "codex_effort"):
        if saved.get(k):
            merged[k] = saved[k]
    if saved.get("agy_options"):
        merged["agy_options"] = saved["agy_options"]
    if saved.get("codex_options"):
        merged["codex_options"] = saved["codex_options"]
    # Always report live model_sources so stale saved files cannot misreport discovery status
    merged["model_sources"] = defaults["model_sources"]
    return merged


def save_model_settings(data: dict) -> None:
    config.write_json(config.MODELS_PATH, data)


def _find_binary(names: list[str], extra_paths: list[Path] | None = None) -> str:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for p in extra_paths or []:
        if p.exists():
            return str(p)
    return ""


def probe_cli_version(bin_path: str, timeout: float = 3.0) -> str:
    """Safely query `<cli> --version` (falling back to `version`) with a hard timeout."""
    if not bin_path:
        return ""
    for arg in ("--version", "version"):
        # defensive: fixed argument list with no shell string interpolation prevents command injection
        if os.name == "nt" and bin_path.lower().endswith((".cmd", ".bat")):
            cmd = ["cmd", "/c", bin_path, arg]
        else:
            cmd = [bin_path, arg]
        try:
            # defensive: hard timeout + DEVNULL stdin ensures a hung or interactive CLI never wedges doctor
            proc = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=config.NO_WINDOW_FLAGS,
            )
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            first_line = next((ln.strip() for ln in combined.splitlines() if ln.strip()), "")
            if proc.returncode == 0 and first_line:
                return first_line[:80]
        except subprocess.TimeoutExpired:
            # defensive: availability — treat timed-out probe as unknown instead of retrying or hanging
            return "unknown"
        except Exception:
            continue
    return "unknown"


def detect_cli_status(force: bool = False, probe_versions: bool = False) -> dict:
    now = time.time()
    if (
        not force
        and not probe_versions
        and _CLI_CACHE["data"] is not None
        and (now - _CLI_CACHE["ts"]) < 30.0
    ):
        return _CLI_CACHE["data"]

    home = _effective_home()
    use_extra = bool(os.environ.get("PATH", "").strip())
    local_app = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    roaming_app = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))

    agy_path = _find_binary(
        ["agy", "agy.exe"],
        [local_app / "agy" / "bin" / "agy.exe", home / ".local" / "bin" / "agy"] if use_extra else [],
    )
    codex_path = _find_binary(
        ["codex", "codex.cmd", "codex.exe"],
        [roaming_app / "npm" / "codex.cmd", home / ".npm-global" / "bin" / "codex"] if use_extra else [],
    )
    dsh_path = _find_binary(
        ["dsh", "dsh.cmd", "dsh.ps1"],
        [roaming_app / "npm" / "dsh.cmd", Path(r"D:\nodejs\dsh.cmd"), Path(r"D:\nodejs\dsh.ps1")] if use_extra else [],
    )
    claude_path = _find_binary(["claude", "claude.cmd", "claude.exe"])
    gemini_path = _find_binary(["gemini", "gemini.cmd", "gemini.exe"])

    paths = {
        "agy": agy_path,
        "codex": codex_path,
        "dsh": dsh_path,
        "claude": claude_path,
        "gemini": gemini_path,
    }
    result = {}
    for cid, cpath in paths.items():
        _, m_src = discover_engine_models(cid)
        entry = {
            "ready": bool(cpath),
            "installed": bool(cpath),
            "path": cpath,
            "model_source": m_src,
        }
        if probe_versions:
            entry["version"] = probe_cli_version(cpath) if cpath else ""
        result[cid] = entry

    if not probe_versions:
        _CLI_CACHE["ts"] = now
        _CLI_CACHE["data"] = result
    return result


def load_custom_engines() -> list[dict]:
    data = config.read_json(config.ENGINES_PATH, {"items": []})
    return data.get("items", [])


def save_custom_engines(items: list[dict]) -> None:
    config.write_json(config.ENGINES_PATH, {"items": items})


def add_custom_engine(payload: dict) -> dict:
    items = load_custom_engines()
    name = str(payload.get("name", "")).strip()
    kind = str(payload.get("kind", "openai-compat")).strip()
    if not name:
        raise ValueError("引擎名称不能为空")
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or f"engine-{len(items) + 1}"
    existing_ids = {i["id"] for i in items} | {"agy", "codex", "claude", "gemini", "dsh"}
    if slug in existing_ids:
        slug = f"{slug}-{len(items) + 1}"

    if kind == "openai-compat":
        base_url = str(payload.get("base_url", "")).strip().rstrip("/")
        model = str(payload.get("default_model", "")).strip()
        api_key = str(payload.get("api_key", "")).strip()
        if not base_url or not model:
            raise ValueError("OpenAI 兼容引擎必须填写 Base URL 和默认模型名")
        item = {
            "id": slug,
            "name": name,
            "kind": "openai-compat",
            "base_url": base_url,
            "api_key": api_key,
            "default_model": model,
            "models": [{"id": model, "label": model}],
            "can_edit_files": False,
        }
    elif kind == "custom-cli":
        cmd_tpl = str(payload.get("command_template", "")).strip()
        if not cmd_tpl:
            raise ValueError("自定义 CLI 必须填写命令模板（可用 {prompt} 与 {cwd}）")
        item = {
            "id": slug,
            "name": name,
            "kind": "custom-cli",
            "command_template": cmd_tpl,
            "default_model": str(payload.get("default_model", "default")).strip() or "default",
            "models": [{"id": "default", "label": "default"}],
            "can_edit_files": bool(payload.get("can_edit_files", True)),
        }
    else:
        raise ValueError(f"Unsupported engine kind: {kind}")

    items.append(item)
    save_custom_engines(items)
    return item


def delete_custom_engine(engine_id: str) -> bool:
    items = load_custom_engines()
    kept = [i for i in items if i.get("id") != engine_id]
    if len(kept) == len(items):
        return False
    save_custom_engines(kept)
    return True


def list_all_engines(mask_secrets: bool = True) -> list[dict]:
    clis = detect_cli_status()
    mcfg = load_model_settings()
    sources = mcfg.get("model_sources", {})
    builtin = [
        {
            "id": "agy",
            "name": "Antigravity CLI",
            "short": "AGY",
            "kind": "cli-agy",
            "ready": clis["agy"]["ready"],
            "path": clis["agy"]["path"],
            "model_source": sources.get("agy", "fallback"),
            "can_edit_files": True,
            "supports_effort": False,
            "default_model": mcfg.get("agy_model", "gemini-4-neon-high"),
            "models": mcfg.get("agy_options", DEFAULT_AGY_OPTIONS),
            "builtin": True,
        },
        {
            "id": "codex",
            "name": "OpenAI Codex CLI",
            "short": "CDX",
            "kind": "cli-codex",
            "ready": clis["codex"]["ready"],
            "path": clis["codex"]["path"],
            "model_source": sources.get("codex", "fallback"),
            "can_edit_files": True,
            "supports_effort": True,
            "default_model": mcfg.get("codex_model", "gpt-6.2-sol"),
            "models": mcfg.get("codex_options", FALLBACK_CODEX_OPTIONS),
            "builtin": True,
        },
        {
            "id": "claude",
            "name": "Claude Code CLI",
            "short": "CLD",
            "kind": "cli-claude",
            "ready": clis["claude"]["ready"],
            "path": clis["claude"]["path"],
            "model_source": sources.get("claude", "fallback"),
            "can_edit_files": True,
            "supports_effort": False,
            "default_model": "claude-sonnet-4-5",
            "models": DEFAULT_CLAUDE_OPTIONS,
            "builtin": True,
        },
        {
            "id": "gemini",
            "name": "Gemini CLI",
            "short": "GEM",
            "kind": "cli-gemini",
            "ready": clis["gemini"]["ready"],
            "path": clis["gemini"]["path"],
            "model_source": sources.get("gemini", "fallback"),
            "can_edit_files": True,
            "supports_effort": False,
            "default_model": "gemini-2.5-pro",
            "models": DEFAULT_GEMINI_OPTIONS,
            "builtin": True,
        },
        {
            "id": "dsh",
            "name": "DSH CLI",
            "short": "DSH",
            "kind": "cli-dsh",
            "ready": clis["dsh"]["ready"],
            "path": clis["dsh"]["path"],
            "model_source": "n/a",
            "can_edit_files": False,
            "supports_effort": False,
            "default_model": "headless",
            "models": [{"id": "headless", "label": "headless (default)"}],
            "builtin": True,
        },
    ]

    custom_out = []
    for item in load_custom_engines():
        c = dict(item)
        c["builtin"] = False
        c["ready"] = True
        c["short"] = (c.get("name", "API")[:3]).upper()
        c["supports_effort"] = False
        if mask_secrets and c.get("api_key"):
            # defensive: never expose raw API keys in UI/API snapshots; mask before returning
            k = c["api_key"]
            c["api_key_masked"] = (k[:4] + "****" + k[-4:]) if len(k) > 8 else "****"
            c.pop("api_key", None)
        custom_out.append(c)

    return builtin + custom_out


def get_engine_by_id(engine_id: str, mask_secrets: bool = False) -> dict | None:
    for eng in list_all_engines(mask_secrets=mask_secrets):
        if eng["id"] == engine_id:
            return eng
    return None


def default_role_bindings() -> dict:
    mcfg = load_model_settings()
    clis = detect_cli_status()
    # Pick best available fallback if a default CLI isn't installed on another user's machine
    def pick(preferred: list[str]) -> str:
        for p in preferred:
            if clis.get(p, {}).get("ready"):
                return p
        return preferred[0]

    p_eng = pick(["agy", "claude", "gemini", "codex"])
    b_eng = pick(["codex", "claude", "agy", "gemini"])
    r_eng = pick(["dsh", "agy", "codex", "claude", "gemini"])

    return {
        "planner": {
            "id": "planner",
            "label": "策划 · 方案",
            "aigc_label": "编剧 · 分镜",
            "custom_label": "",
            "system_prompt": "",
            "engine": p_eng,
            "model": mcfg.get("agy_model", "gemini-4-neon-high") if p_eng == "agy" else "",
            "effort": "high",
        },
        "builder": {
            "id": "builder",
            "label": "核心执行",
            "aigc_label": "制片 · 剪辑",
            "custom_label": "",
            "system_prompt": "",
            "engine": b_eng,
            "model": mcfg.get("codex_model", "gpt-6.2-sol") if b_eng == "codex" else "",
            "effort": mcfg.get("codex_effort", "high"),
        },
        "reviewer": {
            "id": "reviewer",
            "label": "独立质检",
            "aigc_label": "审片 · 质检",
            "custom_label": "",
            "system_prompt": "",
            "engine": r_eng,
            "model": "headless" if r_eng == "dsh" else "",
            "effort": "medium",
        },
    }


def load_role_bindings() -> dict:
    defaults = default_role_bindings()
    if not config.ROLES_PATH.exists():
        save_role_bindings(defaults)
        return defaults
    saved = config.read_json(config.ROLES_PATH, {})
    merged = {}
    for slot_id, def_val in defaults.items():
        cur = dict(def_val)
        if isinstance(saved.get(slot_id), dict):
            for k in ("label", "aigc_label", "custom_label", "system_prompt", "engine", "model", "effort"):
                if saved[slot_id].get(k) is not None:
                    cur[k] = saved[slot_id][k]
        merged[slot_id] = cur
    return merged


def save_role_bindings(data: dict) -> None:
    config.write_json(config.ROLES_PATH, data)


def stream_openai_compat(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    on_delta,
    on_reasoning,
    is_aborted,
    image_paths: list[str] | None = None,
) -> tuple[int, str]:
    import base64
    import mimetypes

    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = endpoint + "/chat/completions"

    user_content: str | list[dict] = user_prompt
    valid_imgs = [Path(p) for p in (image_paths or []) if Path(p).exists()]
    if valid_imgs:
        parts: list[dict] = [{"type": "text", "text": user_prompt}]
        for ip in valid_imgs[:4]:
            mime, _ = mimetypes.guess_type(str(ip))
            b64 = base64.b64encode(ip.read_bytes()).decode("ascii")
            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime or 'image/png'};base64,{b64}"}})
        user_content = parts

    payload = {
        "model": model,
        "stream": True,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    chunks = []
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            for raw_line in resp:
                if is_aborted():
                    return 1, "".join(chunks).strip()
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    ev = json.loads(data_str)
                except ValueError:
                    continue
                choices = ev.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                r_txt = delta.get("reasoning_content") or ""
                if r_txt and on_reasoning:
                    on_reasoning(r_txt)
                c_txt = delta.get("content") or ""
                if c_txt:
                    chunks.append(c_txt)
                    if on_delta:
                        on_delta(c_txt)
        return 0, "".join(chunks).strip()
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        return 1, f"HTTP {exc.code}: {err_body or exc.reason}"
    except Exception as exc:
        return 1, f"API 请求失败: {exc}"
