import json
import os
import secrets
import subprocess
from datetime import datetime
from pathlib import Path

NO_WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
STATIC_DIR = PACKAGE_DIR / "static"
BUILTIN_SKILLS_DIR = REPO_ROOT / "skills"

# Runtime data directory (gitignored, can be overridden via SUPER_WORKBENCH_DATA_DIR)
DATA_DIR = Path(os.environ.get("SUPER_WORKBENCH_DATA_DIR", str(REPO_ROOT / ".workbench"))).resolve()
HISTORY_DIR = DATA_DIR / "history"
USER_SKILLS_DIR = DATA_DIR / "skills"
UPLOADS_DIR = DATA_DIR / "uploads"
WORKSPACES_PATH = DATA_DIR / "workspaces.json"
MODELS_PATH = DATA_DIR / "models.json"
ROLES_PATH = DATA_DIR / "roles.json"
ENGINES_PATH = DATA_DIR / "engines.json"
SKILLS_STATE_PATH = DATA_DIR / "skills_state.json"
MCP_PATH = DATA_DIR / "mcp_servers.json"
SETTINGS_PATH = DATA_DIR / "settings.json"
TOKEN_PATH = DATA_DIR / "session.token"
THREADS_PATH = DATA_DIR / "threads.json"
STATE_PATH = DATA_DIR / "state.json"
MESSAGES_PATH = DATA_DIR / "messages.json"
SELF_CHECK_PATH = DATA_DIR / "self_check.json"
OBJECTION_PATH = DATA_DIR / "OBJECTION.json"
AUDIT_PATH = DATA_DIR / "AUDIT_REPORT.json"
VERDICT_PATH = DATA_DIR / "PLAYTEST_VERDICT.json"
NEXT_FOR_CODEX_PATH = DATA_DIR / "NEXT_FOR_CODEX.md"
NEXT_FOR_DSH_PATH = DATA_DIR / "NEXT_FOR_DSH.md"

HOST = os.environ.get("SUPER_WORKBENCH_HOST", "127.0.0.1")
PORT = int(os.environ.get("SUPER_WORKBENCH_PORT", "8765"))


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_text(path: Path, default: str = "") -> str:
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8", errors="replace")


def default_workspaces() -> dict:
    return {
        "active_id": "super-workbench",
        "items": [
            {
                "id": "super-workbench",
                "name": "Super Workbench",
                "type": "general",
                "path": str(REPO_ROOT),
                "description": "Local multi-agent orchestration studio",
                "created_at": now_iso(),
            }
        ],
    }


def load_workspaces() -> dict:
    ensure_data_dir()
    if not WORKSPACES_PATH.exists():
        data = default_workspaces()
        save_workspaces(data)
        return data
    data = read_json(WORKSPACES_PATH, {})
    if "items" not in data and "workspaces" in data:
        data["items"] = data["workspaces"]
    if not data.get("items"):
        data = default_workspaces()
        save_workspaces(data)
    return data


def save_workspaces(data: dict) -> None:
    ensure_data_dir()
    write_json(WORKSPACES_PATH, data)


def get_active_workspace() -> dict:
    data = load_workspaces()
    active_id = data.get("active_id")
    items = data.get("items", [])
    for ws in items:
        if ws.get("id") == active_id:
            return ws
    return items[0]


def load_app_settings() -> dict:
    defaults = {
        "approve_before_build": False,
        "user_name": "我",
        "lang": "zh",
        "exit_on_close": False,
        "use_system_proxy_for_remote_skills": False,
    }
    raw = read_json(SETTINGS_PATH, {})
    if not isinstance(raw, dict):
        return defaults
    uname = str(raw.get("user_name", "") or "").strip()[:16] or "我"
    lang = "en" if str(raw.get("lang", "zh")).lower() == "en" else "zh"
    return {
        "approve_before_build": bool(raw.get("approve_before_build", False)),
        "user_name": uname,
        "lang": lang,
        "exit_on_close": bool(raw.get("exit_on_close", False)),
        "use_system_proxy_for_remote_skills": raw.get("use_system_proxy_for_remote_skills") is True,
    }


def save_app_settings(patch: dict) -> dict:
    cur = load_app_settings()
    if "approve_before_build" in patch:
        cur["approve_before_build"] = bool(patch["approve_before_build"])
    if "user_name" in patch:
        uname = str(patch.get("user_name") or "").strip()[:16]
        cur["user_name"] = uname or "我"
    if "lang" in patch:
        cur["lang"] = "en" if str(patch.get("lang", "zh")).lower() == "en" else "zh"
    if "exit_on_close" in patch:
        cur["exit_on_close"] = bool(patch["exit_on_close"])
    if "use_system_proxy_for_remote_skills" in patch:
        cur["use_system_proxy_for_remote_skills"] = patch["use_system_proxy_for_remote_skills"] is True
    write_json(SETTINGS_PATH, cur)
    return cur


def get_or_create_session_token() -> tuple[str, str]:
    """Return (session_token, source_label). Never prints or logs the token value."""
    env_tok = str(os.environ.get("SUPER_WORKBENCH_TOKEN", "") or "").strip()
    if env_tok:
        return env_tok, "env:SUPER_WORKBENCH_TOKEN"
    ensure_data_dir()
    if TOKEN_PATH.exists():
        try:
            existing = TOKEN_PATH.read_text(encoding="utf-8").strip()
            if existing:
                return existing, str(TOKEN_PATH)
        except OSError:
            pass
    tok = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(tok + "\n", encoding="utf-8")
    if os.name != "nt":
        try:
            os.chmod(TOKEN_PATH, 0o600)
        except OSError:
            pass
    return tok, str(TOKEN_PATH)
