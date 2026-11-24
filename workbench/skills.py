import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from http.client import HTTPException
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

import config


MAX_SKILL_BYTES = 128 * 1024
REMOTE_TIMEOUT_SECONDS = 8
REMOTE_HOSTS = {"github.com", "raw.githubusercontent.com", "gist.githubusercontent.com"}
_REMOTE_DOWNLOADS = threading.BoundedSemaphore(4)


def _scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except ValueError:
            return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def _parse_tags(value: str | list[str]) -> list[str]:
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            try:
                value = json.loads(value)
            except ValueError:
                value = [_scalar(part) for part in value[1:-1].split(",")]
        else:
            value = [_scalar(part) for part in value.split(",")]
    return list(dict.fromkeys(tag for item in value if isinstance(item, str) and (tag := item.strip())))


def _parse_skill_text(raw: str, fallback_name: str) -> dict:
    body = raw.lstrip("\ufeff").strip()
    metadata = {}
    if re.match(r"^---[ \t]*\r?\n", body):
        parts = re.split(r"^---[ \t]*\r?$", body, maxsplit=2, flags=re.MULTILINE)
        if len(parts) == 3:
            body = parts[2].strip()
            for key, value in re.findall(r"^(name|description|category|tags):[ \t]*([^\r\n]*)", parts[1], re.MULTILINE):
                metadata[key] = value
    description = _scalar(metadata.get("description", ""))
    if not description:
        lines = (line.strip().lstrip("#").strip() for line in body.splitlines())
        description = next((line[:90] for line in lines if line), "")
    return {
        "name": _scalar(metadata.get("name", "")).strip() or fallback_name,
        "description": description,
        "category": _scalar(metadata.get("category", "")).strip() or "general",
        "tags": _parse_tags(metadata.get("tags", "")),
        "body": body,
    }


def _parse_skill_md(path: Path) -> dict:
    return _parse_skill_text(path.read_text(encoding="utf-8", errors="replace"), path.parent.name)


def _safe_slug(raw: str) -> str:
    name = raw.strip()
    if not name:
        raise ValueError("技能名称不能为空")
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")
    if slug and len(slug) <= 80 and not re.fullmatch(r"con|prn|aux|nul|com[0-9]|lpt[0-9]", slug):
        return slug
    suffix = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    return f"skill-{suffix}"


def _contained_path(root: Path, path: Path) -> bool:
    resolved = path.resolve()
    return resolved != root and resolved.is_relative_to(root)


