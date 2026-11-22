import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adapters  # noqa: E402
import config    # noqa: E402
import mcp_manager  # noqa: E402
import presets   # noqa: E402
import runner    # noqa: E402
import skills    # noqa: E402
import threads   # noqa: E402

_STATE_LOCK = threading.Lock()
_STATE_VERSION = 1
_WS_DISK_CACHE: dict[str, dict] = {}


def bump_version() -> int:
    global _STATE_VERSION
    with _STATE_LOCK:
        _STATE_VERSION += 1
        return _STATE_VERSION


def get_version() -> int:
    with _STATE_LOCK:
        return _STATE_VERSION


def _get_cached_ws_disk(ws_id: str, ws_path: Path, ws_type: str, current_round: int, force: bool = False) -> dict:
    now = time.time()
    entry = _WS_DISK_CACHE.get(ws_id)
    if not force and entry and (now - entry["ts"]) < 10.0 and entry["path"] == str(ws_path):
        return entry["data"]

    is_game = ws_type == "godot-game"
    is_aigc = ws_type == "aigc-studio"
    aigc_data = presets.get_aigc_studio_data(ws_path) if is_aigc else {"milestones": [], "images": [], "videos": [], "audios": []}

    if is_game:
        rounds = presets.collect_round_metrics(ws_path, limit=8)
        detected = presets.detect_rounds(ws_path)
        latest_r = detected[-1] if detected else current_round
        eff_round = max(current_round, latest_r)
        tel = presets.get_game_telemetry(ws_path, eff_round)
        asset_contract = presets.validate_asset_contract(ws_path)
    else:
        rounds = []
        detected = []
        recent = presets.scan_recent_files(ws_path, limit=12)
        last_age = recent[0]["age_seconds"] if recent else 999999
        tel = {
            "target_round": current_round,
            "codex_active": last_age <= 90,
            "last_age_seconds": last_age,
            "last_file": recent[0]["file"] if recent else "—",
            "godot_running": [],
            "recent_files": recent,
            "milestones": aigc_data["milestones"] if is_aigc else [],
        }
        asset_contract = {"status": "PASS", "png_count": 0, "warnings": []}

    data = {
        "rounds": rounds,
        "detected": detected,
        "tel": tel,
        "asset_contract": asset_contract,
        "skills": skills.list_skills(ws_id, ws_path),
        "git": presets.get_git_status_summary(ws_path),
        "aigc": aigc_data,
    }
    _WS_DISK_CACHE[ws_id] = {"ts": now, "path": str(ws_path), "data": data}
    return data


def append_message(
    sender: str,
    receiver: str,
    msg_type: str,
    title: str,
    body: str,
    round_num: int | None = None,
    workspace_id: str | None = None,
    thread_id: str | None = None,
    attachments: list[dict] | None = None,
) -> dict:
    msgs = config.read_json(config.MESSAGES_PATH, [])
    state = config.read_json(config.STATE_PATH, {})
    ws_id = workspace_id or config.get_active_workspace().get("id", "super-workbench")
    tid = thread_id or threads.ensure_workspace_thread(ws_id)[0]["id"]
    msg = {
        "id": f"msg-{len(msgs) + 1:03d}",
        "workspace_id": ws_id,
        "thread_id": tid,
        "from": sender,
        "to": receiver,
        "type": msg_type,
        "round": round_num if round_num is not None else state.get("current_round", 1),
        "title": title,
        "body": body,
        "attachments": attachments or [],
        "ts": config.now_iso(),
    }
    msgs.append(msg)
    if len(msgs) > 400:
        msgs = msgs[-400:]
    config.write_json(config.MESSAGES_PATH, msgs)
    return msg


def _is_path_allowed(target: Path) -> bool:
    try:
        resolved = target.resolve()
    except OSError:
        return False
    allowed_roots = [config.DATA_DIR.resolve(), config.REPO_ROOT.resolve()]
    ws_data = config.load_workspaces()
    for item in ws_data.get("items", []):
        p = item.get("path")
        if p:
            try:
                rp = Path(p).resolve()
                allowed_roots.append(rp)
                if rp.parent.exists():
                    allowed_roots.append(rp.parent)
            except OSError:
                pass
    target_str = str(resolved).lower()
    return any(target_str.startswith(str(r).lower()) for r in allowed_roots)


