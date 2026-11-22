"""
Visual MCP (Model Context Protocol) Registry & 1-Click Local CLI Sync.
Zero-JSON beginner-friendly management for stdio & HTTP MCP servers,
with native sync to installed agy / codex / claude CLIs.
"""
import os
import re
import shlex
import subprocess
from pathlib import Path

import adapters
import config

SECRET_KEY_HINTS = ("TOKEN", "KEY", "SECRET", "PASS", "AUTH")

MCP_TEMPLATES = [
    {
        "id": "playwright",
        "name": "playwright",
        "title": "Playwright 浏览器",
        "desc": "让 AI 自动打开网页、截图、点击按钮与测试前端交互",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@playwright/mcp@latest"],
        "url": "",
        "env_hints": [],
    },
    {
        "id": "github",
        "name": "github",
        "title": "GitHub 仓库协作",
        "desc": "自动查 Issue、提 PR、检索仓库代码与发布版本",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "url": "",
        "env_hints": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    },
    {
        "id": "figma",
        "name": "figma",
        "title": "Figma 设计稿读取",
        "desc": "直接读取 Figma 图层、配色与布局尺寸还原页面代码",
        "transport": "http",
        "command": "",
        "args": [],
        "url": "https://mcp.figma.com/mcp",
        "env_hints": [],
    },
    {
        "id": "comfyui",
        "name": "comfyui",
        "title": "ComfyUI / AIGC 桥接",
        "desc": "把分镜提示词直接推送给本地 ComfyUI 生图与视频队列",
        "transport": "http",
        "command": "",
        "args": [],
        "url": "http://127.0.0.1:8188/mcp",
        "env_hints": [],
    },
    {
        "id": "filesystem",
        "name": "extra-fs",
        "title": "本地参考目录扩展",
        "desc": "授权 AI 只读或读写当前项目外的指定本地素材/文档目录",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
        "url": "",
        "env_hints": [],
    },
]