def _scan_dir(base: Path, source: str, source_label: str, editable: bool) -> list[dict]:
    if not base.exists() or not base.is_dir():
        return []
    root = base.resolve()
    if editable and root != base:
        return []
    found = []
    try:
        for child in sorted(base.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            md = child / "SKILL.md"
            if not md.is_file():
                continue
            if editable and (
                child.resolve() != root / child.name
                or md.resolve() != child.resolve() / "SKILL.md"
            ):
                continue
            metadata = _parse_skill_md(md)
            slug = _safe_slug(metadata["name"])
            # The old scanner used the folder name when the display name had no ASCII slug.
            if not re.search(r"[a-z0-9_]", metadata["name"].lower()) and re.fullmatch(r"[a-z0-9_-]+", child.name.lower()):
                slug = child.name.lower()
            skill_id = f"{source}:{slug}"
            found.append(
                {
                    "id": skill_id,
                    "slug": slug,
                    **metadata,
                    "source": source,
                    "source_label": source_label,
                    "editable": editable,
                    "path": str(md),
                }
            )
    except OSError:
        return []
    return found


def load_skills_state() -> dict:
    data = config.read_json(
        config.SKILLS_STATE_PATH,
        {"global_enabled": [], "workspace_enabled": {}},
    )
    data.setdefault("global_enabled", [])
    data.setdefault("workspace_enabled", {})
    return data


def save_skills_state(data: dict) -> None:
    config.write_json(config.SKILLS_STATE_PATH, data)


def list_skills(ws_id: str, ws_path: Path) -> list[dict]:
    state = load_skills_state()
    global_set = set(state.get("global_enabled", []))
    ws_set = set(state.get("workspace_enabled", {}).get(ws_id, []))

    home = Path.home()
    items = []
    items.extend(_scan_dir(config.BUILTIN_SKILLS_DIR, "builtin", "内置推荐", False))
    items.extend(_scan_dir(_user_root(), "user", "自定义技能", True))

    # Avoid duplicating builtin skills when active workspace is SuperWorkbench itself
    ws_resolved = ws_path.resolve()
    if ws_resolved != config.REPO_ROOT.resolve():
        items.extend(_scan_dir(ws_resolved / ".agents" / "skills", "workspace", "当前空间", True))
        items.extend(_scan_dir(ws_resolved / "skills", "workspace", "当前空间", True))

    # Auto-discover skills already installed for local CLIs (read-only)
    ext_dirs = [
        (home / ".codex" / "skills", "ext-codex", "本机 Codex"),
        (home / ".gemini" / "antigravity" / "skills", "ext-agy", "本机 AGY"),
        (home / ".gemini" / "skills", "ext-gemini", "本机 Gemini"),
        (home / ".claude" / "skills", "ext-claude", "本机 Claude"),
        (home / ".dsh" / "skills", "ext-dsh", "本机 DSH"),
    ]
    for d, src, lbl in ext_dirs:
        items.extend(_scan_dir(d, src, lbl, False))

    seen = set()
    unique = []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        it["enabled_global"] = it["id"] in global_set
        it["enabled_workspace"] = it["id"] in ws_set
        it["active"] = it["enabled_global"] or it["enabled_workspace"]
        unique.append(it)
    return unique


def toggle_skill(skill_id: str, scope: str, enabled: bool, ws_id: str) -> dict:
    state = load_skills_state()
    if scope == "global":
        cur = set(state.get("global_enabled", []))
        if enabled:
            cur.add(skill_id)
        else:
            cur.discard(skill_id)
        state["global_enabled"] = sorted(cur)
    else:
        ws_map = state.setdefault("workspace_enabled", {})
        cur = set(ws_map.get(ws_id, []))
        if enabled:
            cur.add(skill_id)
        else:
            cur.discard(skill_id)
        ws_map[ws_id] = sorted(cur)
    save_skills_state(state)
    return state


def _format_skill(metadata: dict) -> str:
    fields = [
        f"{key}: {json.dumps(metadata[key], ensure_ascii=False)}"
        for key in ("name", "description", "category", "tags")
    ]
    return "\n".join(["---", *fields, "---", "", metadata["body"], ""])


def _write_skill(base: Path, slug: str, content: bytes) -> Path:
    root = base.resolve()
    target = root / slug
    path = target / "SKILL.md"
    if (
        root != base
        or not _contained_path(root, target)
        or target.resolve() != target
        or path.resolve() != path
    ):
        raise ValueError("技能目标路径越界或包含符号链接")
    target.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target, delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
        if target.resolve() != target:
            raise ValueError("技能目标目录已变化")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def _store_skill(
    base: Path, source: str, scope: str, ws_id: str, name: str, content: bytes,
) -> dict:
    slug = _safe_slug(name)
    path = _write_skill(base, slug, content)
    skill_id = f"{source}:{slug}"
    toggle_skill(skill_id, scope, True, ws_id)
    return {"id": skill_id, "slug": slug, "path": str(path)}


def _user_root() -> Path:
    return config.USER_SKILLS_DIR.parent.resolve() / config.USER_SKILLS_DIR.name


def create_skill(
    name: str, description: str, body: str, scope: str, ws_path: Path, ws_id: str,
    *, category: str = "general", tags: str | list[str] = "",
) -> dict:
    name = name.strip()
    if not name or not body.strip():
        raise ValueError("技能名称与规则正文不能为空")
    metadata = {
        "name": name,
        "description": description.strip() or name,
        "category": category.strip() or "general",
        "tags": _parse_tags(tags),
        "body": body.strip(),
    }
    content = _format_skill(metadata).encode("utf-8")
    if scope == "workspace" and ws_path.exists() and ws_path.resolve() != config.REPO_ROOT.resolve():
        base = ws_path.resolve() / ".agents" / "skills"
        return _store_skill(base, "workspace", "workspace", ws_id, name, content)
    return _store_skill(_user_root(), "user", "workspace" if scope == "workspace" else "global", ws_id, name, content)


def _validate_skill_bytes(content: bytes, fallback_name: str) -> dict:
    if len(content) > MAX_SKILL_BYTES:
        raise ValueError("SKILL.md 超过 128 KB")
    try:
        raw = content.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("SKILL.md 必须是 UTF-8 文本") from exc
    if "\0" in raw or re.match(r"^\s*<(?:!doctype\s+html\b|html\b)", raw, re.IGNORECASE):
        raise ValueError("URL 或路径未提供 SKILL.md 文本")
    metadata = _parse_skill_text(raw, fallback_name)
    if not metadata["body"]:
        raise ValueError("技能规则正文不能为空")
    return metadata


def import_local_skill(source_path: str, ws_id: str) -> dict:
    source = source_path.strip().strip("\"'")
    if not source:
        raise ValueError("请选择技能文件或目录")
    selected = Path(os.path.abspath(source))
    if selected.is_symlink() or selected.resolve() != selected.parent.resolve() / selected.name:
        raise ValueError("不支持通过符号链接导入技能")
    if selected.is_dir():
        path = selected / "SKILL.md"
    elif selected.suffix.lower() == ".md":
        path = selected
    else:
        raise ValueError("请选择包含 SKILL.md 的文件夹，或直接指向一个 .md 技能文件")

    if path.is_symlink() or path.resolve() != path.parent.resolve() / path.name:
        raise ValueError("不支持通过符号链接导入技能")
    if not path.is_file():
        raise ValueError("未找到可导入的 SKILL.md 文件")
    with path.open("rb") as file:
        content = file.read(MAX_SKILL_BYTES + 1)
    metadata = _validate_skill_bytes(content, path.parent.name)
    return _store_skill(_user_root(), "user", "global", ws_id, metadata["name"], content)


def _checked_remote_url(url: str) -> str:
    if "\\" in url or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise ValueError("技能 URL 包含无效字符")
    parsed = urlsplit(url)
    host = parsed.hostname
    if parsed.scheme != "https" or host not in REMOTE_HOSTS or parsed.netloc.lower() not in (host, f"{host}:443"):
        raise ValueError("技能 URL 必须使用 HTTPS 和允许的 GitHub 域名")
    return urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))


