import json
import os
import re
import shlex
import signal
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import adapters
import config
import presets
import skills
import threads

# Map internal slot IDs to legacy UI node IDs so existing messages & mini-rail stay seamless
SLOT_TO_NODE = {"planner": "agy", "builder": "codex", "reviewer": "dsh"}
NODE_TO_SLOT = {"agy": "planner", "codex": "builder", "dsh": "reviewer", "planner": "planner", "builder": "builder", "reviewer": "reviewer"}


def _load_recent_chat_context(ws_id: str, thread_id: str | None = None, limit: int = 6) -> str:
    all_msgs = config.read_json(config.MESSAGES_PATH, [])
    tid = thread_id or threads.ensure_workspace_thread(ws_id)[0]["id"]
    t_obj = threads.get_thread_by_id(tid)
    t_msgs = threads.filter_thread_messages(all_msgs, ws_id, tid)

    parts = []
    if t_obj and t_obj.get("summary"):
        parts.append(f"【本会话已压缩记忆摘要（覆盖前 {t_obj.get('compacted_count', 0)} 条对话）】\n{t_obj['summary']}")

    recent = t_msgs[-limit:]
    if recent:
        role_names = {"xiu": "制作人", "agy": "策划/方案(Planner)", "codex": "核心执行(Builder)", "dsh": "独立质检(Reviewer)"}
        lines = ["【本会话近期原话上下文】"]
        for m in recent:
            sender = role_names.get(m.get("from", ""), m.get("from", ""))
            body = (m.get("body") or "").strip()
            if len(body) > 550:
                body = body[:550] + "..."
            lines.append(f"- {sender}: {body}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _workspace_brief(ws_path: Path) -> str:
    recent = presets.scan_recent_files(ws_path, limit=10)
    if not recent:
        return ""
    lines = ["【工作空间近期变动文件】"]
    for f in recent:
        lines.append(f"- {f['file']} (更新于 {f['mtime_str']})")
    return "\n".join(lines)


class JobManager:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.agent = ""  # Node id: agy / codex / dsh
        self.slot = ""   # Slot id: planner / builder / reviewer
        self.engine_name = ""
        self.mode = "single"
        self.workspace_id = ""
        self.thread_id = ""
        self.title = ""
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.exit_code: int | None = None
        self.logs: list[str] = []
        self.live_reply: str = ""
        self.current_step_desc: str = ""
        self.proc: subprocess.Popen | None = None
        self.abort_requested = False
        self.pending_approval: dict | None = None

    def append_log(self, line: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        with self.lock:
            self.logs.append(f"[{ts}] {line}")
            if len(self.logs) > 350:
                self.logs = self.logs[-350:]

    def status_dict(self) -> dict:
        with self.lock:
            elapsed = 0.0
            if self.started_at:
                end_t = self.finished_at if self.finished_at else time.time()
                elapsed = round(max(0.0, end_t - self.started_at), 1)
            appr = None
            if self.pending_approval:
                appr = {
                    "id": self.pending_approval.get("id", ""),
                    "workspace_id": self.pending_approval.get("workspace_id", ""),
                    "thread_id": self.pending_approval.get("thread_id", ""),
                    "created_at": self.pending_approval.get("created_at", ""),
                }
            return {
                "running": self.running,
                "agent": self.agent,
                "slot": self.slot,
                "engine_name": self.engine_name,
                "mode": self.mode,
                "workspace_id": self.workspace_id,
                "thread_id": self.thread_id,
                "title": self.title,
                "elapsed_seconds": elapsed,
                "exit_code": self.exit_code,
                "current_step_desc": self.current_step_desc,
                "live_reply": self.live_reply,
                "pending_approval": appr,
                "logs": list(self.logs[-140:]),
            }

    def abort(self) -> bool:
        with self.lock:
            self.abort_requested = True
            proc = self.proc
        if proc and proc.poll() is None:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        creationflags=config.NO_WINDOW_FLAGS,
                    )
                else:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            self.append_log("用户已中止当前运行进程。")
            return True
        if self.running:
            self.append_log("已请求中止当前流式任务。")
            return True
        return False

    def _build_cli_command(
        self,
        eng: dict,
        model: str,
        effort: str,
        prompt: str,
        ws_path: str,
        image_paths: list[str] | None = None,
    ) -> tuple[list[str], bool]:
        kind = eng.get("kind", "")
        exe = eng.get("path") or eng.get("id")
        use_model = model or eng.get("default_model", "")

        if kind == "cli-agy":
            cmd = [exe, "--mode", "plan", "--output-format", "stream-json"]
            if use_model:
                cmd += ["--model", use_model]
            cmd += ["-p", prompt]
            return cmd, False

        if kind == "cli-codex":
            cmd = [exe, "exec", "--json"]
            if use_model:
                cmd += ["-m", use_model]
            if effort:
                cmd += ["-c", f'model_reasoning_effort="{effort}"']
            for img in (image_paths or [])[:4]:
                if Path(img).exists():
                    cmd += ["-i", img]
            cmd += ["-C", ws_path, "--add-dir", str(config.DATA_DIR), "--approve-for-me", "--skip-git-repo-check", "-"]
            return cmd, True

        if kind == "cli-claude":
            cmd = [exe, "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits"]
            if use_model:
                cmd += ["--model", use_model]
            return cmd, True

        if kind == "cli-gemini":
            cmd = [exe, "--output-format", "stream-json"]
            if use_model:
                cmd += ["-m", use_model]
            cmd += ["-p", prompt]
            return cmd, False

        if kind == "cli-dsh":
            one_line = " ".join(prompt.splitlines())
            if str(exe).lower().endswith(".ps1"):
                return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", exe, "--profile", "headless", one_line], False
            return [exe, "--profile", "headless", one_line], False

        if kind == "custom-cli":
            tpl = eng.get("command_template", "")
            one_line = " ".join(prompt.splitlines())
            filled = tpl.replace("{cwd}", ws_path).replace("{prompt}", one_line)
            return shlex.split(filled, posix=(os.name != "nt")), False

        raise ValueError(f"Unsupported CLI engine kind: {kind}")

    def _parse_stream_line(self, kind: str, line: str) -> None:
        s = line.strip()
        if not s:
            return
        if s.startswith("{") and s.endswith("}"):
            try:
                obj = json.loads(s)
            except ValueError:
                self.append_log(s)
                return

            if kind == "cli-agy":
                ev = obj.get("event")
                if ev == "init":
                    cid = obj.get("conversation_id", "")
                    with self.lock:
                        self.current_step_desc = "AGY 已建立会话，正在思考分析..."
                    self.append_log(f"AGY 会话已建立 ({cid[:8]})")
                elif ev == "step_update":
                    su = obj.get("step_update") or {}
                    delta = su.get("text_delta", "")
                    if delta:
                        with self.lock:
                            self.live_reply += delta
                            self.current_step_desc = "AGY 正在实时输出回复..."
                    elif su.get("step_type") and su.get("step_type") != "user_input":
                        with self.lock:
                            self.current_step_desc = f"AGY 步骤: {su.get('step_type')}"
                elif ev == "result":
                    res = obj.get("result") or {}
                    resp = (res.get("response") or "").strip()
                    if resp:
                        with self.lock:
                            self.live_reply = resp
                            self.current_step_desc = "AGY 回复生成完毕"
                    if res.get("duration_seconds"):
                        self.append_log(f"AGY 完成 (耗时 {res['duration_seconds']:.1f}s)")
                return

            if kind == "cli-codex":
                ev_type = obj.get("type", "")
                if ev_type == "thread.started":
                    with self.lock:
                        self.current_step_desc = "Codex 已启动执行线程..."
                    self.append_log(f"Codex 线程已建立 ({obj.get('thread_id', '')[:8]})")
                elif ev_type in ("item.started", "item.updated", "item.completed"):
                    item = obj.get("item") or {}
                    itype = item.get("type", "")
                    if itype == "agent_message" and ev_type == "item.completed":
                        txt = (item.get("text") or "").strip()
                        if txt:
                            with self.lock:
                                self.live_reply = (self.live_reply + "\n\n" + txt) if self.live_reply else txt
                                self.current_step_desc = "Codex 输出阶段汇报"
                            self.append_log(f"Codex: {txt[:120]}")
                    elif itype == "reasoning" and ev_type == "item.completed":
                        txt = (item.get("text") or "").strip()
                        if txt:
                            with self.lock:
                                self.current_step_desc = f"思考: {txt[:60]}..."
                            self.append_log(f"思考: {txt[:140]}")
                    elif itype == "command_execution":
                        cmd_str = item.get("command") or ""
                        if ev_type == "item.started":
                            with self.lock:
                                self.current_step_desc = f"执行命令: {cmd_str[:55]}"
                            self.append_log(f"执行命令: {cmd_str}")
                        elif ev_type == "item.completed":
                            self.append_log(f"命令完成 (exit={item.get('exit_code')})")
                    elif itype == "file_change" and ev_type == "item.completed":
                        changes = item.get("changes") or []
                        paths = [c.get("path", "") for c in changes if isinstance(c, dict)]
                        p_str = ", ".join(paths) if paths else "文件修改"
                        with self.lock:
                            self.current_step_desc = f"已修改文件: {p_str[:60]}"
                        self.append_log(f"修改文件: {p_str}")
                elif ev_type == "turn.completed":
                    self.append_log("Codex 当前执行回合完成")
                elif ev_type == "error":
                    self.append_log(f"Codex 错误: {obj.get('message') or obj}")
                return

            if kind in ("cli-claude", "cli-gemini"):
                # Generic stream-json parser for Claude Code / Gemini CLI
                if obj.get("type") == "assistant":
                    msg = obj.get("message") or {}
                    for blk in msg.get("content") or []:
                        if isinstance(blk, dict) and blk.get("type") == "text":
                            txt = blk.get("text", "")
                            if txt:
                                with self.lock:
                                    self.live_reply = (self.live_reply + "\n" + txt).strip()
                                    self.current_step_desc = "正在输出回复..."
                elif obj.get("type") == "result" and obj.get("result"):
                    with self.lock:
                        self.live_reply = str(obj["result"]).strip()
                        self.current_step_desc = "执行完成"
                elif obj.get("response"):
                    with self.lock:
                        self.live_reply = str(obj["response"]).strip()
                elif obj.get("delta") or obj.get("text"):
                    with self.lock:
                        self.live_reply += str(obj.get("delta") or obj.get("text"))
                return

        self.append_log(s)
        if kind in ("cli-dsh", "custom-cli") and not s.startswith("warning:"):
            with self.lock:
                self.live_reply += s + "\n"
                self.current_step_desc = "正在输出回复..."

    def _run_slot_blocking(
        self,
        slot: str,
        prompt: str,
        system_prompt: str,
        ws_path: str,
        image_paths: list[str] | None = None,
    ) -> tuple[int, str]:
        roles = adapters.load_role_bindings()
        role_cfg = roles.get(slot) or roles["planner"]
        eng_id = role_cfg.get("engine", "agy")
        eng = adapters.get_engine_by_id(eng_id, mask_secrets=False)
        if not eng:
            msg = f"未找到槽位 {slot} 绑定的引擎 `{eng_id}`，请在左下角「模型与角色配置」重新选择。"
            self.append_log(msg)
            return 1, msg

        model = role_cfg.get("model") or eng.get("default_model", "")
        effort = role_cfg.get("effort", "high")
        kind = eng.get("kind", "")

        with self.lock:
            self.slot = slot
            self.agent = SLOT_TO_NODE.get(slot, "agy")
            self.engine_name = f"{eng['name']} ({model})" if model else eng["name"]
            self.live_reply = ""
            self.current_step_desc = f"正在唤醒 {eng['name']} ({model})..."

        # Path A: OpenAI-compatible HTTP SSE API (Ollama / DeepSeek / OpenRouter / etc.)
        if kind == "openai-compat":
            self.append_log(f"连接 OpenAI 兼容 API: {eng['name']} [{model}] @ {eng.get('base_url')}")
            reasoning_len = [0]

            def on_delta(chunk: str) -> None:
                with self.lock:
                    self.live_reply += chunk
                    self.current_step_desc = f"{eng['name']} 正在实时流式输出..."

            def on_reasoning(r_chunk: str) -> None:
                reasoning_len[0] += len(r_chunk)
                with self.lock:
                    self.current_step_desc = f"{eng['name']} 深度思考中 ({reasoning_len[0]} 字)..."

            rc, reply = adapters.stream_openai_compat(
                base_url=eng.get("base_url", ""),
                api_key=eng.get("api_key", ""),
                model=model,
                system_prompt=system_prompt,
                user_prompt=prompt,
                on_delta=on_delta,
                on_reasoning=on_reasoning,
                is_aborted=lambda: self.abort_requested,
                image_paths=image_paths,
            )
            if slot == "planner" and rc == 0 and reply:
                config.NEXT_FOR_CODEX_PATH.write_text(reply + "\n", encoding="utf-8")
                self.append_log("已同步方案至 .workbench/NEXT_FOR_CODEX.md")
            self.append_log(f"{eng['name']} 请求结束，退出码={rc}")
            return rc, reply

        # Path B: Local CLI Engine
        if not eng.get("ready") and kind != "custom-cli":
            msg = f"引擎 `{eng['name']}` 未在本机检测到可用 CLI，请在左下角「模型与角色配置」中切换为其他已安装 CLI 或接入 API。"
            self.append_log(msg)
            return 1, msg

        cmd, use_stdin = self._build_cli_command(eng, model, effort, prompt, ws_path, image_paths=image_paths)
        self.append_log(f"启动 {eng['name']} [{model}] (工作目录: {ws_path})")
        raw_tail = []
        popen_kwargs = {
            "cwd": ws_path if Path(ws_path).exists() else str(config.REPO_ROOT),
            "stdin": subprocess.PIPE if use_stdin else subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = config.NO_WINDOW_FLAGS
        else:
            popen_kwargs["start_new_session"] = True
        try:
            proc = subprocess.Popen(cmd, **popen_kwargs)
            with self.lock:
                self.proc = proc
            if use_stdin and proc.stdin:
                try:
                    proc.stdin.write(prompt)
                    proc.stdin.close()
                except Exception:
                    pass
            if proc.stdout:
                for raw in proc.stdout:
                    s = raw.rstrip("\r\n")
                    if s.strip():
                        raw_tail.append(s.strip())
                        if len(raw_tail) > 15:
                            raw_tail.pop(0)
                        self._parse_stream_line(kind, s)
            rc = proc.wait()
            with self.lock:
                self.proc = None
                final_reply = self.live_reply.strip()

            if slot == "planner" and rc == 0 and final_reply:
                config.NEXT_FOR_CODEX_PATH.write_text(final_reply + "\n", encoding="utf-8")
                self.append_log("已同步方案至 .workbench/NEXT_FOR_CODEX.md")

            self.append_log(f"{eng['name']} 执行结束，退出码={rc}")
            if not final_reply:
                final_reply = "\n".join(raw_tail[-8:])
            return rc, final_reply
        except Exception as exc:
            self.append_log(f"启动失败: {exc}")
            return 1, str(exc)

    def start_job(
        self,
        target: str,
        instruction: str,
        pipeline: bool,
        workspace: dict,
        on_event,
        skill_ids: list[str] | None = None,
        thread_id: str | None = None,
        attachments: list[dict] | None = None,
    ) -> tuple[bool, str]:
        slot = NODE_TO_SLOT.get(target, "planner")
        ws_id = workspace.get("id", "")
        tid = thread_id or threads.ensure_workspace_thread(ws_id)[0]["id"]
        with self.lock:
            if self.running:
                return False, f"当前已有任务正在运行（{self.engine_name or self.agent}），请等待完成或点击中止"
            self.running = True
            self.abort_requested = False
            self.pending_approval = None
            self.slot = slot
            self.agent = SLOT_TO_NODE.get(slot, "agy")
            self.engine_name = ""
            self.mode = "pipeline" if pipeline else "single"
            self.workspace_id = ws_id
            self.thread_id = tid
            self.title = instruction[:60]
            self.started_at = time.time()
            self.finished_at = None
            self.exit_code = None
            self.logs = []
            self.live_reply = ""
            self.current_step_desc = "正在初始化..."

        threads.auto_title_if_generic(tid, instruction)

        t = threading.Thread(
            target=self._worker,
            args=(slot, instruction, pipeline, workspace, on_event, skill_ids or [], tid, attachments or []),
            daemon=True,
        )
        t.start()
        return True, "started"

    def compact_thread(self, ws_id: str, thread_id: str, workspace: dict, on_done) -> tuple[bool, str]:
        with self.lock:
            if self.running:
                return False, "当前有任务正在运行，请等待结束后再压缩上下文"
            self.running = True
            self.abort_requested = False
            self.slot = "planner"
            self.agent = "agy"
            self.engine_name = "Context Compactor"
            self.mode = "compact"
            self.workspace_id = ws_id
            self.thread_id = thread_id
            self.title = "压缩会话上下文"
            self.started_at = time.time()
            self.finished_at = None
            self.exit_code = None
            self.logs = []
            self.live_reply = ""
            self.current_step_desc = "正在压缩历史对话为长期记忆摘要..."

        def _do_compact() -> None:
            ws_path = workspace.get("path", str(config.REPO_ROOT))
            try:
                all_msgs = config.read_json(config.MESSAGES_PATH, [])
                t_msgs = threads.filter_thread_messages(all_msgs, ws_id, thread_id)
                t_obj = threads.get_thread_by_id(thread_id)
                prev_sum = (t_obj or {}).get("summary", "")

                if not t_msgs:
                    self.append_log("当前对话暂无消息，无需压缩。")
                    return

                lines = []
                if prev_sum:
                    lines.append(f"[已有历史摘要]\n{prev_sum}\n")
                for m in t_msgs[-30:]:
                    who = m.get("from", "")
                    body = (m.get("body") or "").strip()
                    if len(body) > 700:
                        body = body[:700] + "..."
                    lines.append(f"- {who}: {body}")
                transcript = "\n".join(lines)

                sys_p = "你是对话上下文压缩器。请将对话记录浓缩为一份高密度、结构化的中文工作记忆摘要（不超过 450 字），保留：1.核心目标；2.已敲定的关键决策；3.已改文件/产物；4.待办下一步。"
                user_p = f"请严格压缩以下会话内容（绝对不要调用任何工具，直接输出 Markdown 摘要正文）：\n\n{transcript}"
                rc, summary = self._run_slot_blocking("planner", user_p, sys_p, ws_path)
                if rc != 0 or not summary.strip():
                    bullets = []
                    for m in t_msgs[-10:]:
                        b = " ".join((m.get("body") or "").splitlines())[:120]
                        if b:
                            bullets.append(f"- **{m.get('from', '')}**: {b}")
                    summary = "### 自动提炼记忆摘要\n" + "\n".join(bullets)
                threads.set_thread_summary(thread_id, summary, len(t_msgs))
                with self.lock:
                    self.exit_code = 0
                on_done(ws_id, thread_id, summary, len(t_msgs))
            finally:
                with self.lock:
                    self.running = False
                    self.finished_at = time.time()
                    self.proc = None
                    self.current_step_desc = ""

        threading.Thread(target=_do_compact, daemon=True).start()
        return True, "compacting"

    def _format_attachments(self, attachments: list[dict] | None) -> tuple[str, list[str]]:
        if not attachments:
            return "", []
        text_exts = {".txt", ".md", ".py", ".gd", ".json", ".yaml", ".yml", ".toml", ".csv", ".js", ".ts", ".html", ".css", ".sh", ".cmd", ".ps1", ".log", ".xml", ".sql"}
        lines = ["【用户附带的本地附件 / 图片】"]
        img_paths = []
        for att in attachments[:6]:
            p = Path(str(att.get("path", "")))
            name = att.get("name") or p.name
            is_img = bool(att.get("is_image"))
            if not p.exists():
                continue
            if is_img:
                img_paths.append(str(p))
                lines.append(f"- [图片] {name} (本地路径: {p})")
            else:
                lines.append(f"- [文件] {name} (本地路径: {p})")
                if p.suffix.lower() in text_exts:
                    try:
                        txt = p.read_text(encoding="utf-8", errors="replace")
                        if len(txt) > 5000:
                            txt = txt[:5000] + "\n...(内容过长已截断)"
                        lines.append(f"```\n{txt}\n```")
                    except OSError:
                        pass
        return ("\n".join(lines) if len(lines) > 1 else ""), img_paths

    def _build_prompts(
        self,
        slot: str,
        instruction: str,
        workspace: dict,
        skill_ids: list[str] | None = None,
        thread_id: str | None = None,
        attachments: list[dict] | None = None,
    ) -> tuple[str, str, list[str]]:
        ws_path = workspace.get("path", str(config.REPO_ROOT))
        ws_name = workspace.get("name", "")
        ws_id = workspace.get("id", "")
        is_aigc = workspace.get("type") == "aigc-studio"
        chat_ctx = _load_recent_chat_context(ws_id, thread_id)
        ws_brief = _workspace_brief(Path(ws_path))
        skills_block, mounted_names = skills.build_active_skills_prompt(ws_id, Path(ws_path), skill_ids)
        if mounted_names:
            self.append_log(f"已挂载技能规范: {', '.join(mounted_names)}")
        skills_section = f"\n\n{skills_block}\n" if skills_block else ""
        att_block, img_paths = self._format_attachments(attachments)
        if att_block:
            self.append_log(f"已附带 {len(attachments or [])} 个附件/图片")
        att_section = f"\n\n{att_block}\n" if att_block else ""

        if slot == "planner":
            role_title = "AIGC 编剧与分镜导演" if is_aigc else "策划与架构审计官"
            sys_p = f"你是多智能体工作台中的【{role_title}】。请用结构清晰、有深度的中文 Markdown 直接回复设计方案、权衡选项与具体执行清单。"
            user_p = (
                f"工作空间：{ws_name} ({ws_path})\n{ws_brief}\n{chat_ctx}{skills_section}{att_section}\n\n"
                f"用户需求：\n「{instruction}」\n\n"
                f"注意：若处于无头流式模式请勿调用 shell 命令，直接输出高质量 Markdown 方案与建议。"
            )
            return sys_p, user_p, img_paths

        if slot == "builder":
            role_title = "AIGC 制片与剪辑自动化工程师" if is_aigc else "核心工程主程"
            sys_p = f"你是多智能体工作台中的【{role_title}】，负责在本地工作区直接完成实现与验证，并用清晰中文 Markdown 汇报结果。"
            user_p = (
                f"工作空间：{ws_name} ({ws_path})\n{chat_ctx}{skills_section}{att_section}\n\n"
                f"用户指令：\n「{instruction}」\n\n"
                f"请直接在工作区完成实现与必要验证，完成后汇报修改或新增了哪些文件、核心逻辑以及实测结果。"
            )
            return sys_p, user_p, img_paths

        role_title = "AIGC 审片与合规质检官" if is_aigc else "独立测试与代码质检官"
        sys_p = f"你是多智能体工作台中的【{role_title}】，负责基于事实做只读审查、风险诊断与客观核验，用简洁中文 Markdown 输出结论。"
        user_p = (
            f"工作空间：{ws_name} ({ws_path})\n{ws_brief}\n{chat_ctx}{skills_section}{att_section}\n\n"
            f"请针对以下内容进行独立核验与诊断：\n「{instruction}」"
        )
        return sys_p, user_p, img_paths

    def _worker(
        self,
        slot: str,
        instruction: str,
        pipeline: bool,
        workspace: dict,
        on_event,
        skill_ids: list[str] | None = None,
        thread_id: str | None = None,
        attachments: list[dict] | None = None,
    ) -> None:
        ws_path = workspace.get("path", str(config.REPO_ROOT))
        ws_id = workspace.get("id", "")
        is_game = workspace.get("type") == "godot-game"

        def emit(ev, lock_owner, title, body, sender, receiver, att_list=None):
            on_event(
                ev, lock_owner, title, body, sender, receiver,
                workspace_id=ws_id, thread_id=thread_id, attachments=att_list
            )

        try:
            if not pipeline:
                node_id = SLOT_TO_NODE.get(slot, "agy")
                uname = config.load_app_settings().get("user_name", "我")
                emit("lock", node_id, f"{uname} → {slot.upper()}", instruction, "xiu", node_id, att_list=attachments)
                sys_p, user_p, img_paths = self._build_prompts(slot, instruction, workspace, skill_ids, thread_id, attachments)
                rc, full_reply = self._run_slot_blocking(slot, user_p, sys_p, ws_path, image_paths=img_paths)
                with self.lock:
                    self.exit_code = rc
                    eng_label = self.engine_name or slot.upper()
                if not self.abort_requested:
                    emit(
                        "done_single",
                        "xiu",
                        f"{eng_label} ({'完成' if rc == 0 else f'退出码 {rc}'})",
                        full_reply or "执行完毕，请查看终端日志。",
                        node_id,
                        "xiu",
                    )
                return

            # Full Auto-Pipeline: Planner -> (Optional Approval Pause) -> Builder -> Reviewer -> Xiu
            emit("lock", "agy", "自动流转 [1/3]：策划拆解方案", instruction, "xiu", "agy", att_list=attachments)
            sys1, user1, img_paths = self._build_prompts("planner", instruction, workspace, skill_ids, thread_id, attachments)
            rc1, reply1 = self._run_slot_blocking("planner", user1, sys1, ws_path, image_paths=img_paths)
            if self.abort_requested or rc1 != 0:
                with self.lock:
                    self.exit_code = rc1
                emit("error", "xiu", f"策划阶段中止或异常 (code={rc1})", reply1, "agy", "xiu")
                return

            if config.load_app_settings().get("approve_before_build"):
                with self.lock:
                    self.exit_code = 0
                    self.pending_approval = {
                        "id": f"appr-{int(time.time() * 1000)}",
                        "workspace_id": ws_id,
                        "thread_id": thread_id,
                        "workspace": workspace,
                        "instruction": instruction,
                        "plan_body": reply1,
                        "skill_ids": list(skill_ids or []),
                        "attachments": list(attachments or []),
                        "created_at": config.now_iso(),
                    }
                emit("waiting_approval", "xiu", "方案已生成 · 等待确认执行", reply1, "agy", "xiu")
                return

            emit("lock", "codex", "方案已生成并交棒 → 核心执行", reply1, "agy", "codex")
            self._run_pipeline_tail(instruction, reply1, workspace, emit, skill_ids, thread_id, attachments)
        finally:
            with self.lock:
                self.running = False
                self.finished_at = time.time()
                self.proc = None
                self.current_step_desc = ""

    def _run_pipeline_tail(
        self,
        instruction: str,
        plan_body: str,
        workspace: dict,
        emit,
        skill_ids: list[str] | None = None,
        thread_id: str | None = None,
        attachments: list[dict] | None = None,
        extra_note: str = "",
    ) -> None:
        ws_path = workspace.get("path", str(config.REPO_ROOT))
        is_game = workspace.get("type") == "godot-game"

        sys2, _, img_paths2 = self._build_prompts("builder", instruction, workspace, skill_ids, thread_id, attachments)
        att_block2, _ = self._format_attachments(attachments)
        att_s2 = f"\n\n{att_block2}\n" if att_block2 else ""
        note_s = f"\n\n用户审批补充说明：\n{extra_note}\n" if extra_note else ""
        user2 = (
            f"工作空间：{workspace.get('name')} ({ws_path})\n"
            f"用户原始需求：{instruction}{att_s2}\n\n"
            f"策划拆解方案：\n{plan_body}{note_s}\n\n"
            f"请直接在工作区中完成实现与自检验证，完成后用清晰的中文 Markdown 汇报改动文件、核心逻辑与测试结果。"
        )
        rc2, reply2 = self._run_slot_blocking("builder", user2, sys2, ws_path, image_paths=img_paths2)
        if self.abort_requested or rc2 != 0:
            with self.lock:
                self.exit_code = rc2
            emit("error", "xiu", f"执行阶段中止或异常 (code={rc2})", reply2, "codex", "xiu")
            return

        emit("lock", "dsh", "执行完成并交棒 → 独立质检", reply2, "codex", "dsh")

        if is_game:
            with self.lock:
                self.slot = "reviewer"
                self.agent = "dsh"
                self.live_reply = ""
                self.current_step_desc = "正在执行 Godot 门禁与客观指标核验..."
            sc = presets.run_pre_submit_self_check(Path(ws_path))
            dsh_res = presets.run_dsh_verification(Path(ws_path))
            o3 = dsh_res["objective_3"]
            verdict_str = (
                f"### 独立质检与门禁报告\n"
                f"- **提交前自检三条**：`{sc.get('status')}`（场景：`{sc.get('scene')}`）\n"
                f"- **实测帧率**：`{o3['fps_ge_60']['value']} FPS`\n"
                f"- **输入延迟**：`{o3['input_latency_lt_100ms']['value']} ms`\n"
                f"- **资产契约**：`{dsh_res['asset_contract']['status']}`"
            )
            with self.lock:
                self.exit_code = 0 if sc.get("status") == "PASS" else 1
            emit("pipeline_done", "xiu", "质检完成 → 请验收", verdict_str, "dsh", "xiu")
        else:
            sys3, _, _ = self._build_prompts("reviewer", instruction, workspace, skill_ids, thread_id)
            user3 = (
                f"工作空间：{workspace.get('name')} ({ws_path})\n{_workspace_brief(Path(ws_path))}\n\n"
                f"用户需求：{instruction}\n"
                f"执行方汇报：\n{reply2}\n\n"
                f"请对本次实现进行独立审查与风险诊断，给出简洁清晰的验收建议。"
            )
            rc3, reply3 = self._run_slot_blocking("reviewer", user3, sys3, ws_path)
            with self.lock:
                self.exit_code = rc3
            emit("pipeline_done", "xiu", "质检完成 → 请验收", reply3 or "质检完成", "dsh", "xiu")

    def approve_pending(self, note: str, on_event) -> tuple[bool, str]:
        with self.lock:
            if self.running:
                return False, "当前已有任务正在运行"
            if not self.pending_approval:
                return False, "当前没有待审批的执行计划"
            appr = self.pending_approval
            self.pending_approval = None
            self.running = True
            self.abort_requested = False
            self.slot = "builder"
            self.agent = "codex"
            self.engine_name = ""
            self.mode = "pipeline"
            self.workspace_id = appr["workspace_id"]
            self.thread_id = appr["thread_id"]
            self.title = appr["instruction"][:60]
            self.started_at = time.time()
            self.finished_at = None
            self.exit_code = None
            self.logs = []
            self.live_reply = ""
            self.current_step_desc = "已批准，正在交棒执行..."

        def _resume():
            ws = appr["workspace"]
            ws_id = appr["workspace_id"]
            tid = appr["thread_id"]

            def emit(ev, lock_owner, title, body, sender, receiver, att_list=None):
                on_event(
                    ev, lock_owner, title, body, sender, receiver,
                    workspace_id=ws_id, thread_id=tid, attachments=att_list
                )

            try:
                note_txt = note.strip()
                emit("lock", "codex", "已批准方案 → 核心执行", note_txt or "已确认方案，开始落地实现。", "xiu", "codex")
                self._run_pipeline_tail(
                    appr["instruction"],
                    appr["plan_body"],
                    ws,
                    emit,
                    appr.get("skill_ids"),
                    tid,
                    appr.get("attachments"),
                    extra_note=note_txt,
                )
            finally:
                with self.lock:
                    self.running = False
                    self.finished_at = time.time()
                    self.proc = None
                    self.current_step_desc = ""

        threading.Thread(target=_resume, daemon=True).start()
        return True, "approved"

    def reject_pending(self) -> bool:
        with self.lock:
            if not self.pending_approval:
                return False
            self.pending_approval = None
            return True

    def draft_commit_message(self, workspace: dict) -> tuple[bool, str]:
        """Synchronously ask the Planner slot to draft a Conventional Commit message from the current diff."""
        ws_path = workspace.get("path", str(config.REPO_ROOT))
        ctx = presets.collect_diff_for_commit(Path(ws_path))
        if not ctx.get("ok"):
            return False, ctx.get("error", "无法读取改动")

        with self.lock:
            if self.running:
                return False, "当前已有任务在运行，请稍后再起草提交信息"
            self.running = True
            self.abort_requested = False
            self.mode = "commit_msg"
            self.workspace_id = workspace.get("id", "")
            self.thread_id = "__commit__"
            self.title = "起草提交信息"
            self.started_at = time.time()
            self.finished_at = None
            self.exit_code = None
            self.logs = []
            self.live_reply = ""
            self.current_step_desc = "正在阅读改动并起草提交信息..."

        try:
            untracked = "\n".join(f"- {u}" for u in ctx.get("untracked", [])) or "(无)"
            style_hint = ctx.get("recent_subjects") or "(新仓库，暂无历史)"
            sys_p = "你是严谨的 Git 提交信息撰写助手，只输出提交信息正文本身，不要任何解释、前后缀或代码块围栏。"
            user_p = (
                "请根据以下改动起草一条 Git 提交信息：\n"
                "1. 第一行使用 Conventional Commits 格式（feat/fix/refactor/docs/chore/perf/test 等），简洁英文，不超过 72 个字符；\n"
                "2. 若改动较多，空一行后用 2-4 条简短要点（- 开头）说明关键变化；\n"
                "3. 保持与该仓库近期提交风格一致；绝对不要调用任何工具，直接输出结果。\n\n"
                f"【近期提交标题】\n{style_hint}\n\n"
                f"【改动统计】\n{ctx.get('stat') or '(仅新增未跟踪文件)'}\n\n"
                f"【新增未跟踪文件】\n{untracked}\n\n"
                f"【Diff】\n{ctx.get('diff') or '(无)'}"
            )
            rc, reply = self._run_slot_blocking("planner", user_p, sys_p, ws_path)
            msg = _clean_commit_message(reply)
            if rc != 0 or not msg:
                msg = _fallback_commit_message(ctx)
            with self.lock:
                self.exit_code = 0
            return True, msg
        finally:
            with self.lock:
                self.running = False
                self.finished_at = time.time()
                self.proc = None
                self.current_step_desc = ""
                self.live_reply = ""


def _clean_commit_message(raw: str) -> str:
    text = (raw or "").strip()
    text = text.replace("```text", "").replace("```git", "").replace("```", "").strip()
    lines = [ln.rstrip() for ln in text.splitlines()]
    # Drop chatty preambles like "提交信息如下：" before the conventional subject
    pat = re.compile(r"^(feat|fix|refactor|docs|chore|perf|test|style|build|ci|revert)(\([^)]*\))?!?:\s")
    for idx, ln in enumerate(lines):
        if pat.match(ln.strip().strip("`")):
            lines = lines[idx:]
            break
    cleaned = "\n".join(lines).strip().strip("`").strip()
    return cleaned[:1200]


def _fallback_commit_message(ctx: dict) -> str:
    files = [ln[3:].strip() for ln in (ctx.get("status") or "").splitlines() if len(ln) > 3]
    if not files:
        return "chore: update files"
    head = ", ".join(Path(f).name for f in files[:3])
    more = f" (+{len(files) - 3} more)" if len(files) > 3 else ""
    return f"chore: update {head}{more}"[:72]


JOB_MANAGER = JobManager()
