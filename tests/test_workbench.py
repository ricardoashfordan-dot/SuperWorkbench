import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKBENCH_DIR = REPO_ROOT / "workbench"

# Isolate test runtime data directory before importing workbench modules
_TEST_TMP_DIR = Path(tempfile.mkdtemp(prefix="swb_test_data_"))
os.environ["SUPER_WORKBENCH_DATA_DIR"] = str(_TEST_TMP_DIR)
sys.path.insert(0, str(WORKBENCH_DIR))

import adapters     # noqa: E402
import config       # noqa: E402
import mcp_manager  # noqa: E402
import presets      # noqa: E402
import runner       # noqa: E402
import server       # noqa: E402
import skills       # noqa: E402
import threads      # noqa: E402


def tearDownModule():
    shutil.rmtree(_TEST_TMP_DIR, ignore_errors=True)


class ConversationTestSuite(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        paths = mock.patch.multiple(
            config,
            MESSAGES_PATH=self.project / "messages.json",
            THREADS_PATH=self.project / "threads.json",
            STATE_PATH=self.project / "state.json",
            NEXT_FOR_CODEX_PATH=self.project / "NEXT_FOR_CODEX.md",
        )
        paths.start()
        self.addCleanup(paths.stop)
        self.workspace = {"id": "workspace-a", "name": "Project", "path": str(self.project)}
        self.thread = threads.ensure_workspace_thread(self.workspace["id"])[0]["id"]

    def _seed_context(self):
        ws_id = self.workspace["id"]
        threads.clear_messages(ws_id, self.thread)
        threads.set_thread_summary(self.thread, "Saved decision " + "s" * 1500 + "summary overflow", 1, ws_id=ws_id)
        server.append_message("xiu", "agy", "LOCK", "Legacy task", "Previous requirement", workspace_id=ws_id, thread_id=self.thread)
        server.append_message("agy", "xiu", "DONE_SINGLE", "Done", "Previous reply " + "r" * 600 + "reply overflow",
                              workspace_id=ws_id, thread_id=self.thread)
        server.append_message("agy", "xiu", "COMPACT", "Summary saved", "Internal compaction event",
                              workspace_id=ws_id, thread_id=self.thread)
        server.append_message("xiu", "agy", "TASK", "Other thread", "Other thread only",
                              workspace_id=ws_id, thread_id="other-thread")
        server.append_message("xiu", "agy", "TASK", "Other workspace", "Other workspace only",
                              workspace_id="workspace-b", thread_id=self.thread)

    def _assert_prompt_context(self, prompt, instruction):
        for expected in ("Saved decision", "Previous requirement", "Previous reply"):
            self.assertIn(expected, prompt)
        for excluded in ("summary overflow", "reply overflow", "Internal compaction event",
                         "Other thread only", "Other workspace only"):
            self.assertNotIn(excluded, prompt)
        self.assertEqual(prompt.count(instruction), 1)

    def test_single_cli_transports_include_persona_and_bounded_thread_context(self):
        for engine in ("agy", "codex", "claude", "gemini", "dsh", "custom"):
            with self.subTest(engine=engine):
                self._seed_context()
                instruction = "Follow up on the earlier decision"
                persona = 'DIY role: use "strict" terminology'
                role = {"engine": engine, "system_prompt": persona}
                engine_config = {"name": engine, "kind": f"cli-{engine}", "ready": True, "path": engine}
                if engine == "custom":
                    engine_config.update(kind="custom-cli", command_template='example --prompt "{prompt}"')
                process = mock.Mock(stdout=["Follow-up reply\n"])
                process.wait.return_value = 0
                manager = runner.JobManager()
                with (
                    mock.patch.object(adapters, "load_role_bindings", return_value={"reviewer": role}),
                    mock.patch.object(adapters, "get_engine_by_id", return_value=engine_config),
                    mock.patch.object(skills, "build_active_skills_prompt", return_value=("", [])),
                    mock.patch.object(runner.subprocess, "Popen", return_value=process) as launch,
                ):
                    manager._worker("reviewer", instruction, False, self.workspace, server._on_job_event, thread_id=self.thread)

                launch.assert_called_once()
                if os.name == "nt":
                    self.assertEqual(launch.call_args.kwargs["creationflags"], config.NO_WINDOW_FLAGS)
                command = launch.call_args.args[0]
                if engine in ("codex", "claude"):
                    prompt = process.stdin.write.call_args.args[0]
                else:
                    prompt = command[-1]
                self.assertIn(persona, prompt)
                self._assert_prompt_context(prompt, instruction)
                self.assertEqual(manager.exit_code, 0)

    def test_pipeline_and_approval_resume_pass_same_history_to_cli_and_api(self):
        roles = {
            "planner": {"engine": "agy", "system_prompt": "Planner persona"},
            "builder": {"engine": "codex", "system_prompt": "Builder persona"},
            "reviewer": {"engine": "api", "system_prompt": "Reviewer persona"},
        }
        engines = {
            "agy": {"name": "Antigravity", "kind": "cli-agy", "path": "agy", "ready": True},
            "codex": {"name": "Codex", "kind": "cli-codex", "path": "codex", "ready": True},
            "api": {"name": "API", "kind": "openai-compat"},
        }
        for approval in (False, True):
            with self.subTest(approval=approval):
                self._seed_context()
                instruction = "Implement the reported issue"
                planner = mock.Mock(stdout=["Planning handoff\n"])
                planner.wait.return_value = 0
                builder = mock.Mock(stdout=["Build report\n"])
                builder.wait.return_value = 0
                manager = runner.JobManager()
                with (
                    mock.patch.object(config, "load_app_settings", return_value={"approve_before_build": approval}),
                    mock.patch.object(adapters, "load_role_bindings", return_value=roles),
                    mock.patch.object(adapters, "get_engine_by_id", side_effect=lambda name, **_: engines[name]),
                    mock.patch.object(skills, "build_active_skills_prompt", return_value=("", [])),
                    mock.patch.object(runner.subprocess, "Popen", side_effect=[planner, builder]) as cli,
                    mock.patch.object(adapters, "stream_openai_compat", return_value=(0, "Review result")) as api,
                ):
                    manager._worker("planner", instruction, True, self.workspace, server._on_job_event, thread_id=self.thread)
                    if approval:
                        self.assertEqual(cli.call_count, 1)
                        api.assert_not_called()
                        with mock.patch.object(runner.threading, "Thread") as thread:
                            thread.side_effect = lambda *, target, daemon: mock.Mock(start=target)
                            ok, _ = manager.approve_pending("Approval note", server._on_job_event)
                        self.assertTrue(ok)
                self.assertEqual(cli.call_count, 2)
                api.assert_called_once()
                planner_prompt = cli.call_args_list[0].args[0][-1]
                builder_prompt = builder.stdin.write.call_args.args[0]
                reviewer_prompt = api.call_args.kwargs["user_prompt"]
                for prompt in (planner_prompt, builder_prompt, reviewer_prompt):
                    self._assert_prompt_context(prompt, instruction)
                self.assertIn("Planner persona", planner_prompt)
                self.assertIn("Builder persona", builder_prompt)
                self.assertIn("Planning handoff", builder_prompt)
                self.assertIn("Build report", reviewer_prompt)
                self.assertEqual(api.call_args.kwargs["system_prompt"], "Reviewer persona")
                if approval:
                    self.assertIn("Approval note", builder_prompt)
                self.assertEqual(manager.exit_code, 0)

    def test_interleaved_history_preserves_legacy_rows_and_ids_across_restart(self):
        a, b = self.workspace["id"], "workspace-b"
        legacy = [
            {"id": "msg-401", "workspace_id": a, "body": "legacy A"},
            {"id": "msg-401", "workspace_id": b, "body": "legacy B"},
        ]
        config.write_json(config.MESSAGES_PATH, legacy)
        new_ids = []
        for index in range(405):
            for workspace in (a, b):
                message = server.append_message(
                    "xiu", "agy", "TASK", "Request", f"message {index}",
                    workspace_id=workspace, thread_id=threads.default_thread_id(workspace),
                )
                new_ids.append(int(message["id"].split("-")[1]))
        self.assertEqual(new_ids, list(range(402, 1212)))
        self.assertEqual(config.read_json(config.MESSAGES_PATH, [])[:2], legacy)

        script = """
import json
import server
import threads
histories = [threads.load_thread_messages(ws, threads.default_thread_id(ws))
             for ws in ("workspace-a", "workspace-b")]
for ws in ("workspace-a", "workspace-b"):
    threads.clear_messages(ws)
message = server.append_message("xiu", "agy", "TASK", "Follow up", "After restart",
                                workspace_id="workspace-a", thread_id="default-workspace-a")
print(json.dumps([[len(rows), rows[0]["body"], rows[1]["body"]] for rows in histories] + [message["id"]]))
"""
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=WORKBENCH_DIR, capture_output=True, text=True,
            encoding="utf-8", env={**os.environ, "SUPER_WORKBENCH_DATA_DIR": str(self.project)},
            check=True, timeout=20, creationflags=config.NO_WINDOW_FLAGS,
        )
        self.assertEqual(
            json.loads(result.stdout),
            [[406, "legacy A", "message 0"], [406, "legacy B", "message 0"], "msg-1212"],
        )

    def test_concurrent_appends_after_removing_legacy_history(self):
        ws_id = self.workspace["id"]
        config.write_json(config.MESSAGES_PATH, [{"id": "msg-401", "workspace_id": ws_id, "body": "legacy"}])
        threads.clear_messages(ws_id, self.thread)

        def append(index):
            return server.append_message(
                "xiu", "agy", "TASK", "Request", str(index), workspace_id=ws_id, thread_id=self.thread,
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            created = list(pool.map(append, range(16)))
        saved = threads.load_thread_messages(ws_id, self.thread)
        self.assertEqual({m["body"] for m in saved}, {m["body"] for m in created})
        self.assertEqual([int(m["id"].split("-")[1]) for m in saved], list(range(402, 418)))


class SuperWorkbenchTestSuite(unittest.TestCase):
    def test_01_app_settings_roundtrip(self):
        defaults = config.load_app_settings()
        self.assertFalse(defaults["approve_before_build"])
        self.assertFalse(defaults["exit_on_close"])
        self.assertEqual(defaults["user_name"], "我")
        self.assertEqual(defaults["lang"], "zh")

        updated = config.save_app_settings({
            "approve_before_build": True,
            "exit_on_close": True,
            "user_name": "Ricardo",
            "lang": "en",
        })
        self.assertTrue(updated["approve_before_build"])
        self.assertTrue(updated["exit_on_close"])
        self.assertEqual(updated["user_name"], "Ricardo")
        self.assertEqual(updated["lang"], "en")

        config.save_app_settings(defaults)

    def test_02_workspaces_and_threads(self):
        ws_data = config.load_workspaces()
        self.assertTrue(len(ws_data.get("items", [])) >= 1)
        ws_id = ws_data["items"][0]["id"]

        active_t, t_list = threads.ensure_workspace_thread(ws_id)
        self.assertIsNotNone(active_t)
        self.assertTrue(len(t_list) >= 1)

        new_t = threads.create_thread(ws_id, "架构讨论")
        self.assertEqual(new_t["title"], "架构讨论")

        ok = threads.rename_thread(new_t["id"], "核心重构")
        self.assertTrue(ok)
        self.assertEqual(threads.get_thread_by_id(new_t["id"])["title"], "核心重构")

        threads.set_thread_summary(new_t["id"], "已完成模块化拆分", 8)
        reloaded = threads.get_thread_by_id(new_t["id"])
        self.assertEqual(reloaded["summary"], "已完成模块化拆分")
        self.assertEqual(reloaded["compacted_count"], 8)

        self.assertTrue(threads.delete_thread(ws_id, new_t["id"]))

    def test_03_skills_discovery_crud_and_injection(self):
        ws = config.get_active_workspace()
        ws_id = ws["id"]
        ws_path = Path(ws["path"])

        discovered = skills.list_skills(ws_id, ws_path)
        slugs = {s["slug"] for s in discovered}
        self.assertIn("aigc-storyboard", slugs)
        self.assertIn("code-review-strict", slugs)
        self.assertIn("git-commit-release", slugs)

        created = skills.create_skill(
            name="unit-test-skill",
            description="Unit test custom skill",
            body="Always run unit tests before committing.",
            scope="user",
            ws_path=ws_path,
            ws_id=ws_id,
        )
        self.assertEqual(created["slug"], "unit-test-skill")

        prompt_block, mounted = skills.build_active_skills_prompt(ws_id, ws_path, [created["id"]])
        self.assertIn("unit-test-skill", mounted)
        self.assertIn("Always run unit tests before committing.", prompt_block)

        self.assertTrue(skills.delete_skill(created["id"], ws_id, ws_path))

    def test_04_mcp_registry_and_secret_masking(self):
        srv = mcp_manager.upsert_server(
            name="github-test",
            title="GitHub Test",
            desc="Test MCP",
            transport="stdio",
            command="npx",
            args="-y @modelcontextprotocol/server-github",
            env="GITHUB_PERSONAL_ACCESS_TOKEN=ghp_1234567890abcdef",
        )
        self.assertEqual(srv["name"], "github-test")

        masked_reg = mcp_manager.load_mcp_registry(mask_secrets=True)
        found = next(s for s in masked_reg["servers"] if s["name"] == "github-test")
        self.assertIn("***", found["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"])

        unmasked_reg = mcp_manager.load_mcp_registry(mask_secrets=False)
        found_raw = next(s for s in unmasked_reg["servers"] if s["name"] == "github-test")
        self.assertEqual(found_raw["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"], "ghp_1234567890abcdef")

        mcp_manager.delete_server("github-test", unsync=False)

    def test_05_git_diff_and_commit_loop(self):
        git_bin = presets.find_git_bin()
        if not git_bin:
            self.skipTest("git binary not installed")
        tmp_repo = Path(tempfile.mkdtemp(prefix="swb_git_unit_"))
        try:
            subprocess.run(
                [git_bin, "init", "-q", "-b", "main", str(tmp_repo)],
                check=True,
                creationflags=config.NO_WINDOW_FLAGS,
            )
            subprocess.run([git_bin, "-C", str(tmp_repo), "config", "user.name", "Test"], check=True, creationflags=config.NO_WINDOW_FLAGS)
            subprocess.run([git_bin, "-C", str(tmp_repo), "config", "user.email", "test@example.com"], check=True, creationflags=config.NO_WINDOW_FLAGS)

            (tmp_repo / "hello.py").write_text("print('hi')\n", encoding="utf-8")
            ctx = presets.collect_diff_for_commit(tmp_repo)
            self.assertTrue(ctx["ok"])
            self.assertIn("hello.py", ctx["untracked"])

            res = presets.git_commit_all(tmp_repo, "feat: add hello.py")
            self.assertTrue(res["ok"])
            self.assertTrue(len(res["hash"]) >= 6)

            cleaned = runner._clean_commit_message("Here is the commit:\n```\nfeat(core): add parser\n```")
            self.assertEqual(cleaned, "feat(core): add parser")
        finally:
            shutil.rmtree(tmp_repo, ignore_errors=True)

    def test_06_static_assets_and_privacy_audit(self):
        for fname in ("index.html", "app.css", "app.js", "icon.svg", "icon-256.png", "icon.ico", "manifest.json"):
            fpath = config.STATIC_DIR / fname
            self.assertTrue(fpath.exists() and fpath.stat().st_size > 0, f"Missing static file: {fname}")

        if shutil.which("node"):
            r = subprocess.run(
                ["node", "--check", str(config.STATIC_DIR / "app.js")],
                capture_output=True,
                text=True,
                creationflags=config.NO_WINDOW_FLAGS,
            )
            self.assertEqual(r.returncode, 0, f"JS syntax error: {r.stderr}")

        forbidden = re.compile(r"决战|DeepSpaceBrawlLab|ASUS", re.IGNORECASE)
        skip_dirs = {".workbench", "__pycache__", ".git", ".venv", "venv", "tests"}
        for root_dir, dirs, files in os.walk(REPO_ROOT):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                p = Path(root_dir) / f
                if p.suffix in {".py", ".html", ".css", ".js", ".md", ".json", ".cmd", ".sh"}:
                    txt = p.read_text(encoding="utf-8", errors="replace")
                    m = forbidden.search(txt)
                    self.assertIsNone(m, f"Personal leak '{m.group(0) if m else ''}' found in {p.relative_to(REPO_ROOT)}")

        snap = server.build_snapshot()
        for key in ("version", "workspaces", "threads", "roles", "engines", "skills", "mcp", "settings", "git", "aigc"):
            self.assertIn(key, snap)

    def test_07_role_diy_persona_and_doctor(self):
        roles = adapters.load_role_bindings()
        roles["planner"]["custom_label"] = "增长文案总监"
        roles["planner"]["system_prompt"] = "你是顶级增长文案总监，只输出高转化方案。"
        adapters.save_role_bindings(roles)

        reloaded = adapters.load_role_bindings()
        self.assertEqual(reloaded["planner"]["custom_label"], "增长文案总监")
        self.assertEqual(reloaded["planner"]["system_prompt"], "你是顶级增长文案总监，只输出高转化方案。")

        ws = config.get_active_workspace()
        sys_p, _, _ = runner.JOB_MANAGER._build_prompts("planner", "写一个发布方案", ws)
        self.assertEqual(sys_p, "你是顶级增长文案总监，只输出高转化方案。")

        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "start.py"), "--doctor", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            creationflags=config.NO_WINDOW_FLAGS,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        import json as _json
        doc = _json.loads(proc.stdout)
        self.assertTrue(doc["ok"])
        self.assertIn("clis", doc)
        self.assertIn("ollama", doc)
        self.assertTrue(doc.get("api_auth", {}).get("enabled"))

    def test_08_local_api_security(self):
        import http.client
        import threading
        from http.server import ThreadingHTTPServer

        token = server.get_session_token()
        self.assertTrue(len(token) >= 16)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.WorkbenchHandler)
        port = srv.server_port
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            def req(method, path, headers=None, body=None):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    hdrs = dict(headers or {})
                    if body is not None and "Content-Type" not in hdrs:
                        hdrs["Content-Type"] = "application/json"
                    conn.request(method, path, body=body, headers=hdrs)
                    resp = conn.getresponse()
                    data = resp.read().decode("utf-8", errors="replace")
                    return resp.status, dict(resp.getheaders()), data
                finally:
                    conn.close()

            # 1. /api/* without credentials -> 403
            st, _, _ = req("GET", "/api/state")
            self.assertEqual(st, 403)
            st, _, _ = req("POST", "/api/settings", body="{}")
            self.assertEqual(st, 403)

            # 2. GET /?token=<wrong> -> 200 static HTML, NO Set-Cookie
            st, hdrs, _ = req("GET", "/?token=wrong-token-value")
            self.assertEqual(st, 200)
            self.assertNotIn("Set-Cookie", hdrs)

            # 3. GET /?token=<valid> -> 200 + Set-Cookie swb_session (HttpOnly; SameSite=Strict)
            st, hdrs, _ = req("GET", f"/?token={token}")
            self.assertEqual(st, 200)
            set_cookie = hdrs.get("Set-Cookie", "")
            self.assertIn(f"swb_session={token}", set_cookie)
            self.assertIn("HttpOnly", set_cookie)
            self.assertIn("SameSite=Strict", set_cookie)

            # 4. /api/state with valid Cookie -> 200
            st, _, _ = req("GET", "/api/state", headers={"Cookie": f"swb_session={token}"})
            self.assertEqual(st, 200)

            # 5. /api/state with valid X-Workbench-Token header -> 200
            st, _, _ = req("GET", "/api/state", headers={"X-Workbench-Token": token})
            self.assertEqual(st, 200)

            # 6. Request with foreign Host header (DNS rebinding) -> 403
            st, _, _ = req("GET", "/api/state", headers={"Host": f"evil.example.com:{port}", "X-Workbench-Token": token})
            self.assertEqual(st, 403)
            st, _, _ = req("GET", "/", headers={"Host": f"evil.example.com:{port}"})
            self.assertEqual(st, 403)

            # 7. POST with cross-site Origin (even with valid token) -> 403
            st, _, _ = req(
                "POST",
                "/api/settings",
                headers={"Origin": "https://evil.example.com", "X-Workbench-Token": token},
                body="{}",
            )
            self.assertEqual(st, 403)

            # 8. POST with no Origin + valid X-Workbench-Token (curl / desktop WebView) -> 200
            st, _, _ = req("POST", "/api/settings", headers={"X-Workbench-Token": token}, body="{}")
            self.assertEqual(st, 200)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
