import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import config

_CLI_CACHE: dict = {"ts": 0.0, "data": None}
MAX_DISCOVERED_MODELS = 50
MAX_MODEL_ID_LEN = 120
MAX_CACHE_BYTES = 2 * 1024 * 1024
ROLE_SLOTS = ("planner", "builder", "reviewer")
MAX_ROLES = 8
ROLE_FIELD_LIMITS = {"engine": 120, "model": 120, "effort": 32, "label": 64,
                     "aigc_label": 64, "custom_label": 24, "system_prompt": 2000}
_ROLES_LOCK = threading.RLock()
_DEFAULT_ENGINE_ORDER = (
    ("agy", "claude", "gemini", "codex", "dsh"),
    ("codex", "claude", "agy", "gemini", "dsh"),
    ("dsh", "agy", "codex", "claude", "gemini"),
)
_ENGINE_PROFILES = {
    "codex": ("重型写代码与重构", "Large code changes and refactoring", ("coding", "architecture", "review")),
    "agy": ("架构、多模态创意与审计", "Architecture, multimodal ideation, and review",
            ("architecture", "multimodal", "writing", "review", "coding")),
    "claude": ("长文与精细代码", "Long-form writing and detailed code", ("writing", "coding", "review")),
    "gemini": ("长上下文与检索", "Long-context reading and retrieval",
               ("research", "multimodal", "writing", "architecture")),
    "dsh": ("轻量核验", "Quick verification", ("review", "fast")),
    "openai-compat": ("API 对话与文本分析", "API chat and text analysis", ("writing", "research", "review")),
    "custom-cli": ("自定义命令行工作流", "Custom command-line workflows", ("coding", "review")),
}
SCENE_PRESETS = {
    "coding": {
        "label_zh": "代码重活", "label_en": "Heavy coding",
        "labels": ("架构策划", "核心主程", "独立审计"),
        "priorities": (("agy", "claude", "gemini"), ("codex", "claude", "agy"), ("dsh", "codex", "claude")),
        "capabilities": ("architecture", "coding", "review"),
        "skills": ("code-review-strict", "bug-triage", "security-audit"),
    },
    "vibe-video": {
        "label_zh": "视频 / Vibe 创作", "label_en": "Video and vibe creation",
        "labels": ("创意编剧", "视觉生成", "审片质检"),
        "priorities": (("claude", "agy", "gemini"), ("agy", "gemini", "codex"), ("gemini", "agy", "claude")),
        "capabilities": ("writing", "multimodal", "multimodal"),
        "skills": ("aigc-storyboard",),
    },
    "art-3d": {
        "label_zh": "美术与 3D 建模", "label_en": "Art and 3D modeling",
        "labels": ("美术总监", "建模与资产", "规范验收"),
        "priorities": (("agy", "gemini", "claude"), ("codex", "agy", "claude"), ("gemini", "codex", "dsh")),
        "capabilities": ("multimodal", "coding", "review"),
        "skills": ("art-3d-pipeline", "aigc-storyboard"),
    },
    "paper-study": {
        "label_zh": "论文与深度学习", "label_en": "Papers and deep learning",
        "labels": ("论文导读", "推导与复现", "质疑自测"),
        "priorities": (("gemini", "claude", "agy"), ("claude", "codex", "gemini"), ("agy", "gemini", "claude")),
        "capabilities": ("research", "research", "review"),
        "skills": ("paper-study", "deep-research"),
    },
    "security-audit": {
        "label_zh": "安全与代码审计", "label_en": "Security and code review",
        "labels": ("威胁建模", "漏洞复核", "修复验证"),
        "priorities": (("agy", "codex", "claude"), ("codex", "claude", "agy"), ("dsh", "codex", "claude")),
        "capabilities": ("architecture", "coding", "review"),
        "skills": ("security-audit", "code-review-strict"),
    },
}

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
    detected = detect_cli_status()
    clis = {
        id_: {"ready": False, "path": "", **detected.get(id_, {})}
        for id_ in ("agy", "codex", "claude", "gemini", "dsh")
    }
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
            "default_effort": mcfg.get("codex_effort", "high"),
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
        c["short"] = compute_model_badge(c["id"], engine_name=c.get("name", ""))
        c["supports_effort"] = False
        if mask_secrets and c.get("api_key"):
            # defensive: never expose raw API keys in UI/API snapshots; mask before returning
            k = c["api_key"]
            c["api_key_masked"] = (k[:4] + "****" + k[-4:]) if len(k) > 8 else "****"
            c.pop("api_key", None)
        custom_out.append(c)

    for engine in builtin + custom_out:
        profile = _ENGINE_PROFILES.get(engine["id"] if engine["builtin"] else engine["kind"], _ENGINE_PROFILES["custom-cli"])
        strength_zh, strength_en, capabilities = profile
        engine.update(strength_zh=strength_zh, strength_en=strength_en, capabilities=list(capabilities))
        if not engine.get("can_edit_files") and "coding" in engine["capabilities"]:
            engine["capabilities"].remove("coding")
    return builtin + custom_out