def _normalize_skill_url(url: str) -> str:
    checked = _checked_remote_url(url.strip())
    parsed = urlsplit(checked)
    if parsed.hostname != "github.com":
        return checked
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2 or not all(parts[:2]):
        raise ValueError("请输入 GitHub 仓库、目录或文件链接")
    owner, repo, *rest = parts
    if not rest:
        raw_path = ["HEAD", "SKILL.md"]
    elif rest[0] == "blob" and len(rest) >= 3 and all(rest):
        raw_path = rest[1:]
    elif rest[0] == "tree" and len(rest) >= 2 and all(rest):
        raw_path = [*rest[1:], "SKILL.md"]
    else:
        raise ValueError("请输入 GitHub 仓库、目录或文件链接")
    return f"https://raw.githubusercontent.com/{'/'.join([owner, repo, *raw_path])}"


def _time_left(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    return remaining


class _SkillRedirectHandler(HTTPRedirectHandler):
    def __init__(self, deadline: float) -> None:
        self.deadline = deadline
        self.redirects = 0

    def http_error_302(self, req, fp, code, msg, headers):
        try:
            location = headers.get("Location") or headers.get("URI")
            if not location:
                raise ValueError("远程技能重定向缺少目标 URL")
            checked = _checked_remote_url(urljoin(req.full_url, location))
            self.redirects += 1
            if self.redirects > 3:
                raise ValueError("技能 URL 超过 3 次重定向")
            redirect = super().redirect_request(req, fp, code, msg, headers, checked)
        finally:
            # A redirect response body is irrelevant and can be arbitrarily large.
            fp.close()
        return self.parent.open(redirect, timeout=_time_left(self.deadline))

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _download_skill(url: str, deadline: float) -> tuple[bytes, str]:
    opener = build_opener(ProxyHandler({}), _SkillRedirectHandler(deadline))
    request = Request(url, headers={"Accept": "text/plain, text/markdown, application/octet-stream"})
    with opener.open(request, timeout=_time_left(deadline)) as response:
        resolved_url = _checked_remote_url(response.geturl())
        data = bytearray()
        while True:
            _time_left(deadline)
            block = response.read1(min(8192, MAX_SKILL_BYTES + 1 - len(data)))
            if not block:
                return bytes(data), resolved_url
            data.extend(block)
            if len(data) > MAX_SKILL_BYTES:
                raise ValueError("SKILL.md 超过 128 KB")


def preview_remote_skill(url: str) -> dict:
    normalized = _normalize_skill_url(url)
    deadline = time.monotonic() + REMOTE_TIMEOUT_SECONDS
    if not _REMOTE_DOWNLOADS.acquire(blocking=False):
        raise ValueError("远程技能下载繁忙，请稍后再试")
    result = Future()

    def download() -> None:
        try:
            result.set_result(_download_skill(normalized, deadline))
        except Exception as exc:
            result.set_exception(exc)
        finally:
            _REMOTE_DOWNLOADS.release()

    worker = threading.Thread(target=download, daemon=True)
    try:
        worker.start()
    except RuntimeError:
        _REMOTE_DOWNLOADS.release()
        raise
    try:
        content, resolved_url = result.result(timeout=_time_left(deadline))
    except (TimeoutError, FutureTimeoutError) as exc:
        raise ValueError("远程技能下载超时（8 秒）") from exc
    except (OSError, HTTPException) as exc:
        raise ValueError("无法读取远程 SKILL.md") from exc
    path_parts = urlsplit(resolved_url).path.rstrip("/").split("/")
    fallback_name = unquote(path_parts[-2] if len(path_parts) > 1 else "") or "remote-skill"
    metadata = _validate_skill_bytes(content, fallback_name)
    return {**metadata, "resolved_url": resolved_url, "byte_size": len(content)}


def install_remote_skill(url: str, ws_id: str) -> dict:
    skill = preview_remote_skill(url)
    installation = _store_skill(_user_root(), "user", "global", ws_id, skill["name"], _format_skill(skill).encode("utf-8"))
    return {**installation, "name": skill["name"], "resolved_url": skill["resolved_url"]}


def export_skill(skill_id: str, ws_id: str, ws_path: Path) -> dict:
    skill = next((item for item in list_skills(ws_id, ws_path) if item["id"] == skill_id), None)
    if skill is None:
        raise ValueError("未找到要导出的技能")
    return {
        "id": skill_id, "slug": skill["slug"], "name": skill["name"], "filename": "SKILL.md",
        "content": _format_skill(skill),
    }


def delete_skill(skill_id: str, ws_id: str, ws_path: Path) -> bool:
    all_items = list_skills(ws_id, ws_path)
    target = next((x for x in all_items if x["id"] == skill_id), None)
    if not target or not target.get("editable"):
        return False
    skill_dir = Path(target["path"]).parent
    workspace = ws_path.resolve()
    roots = (_user_root(), workspace / ".agents" / "skills", workspace / "skills")
    if skill_dir.parent not in roots or skill_dir.resolve() != skill_dir:
        return False
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    # Clean state references
    state = load_skills_state()
    state["global_enabled"] = [x for x in state.get("global_enabled", []) if x != skill_id]
    for k, lst in list(state.get("workspace_enabled", {}).items()):
        state["workspace_enabled"][k] = [x for x in lst if x != skill_id]
    save_skills_state(state)
    return True


def build_active_skills_prompt(ws_id: str, ws_path: Path, explicit_ids: list[str] | None = None) -> tuple[str, list[str]]:
    all_items = list_skills(ws_id, ws_path)
    explicit_set = set(explicit_ids or [])
    chosen = [s for s in all_items if s["active"] or s["id"] in explicit_set or s["slug"] in explicit_set]
    if not chosen:
        return "", []
    blocks = ["【已挂载的技能规范 (Active Skills) — 请严格遵循】"]
    names = []
    for s in chosen[:5]:  # Cap at 5 skills per turn to protect context budget
        names.append(s["name"])
        body = s["body"]
        if len(body) > 2600:
            body = body[:2600] + "\n...(truncated)"
        blocks.append(f"### Skill: {s['name']}\n{body}")
    return "\n\n".join(blocks), names