def build_snapshot() -> dict:
    config.ensure_data_dir()
    state = config.read_json(
        config.STATE_PATH,
        {
            "current_round": 1,
            "latest_playable_round": 0,
            "stage": "IDLE",
            "edit_lock": "xiu",
            "sla_hours": 48,
            "objection_active": False,
            "gates": {"pre_submit_3": "PENDING", "objective_3": "PENDING", "asset_contract": "PENDING"},
        },
    )
    ws_data = config.load_workspaces()
    active_ws = config.get_active_workspace()
    ws_id = active_ws.get("id", "super-workbench")
    ws_path = Path(active_ws.get("path", str(config.REPO_ROOT)))
    ws_type = active_ws.get("type", "general")
    is_game = ws_type == "godot-game"

    disk = _get_cached_ws_disk(ws_id, ws_path, ws_type, int(state.get("current_round", 1)))
    rounds = disk["rounds"]
    detected = disk["detected"]
    if is_game and detected:
        latest_r = detected[-1]
        state["latest_playable_round"] = latest_r
        if int(state.get("current_round", 0)) < latest_r:
            state["current_round"] = latest_r
    tel = disk["tel"]

    all_msgs = config.read_json(config.MESSAGES_PATH, [])
    active_thread, ws_threads = threads.ensure_workspace_thread(ws_id)
    ws_msgs = threads.filter_thread_messages(all_msgs, ws_id, active_thread["id"])

    stage_concept = ""
    if is_game:
        candidate = ws_path.parent / "美术规划" / "stage_orbital_bay_concept.jpg"
        if candidate.exists():
            stage_concept = str(candidate)

    return {
        "version": get_version(),
        "state": state,
        "workspaces": ws_data,
        "active_workspace": active_ws,
        "threads": ws_threads,
        "active_thread": active_thread,
        "clis": adapters.detect_cli_status(),
        "models": adapters.load_model_settings(),
        "roles": adapters.load_role_bindings(),
        "engines": adapters.list_all_engines(mask_secrets=True),
        "skills": disk.get("skills", []),
        "mcp": mcp_manager.load_mcp_registry(mask_secrets=True),
        "settings": config.load_app_settings(),
        "git": disk.get("git", {}),
        "aigc": disk.get("aigc", {}),
        "live_job": runner.JOB_MANAGER.status_dict(),
        "messages": ws_msgs,
        "self_check": config.read_json(config.SELF_CHECK_PATH, {}),
        "objection": config.read_json(config.OBJECTION_PATH, {}),
        "audit": config.read_json(config.AUDIT_PATH, {}),
        "verdict": config.read_json(config.VERDICT_PATH, {}),
        "asset_contract": disk["asset_contract"],
        "rounds_metrics": rounds,
        "next_for_codex": config.read_text(config.NEXT_FOR_CODEX_PATH),
        "next_for_dsh": config.read_text(config.NEXT_FOR_DSH_PATH),
        "stage_concept_path": stage_concept,
        "telemetry": tel,
    }


def _on_job_event(
    event_type: str,
    lock_owner: str,
    title: str,
    body: str,
    sender: str,
    receiver: str,
    workspace_id: str | None = None,
    thread_id: str | None = None,
    attachments: list[dict] | None = None,
) -> None:
    state = config.read_json(config.STATE_PATH, {})
    stage_map = {
        "agy": "AUDITING_AGY",
        "codex": "CODING_CODEX",
        "dsh": "VERIFYING_DSH",
        "xiu": "WAITING_HUMAN",
    }
    state["edit_lock"] = lock_owner
    state["stage"] = stage_map.get(lock_owner, state.get("stage", "IDLE"))
    state["updated_at"] = config.now_iso()
    config.write_json(config.STATE_PATH, state)
    append_message(
        sender, receiver, event_type.upper(), title, body,
        workspace_id=workspace_id, thread_id=thread_id, attachments=attachments
    )
    _WS_DISK_CACHE.clear()
    bump_version()