def get_engine_by_id(engine_id: str, mask_secrets: bool = False) -> dict | None:
    for eng in list_all_engines(mask_secrets=mask_secrets):
        if eng["id"] == engine_id:
            return eng
    return None


def compute_model_badge(engine_id: str, model: str = "", engine_name: str = "") -> str:
    engine_id = engine_id.strip().lower()
    if not engine_id:
        return ""
    short = {"agy": "AGY", "codex": "CDX", "claude": "CLD", "gemini": "GEM", "dsh": "DSH"}
    model = model.strip()
    if not model and engine_id in short:
        return short[engine_id]
    key = (model or engine_name.strip() or engine_id).lower().rsplit("/", 1)[-1]
    for prefix, badge in (
        ("deepseek-reasoner", "DSR"), ("deepseek", "DS"), ("o4-mini", "O4M"),
        ("gpt", "GPT"), ("claude", "CLD"), ("gemini", "GEM"), ("qwen", "QWN"),
        ("kimi", "KMI"), ("headless", "DSH"),
    ):
        if key.startswith(prefix):
            return badge
    match = re.match(r"^(o[0-9]+)(?:[-_:]|$)", key)
    if match:
        return match[1][:4].upper()
    compact = re.sub(r"[^a-z0-9]", "", key)
    if len(compact) >= 2:
        return compact[:4].upper()
    if engine_id in short:
        return short[engine_id]
    for value in (engine_name, engine_id):
        compact = re.sub(r"[^a-z0-9]", "", value.lower())
        if len(compact) >= 2:
            return compact[:4].upper()
    return "AI"


def _available_engines(engines: list[dict]) -> dict:
    return {engine["id"]: engine for engine in engines if engine["ready"]}


def _pick_engine(preferred: tuple[str, ...], available: dict) -> dict:
    return next((available[id_] for id_ in preferred if id_ in available), next(iter(available.values()), {}))


def _binding(engine: dict) -> dict:
    return {"engine": engine.get("id", ""), "model": engine.get("default_model", "")}


def _with_badge(role: dict, available: dict) -> dict:
    engine = available.get(role["engine"], {})
    return {**role, "badge": compute_model_badge(role["engine"], role["model"], engine.get("name", ""))}


def _default_roles(available: dict) -> dict:
    labels = (("策划 · 方案", "编剧 · 分镜"), ("核心执行", "制片 · 剪辑"), ("独立质检", "审片 · 质检"))
    efforts = ("high", available.get("codex", {}).get("default_effort", "high"), "medium")
    return {
        slot: {
            "id": slot, "label": label, "aigc_label": aigc_label, "builtin": True,
            "custom_label": "", "system_prompt": "", "effort": effort,
            **_binding(_pick_engine(preferred, available)),
        }
        for slot, (label, aigc_label), effort, preferred in zip(ROLE_SLOTS, labels, efforts, _DEFAULT_ENGINE_ORDER)
    }


