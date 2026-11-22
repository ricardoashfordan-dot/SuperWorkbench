import time
from pathlib import Path

import config


def default_thread_id(ws_id: str) -> str:
    return f"default-{ws_id}"


def load_threads_data() -> dict:
    data = config.read_json(config.THREADS_PATH, {"active_by_ws": {}, "items": []})
    data.setdefault("active_by_ws", {})
    data.setdefault("items", [])
    return data


def save_threads_data(data: dict) -> None:
    config.write_json(config.THREADS_PATH, data)


def ensure_workspace_thread(ws_id: str) -> tuple[dict, list[dict]]:
    data = load_threads_data()
    ws_threads = [t for t in data["items"] if t.get("workspace_id") == ws_id]
    changed = False
    if not ws_threads:
        tid = default_thread_id(ws_id)
        t_obj = {
            "id": tid,
            "workspace_id": ws_id,
            "title": "主对话",
            "summary": "",
            "compacted_at": None,
            "compacted_count": 0,
            "created_at": config.now_iso(),
            "updated_at": config.now_iso(),
        }
        data["items"].append(t_obj)
        ws_threads = [t_obj]
        changed = True

    active_id = data["active_by_ws"].get(ws_id)
    active = next((t for t in ws_threads if t["id"] == active_id), None)
    if not active:
        active = ws_threads[0]
        data["active_by_ws"][ws_id] = active["id"]
        changed = True

    if changed:
        save_threads_data(data)
    return active, ws_threads


def create_thread(ws_id: str, title: str = "") -> dict:
    data = load_threads_data()
    ensure_workspace_thread(ws_id)
    data = load_threads_data()
    tid = f"t-{int(time.time() * 1000) % 100000000:08d}"
    t_obj = {
        "id": tid,
        "workspace_id": ws_id,
        "title": title.strip() or "新对话",
        "summary": "",
        "compacted_at": None,
        "compacted_count": 0,
        "created_at": config.now_iso(),
        "updated_at": config.now_iso(),
    }
    data["items"].insert(0, t_obj)
    data["active_by_ws"][ws_id] = tid
    save_threads_data(data)
    return t_obj


def switch_thread(ws_id: str, thread_id: str) -> dict | None:
    data = load_threads_data()
    target = next((t for t in data["items"] if t["id"] == thread_id and t.get("workspace_id") == ws_id), None)
    if not target:
        return None
    data["active_by_ws"][ws_id] = thread_id
    save_threads_data(data)
    return target


def rename_thread(thread_id: str, new_title: str) -> bool:
    new_title = new_title.strip()
    if not new_title:
        return False
    data = load_threads_data()
    for t in data["items"]:
        if t["id"] == thread_id:
            t["title"] = new_title[:48]
            t["updated_at"] = config.now_iso()
            save_threads_data(data)
            return True
    return False


def auto_title_if_generic(thread_id: str, user_text: str) -> None:
    clean = " ".join(user_text.strip().splitlines())
    if not clean:
        return
    data = load_threads_data()
    for t in data["items"]:
        if t["id"] == thread_id:
            if t.get("title") in ("新对话", "New Chat", ""):
                t["title"] = clean[:22] + ("…" if len(clean) > 22 else "")
            t["updated_at"] = config.now_iso()
            save_threads_data(data)
            return


def delete_thread(ws_id: str, thread_id: str) -> bool:
    data = load_threads_data()
    ws_threads = [t for t in data["items"] if t.get("workspace_id") == ws_id]
    if len(ws_threads) <= 1:
        return False
    data["items"] = [t for t in data["items"] if t["id"] != thread_id]
    remaining = [t for t in data["items"] if t.get("workspace_id") == ws_id]
    if data["active_by_ws"].get(ws_id) == thread_id and remaining:
        data["active_by_ws"][ws_id] = remaining[0]["id"]
    save_threads_data(data)

    # Remove messages belonging exclusively to the deleted thread
    all_msgs = config.read_json(config.MESSAGES_PATH, [])
    kept = [m for m in all_msgs if msg_thread_id(m) != thread_id]
    config.write_json(config.MESSAGES_PATH, kept)
    return True


def msg_thread_id(msg: dict) -> str:
    if msg.get("thread_id"):
        return msg["thread_id"]
    ws_id = msg.get("workspace_id", "super-workbench")
    return default_thread_id(ws_id)


def filter_thread_messages(all_msgs: list[dict], ws_id: str, thread_id: str) -> list[dict]:
    return [
        m for m in all_msgs
        if m.get("workspace_id") == ws_id and msg_thread_id(m) == thread_id
    ]


def set_thread_summary(thread_id: str, summary: str, compacted_count: int) -> dict | None:
    data = load_threads_data()
    for t in data["items"]:
        if t["id"] == thread_id:
            t["summary"] = summary.strip()
            t["compacted_count"] = compacted_count
            t["compacted_at"] = config.now_iso()
            t["updated_at"] = config.now_iso()
            save_threads_data(data)
            return t
    return None


def get_thread_by_id(thread_id: str) -> dict | None:
    data = load_threads_data()
    return next((t for t in data["items"] if t["id"] == thread_id), None)
