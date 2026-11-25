import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import config

_MESSAGE_LOCK = threading.Lock()
_HISTORY_CACHE: tuple[tuple, "_History"] | None = None


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
    if len(ws_threads) <= 1 or not any(t["id"] == thread_id for t in ws_threads):
        return False
    data["items"] = [t for t in data["items"] if not (t.get("workspace_id") == ws_id and t["id"] == thread_id)]
    remaining = [t for t in data["items"] if t.get("workspace_id") == ws_id]
    if data["active_by_ws"].get(ws_id) == thread_id and remaining:
        data["active_by_ws"][ws_id] = remaining[0]["id"]
    save_threads_data(data)

    clear_messages(ws_id, thread_id)
    return True


def msg_thread_id(msg: dict) -> str:
    if msg.get("thread_id"):
        return msg["thread_id"]
    ws_id = msg.get("workspace_id", "super-workbench")
    return default_thread_id(ws_id)


def _matches_history(msg: dict, ws_id: str, thread_id: str | None) -> bool:
    return msg.get("workspace_id") == ws_id and (
        thread_id is None or msg_thread_id(msg) == thread_id
    )


def _read_history_json(path: Path, default):
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return default


def _write_history_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def _message_transaction():
    lock_path = config.MESSAGES_PATH.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _MESSAGE_LOCK, lock_path.open("a+b") as lock:
        # Lock a separate file so replacing messages.json never changes the lock.
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def _read_messages() -> list[dict]:
    messages = _read_history_json(config.MESSAGES_PATH, [])
    if not isinstance(messages, list) or any(not isinstance(msg, dict) for msg in messages):
        raise ValueError("messages.json must contain an array of messages")
    return messages


def _message_number(msg: dict) -> int:
    prefix, _, number = str(msg.get("id", "")).partition("-")
    return int(number) if prefix == "msg" and number.isascii() and number.isdecimal() else 0


@dataclass
class _History:
    messages: list[dict]
    by_thread: dict[tuple[str, str], list[dict]] = field(default_factory=dict)
    high_water: int = 0

    def __post_init__(self) -> None:
        for message in self.messages:
            self.index(message)

    def index(self, message: dict) -> None:
        self.high_water = max(self.high_water, _message_number(message))
        workspace_id = message.get("workspace_id")
        if isinstance(workspace_id, str):
            thread_id = msg_thread_id(message)
            if isinstance(thread_id, str):
                self.by_thread.setdefault((workspace_id, thread_id), []).append(message)


def _history_fingerprint() -> tuple:
    path = config.MESSAGES_PATH
    try:
        stat = path.stat()
    except FileNotFoundError:
        return (path,)
    return (path, stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns, stat.st_dev, stat.st_ino)


def _load_history() -> _History:
    global _HISTORY_CACHE
    fingerprint = _history_fingerprint()
    if _HISTORY_CACHE is None or _HISTORY_CACHE[0] != fingerprint:
        _HISTORY_CACHE = (fingerprint, _History(_read_messages()))
    return _HISTORY_CACHE[1]


def _remember_history(history: _History) -> None:
    global _HISTORY_CACHE
    _HISTORY_CACHE = (_history_fingerprint(), history)


def _last_message_number(history: _History, sequence_path: Path) -> int:
    saved_number = _read_history_json(sequence_path, 0)
    if type(saved_number) is not int or saved_number < 0:
        raise ValueError("Invalid message sequence")
    return max(saved_number, history.high_water)


def load_thread_messages(ws_id: str, thread_id: str) -> list[dict]:
    with _message_transaction():
        return deepcopy(_load_history().by_thread.get((ws_id, thread_id), []))


def append_chat_message(message: dict) -> dict:
    with _message_transaction():
        history = _load_history()
        sequence_path = config.MESSAGES_PATH.with_suffix(".sequence.json")
        number = _last_message_number(history, sequence_path) + 1
        # Reserve the ID before publishing the message. A failed append can leave a gap.
        _write_history_json(sequence_path, number)
        message = deepcopy({**message, "id": f"msg-{number:03d}"})
        _write_history_json(config.MESSAGES_PATH, [*history.messages, message])
        history.messages.append(message)
        history.index(message)
        _remember_history(history)
        return deepcopy(message)


def clear_messages(ws_id: str, thread_id: str | None = None) -> None:
    with _message_transaction():
        history = _load_history()
        messages = history.messages
        kept = [msg for msg in messages if not _matches_history(msg, ws_id, thread_id)]
        if len(kept) == len(messages):
            return
        sequence_path = config.MESSAGES_PATH.with_suffix(".sequence.json")
        # Keep the high-water mark even when clearing legacy history before its first append.
        _write_history_json(sequence_path, _last_message_number(history, sequence_path))
        _write_history_json(config.MESSAGES_PATH, kept)
        _remember_history(_History(kept))


def set_thread_summary(thread_id: str, summary: str, compacted_count: int, *, ws_id: str | None = None) -> dict | None:
    data = load_threads_data()
    for t in data["items"]:
        if t["id"] == thread_id and (ws_id is None or t.get("workspace_id") == ws_id):
            t["summary"] = summary.strip()
            t["compacted_count"] = compacted_count
            t["compacted_at"] = config.now_iso()
            t["updated_at"] = config.now_iso()
            save_threads_data(data)
            return t
    return None


def get_thread_by_id(thread_id: str, *, ws_id: str | None = None) -> dict | None:
    data = load_threads_data()
    return next(
        (t for t in data["items"] if t["id"] == thread_id and (ws_id is None or t.get("workspace_id") == ws_id)),
        None,
    )