def default_role_bindings() -> dict:
    available = _available_engines(list_all_engines())
    return {slot: _with_badge(role, available) for slot, role in _default_roles(available).items()}


def _read_saved_roles() -> dict:
    saved = config.read_json(config.ROLES_PATH, {})
    return saved if isinstance(saved, dict) else {}


def _workspace_map(saved: dict) -> dict:
    workspaces = saved.get("workspaces", {})
    return workspaces if isinstance(workspaces, dict) else {}


def _role_fields(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in ROLE_FIELD_LIMITS if isinstance(value.get(key), str)}


def _merge_role(role: dict, patch: object) -> dict:
    fields = _role_fields(patch)
    if "engine" in fields and fields["engine"] != role.get("engine"):
        fields.setdefault("model", "")
    return {**role, **fields}


def is_custom_role_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"role-[a-z0-9][a-z0-9_-]{0,47}", value) is not None


def _roster_scope(saved: dict, ws_id: str | None) -> dict | None:
    if ws_id is None:
        return saved
    value = _workspace_map(saved).get(ws_id)
    return value if isinstance(value, dict) else None


def _roster_structure(saved: dict, scope: dict) -> tuple[dict, list[str]]:
    raw_custom = scope.get("custom_roles", saved.get("custom_roles", {}))
    customs = {}
    if isinstance(raw_custom, dict):
        customs = {
            id_: fields for id_, fields in raw_custom.items()
            if is_custom_role_id(id_) and isinstance(fields, dict)
        }
        customs = dict(list(customs.items())[:MAX_ROLES - len(ROLE_SLOTS)])
    ids = [*ROLE_SLOTS, *customs]
    raw_order = scope.get("roster_order", saved.get("roster_order"))
    order = list(dict.fromkeys(id_ for id_ in raw_order if isinstance(id_, str) and id_ in ids)) if isinstance(raw_order, list) else []
    return customs, order or ids


def _editable_roster_scope(saved: dict, ws_id: str | None) -> dict:
    scope = _roster_scope(saved, ws_id)
    if scope is None:
        workspaces = _workspace_map(saved)
        saved["workspaces"] = workspaces
        scope = workspaces[ws_id] = {}
    return scope


def _resolve_role_binding(role: dict, fallback: dict, available: dict) -> dict:
    if role["engine"] and role["engine"] not in available:
        role = {**role, "engine": fallback["engine"], "model": fallback["model"]}
    if not role["engine"]:
        role = {**role, "model": ""}
    return role


def _custom_role_defaults(role_id: str, available: dict) -> dict:
    label = role_id.removeprefix("role-")
    return {
        "id": role_id, "builtin": False, "label": label, "aigc_label": label,
        "system_prompt": "", "custom_label": "", "effort": "high",
        **_binding(_pick_engine((), available)),
    }


def get_workspace_roster(ws_id: str | None = None, *, engines: list[dict] | None = None) -> dict:
    available = _available_engines(list_all_engines() if engines is None else engines)
    with _ROLES_LOCK:
        saved = _read_saved_roles()
    override = _roster_scope(saved, ws_id) if ws_id is not None else None
    customs, order = _roster_structure(saved, override if override is not None else saved)
    scene = override.get("scene", "") if override is not None else ""
    if not isinstance(scene, str) or scene not in SCENE_PRESETS:
        scene = ""
    fallback = _scene_roles(scene, available) if scene else _default_roles(available)
    roles = {}
    for slot, default in _default_roles(available).items():
        role = _merge_role(default, saved.get(slot))
        if override is not None:
            role = _merge_role(role, override.get(slot))
        roles[slot] = _resolve_role_binding(role, fallback[slot], available)
    for id_, fields in customs.items():
        default = _custom_role_defaults(id_, available)
        roles[id_] = _resolve_role_binding(_merge_role(default, fields), default, available)
    positions = {id_: position for position, id_ in enumerate(order)}
    roles = {
        id_: _with_badge({**role, "enabled": id_ in positions, "order": positions.get(id_)}, available)
        for id_, role in roles.items()
    }
    return {
        "roles": roles, "active_scene": scene,
        "roster": [roles[id_] for id_ in order], "roster_order": order,
        "roles_scope": "workspace" if override is not None else "global",
        "recommended_skills": list(SCENE_PRESETS[scene]["skills"]) if scene else [],
    }