def _on_compact_done(ws_id: str, thread_id: str, summary: str, count: int) -> None:
    append_message(
        "agy",
        "xiu",
        "COMPACT",
        f"上下文已压缩（浓缩前 {count} 条对话为长期记忆）",
        summary,
        workspace_id=ws_id,
        thread_id=thread_id,
    )
    bump_version()


class WorkbenchHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            html_file = config.STATIC_DIR / "index.html"
            data = html_file.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed.path == "/api/state":
            self._send_json(build_snapshot())
            return

        if parsed.path == "/api/live":
            self._send_json({
                "version": get_version(),
                "live_job": runner.JOB_MANAGER.status_dict(),
            })
            return

        if parsed.path == "/api/diff":
            qs = urllib.parse.parse_qs(parsed.query)
            rel_file = (qs.get("file") or [""])[0]
            active_ws = config.get_active_workspace()
            ws_path = Path(active_ws.get("path", str(config.REPO_ROOT)))
            if not rel_file:
                self._send_json({"mode": "error", "content": "未指定文件"}, 400)
                return
            self._send_json(presets.get_file_diff_or_preview(ws_path, rel_file))
            return

        if parsed.path in ("/api/image", "/api/media"):
            qs = urllib.parse.parse_qs(parsed.query)
            raw_path = (qs.get("path") or [""])[0]
            try:
                target = Path(raw_path).resolve()
                if not _is_path_allowed(target):
                    self._send_json({"error": "Forbidden path outside registered workspaces"}, 403)
                    return
                if not target.exists() or not target.is_file():
                    self._send_json({"error": "File not found"}, 404)
                    return
                ctype, _ = mimetypes.guess_type(str(target))
                size = target.stat().st_size
                range_hdr = self.headers.get("Range")
                if range_hdr and range_hdr.startswith("bytes="):
                    spec = range_hdr[6:].split(",")[0].strip()
                    start_s, _, end_s = spec.partition("-")
                    start = int(start_s) if start_s else 0
                    end = int(end_s) if end_s else size - 1
                    end = min(end, size - 1)
                    if start > end or start >= size:
                        self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                    length = end - start + 1
                    with target.open("rb") as f:
                        f.seek(start)
                        chunk = f.read(length)
                    self.send_response(HTTPStatus.PARTIAL_CONTENT)
                    self.send_header("Content-Type", ctype or "application/octet-stream")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.send_header("Content-Length", str(len(chunk)))
                    self.end_headers()
                    self.wfile.write(chunk)
                    return

                data = target.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", ctype or "application/octet-stream")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except OSError as exc:
                self._send_json({"error": str(exc)}, 500)
            return

        self._send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        data = self._read_body()
        bump_version()
        state = config.read_json(config.STATE_PATH, {"gates": {}})
        state.setdefault("gates", {})
        active_ws = config.get_active_workspace()
        ws_path = Path(active_ws.get("path", str(config.REPO_ROOT)))

        if parsed.path == "/api/workspace":
            action = str(data.get("action", "switch"))
            ws_data = config.load_workspaces()
            if action == "switch":
                ws_id = str(data.get("id", "")).strip()
                if any(item.get("id") == ws_id for item in ws_data.get("items", [])):
                    ws_data["active_id"] = ws_id
                    config.save_workspaces(ws_data)
                self._send_json({"ok": True, "snapshot": build_snapshot()})
                return
            if action == "create":
                name = str(data.get("name", "")).strip()
                path_str = str(data.get("path", "")).strip()
                wtype = str(data.get("type", "general")).strip()
                desc = str(data.get("description", "")).strip()
                if not name or not path_str:
                    self._send_json({"ok": False, "error": "请填写工作空间名称与本地目录路径"}, 400)
                    return
                slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or f"ws-{len(ws_data['items']) + 1}"
                if any(i.get("id") == slug for i in ws_data["items"]):
                    slug = f"{slug}-{len(ws_data['items']) + 1}"
                presets.init_workspace_preset(Path(path_str), wtype)
                new_item = {
                    "id": slug,
                    "name": name,
                    "type": wtype,
                    "path": path_str,
                    "description": desc or f"{wtype} workspace",
                    "created_at": config.now_iso(),
                }
                ws_data["items"].append(new_item)
                ws_data["active_id"] = slug
                config.save_workspaces(ws_data)
                append_message("xiu", "agy", "WORKSPACE", f"新建工作空间：{name}", f"路径：{path_str}", workspace_id=slug)
                self._send_json({"ok": True, "snapshot": build_snapshot()})
                return
            if action == "delete":
                ws_id = str(data.get("id", "")).strip()
                items = ws_data.get("items", [])
                if len(items) <= 1:
                    self._send_json({"ok": False, "error": "至少需要保留一个工作空间"}, 400)
                    return
                new_items = [i for i in items if i.get("id") != ws_id]
                if len(new_items) == len(items):
                    self._send_json({"ok": False, "error": "未找到要移除的工作空间"}, 404)
                    return
                ws_data["items"] = new_items
                if ws_data.get("active_id") == ws_id:
                    ws_data["active_id"] = new_items[0]["id"]
                config.save_workspaces(ws_data)
                if data.get("purge_messages", False):
                    all_msgs = config.read_json(config.MESSAGES_PATH, [])
                    kept = [m for m in all_msgs if m.get("workspace_id") != ws_id]
                    config.write_json(config.MESSAGES_PATH, kept)
                self._send_json({"ok": True, "snapshot": build_snapshot()})
                return
            if action == "rename":
                ws_id = str(data.get("id", "")).strip()
                new_name = str(data.get("name", "")).strip()
                if not new_name:
                    self._send_json({"ok": False, "error": "空间名称不能为空"}, 400)
                    return
                for item in ws_data.get("items", []):
                    if item.get("id") == ws_id:
                        item["name"] = new_name
                        if data.get("path"):
                            item["path"] = str(data["path"]).strip()
                        break
                config.save_workspaces(ws_data)
                self._send_json({"ok": True, "snapshot": build_snapshot()})
                return

        if parsed.path == "/api/thread":
            action = str(data.get("action", "switch"))
            ws_id = active_ws.get("id", "super-workbench")
            if action == "create":
                t_obj = threads.create_thread(ws_id, str(data.get("title", "")))
                self._send_json({"ok": True, "thread": t_obj, "snapshot": build_snapshot()})
                return
            if action == "switch":
                tid = str(data.get("id", "")).strip()
                t_obj = threads.switch_thread(ws_id, tid)
                if not t_obj:
                    self._send_json({"ok": False, "error": "未找到该对话线程"}, 404)
                    return
                self._send_json({"ok": True, "thread": t_obj, "snapshot": build_snapshot()})
                return
            if action == "rename":
                tid = str(data.get("id", "")).strip()
                ok = threads.rename_thread(tid, str(data.get("title", "")))
                if not ok:
                    self._send_json({"ok": False, "error": "重命名失败"}, 400)
                    return
                self._send_json({"ok": True, "snapshot": build_snapshot()})
                return
            if action == "delete":
                tid = str(data.get("id", "")).strip()
                ok = threads.delete_thread(ws_id, tid)
                if not ok:
                    self._send_json({"ok": False, "error": "每个空间至少需要保留一个对话"}, 400)
                    return
                self._send_json({"ok": True, "snapshot": build_snapshot()})
                return

        if parsed.path == "/api/compact":
            ws_id = active_ws.get("id", "super-workbench")
            active_thread, _ = threads.ensure_workspace_thread(ws_id)
            ok, reason = runner.JOB_MANAGER.compact_thread(ws_id, active_thread["id"], active_ws, _on_compact_done)
            if not ok:
                self._send_json({"ok": False, "error": reason}, 409)
                return
            self._send_json({"ok": True, "snapshot": build_snapshot()})
            return

        if parsed.path == "/api/clear_chat":
            ws_id = active_ws.get("id", "super-workbench")
            active_thread, _ = threads.ensure_workspace_thread(ws_id)
            tid = active_thread["id"]
            all_msgs = config.read_json(config.MESSAGES_PATH, [])
            kept = [m for m in all_msgs if not (m.get("workspace_id") == ws_id and threads.msg_thread_id(m) == tid)]
            config.write_json(config.MESSAGES_PATH, kept)
            threads.set_thread_summary(tid, "", 0)
            self._send_json({"ok": True, "snapshot": build_snapshot()})
            return

        if parsed.path == "/api/models":
            mcfg = adapters.load_model_settings()
            if data.get("agy_model"):
                mcfg["agy_model"] = str(data["agy_model"]).strip()
            if data.get("codex_model"):
                mcfg["codex_model"] = str(data["codex_model"]).strip()
            if data.get("codex_effort"):
                mcfg["codex_effort"] = str(data["codex_effort"]).strip()
            adapters.save_model_settings(mcfg)
            self._send_json({"ok": True, "models": mcfg, "snapshot": build_snapshot()})
            return

        if parsed.path == "/api/roles":
            roles = adapters.load_role_bindings()
            updates = data.get("roles") if isinstance(data.get("roles"), dict) else data
            for slot_id in ("planner", "builder", "reviewer"):
                patch = updates.get(slot_id)
                if isinstance(patch, dict):
                    for k in ("engine", "model", "effort", "label", "aigc_label"):
                        if k in patch and patch[k] is not None:
                            roles[slot_id][k] = str(patch[k]).strip()
            adapters.save_role_bindings(roles)
            self._send_json({"ok": True, "roles": roles, "snapshot": build_snapshot()})
            return

        if parsed.path == "/api/engines":
            action = str(data.get("action", "add"))
            try:
                if action == "add":
                    item = adapters.add_custom_engine(data)
                    self._send_json({"ok": True, "engine": item, "snapshot": build_snapshot()})
                    return
                if action == "delete":
                    eng_id = str(data.get("id", "")).strip()
                    removed = adapters.delete_custom_engine(eng_id)
                    if not removed:
                        self._send_json({"ok": False, "error": "无法删除内置引擎或未找到该引擎"}, 400)
                        return
                    self._send_json({"ok": True, "snapshot": build_snapshot()})
                    return
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, 400)
                return

        if parsed.path == "/api/skills":
            action = str(data.get("action", "toggle"))
            ws_id = active_ws.get("id", "super-workbench")
            try:
                if action == "toggle":
                    sid = str(data.get("id", "")).strip()
                    scope = str(data.get("scope", "workspace"))
                    enabled = bool(data.get("enabled", True))
                    skills.toggle_skill(sid, scope, enabled, ws_id)
                    _WS_DISK_CACHE.clear()
                    self._send_json({"ok": True, "snapshot": build_snapshot()})
                    return
                if action == "create":
                    created = skills.create_skill(
                        name=str(data.get("name", "")),
                        description=str(data.get("description", "")),
                        body=str(data.get("body", "")),
                        scope=str(data.get("scope", "user")),
                        ws_path=ws_path,
                        ws_id=ws_id,
                    )
                    _WS_DISK_CACHE.clear()
                    self._send_json({"ok": True, "skill": created, "snapshot": build_snapshot()})
                    return
                if action == "import":
                    imported = skills.import_local_skill(str(data.get("source_path", "")), ws_id)
                    _WS_DISK_CACHE.clear()
                    self._send_json({"ok": True, "skill": imported, "snapshot": build_snapshot()})
                    return
                if action == "delete":
                    sid = str(data.get("id", "")).strip()
                    ok = skills.delete_skill(sid, ws_id, ws_path)
                    if not ok:
                        self._send_json({"ok": False, "error": "仅支持删除自定义或当前空间技能"}, 400)
                        return
                    _WS_DISK_CACHE.clear()
                    self._send_json({"ok": True, "snapshot": build_snapshot()})
                    return
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, 400)
                return

        if parsed.path == "/api/mcp":
            action = str(data.get("action", "")).strip()
            try:
                if action == "save":
                    srv = mcp_manager.upsert_server(
                        name=str(data.get("name", "")),
                        title=str(data.get("title", "")),
                        desc=str(data.get("desc", "")),
                        transport=str(data.get("transport", "stdio")),
                        command=str(data.get("command", "")),
                        args=data.get("args", ""),
                        url=str(data.get("url", "")),
                        env=data.get("env", ""),
                    )
                    sync_res = None
                    if bool(data.get("auto_sync", True)):
                        sync_res = mcp_manager.sync_server_to_clis(srv["name"])
                    bump_version()
                    self._send_json({"ok": True, "server": srv, "sync": sync_res, "snapshot": build_snapshot()})
                    return

                if action == "sync":
                    name = str(data.get("name", "")).strip()
                    clis_target = data.get("clis") if isinstance(data.get("clis"), list) else None
                    sync_res = mcp_manager.sync_server_to_clis(name, clis_target)
                    bump_version()
                    self._send_json({"ok": True, "sync": sync_res, "snapshot": build_snapshot()})
                    return

                if action == "delete":
                    name = str(data.get("name", "")).strip()
                    unsync = bool(data.get("unsync", True))
                    res = mcp_manager.delete_server(name, unsync=unsync)
                    bump_version()
                    self._send_json({"ok": True, "result": res, "snapshot": build_snapshot()})
                    return

                if action == "scan":
                    scanned = mcp_manager.scan_cli_mcps()
                    bump_version()
                    self._send_json({"ok": True, "scanned": scanned, "snapshot": build_snapshot()})
                    return
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, 400)
                return

        if parsed.path == "/api/upload":
            import base64

            raw_name = str(data.get("filename", "attachment.bin")).strip()
            mime = str(data.get("mime_type", "")).strip()
            b64 = str(data.get("data_base64", "")).strip()
            if not b64:
                self._send_json({"ok": False, "error": "文件内容为空"}, 400)
                return
            if "," in b64 and b64.startswith("data:"):
                b64 = b64.split(",", 1)[1]
            try:
                blob = base64.b64decode(b64)
            except Exception:
                self._send_json({"ok": False, "error": "Base64 解码失败"}, 400)
                return
            if len(blob) > 15 * 1024 * 1024:
                self._send_json({"ok": False, "error": "单个附件不能超过 15 MB"}, 400)
                return

            safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", Path(raw_name).name).strip() or "upload.bin"
            config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            ts_id = f"{int(time.time() * 1000) % 100000000:08d}"
            target = config.UPLOADS_DIR / f"{ts_id}_{safe_name}"
            target.write_bytes(blob)
            is_img = mime.startswith("image/") or target.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
            att = {
                "id": f"att-{ts_id}",
                "name": safe_name,
                "path": str(target),
                "is_image": is_img,
                "size": len(blob),
            }
            self._send_json({"ok": True, "attachment": att})
            return

        if parsed.path == "/api/dispatch":
            target = str(data.get("target", "codex"))
            text = str(data.get("instruction", "")).strip()
            auto_run = bool(data.get("auto_run", True))
            skill_ids = data.get("skill_ids") if isinstance(data.get("skill_ids"), list) else []
            attachments = data.get("attachments") if isinstance(data.get("attachments"), list) else []
            if not text and not attachments:
                self._send_json({"ok": False, "error": "请先输入指令内容或添加附件"}, 400)
                return
            if not text and attachments:
                text = "请结合我附带的图片/附件进行分析与处理。"
            r = int(state.get("current_round", 1))
            if target in ("codex", "pipeline") and len(text) >= 160:
                md = f"# 给 Codex 的最新指令 · [{active_ws.get('name')}]\n\n{text}\n"
                config.NEXT_FOR_CODEX_PATH.write_text(md, encoding="utf-8")
            if target == "dsh":
                config.NEXT_FOR_DSH_PATH.write_text(f"# 给 DSH 的质检指令\n\n{text}\n", encoding="utf-8")

            if auto_run:
                ws_id = active_ws.get("id", "super-workbench")
                active_thread, _ = threads.ensure_workspace_thread(ws_id)
                is_pipe = target == "pipeline"
                first_agent = "agy" if is_pipe else target
                ok, reason = runner.JOB_MANAGER.start_job(
                    first_agent,
                    text,
                    is_pipe,
                    active_ws,
                    _on_job_event,
                    skill_ids=skill_ids,
                    thread_id=active_thread["id"],
                    attachments=attachments,
                )
                if not ok:
                    self._send_json({"ok": False, "error": reason}, 409)
                    return
                self._send_json({"ok": True, "started_cli": first_agent, "pipeline": is_pipe, "snapshot": build_snapshot()})
                return

            state["edit_lock"] = "agy" if target == "pipeline" else target
            state["updated_at"] = config.now_iso()
            config.write_json(config.STATE_PATH, state)
            uname = config.load_app_settings().get("user_name", "我")
            msg = append_message("xiu", state["edit_lock"], "TASK", f"{uname}下达任务 → {target.upper()}", text, round_num=r)
            self._send_json({"ok": True, "message": msg, "snapshot": build_snapshot()})
            return

        if parsed.path == "/api/abort":
            aborted = runner.JOB_MANAGER.abort()
            self._send_json({"ok": True, "aborted": aborted, "snapshot": build_snapshot()})
            return

        if parsed.path == "/api/settings":
            updated = config.save_app_settings(data if isinstance(data, dict) else {})
            bump_version()
            self._send_json({"ok": True, "settings": updated, "snapshot": build_snapshot()})
            return

        if parsed.path == "/api/approve":
            action = str(data.get("action", "approve")).strip().lower()
            note = str(data.get("note", "")).strip()
            if action == "reject":
                runner.JOB_MANAGER.reject_pending()
                bump_version()
                self._send_json({"ok": True, "rejected": True, "snapshot": build_snapshot()})
                return
            ok, reason = runner.JOB_MANAGER.approve_pending(note, _on_job_event)
            if not ok:
                self._send_json({"ok": False, "error": reason}, 409)
                return
            bump_version()
            self._send_json({"ok": True, "approved": True, "snapshot": build_snapshot()})
            return

        if parsed.path == "/api/self_check":
            res = presets.run_pre_submit_self_check(ws_path, data.get("round"))
            passed = res.get("status") == "PASS"
            state["gates"]["pre_submit_3"] = "PASS" if passed else "FAIL"
            if passed and state.get("stage") in ("CODING_CODEX", "IDLE"):
                state["stage"] = "VERIFYING_DSH"
                state["edit_lock"] = "dsh"
            state["updated_at"] = config.now_iso()
            config.write_json(config.STATE_PATH, state)
            msg = append_message(
                "codex",
                "dsh" if passed else "codex",
                "SELF_CHECK",
                f"提交前自检三条：{'全部通过' if passed else '未通过'}",
                f"场景 {res.get('scene')} | 能跑={res['checks']['bootable']['passed']} 无报错={res['checks']['zero_errors']['passed']}",
                round_num=res.get("round"),
            )
            self._send_json({"ok": True, "result": res, "message": msg, "snapshot": build_snapshot()})
            return

        if parsed.path == "/api/dsh_verify":
            sc = config.read_json(config.SELF_CHECK_PATH, {})
            if sc.get("status") not in ("PASS", "PASSED_BASELINE"):
                self._send_json({"ok": False, "error": "提交前自检三条尚未通过，禁止进入 DSH 质检"}, 400)
                return
            res = presets.run_dsh_verification(ws_path)
            state["gates"]["asset_contract"] = res["asset_contract"]["status"]
            state["gates"]["objective_3"] = "PASS" if res["overall_pass"] else "FAIL"
            state["stage"] = "AUDITING_AGY" if res["overall_pass"] else "CODING_CODEX"
            state["edit_lock"] = "agy" if res["overall_pass"] else "codex"
            state["updated_at"] = config.now_iso()
            config.write_json(config.STATE_PATH, state)
            o3 = res["objective_3"]
            msg = append_message(
                "dsh",
                "agy" if res["overall_pass"] else "codex",
                "DSH_VERIFY",
                f"DSH 客观硬指标核验：{'通过' if res['overall_pass'] else '未达标'}",
                f"FPS={o3['fps_ge_60']['value']} | 延迟={o3['input_latency_lt_100ms']['value']}ms | 契约={res['asset_contract']['status']}",
            )
            self._send_json({"ok": True, "result": res, "message": msg, "snapshot": build_snapshot()})
            return

        if parsed.path == "/api/objection":
            summary = str(data.get("summary", "")).strip()
            evidence = str(data.get("evidence", "")).strip()
            if not summary or not evidence:
                self._send_json({"ok": False, "error": "提交技术异议必须写明异议摘要和代码/实测依据"}, 400)
                return
            deadline = (datetime.now().astimezone() + timedelta(hours=48)).isoformat(timespec="seconds")
            obj = {
                "status": "OPEN",
                "round": state.get("current_round", 1),
                "raised_by": "codex",
                "summary": summary,
                "evidence": evidence,
                "created_at": config.now_iso(),
                "sla_deadline": deadline,
                "resolution": None,
            }
            config.write_json(config.OBJECTION_PATH, obj)
            state["stage"] = "DISPUTED"
            state["objection_active"] = True
            state["objection_deadline"] = deadline
            state["edit_lock"] = "xiu"
            state["updated_at"] = config.now_iso()
            config.write_json(config.STATE_PATH, state)
            msg = append_message("codex", "xiu", "OBJECTION", "提交技术实现异议（48h SLA 仲裁）", f"{summary}\n依据：{evidence}")
            self._send_json({"ok": True, "objection": obj, "message": msg, "snapshot": build_snapshot()})
            return

        if parsed.path == "/api/arbitrate":
            resolution = str(data.get("resolution", "维持原案"))
            note = str(data.get("note", "")).strip()
            obj = config.read_json(config.OBJECTION_PATH, {})
            obj["status"] = "RESOLVED"
            obj["resolution"] = resolution
            obj["resolved_by"] = "xiu"
            obj["resolved_at"] = config.now_iso()
            obj["note"] = note
            config.write_json(config.OBJECTION_PATH, obj)
            state["stage"] = "CODING_CODEX"
            state["objection_active"] = False
            state["objection_deadline"] = None
            state["edit_lock"] = "codex"
            state["updated_at"] = config.now_iso()
            config.write_json(config.STATE_PATH, state)
            msg = append_message("xiu", "codex", "ARBITRATE", f"仲裁裁决：{resolution}", note or "按裁决继续推进。")
            self._send_json({"ok": True, "message": msg, "snapshot": build_snapshot()})
            return

        if parsed.path == "/api/verdict":
            verdict = str(data.get("verdict", "PASS")).upper()
            notes = str(data.get("notes", "")).strip()
            v_obj = {"round": state.get("current_round", 1), "verdict": verdict, "notes": notes, "ts": config.now_iso()}
            config.write_json(config.VERDICT_PATH, v_obj)
            state["gates"]["human_50_50"] = verdict
            if verdict == "PASS":
                state["current_round"] = int(state.get("current_round", 1)) + 1
                state["stage"] = "IDLE"
                state["edit_lock"] = "agy"
                msg = append_message("xiu", "agy", "VERDICT_PASS", f"验收通过 → 进入第 {state['current_round']} 轮", notes or "手感与目标达标。")
            else:
                state["stage"] = "CODING_CODEX"
                state["edit_lock"] = "codex"
                msg = append_message("xiu", "codex", "VERDICT_REJECT", "验收退回修改", notes or "请按说明返工。")
            state["updated_at"] = config.now_iso()
            config.write_json(config.STATE_PATH, state)
            self._send_json({"ok": True, "message": msg, "snapshot": build_snapshot()})
            return

        if parsed.path == "/api/launch_game":
            try:
                if active_ws.get("type") == "godot-game" and (ws_path / "Launch-Latest.cmd").exists() and os.name == "nt":
                    subprocess.Popen(["cmd", "/c", str(ws_path / "Launch-Latest.cmd")], cwd=str(ws_path))
                elif os.name == "nt":
                    os.startfile(str(ws_path))
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(ws_path)])
                else:
                    subprocess.Popen(["xdg-open", str(ws_path)])
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        self._send_json({"error": "Not found"}, 404)


def run_server(host: str | None = None, port: int | None = None) -> None:
    config.ensure_data_dir()
    h = host or config.HOST
    p = port or config.PORT
    srv = ThreadingHTTPServer((h, p), WorkbenchHandler)
    print(f"Super Workbench running at http://{h}:{p} (data: {config.DATA_DIR})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nSuper Workbench stopped.", flush=True)


if __name__ == "__main__":
    run_server()
