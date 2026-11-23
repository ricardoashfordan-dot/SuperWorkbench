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
from unittest.mock import Mock, patch

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


class PipelineReviewTests(unittest.TestCase):
    def test_reviewer_reports_success_failure_and_cancellation(self):
        workspace = {"name": "Example", "path": str(_TEST_TMP_DIR)}
        scenarios = (
            (0, False, 0, "pipeline_done", "质检完成 → 请验收"),
            (7, False, 7, "error", "质检阶段失败"),
            (0, True, 130, "error", "质检已中止"),
            (None, False, 1, "error", "质检阶段异常"),
        )
        for engine_code, cancel, exit_code, event, title in scenarios:
            with self.subTest(engine_code=engine_code, cancel=cancel):
                manager = runner.JobManager()
                emit = Mock()

                def run_slot(slot, *_args, **_kwargs):
                    if slot == "builder":
                        return 0, "Build complete"
                    manager.abort_requested = cancel
                    if engine_code is None:
                        raise OSError("Reviewer unavailable")
                    return engine_code, "Reviewer output"

                with (
                    patch.object(manager, "_build_prompts", return_value=("", "", [])),
                    patch.object(manager, "_run_slot_blocking", side_effect=run_slot),
                ):
                    manager._run_pipeline_tail("Implement change", "Plan", workspace, emit)

                self.assertEqual(manager.exit_code, exit_code)
                kind, _, message_title, body, *_ = emit.call_args.args
                self.assertEqual(kind, event)
                self.assertIn(title, message_title)
                self.assertEqual(body, "Reviewer unavailable" if engine_code is None else "Reviewer output")

    def test_planner_and_builder_error_titles_match_exit_code(self):
        workspace = {"name": "Example", "path": str(_TEST_TMP_DIR)}
        for stage in ("planner", "builder"):
            for engine_code, cancelled, expected in ((0, True, 130), (7, True, 130), (7, False, 7)):
                with self.subTest(stage=stage, engine_code=engine_code, cancelled=cancelled):
                    manager = runner.JobManager()
                    emit = Mock()

                    def run_slot(slot, *_args, **_kwargs):
                        if slot == stage:
                            manager.abort_requested = cancelled
                            return engine_code, "Stage ended"
                        return 0, "Plan ready"

                    with (
                        patch.object(config, "load_app_settings", return_value={"approve_before_build": False}),
                        patch.object(manager, "_build_prompts", return_value=("", "", [])),
                        patch.object(manager, "_run_slot_blocking", side_effect=run_slot) as run,
                    ):
                        manager._worker("planner", "Implement change", True, workspace, emit)

                    self.assertEqual([call.args[0] for call in run.call_args_list],
                                     ["planner"] if stage == "planner" else ["planner", "builder"])
                    self.assertEqual(manager.exit_code, expected)
                    event, _, title, body, *_ = emit.call_args.args
                    self.assertEqual(event, "error")
                    self.assertTrue(title.endswith(f"(code={expected})"), title)
                    self.assertEqual(body, "Stage ended")

    def test_godot_manual_and_automatic_review_use_same_round_evidence(self):
        scenarios = (
            (60, 0, True, "PASS", True),
            (59.999, 20, True, "PASS", False),
            (120, 100, True, "PASS", False),
            (120, 20, False, "FAIL", False),
            (120, 20, None, "PENDING", False),
            (120, None, True, "PASS", False),
        )
        for fps, latency, bo3, bo3_status, expected in scenarios:
            with self.subTest(fps=fps, latency=latency, bo3=bo3):
                with tempfile.TemporaryDirectory() as scratch:
                    project = Path(scratch)
                    scenes = project / "scenes"
                    scenes.mkdir()
                    for r in (1, 2):
                        (scenes / f"bout_arena{r}.tscn").touch()
                    (project / "ROUND2_REPORT.md").write_text("Frame interval: 16 ms\n", encoding="utf-8")
                    config.write_json(
                        project / "test-results/round1/1-desktop.json",
                        {"avg_fps": 120, "input_latency_ms": 20},
                    )
                    config.write_json(
                        project / "test-results/round1/1-smoke_left.json",
                        {"bo3_pass": True, "failures": []},
                    )
                    config.write_json(
                        project / "test-results/round2/2-desktop.json",
                        {"avg_fps": fps, "input_latency_ms": latency},
                    )
                    if bo3 is not None:
                        config.write_json(
                            project / "test-results/round2/2-smoke_left.json",
                            {"bo3_pass": bo3, "failures": []},
                        )
                    workspace = {"name": "Game", "path": str(project), "type": "godot-game"}
                    handler = server.WorkbenchHandler.__new__(server.WorkbenchHandler)
                    handler._validate_host_and_origin = Mock(return_value=True)
                    handler._authorize = Mock(return_value=True)
                    handler._read_body = Mock(return_value={})
                    handler._send_json = Mock()
                    manager = runner.JobManager()
                    emit = Mock()

                    with (
                        patch.object(config, "STATE_PATH", project / "state.json"),
                        patch.object(config, "SELF_CHECK_PATH", project / "self_check.json"),
                        patch.object(config, "get_active_workspace", return_value=workspace),
                        patch.object(presets, "find_godot_console", return_value=Path("godot")),
                        patch.object(presets.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")),
                        patch.object(server, "append_message", return_value={}) as append_message,
                        patch.object(server, "build_snapshot", return_value={}),
                        patch.object(manager, "_build_prompts", return_value=("", "", [])),
                        patch.object(manager, "_run_slot_blocking", return_value=(0, "Build complete")),
                    ):
                        handler.path = "/api/self_check"
                        handler.do_POST()
                        self.assertEqual(handler._send_json.call_args.args[0]["result"]["status"], "PASS")
                        self.assertEqual(presets.load_workspace_self_check(project / "another-project"), {})

                        handler.path = "/api/dsh_verify"
                        handler.do_POST()
                        manual = handler._send_json.call_args.args[0]["result"]
                        manual_details = append_message.call_args.args[4]
                        manager._run_pipeline_tail("Implement change", "Plan", workspace, emit)

                    self.assertEqual(manual["round"], 2)
                    self.assertEqual(manual["overall_pass"], expected)
                    objective = manual["objective_3"]
                    self.assertEqual(objective["fps_ge_60"]["passed"], fps >= 60)
                    self.assertEqual(objective["input_latency_lt_100ms"]["value"], latency)
                    self.assertEqual(objective["input_latency_lt_100ms"]["passed"], latency is not None and latency < 100)
                    self.assertEqual(objective["bo3_full_loop"]["value"], bo3_status)
                    self.assertIn(manual_details, emit.call_args.args[3])
                    if latency is None:
                        self.assertIn("输入延迟：未测", manual_details)
                    self.assertEqual(manager.exit_code, 0 if expected else 1)
                    self.assertEqual(emit.call_args.args[0], "pipeline_done" if expected else "error")

    def test_godot_smoke_latency_fallback_and_display(self):
        with tempfile.TemporaryDirectory() as scratch:
            project = Path(scratch)
            (project / "scenes").mkdir()
            (project / "scenes/bout_arena2.tscn").touch()
            results = project / "test-results/round2"
            old_case = results / "old/2-smoke_left.json"
            config.write_json(old_case, {"bo3_pass": False, "movement_ms": 500})
            os.utime(old_case, (1, 1))
            config.write_json(results / "latest/2-smoke_left.json",
                              {"bo3_pass": True, "movement_ms": 26.0416666666667, "jump_ms": 18.75})
            right_case = results / "latest/2-smoke_right.json"
            desktop = results / "2-desktop.json"
            report = project / "ROUND2_REPORT.md"
            config.write_json(desktop, {"fps": 233.541501241437})

            for right_latency, expected in ((25.9, 26.0416666666667), (99.999, 99.999), (100, 100), (120, 120)):
                with self.subTest(right_latency=right_latency):
                    config.write_json(right_case, {"bo3_pass": True, "movement_ms": -1, "jump_ms": right_latency})
                    result = presets.run_dsh_verification(project)
                    self.assertEqual(result["objective_3"]["input_latency_lt_100ms"]["value"], expected)
                    self.assertEqual(result["overall_pass"], expected < 100)
                    details = presets.format_dsh_verification(result)
                    self.assertIn("233.54 FPS", details)
                    if right_latency == 25.9:
                        self.assertIn("26.04 ms", details)
                    if right_latency == 99.999:
                        self.assertIn("输入延迟：< 100 ms", details)

            report.write_text("输入延迟：41.25 ms\n", encoding="utf-8")
            result = presets.run_dsh_verification(project)
            self.assertEqual(result["objective_3"]["input_latency_lt_100ms"]["value"], 41.25)
            config.write_json(desktop, {"fps": 59.999, "input_latency_ms": 0})
            result = presets.run_dsh_verification(project)
            self.assertEqual(result["objective_3"]["input_latency_lt_100ms"]["value"], 0)
            self.assertFalse(result["overall_pass"])
            self.assertIn("帧率：< 60 FPS（要求 >= 60 FPS，未达标）", presets.format_dsh_verification(result))

            config.write_json(results / "latest/2-smoke_left.json",
                              {"bo3_pass": True, "movement_ms": "Infinity", "jump_ms": True})
            config.write_json(right_case, {"bo3_pass": True, "movement_ms": "NaN", "jump_ms": -1})
            config.write_json(desktop, {"fps": 233.541501241437})
            report.write_text("Frame interval: 16 ms\n", encoding="utf-8")
            result = presets.run_dsh_verification(project)
            self.assertIsNone(result["objective_3"]["input_latency_lt_100ms"]["value"])
            self.assertFalse(result["overall_pass"])
            self.assertIn("输入延迟：未测", presets.format_dsh_verification(result))

    def test_failed_godot_self_check_replaces_saved_pass_and_stops_review(self):
        manager = runner.JobManager()
        emit = Mock()
        with tempfile.TemporaryDirectory() as scratch:
            project = Path(scratch)
            workspace = {"name": "Game", "path": str(project), "type": "godot-game"}
            with (
                patch.object(config, "SELF_CHECK_PATH", project / "self_check.json"),
                patch.object(presets, "find_godot_console", return_value=None),
                patch.object(presets, "run_dsh_verification") as verify,
                patch.object(manager, "_build_prompts", return_value=("", "", [])),
                patch.object(manager, "_run_slot_blocking", return_value=(0, "Build complete")),
            ):
                config.write_json(config.SELF_CHECK_PATH, {"status": "PASS", "workspace_path": str(project.resolve())})
                manager._run_pipeline_tail("Implement change", "Plan", workspace, emit)
                self.assertEqual(presets.load_workspace_self_check(project)["status"], "FAIL")
                verify.assert_not_called()
        self.assertEqual(emit.call_args.args[0], "error")
        self.assertEqual(manager.exit_code, 1)


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

        forbidden = re.compile(r"决战|DeepSpaceBrawlLab|深空乱斗|R133|ASUS", re.IGNORECASE)
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

    def test_09_codex_discovery_and_fallback_tagging(self):
        tmp_home = Path(tempfile.mkdtemp(prefix="swb_home_"))
        orig_home = os.environ.get("HOME")
        try:
            os.environ["HOME"] = str(tmp_home)
            codex_dir = tmp_home / ".codex"
            codex_dir.mkdir(parents=True, exist_ok=True)
            cache = codex_dir / "models_cache.json"

            # 1. Valid cache -> discovered (deduped, ignores unknown fields & codex-auto-review)
            cache.write_text(
                '{"models": ['
                '{"slug": "gpt-6.2-sol", "extra_vendor_field": 123},'
                '{"slug": "gpt-6.2-sol"},'
                '{"id": "o4-mini"},'
                '{"slug": "codex-auto-review"},'
                '"not-a-dict"'
                ']}',
                encoding="utf-8",
            )
            opts, src = adapters.discover_codex_models_with_source()
            self.assertEqual(src, "discovered")
            self.assertEqual([m["id"] for m in opts], ["gpt-6.2-sol", "o4-mini"])
            self.assertEqual(adapters.default_model_settings()["model_sources"]["codex"], "discovered")

            # 2. Malformed JSON -> fallback
            cache.write_text("{broken json!!!", encoding="utf-8")
            opts, src = adapters.discover_codex_models_with_source()
            self.assertEqual(src, "fallback")
            self.assertEqual(opts, adapters.FALLBACK_CODEX_OPTIONS)
            self.assertEqual(adapters.default_model_settings()["model_sources"]["codex"], "fallback")

            # 3. Valid JSON with missing / renamed fields -> fallback
            cache.write_text('{"items": [{"name": "gpt-99"}]}', encoding="utf-8")
            opts, src = adapters.discover_codex_models_with_source()
            self.assertEqual(src, "fallback")
            self.assertEqual(opts, adapters.FALLBACK_CODEX_OPTIONS)

            # 4. Empty models array -> fallback
            cache.write_text('{"models": []}', encoding="utf-8")
            opts, src = adapters.discover_codex_models_with_source()
            self.assertEqual(src, "fallback")
            self.assertEqual(opts, adapters.FALLBACK_CODEX_OPTIONS)
        finally:
            if orig_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = orig_home
            shutil.rmtree(tmp_home, ignore_errors=True)

    def test_10_doctor_empty_path_no_clis(self):
        import json as _json

        tmp_home = Path(tempfile.mkdtemp(prefix="swb_empty_path_"))
        try:
            env = os.environ.copy()
            env["PATH"] = ""
            env["HOME"] = str(tmp_home)
            env["SUPER_WORKBENCH_DATA_DIR"] = str(tmp_home / "data")
            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "start.py"), "--doctor", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                timeout=15,
                creationflags=config.NO_WINDOW_FLAGS,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            doc = _json.loads(proc.stdout)
            self.assertTrue(doc["ok"])
            for cid in ("agy", "codex", "claude", "gemini", "dsh"):
                entry = doc["clis"][cid]
                self.assertFalse(entry["installed"], f"{cid} should not be found with empty PATH")
                self.assertEqual(entry["version"], "not installed")
                self.assertIn(entry["model_source"], ("fallback", "n/a"))
        finally:
            shutil.rmtree(tmp_home, ignore_errors=True)

    def test_11_single_cli_default_role_binding(self):
        from unittest.mock import patch

        only_dsh = {
            "agy": {"ready": False, "path": ""},
            "codex": {"ready": False, "path": ""},
            "claude": {"ready": False, "path": ""},
            "gemini": {"ready": False, "path": ""},
            "dsh": {"ready": True, "path": "dsh.CMD"},
        }
        with patch.object(adapters, "detect_cli_status", return_value=only_dsh):
            roles = adapters.default_role_bindings()
        for slot in ("planner", "builder", "reviewer"):
            self.assertEqual(roles[slot]["engine"], "dsh")
            self.assertEqual(roles[slot]["model"], "headless")


if __name__ == "__main__":
    unittest.main()
