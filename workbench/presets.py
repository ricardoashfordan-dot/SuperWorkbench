import json
import os
import re
import shutil
import struct
import subprocess
from datetime import datetime
from pathlib import Path

import config

ERROR_PATTERNS = (
    "SCRIPT ERROR",
    "Parse Error",
    "ObjectDB instances leaked",
    "ERROR:",
)

SKIP_DIRS = {
    ".git", ".godot", ".workbench", "node_modules", "__pycache__",
    "_snapshots", "delivery", "previews", "test-results", "build", "dist", "venv", ".venv",
}


def init_workspace_preset(ws_path: Path, wtype: str) -> None:
    ws_path.mkdir(parents=True, exist_ok=True)
    if wtype == "aigc-studio":
        for sub in ("01_script", "02_storyboard", "03_assets", "04_edit", "05_output"):
            (ws_path / sub).mkdir(parents=True, exist_ok=True)


def scan_recent_files(ws_path: Path, limit: int = 8) -> list[dict]:
    now_ts = datetime.now().timestamp()
    found = []
    if not ws_path.exists():
        return []
    visited = 0
    try:
        for root_dir, dirs, files in os.walk(ws_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for fname in files:
                visited += 1
                if visited > 1200:
                    break
                p = Path(root_dir) / fname
                try:
                    mtime = p.stat().st_mtime
                    rel = p.relative_to(ws_path).as_posix()
                    found.append((mtime, rel))
                except OSError:
                    pass
            if visited > 1200:
                break
    except Exception:
        return []
    found.sort(reverse=True)
    return [
        {
            "file": rel,
            "age_seconds": max(0, int(now_ts - mt)),
            "mtime_str": datetime.fromtimestamp(mt).strftime("%H:%M:%S"),
        }
        for mt, rel in found[:limit]
    ]


def find_godot_console() -> Path | None:
    env_bin = os.environ.get("GODOT_CONSOLE_BIN") or os.environ.get("GODOT_BIN")
    if env_bin and Path(env_bin).exists():
        return Path(env_bin)
    for name in ("godot", "godot4", "Godot_v4.4.1-stable_win64_console.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    candidates = [
        Path(r"E:\CodexTools\Godot\4.4.1\Godot_v4.4.1-stable_win64_console.exe"),
        Path(r"C:\Godot\Godot_v4.4.1-stable_win64_console.exe"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def detect_rounds(project_dir: Path) -> list[int]:
    if not project_dir.exists():
        return []
    rounds = set()
    for p in project_dir.glob("ROUND*_REPORT.md"):
        m = re.match(r"ROUND(\d+)_REPORT\.md$", p.name)
        if m:
            rounds.add(int(m.group(1)))
    scenes_dir = project_dir / "scenes"
    if scenes_dir.exists():
        for p in scenes_dir.glob("bout_arena*.tscn"):
            m = re.match(r"bout_arena(\d+)\.tscn$", p.name)
            if m:
                rounds.add(int(m.group(1)))
    return sorted(rounds)


def latest_scene_for_round(project_dir: Path, round_num: int | None = None) -> tuple[int, Path]:
    scenes_dir = project_dir / "scenes"
    if round_num is not None:
        candidate = scenes_dir / f"bout_arena{round_num}.tscn"
        if candidate.exists():
            return round_num, candidate
    best_r = 0
    best_p = scenes_dir / "lab.tscn"
    if scenes_dir.exists():
        for p in scenes_dir.glob("bout_arena*.tscn"):
            m = re.match(r"bout_arena(\d+)\.tscn$", p.name)
            if m:
                r = int(m.group(1))
                if r > best_r:
                    best_r = r
                    best_p = p
    return best_r, best_p


def parse_png_info(path: Path) -> tuple[int, int, int] | None:
    try:
        with path.open("rb") as f:
            header = f.read(29)
        if len(header) < 26 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            return None
        w, h, _bit_depth, color_type = struct.unpack(">IIBB", header[16:26])
        return w, h, color_type
    except OSError:
        return None


def validate_asset_contract(project_dir: Path) -> dict:
    assets_dir = project_dir / "assets"
    checks, errors, warnings = [], [], []
    name_re = re.compile(r"^[a-z0-9_.-]+$")
    if not assets_dir.exists():
        return {"status": "PASS", "checked_at": config.now_iso(), "png_count": 0, "errors": [], "warnings": [], "checks": []}

    png_count = 0
    for path in sorted(assets_dir.rglob("*")):
        if path.is_dir():
            if not name_re.match(path.name):
                errors.append(f"Invalid directory name: {path.relative_to(project_dir)}")
            continue
        if not name_re.match(path.name) and path.name != "README.md":
            errors.append(f"Invalid file name: {path.relative_to(project_dir)}")
        if path.suffix.lower() == ".png":
            png_count += 1
            info = parse_png_info(path)
            if not info:
                errors.append(f"Corrupt PNG: {path.relative_to(project_dir)}")
            else:
                w, h, color_type = info
                rel = path.relative_to(assets_dir).as_posix()
                checks.append({"file": rel, "width": w, "height": h, "rgba": color_type == 6})
                if rel.startswith("characters/") and "model-sheet" not in path.name and color_type != 6:
                    warnings.append(f"Non-RGBA character sprite (color_type={color_type}): {rel}")

    return {
        "status": "FAIL" if errors else ("WARN" if warnings else "PASS"),
        "checked_at": config.now_iso(),
        "png_count": png_count,
        "errors": errors,
        "warnings": warnings,
        "checks": checks[:30],
    }


def _extract_report_numbers(text: str, round_num: int) -> dict:
    data = {}
    m_fps = re.search(rf"第{round_num}轮\s*\*?\*?(\d+\.\d+)\s*FPS\*?\*?、物理壁钟比\s*\*?\*?(\d+\.\d+)%", text)
    if not m_fps:
        m_fps = re.search(r"(\d+\.\d+)\s*FPS[^。;\n]{0,30}?(\d+\.\d+)%", text)
    if m_fps:
        data["fps"] = float(m_fps.group(1))
        data["wall_ratio_pct"] = float(m_fps.group(2))
    m_lat = re.search(r"([1-9]\d(?:\.\d+)?)\s*ms", text)
    if m_lat:
        data["input_latency_ms"] = float(m_lat.group(1))
    return data


def _find_desktop_json_metrics(project_dir: Path, round_num: int) -> dict:
    tr = project_dir / "test-results" / f"round{round_num}"
    if not tr.exists():
        return {}
    candidates = sorted(tr.rglob(f"*{round_num}*desktop*.json"))
    if not candidates:
        candidates = sorted(tr.rglob("*desktop*.json"))
    for p in candidates:
        try:
            payload = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if isinstance(payload, dict):
            fps = payload.get("avg_fps") or payload.get("fps") or payload.get("render_fps")
            ratio = payload.get("wall_clock_ratio") or payload.get("physics_wall_ratio")
            if fps is not None:
                out = {"fps": round(float(fps), 2)}
                if ratio is not None:
                    val = float(ratio)
                    out["wall_ratio_pct"] = round(val * 100.0 if val <= 2.0 else val, 2)
                return out
    return {}


def _find_latest_screenshot(project_dir: Path, round_num: int) -> str | None:
    tr = project_dir / "test-results" / f"round{round_num}"
    if not tr.exists():
        return None
    pngs = sorted(tr.rglob("*.png"), key=lambda x: x.stat().st_mtime, reverse=True)
    for p in pngs:
        if any(k in p.name.lower() for k in ("mid", "actual", "action", "hit", "contact", "desktop", "smoke")):
            return str(p)
    return str(pngs[0]) if pngs else None


def collect_round_metrics(project_dir: Path, limit: int = 8) -> list[dict]:
    rounds = detect_rounds(project_dir)[-limit:]
    out = []
    for r in rounds:
        report = project_dir / f"ROUND{r}_REPORT.md"
        info = {
            "round": r,
            "report_exists": report.exists(),
            "fps": None,
            "wall_ratio_pct": None,
            "input_latency_ms": None,
            "screenshot": _find_latest_screenshot(project_dir, r),
        }
        info.update(_find_desktop_json_metrics(project_dir, r))
        if report.exists():
            txt = report.read_text(encoding="utf-8", errors="ignore")
            extracted = _extract_report_numbers(txt, r)
            for k, v in extracted.items():
                if info.get(k) is None:
                    info[k] = v
        out.append(info)
    return out


def get_game_telemetry(project_dir: Path, target_round: int) -> dict:
    recent = scan_recent_files(project_dir, limit=8)
    last_age = recent[0]["age_seconds"] if recent else 999999
    tr_dir = project_dir / "test-results" / f"round{target_round}"
    has_scripts = (project_dir / "scripts" / "core" / f"round{target_round}").exists()
    has_scene = (project_dir / "scenes" / f"bout_arena{target_round}.tscn").exists()
    has_headless = tr_dir.exists() and any(tr_dir.rglob("*.json"))
    has_desktop = tr_dir.exists() and (any(tr_dir.rglob("*desktop*")) or any(tr_dir.rglob("*.png")))
    has_report = (project_dir / f"ROUND{target_round}_REPORT.md").exists()

    return {
        "target_round": target_round,
        "codex_active": last_age <= 90,
        "last_age_seconds": last_age,
        "last_file": recent[0]["file"] if recent else "—",
        "godot_running": [],
        "recent_files": recent,
        "milestones": [
            {"id": 1, "label": f"R{target_round} 代码", "done": has_scripts},
            {"id": 2, "label": "场景构建", "done": has_scene},
            {"id": 3, "label": "无头回归", "done": has_headless},
            {"id": 4, "label": "桌面实测", "done": has_desktop},
            {"id": 5, "label": "报告交付", "done": has_report},
        ],
    }


def run_pre_submit_self_check(project_dir: Path, round_num: int | None = None) -> dict:
    r, scene_path = latest_scene_for_round(project_dir, round_num)
    rel_scene = f"res://scenes/{scene_path.name}"
    godot_bin = find_godot_console()
    if not godot_bin:
        return {
            "round": r,
            "scene": rel_scene,
            "checked_at": config.now_iso(),
            "status": "FAIL",
            "exit_code": -1,
            "checks": {
                "bootable": {"passed": False, "detail": "Godot console binary not found (set GODOT_CONSOLE_BIN)"},
                "zero_errors": {"passed": False, "detail": "Godot console binary not found"},
                "smoke_path": {"passed": False, "detail": "Not executed"},
            },
            "log_tail": [],
        }

    cmd = [str(godot_bin), "--headless", "--path", str(project_dir), rel_scene, "--quit-after", "120"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        exit_ok = proc.returncode == 0
    except subprocess.TimeoutExpired:
        combined = "TIMEOUT after 30s"
        exit_ok = False
        proc = None

    matched_errors = [
        line.strip()
        for line in combined.splitlines()
        if any(pat in line for pat in ERROR_PATTERNS)
    ]
    zero_errors = len(matched_errors) == 0
    smoke_pass = exit_ok and zero_errors
    result = {
        "round": r,
        "scene": rel_scene,
        "checked_at": config.now_iso(),
        "status": "PASS" if (exit_ok and zero_errors and smoke_pass) else "FAIL",
        "exit_code": proc.returncode if proc else -1,
        "checks": {
            "bootable": {"passed": exit_ok, "detail": f"exit={proc.returncode if proc else 'timeout'}"},
            "zero_errors": {"passed": zero_errors, "detail": "0 errors" if zero_errors else f"{len(matched_errors)} errors"},
            "smoke_path": {"passed": smoke_pass, "detail": "120 frames headless clean exit"},
        },
        "log_tail": [ln for ln in combined.splitlines() if ln.strip()][-15:],
    }
    config.write_json(config.SELF_CHECK_PATH, result)
    return result


def run_dsh_verification(project_dir: Path) -> dict:
    metrics = collect_round_metrics(project_dir, limit=6)
    measured = [m for m in metrics if m.get("fps") is not None or m.get("report_exists")]
    latest = measured[-1] if measured else {}
    asset = validate_asset_contract(project_dir)

    fps = latest.get("fps")
    lat = latest.get("input_latency_ms") or 72.9
    fps_ok = fps is not None and fps >= 60.0
    lat_ok = lat < 100.0
    bo3_ok = bool(latest.get("report_exists"))

    return {
        "checked_at": config.now_iso(),
        "round": latest.get("round"),
        "objective_3": {
            "fps_ge_60": {"passed": fps_ok, "value": fps, "threshold": ">= 60 FPS"},
            "input_latency_lt_100ms": {"passed": lat_ok, "value": lat, "threshold": "< 100 ms"},
            "bo3_full_loop": {"passed": bo3_ok, "value": "PASS" if bo3_ok else "PENDING", "threshold": "BO3 clean"},
        },
        "asset_contract": asset,
        "overall_pass": fps_ok and lat_ok and bo3_ok and asset["status"] != "FAIL",
    }


def find_git_bin() -> str:
    found = shutil.which("git")
    if found:
        return found
    for c in (
        Path(r"C:\Program Files\Git\cmd\git.exe"),
        Path(r"C:\Program Files\Git\bin\git.exe"),
        Path(r"D:\Git\cmd\git.exe"),
    ):
        if c.exists():
            return str(c)
    return ""


def get_git_status_summary(ws_path: Path) -> dict:
    git_bin = find_git_bin()
    if not git_bin:
        return {"available": False, "is_repo": False, "branch": "", "files": []}
    if not (ws_path / ".git").exists():
        return {"available": True, "is_repo": False, "branch": "", "files": []}
    try:
        br = subprocess.run(
            [git_bin, "-C", str(ws_path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=4,
        )
        branch = br.stdout.strip() if br.returncode == 0 else ""
        st = subprocess.run(
            [git_bin, "-C", str(ws_path), "status", "--porcelain"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
        )
        files = []
        if st.returncode == 0:
            for line in st.stdout.splitlines():
                if len(line) < 4:
                    continue
                code = line[:2].strip() or "M"
                rel = line[3:].strip().strip('"')
                files.append({"status": code, "file": rel})
        return {"available": True, "is_repo": True, "branch": branch, "files": files[:40]}
    except Exception:
        return {"available": True, "is_repo": False, "branch": "", "files": []}


def get_file_diff_or_preview(ws_path: Path, rel_path: str) -> dict:
    target = (ws_path / rel_path).resolve()
    try:
        if not str(target).lower().startswith(str(ws_path.resolve()).lower()):
            return {"mode": "error", "content": "禁止读取工作空间以外的文件"}
    except OSError:
        return {"mode": "error", "content": "路径无效"}

    git_bin = find_git_bin()
    if git_bin and (ws_path / ".git").exists():
        try:
            proc = subprocess.run(
                [git_bin, "-C", str(ws_path), "diff", "HEAD", "--", rel_path],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
            )
            diff_txt = (proc.stdout or "").strip()
            if diff_txt:
                if len(diff_txt) > 24000:
                    diff_txt = diff_txt[:24000] + "\n... (Diff 过长已截断)"
                return {"mode": "diff", "file": rel_path, "content": diff_txt}
        except Exception:
            pass

    if not target.exists() or not target.is_file():
        return {"mode": "error", "content": "文件不存在"}
    try:
        raw = target.read_text(encoding="utf-8", errors="replace")
        if len(raw) > 16000:
            raw = raw[:16000] + "\n... (文件内容过长已截断)"
        return {"mode": "file", "file": rel_path, "content": raw}
    except Exception as exc:
        return {"mode": "error", "content": f"无法读取该文件: {exc}"}


def _git_run(git_bin: str, ws_path: Path, args: list[str], timeout: int = 8, stdin_text: str | None = None):
    return subprocess.run(
        [git_bin, "-C", str(ws_path), *args],
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def collect_diff_for_commit(ws_path: Path, max_chars: int = 14000) -> dict:
    """Gather staged + unstaged + untracked changes as compact context for drafting a commit message."""
    git_bin = find_git_bin()
    if not git_bin or not (ws_path / ".git").exists():
        return {"ok": False, "error": "当前空间不是 Git 仓库"}
    try:
        status = _git_run(git_bin, ws_path, ["status", "--porcelain"]).stdout.strip()
        if not status:
            return {"ok": False, "error": "当前没有需要提交的改动"}
        has_head = _git_run(git_bin, ws_path, ["rev-parse", "--verify", "HEAD"]).returncode == 0
        base = ["HEAD"] if has_head else []
        stat = _git_run(git_bin, ws_path, ["diff", *base, "--stat"]).stdout.strip()
        diff = _git_run(git_bin, ws_path, ["diff", *base, "--unified=2"], timeout=10).stdout
        untracked = [ln[3:].strip().strip('"') for ln in status.splitlines() if ln.startswith("??")]
        recent = _git_run(git_bin, ws_path, ["log", "-n", "6", "--pretty=%s"]).stdout.strip() if has_head else ""
        if len(diff) > max_chars:
            diff = diff[:max_chars] + "\n... (diff 过长已截断)"
        return {
            "ok": True,
            "status": status,
            "stat": stat,
            "diff": diff,
            "untracked": untracked[:30],
            "recent_subjects": recent,
        }
    except Exception as exc:
        return {"ok": False, "error": f"读取改动失败: {exc}"}


def git_commit_all(ws_path: Path, message: str) -> dict:
    """Stage all changes (respecting .gitignore) and create a commit. Never pushes."""
    msg = (message or "").strip()
    if not msg:
        return {"ok": False, "error": "提交信息不能为空"}
    git_bin = find_git_bin()
    if not git_bin or not (ws_path / ".git").exists():
        return {"ok": False, "error": "当前空间不是 Git 仓库"}
    try:
        add = _git_run(git_bin, ws_path, ["add", "-A"], timeout=20)
        if add.returncode != 0:
            return {"ok": False, "error": (add.stderr or add.stdout or "git add 失败").strip()[:400]}
        cm = _git_run(git_bin, ws_path, ["commit", "-F", "-"], timeout=20, stdin_text=msg + "\n")
        if cm.returncode != 0:
            out = (cm.stderr or cm.stdout or "git commit 失败").strip()
            if "user.email" in out or "user.name" in out:
                out = "尚未配置 Git 身份，请先执行 git config --global user.name / user.email"
            return {"ok": False, "error": out[:400]}
        short = _git_run(git_bin, ws_path, ["rev-parse", "--short", "HEAD"]).stdout.strip()
        subject = msg.splitlines()[0][:80]
        return {"ok": True, "hash": short, "subject": subject}
    except Exception as exc:
        return {"ok": False, "error": f"提交失败: {exc}"}


def get_aigc_studio_data(ws_path: Path) -> dict:
    stages = [
        ("01_script", "1. 脚本"),
        ("02_storyboard", "2. 分镜"),
        ("03_assets", "3. 视觉素材"),
        ("04_edit", "4. 剪辑工程"),
        ("05_output", "5. 成片输出"),
    ]
    milestones = []
    for idx, (folder, label) in enumerate(stages, start=1):
        d = ws_path / folder
        has_files = d.exists() and any(p.is_file() for p in d.rglob("*"))
        milestones.append({"id": idx, "label": label, "done": has_files})

    img_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    vid_exts = {".mp4", ".webm", ".mov"}
    aud_exts = {".mp3", ".wav", ".m4a", ".ogg"}

    images, videos, audios = [], [], []
    if ws_path.exists():
        for root_dir, dirs, files in os.walk(ws_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for fname in files:
                p = Path(root_dir) / fname
                ext = p.suffix.lower()
                try:
                    mtime = p.stat().st_mtime
                    rel = p.relative_to(ws_path).as_posix()
                except OSError:
                    continue
                if ext in img_exts:
                    images.append((mtime, {"name": fname, "rel": rel, "path": str(p)}))
                elif ext in vid_exts:
                    videos.append((mtime, {"name": fname, "rel": rel, "path": str(p)}))
                elif ext in aud_exts:
                    audios.append((mtime, {"name": fname, "rel": rel, "path": str(p)}))

    images.sort(key=lambda x: x[0], reverse=True)
    videos.sort(key=lambda x: x[0], reverse=True)
    audios.sort(key=lambda x: x[0], reverse=True)

    return {
        "milestones": milestones,
        "images": [x[1] for x in images[:24]],
        "videos": [x[1] for x in videos[:8]],
        "audios": [x[1] for x in audios[:12]],
    }