def _slugify_name(raw: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", (raw or "").strip().lower()).strip("-_")
    return s[:36] or "mcp-tool"


def _mask_env(env: dict) -> dict:
    masked = {}
    for k, v in (env or {}).items():
        s = str(v or "")
        if any(h in k.upper() for h in SECRET_KEY_HINTS) and len(s) > 6:
            masked[k] = f"{s[:3]}***{s[-3:]}"
        else:
            masked[k] = s
    return masked


def parse_env_text(raw: str) -> dict:
    out = {}
    for line in str(raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k:
            out[k] = v.strip()
    return out


def parse_args_text(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text, posix=(os.name != "nt"))
    except ValueError:
        return text.split()


def load_mcp_registry(mask_secrets: bool = True) -> dict:
    config.ensure_data_dir()
    raw = config.read_json(config.MCP_PATH, {})
    servers = raw.get("servers", []) if isinstance(raw, dict) else []
    cleaned = []
    for item in servers:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        entry = dict(item)
        if mask_secrets:
            entry["env"] = _mask_env(entry.get("env") or {})
        cleaned.append(entry)
    return {
        "servers": cleaned,
        "templates": MCP_TEMPLATES,
        "last_scan": raw.get("last_scan", {}) if isinstance(raw, dict) else {},
    }


def _save_raw_registry(data: dict) -> None:
    config.ensure_data_dir()
    config.write_json(config.MCP_PATH, data)


def upsert_server(
    name: str,
    title: str = "",
    desc: str = "",
    transport: str = "stdio",
    command: str = "",
    args=None,
    url: str = "",
    env=None,
) -> dict:
    slug = _slugify_name(name)
    transport = "http" if str(transport).lower() in ("http", "sse", "url") else "stdio"
    arg_list = parse_args_text(args)
    env_dict = env if isinstance(env, dict) else parse_env_text(str(env or ""))

    if transport == "stdio" and not str(command or "").strip():
        raise ValueError("命令行类型（stdio）必须填写启动命令，例如 npx / uvx / python")
    if transport == "http" and not str(url or "").strip():
        raise ValueError("远程接口类型（http）必须填写服务地址，例如 https://...")

    raw = config.read_json(config.MCP_PATH, {"servers": [], "last_scan": {}})
    servers = list(raw.get("servers", []))

    existing = next((s for s in servers if s.get("name") == slug), None)
    # Preserve unmasked secret if user submitted a masked placeholder like sk-***123
    if existing and existing.get("env"):
        for k, v in list(env_dict.items()):
            if "***" in str(v) and k in existing["env"]:
                env_dict[k] = existing["env"][k]

    record = {
        "id": slug,
        "name": slug,
        "title": (title or slug).strip(),
        "desc": (desc or "").strip(),
        "transport": transport,
        "command": str(command or "").strip(),
        "args": arg_list,
        "url": str(url or "").strip(),
        "env": env_dict,
        "synced_clis": list(existing.get("synced_clis", [])) if existing else [],
        "updated_at": config.now_iso(),
        "created_at": existing.get("created_at", config.now_iso()) if existing else config.now_iso(),
    }

    servers = [s for s in servers if s.get("name") != slug]
    servers.append(record)
    raw["servers"] = servers
    _save_raw_registry(raw)
    return record


def delete_server(name: str, unsync: bool = True) -> dict:
    slug = _slugify_name(name)
    raw = config.read_json(config.MCP_PATH, {"servers": [], "last_scan": {}})
    servers = list(raw.get("servers", []))
    target = next((s for s in servers if s.get("name") == slug), None)
    unsync_results = {}
    if unsync and target:
        unsync_results = remove_from_clis(slug, target.get("synced_clis") or None)
    raw["servers"] = [s for s in servers if s.get("name") != slug]
    _save_raw_registry(raw)
    return {"deleted": slug, "unsync": unsync_results}


def _wrap_cli_cmd(bin_path: str, args: list[str]) -> list[str]:
    if os.name == "nt" and bin_path.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", bin_path, *args]
    return [bin_path, *args]


def _run_cli(bin_path: str, args: list[str], timeout: int = 18) -> tuple[bool, str]:
    cmd = _wrap_cli_cmd(bin_path, args)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return proc.returncode == 0, out[:600]
    except subprocess.TimeoutExpired:
        return False, "命令执行超时"
    except Exception as exc:
        return False, str(exc)


def _supported_sync_clis(target_clis: list[str] | None = None) -> dict[str, str]:
    clis = adapters.detect_cli_status()
    out = {}
    for cid in ("agy", "codex", "claude"):
        if target_clis and cid not in target_clis:
            continue
        info = clis.get(cid, {})
        if info.get("installed") and info.get("path"):
            out[cid] = str(info["path"])
    return out


def sync_server_to_clis(name: str, target_clis: list[str] | None = None) -> dict:
    slug = _slugify_name(name)
    raw = config.read_json(config.MCP_PATH, {"servers": [], "last_scan": {}})
    servers = list(raw.get("servers", []))
    srv = next((s for s in servers if s.get("name") == slug), None)
    if not srv:
        raise ValueError(f"未找到 MCP 服务：{slug}")

    available = _supported_sync_clis(target_clis)
    if not available:
        return {"results": {}, "synced": []}

    results = {}
    synced = set(srv.get("synced_clis", []))
    transport = srv.get("transport", "stdio")
    env_items = [(k, v) for k, v in (srv.get("env") or {}).items() if k]

    for cid, bin_path in available.items():
        if cid == "agy":
            # agy mcp add [-e K=V] [--type http] <name> <url|cmd> [args...]
            cli_args = ["mcp", "add"]
            for k, v in env_items:
                cli_args += ["-e", f"{k}={v}"]
            if transport == "http":
                cli_args += ["--type", "http", slug, srv["url"]]
            else:
                cli_args += [slug, "--", srv["command"], *(srv.get("args") or [])]
        elif cid == "codex":
            # codex mcp add <name> [--env K=V] (--url <url> | -- <cmd> [args...])
            cli_args = ["mcp", "add", slug]
            if transport == "http":
                cli_args += ["--url", srv["url"]]
            else:
                for k, v in env_items:
                    cli_args += ["--env", f"{k}={v}"]
                cli_args += ["--", srv["command"], *(srv.get("args") or [])]
        elif cid == "claude":
            cli_args = ["mcp", "add"]
            if transport == "http":
                cli_args += ["--transport", "http", slug, srv["url"]]
            else:
                for k, v in env_items:
                    cli_args += ["-e", f"{k}={v}"]
                cli_args += [slug, "--", srv["command"], *(srv.get("args") or [])]
        else:
            continue

        ok, detail = _run_cli(bin_path, cli_args)
        results[cid] = {"ok": ok, "detail": detail or ("已同步" if ok else "同步失败")}
        if ok:
            synced.add(cid)

    srv["synced_clis"] = sorted(synced)
    srv["updated_at"] = config.now_iso()
    _save_raw_registry(raw)
    return {"results": results, "synced": srv["synced_clis"]}


def remove_from_clis(name: str, target_clis: list[str] | None = None) -> dict:
    slug = _slugify_name(name)
    available = _supported_sync_clis(target_clis)
    results = {}
    for cid, bin_path in available.items():
        ok, detail = _run_cli(bin_path, ["mcp", "remove", slug])
        results[cid] = {"ok": ok, "detail": detail or ("已移除" if ok else "未配置或移除失败")}
    return results


def scan_cli_mcps() -> dict:
    available = _supported_sync_clis()
    scanned = {}
    for cid, bin_path in available.items():
        ok, out = _run_cli(bin_path, ["mcp", "list"], timeout=12)
        lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
        scanned[cid] = {
            "ok": ok,
            "lines": lines[:20],
            "checked_at": config.now_iso(),
        }
    raw = config.read_json(config.MCP_PATH, {"servers": [], "last_scan": {}})
    raw["last_scan"] = scanned
    _save_raw_registry(raw)
    return scanned
