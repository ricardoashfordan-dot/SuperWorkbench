import re
import shutil
from pathlib import Path

import config


def _parse_skill_md(path: Path) -> tuple[str, str, str]:
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    name = path.parent.name
    desc = ""
    body = raw

    if raw.startswith("---"):
        parts = re.split(r"^---\s*$", raw, maxsplit=2, flags=re.MULTILINE)
        if len(parts) >= 3:
            fm = parts[1]
            body = parts[2].strip()
            m_name = re.search(r"^name:\s*(.+)$", fm, flags=re.MULTILINE)
            m_desc = re.search(r"^description:\s*(.+)$", fm, flags=re.MULTILINE)
            if m_name:
                name = m_name.group(1).strip().strip("\"'")
            if m_desc:
                desc = m_desc.group(1).strip().strip("\"'")

    if not desc:
        for line in body.splitlines():
            clean = line.strip().lstrip("#").strip()
            if clean:
                desc = clean[:90]
                break
    return name, desc, body


def _scan_dir(base: Path, source: str, source_label: str, editable: bool) -> list[dict]:
    if not base.exists() or not base.is_dir():
        return []
    found = []
    try:
        for child in sorted(base.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            md = child / "SKILL.md"
            if not md.exists():
                continue
            name, desc, body = _parse_skill_md(md)
            slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or child.name.lower()
            skill_id = f"{source}:{slug}"
            found.append(
                {
                    "id": skill_id,
                    "slug": slug,
                    "name": name,
                    "description": desc,
                    "body": body,
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
    config.USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    state = load_skills_state()
    global_set = set(state.get("global_enabled", []))
    ws_set = set(state.get("workspace_enabled", {}).get(ws_id, []))

    home = Path.home()
    items = []
    items.extend(_scan_dir(config.BUILTIN_SKILLS_DIR, "builtin", "内置推荐", False))
    items.extend(_scan_dir(config.USER_SKILLS_DIR, "user", "自定义技能", True))

    # Avoid duplicating builtin skills when active workspace is SuperWorkbench itself
    ws_resolved = ws_path.resolve() if ws_path.exists() else ws_path
    if ws_resolved != config.REPO_ROOT.resolve():
        items.extend(_scan_dir(ws_path / ".agents" / "skills", "workspace", "当前空间", True))
        items.extend(_scan_dir(ws_path / "skills", "workspace", "当前空间", True))

    # Auto-discover skills already installed for local CLIs (read-only)
    ext_dirs = [
        (home / ".codex" / "skills", "ext-codex", "本机 Codex"),
        (home / ".gemini" / "antigravity" / "skills", "ext-agy", "本机 AGY"),
        (home / ".claude" / "skills", "ext-claude", "本机 Claude"),
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


def create_skill(name: str, description: str, body: str, scope: str, ws_path: Path, ws_id: str) -> dict:
    name = name.strip()
    description = description.strip()
    body = body.strip()
    if not name or not body:
        raise ValueError("技能名称与规则正文不能为空")

    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")
    if not slug:
        # Support pure Chinese names cleanly by generating a safe folder slug
        slug = f"skill-{abs(hash(name)) % 100000:05d}"

    if scope == "workspace" and ws_path.exists() and ws_path.resolve() != config.REPO_ROOT.resolve():
        target_dir = ws_path / ".agents" / "skills" / slug
        src_key = "workspace"
    else:
        target_dir = config.USER_SKILLS_DIR / slug
        src_key = "user"

    target_dir.mkdir(parents=True, exist_ok=True)
    md_content = f"---\nname: {name}\ndescription: {description or name}\n---\n\n{body}\n"
    (target_dir / "SKILL.md").write_text(md_content, encoding="utf-8")

    skill_id = f"{src_key}:{slug}"
    toggle_skill(skill_id, "workspace" if scope == "workspace" else "global", True, ws_id)
    return {"id": skill_id, "slug": slug, "path": str(target_dir / "SKILL.md")}


def import_local_skill(source_path: str, ws_id: str) -> dict:
    p = Path(source_path.strip().strip("\"'"))
    if not p.exists():
        raise ValueError(f"路径不存在: {p}")

    if p.is_file() and p.name.lower().endswith(".md"):
        name, desc, body = _parse_skill_md(p)
        slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or p.stem.lower()
        dst_dir = config.USER_SKILLS_DIR / slug
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst_dir / "SKILL.md")
    elif p.is_dir() and (p / "SKILL.md").exists():
        name, _, _ = _parse_skill_md(p / "SKILL.md")
        slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or p.name.lower()
        dst_dir = config.USER_SKILLS_DIR / slug
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        shutil.copytree(p, dst_dir)
    else:
        raise ValueError("请选择包含 SKILL.md 的文件夹，或直接指向一个 .md 技能文件")

    skill_id = f"user:{slug}"
    toggle_skill(skill_id, "global", True, ws_id)
    return {"id": skill_id, "slug": slug, "path": str(dst_dir / "SKILL.md")}


def delete_skill(skill_id: str, ws_id: str, ws_path: Path) -> bool:
    all_items = list_skills(ws_id, ws_path)
    target = next((x for x in all_items if x["id"] == skill_id), None)
    if not target or not target.get("editable"):
        return False
    skill_dir = Path(target["path"]).parent
    if skill_dir.exists():
        shutil.rmtree(skill_dir, ignore_errors=True)
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