def load_role_bindings(ws_id: str | None = None) -> dict:
    return get_workspace_roster(ws_id)["roles"]


def _write_saved_roles(saved: dict) -> None:
    config.ROLES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=config.ROLES_PATH.parent, delete=False) as file:
            tmp = Path(file.name)
            json.dump(saved, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(tmp, config.ROLES_PATH)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def save_role_bindings(data: dict, ws_id: str | None = None, *, scene: str | None = None) -> None:
    if scene is not None and (not isinstance(scene, str) or (scene and scene not in SCENE_PRESETS)):
        raise ValueError("未知的阵容场景")
    with _ROLES_LOCK:
        saved = _read_saved_roles()
        target = _editable_roster_scope(saved, ws_id)
        customs, order = _roster_structure(saved, target)
        updates = {}
        enabled_updates = {}
        for id_, raw in data.items():
            if id_ not in (*ROLE_SLOTS, *customs):
                if is_custom_role_id(id_):
                    raise ValueError("角色不属于当前阵容")
                continue
            if not isinstance(raw, dict):
                continue
            if "enabled" in raw:
                if type(raw["enabled"]) is not bool:
                    raise ValueError("enabled 必须是布尔值")
                enabled_updates[id_] = raw["enabled"]
            if fields := _role_fields(raw):
                if id_ in customs:
                    fields.pop("label", None)
                    fields.pop("aigc_label", None)
                updates[id_] = fields
        if not updates and not enabled_updates and scene is None:
            return
        if ws_id is not None and scene is not None:
            target["scene"] = scene
        custom_changed = False
        for slot, fields in updates.items():
            destination = customs if slot in customs else target
            destination[slot] = _merge_role(_role_fields(destination.get(slot)), fields)
            custom_changed |= slot in customs
        if enabled_updates:
            order = [id_ for id_ in order if enabled_updates.get(id_, True)]
            order.extend(id_ for id_, enabled in enabled_updates.items() if enabled and id_ not in order)
            if not order:
                raise ValueError("至少保留一个已启用角色")
        if custom_changed or enabled_updates:
            target.update(custom_roles=customs, roster_order=order)
        _write_saved_roles(saved)


def _validate_role_fields(raw: object, *, custom: bool = False, allow_enabled: bool = False) -> dict:
    allowed = set(ROLE_FIELD_LIMITS)
    if allow_enabled:
        allowed.add("enabled")
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise ValueError("角色含有未知字段")
    fields = {}
    for key, value in raw.items():
        if key == "enabled":
            if type(value) is not bool:
                raise ValueError("enabled 必须是布尔值")
            fields[key] = value
            continue
        limit = 24 if custom and key == "label" else ROLE_FIELD_LIMITS[key]
        if not isinstance(value, str) or len(value) > limit or "\0" in value:
            raise ValueError(f"角色的 {key} 类型或长度无效")
        fields[key] = value.strip()
    if custom and not fields.get("label"):
        raise ValueError("自定义角色名称必须为 1–24 字")
    return fields


def add_custom_role(
    ws_id: str | None, *, label: str, engine: str = "", model: str = "", effort: str = "high",
    system_prompt: str = "", insert_before: str | None = "reviewer",
) -> dict:
    fields = _validate_role_fields(
        dict(label=label, engine=engine, model=model, effort=effort, system_prompt=system_prompt), custom=True,
    )
    engines = list_all_engines()
    available = _available_engines(engines)
    if fields["engine"] and fields["engine"] not in available:
        raise ValueError("角色引擎不可用")
    binding = _binding(available.get(fields["engine"]) or _pick_engine((), available))
    fields["engine"] = binding["engine"]
    fields["model"] = (fields["model"] or binding["model"]) if fields["engine"] else ""
    fields["aigc_label"] = fields["label"]
    with _ROLES_LOCK:
        saved = _read_saved_roles()
        target = _editable_roster_scope(saved, ws_id)
        customs, order = _roster_structure(saved, target)
        if len(customs) + len(ROLE_SLOTS) >= MAX_ROLES:
            raise ValueError("一个阵容最多可保存 8 个角色")
        if insert_before is not None and (not isinstance(insert_before, str) or insert_before not in (*ROLE_SLOTS, *customs)):
            raise ValueError("插入位置不属于当前阵容")
        base = re.sub(r"[^a-z0-9_-]+", "-", fields["label"].lower()).strip("-_")[:36] or "expert"
        role_id = f"role-{base}"
        suffix = 2
        while role_id in customs:
            role_id = f"role-{base}-{suffix}"
            suffix += 1
        customs[role_id] = fields
        position = order.index(insert_before) if insert_before in order else len(order)
        order.insert(position, role_id)
        target.update(custom_roles=customs, roster_order=order)
        _write_saved_roles(saved)
        return get_workspace_roster(ws_id, engines=engines)["roles"][role_id]


def delete_custom_role(ws_id: str | None, role_id: str) -> dict:
    with _ROLES_LOCK:
        saved = _read_saved_roles()
        target = _editable_roster_scope(saved, ws_id)
        customs, order = _roster_structure(saved, target)
        if not is_custom_role_id(role_id) or role_id not in customs:
            raise ValueError("只能删除当前阵容中的自定义角色")
        del customs[role_id]
        order = [id_ for id_ in order if id_ != role_id]
        if not order:
            raise ValueError("至少保留一个已启用角色")
        target.update(custom_roles=customs, roster_order=order)
        _write_saved_roles(saved)
    return get_workspace_roster(ws_id)


def _validate_order(order: object, enabled: list[str]) -> list[str]:
    if (
        not isinstance(order, list) or not 1 <= len(order) <= MAX_ROLES
        or any(not isinstance(id_, str) for id_ in order)
        or len(order) != len(enabled) or set(order) != set(enabled)
    ):
        raise ValueError("排序必须是已启用角色 ID 的完整排列")
    return order


def reorder_roles(ws_id: str | None, order: list[str]) -> dict:
    with _ROLES_LOCK:
        saved = _read_saved_roles()
        target = _editable_roster_scope(saved, ws_id)
        customs, current = _roster_structure(saved, target)
        target.update(custom_roles=customs, roster_order=_validate_order(order, current))
        _write_saved_roles(saved)
    return get_workspace_roster(ws_id)


def reset_workspace_roles(ws_id: str) -> dict:
    with _ROLES_LOCK:
        saved = _read_saved_roles()
        workspaces = _workspace_map(saved)
        if ws_id in workspaces:
            del workspaces[ws_id]
            _write_saved_roles(saved)
    return load_role_bindings(ws_id)


def list_role_scenes() -> list[dict]:
    return [
        {"id": id_, "label_zh": preset["label_zh"], "label_en": preset["label_en"],
         "role_labels": dict(zip(ROLE_SLOTS, preset["labels"])), "recommended_skills": list(preset["skills"])}
        for id_, preset in SCENE_PRESETS.items()
    ]


def _scene_roles(scene: str, available: dict) -> dict:
    roles = _default_roles(available)
    preset = SCENE_PRESETS[scene]
    for slot, label, preferred, capability, default_order in zip(
        ROLE_SLOTS, preset["labels"], preset["priorities"], preset["capabilities"], _DEFAULT_ENGINE_ORDER
    ):
        matches = tuple(id_ for id_, engine in available.items() if capability in engine.get("capabilities", []))
        roles[slot].update(custom_label=label, **_binding(_pick_engine(preferred + matches + default_order, available)))
    return roles


def recommend_workspace_roster(scene_id: str, ws_id: str | None = None) -> dict:
    if not isinstance(scene_id, str) or scene_id not in SCENE_PRESETS:
        raise ValueError("未知的阵容场景")
    available = _available_engines(list_all_engines())
    roles = {slot: _with_badge(role, available) for slot, role in _scene_roles(scene_id, available).items()}
    preset = SCENE_PRESETS[scene_id]
    assigned = [available.get(role["engine"], {}).get("name", "—") for role in roles.values()]
    choices = " / ".join(assigned)
    return {
        "scene": scene_id, "roles": roles,
        "reason_zh": f"{preset['label_zh']}按策划、执行、质检顺序分配当前可用引擎：{choices}。"
        if available else "当前没有可用引擎，三个角色均待配置。",
        "reason_en": f"{preset['label_en']} selects available engines for planner, builder, and reviewer: {choices}."
        if available else "No engines are available. All three roles are unconfigured.",
        "recommended_skills": list(preset["skills"]),
    }


def export_roster_preset(ws_id: str) -> dict:
    roster = get_workspace_roster(ws_id)
    preset = {
        "version": 1, "scene": roster["active_scene"],
        "roles": {slot: _role_fields(role) for slot, role in roster["roles"].items()},
        "recommended_skills": roster["recommended_skills"],
    }
    if set(roster["roles"]) != set(ROLE_SLOTS) or roster["roster_order"] != list(ROLE_SLOTS):
        preset.update(version=2, roster_order=roster["roster_order"])
        for slot, role in roster["roles"].items():
            preset["roles"][slot]["enabled"] = role["enabled"]
    return preset


def import_roster_preset(preset: object, ws_id: str) -> dict:
    if not isinstance(preset, dict):
        raise ValueError("阵容预设必须是 JSON 对象，且只能包含预设字段")
    version = preset.get("version", 1)
    if type(version) is not int or version not in (1, 2):
        raise ValueError("不支持该阵容预设版本")
    permitted = {"version", "scene", "roles", "recommended_skills"}
    if version == 2:
        permitted.add("roster_order")
    if set(preset) - permitted:
        raise ValueError("阵容预设含有未知字段")
    scene = preset.get("scene", "")
    if not isinstance(scene, str) or (scene and scene not in SCENE_PRESETS):
        raise ValueError("未知的阵容场景")
    skills = preset.get("recommended_skills", [])
    if not isinstance(skills, list) or len(skills) > 32 or any(
        not isinstance(slug, str) or re.fullmatch(r"[a-z0-9_-]{1,80}", slug) is None for slug in skills
    ):
        raise ValueError("推荐技能必须是有效的技能 slug 列表")
    raw_roles = preset.get("roles")
    if not isinstance(raw_roles, dict) or not set(ROLE_SLOTS).issubset(raw_roles):
        raise ValueError("阵容预设必须包含策划、执行和质检角色")
    custom_ids = set(raw_roles) - set(ROLE_SLOTS)
    if len(raw_roles) > MAX_ROLES or any(not is_custom_role_id(id_) for id_ in custom_ids) or (version == 1 and custom_ids):
        raise ValueError("阵容角色 ID 无效或超过 8 个")
    available = _available_engines(list_all_engines())
    defaults = _scene_roles(scene, available) if scene else _default_roles(available)
    roles = {}
    enabled = []
    for slot, raw in raw_roles.items():
        fields = _validate_role_fields(raw, custom=slot in custom_ids, allow_enabled=version == 2)
        if fields.pop("enabled", True):
            enabled.append(slot)
        default = _custom_role_defaults(slot, available) if slot in custom_ids else defaults[slot]
        role = _resolve_role_binding(_merge_role(default, fields), default, available)
        roles[slot] = _role_fields(role)
    order = list(ROLE_SLOTS) if version == 1 else _validate_order(preset.get("roster_order"), enabled)
    with _ROLES_LOCK:
        saved = _read_saved_roles()
        target = _editable_roster_scope(saved, ws_id)
        target.update({slot: roles[slot] for slot in ROLE_SLOTS})
        target.update(scene=scene, custom_roles={slot: roles[slot] for slot in roles if slot in custom_ids}, roster_order=order)
        _write_saved_roles(saved)
    return get_workspace_roster(ws_id)


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
