import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from email.message import Message
from hashlib import sha256
from pathlib import Path
from unittest import mock
from unittest.mock import Mock, patch
from urllib.request import HTTPHandler, HTTPSHandler
from urllib.response import addinfourl

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


class SkillEcosystemTests(unittest.TestCase):
    base_url = "https://raw.githubusercontent.com/example/skills/main/SKILL.md"
    raw = (
        '---\nname: remote-review\ndescription: "Readability: check defaults"\n'
        "category: engineering\ntags: [review, docs]\n---\n\n# Review\nRecord the evidence.\n"
    ).encode("utf-8")

    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve()
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.home = self.root / "home"
        self.library = self.root / "library"
        self.settings = self.root / "skills_state.json"
        self.ws_id = "test-project"
        self.requests = []
        patches = ExitStack()
        self.addCleanup(patches.close)
        patches.enter_context(patch.multiple(config, USER_SKILLS_DIR=self.library, SKILLS_STATE_PATH=self.settings))
        patches.enter_context(patch.object(Path, "home", return_value=self.home))
        patches.enter_context(patch.object(HTTPHandler, "http_open", side_effect=AssertionError("HTTP must not open")))

    def _mock_github(self, routes):
        def open_https(_handler, request):
            self.requests.append(request.full_url)
            status, headers, body = routes[request.full_url]
            response_headers = Message()
            for key, value in headers.items():
                response_headers[key] = value
            response = addinfourl(io.BytesIO(body), response_headers, request.full_url, status)
            response.msg = "Mock GitHub"
            return response

        return patch.object(HTTPSHandler, "https_open", autospec=True, side_effect=open_https)

    def test_discovery_metadata_and_read_only_local_engines(self):
        expected = {
            "aigc-storyboard": "aigc", "code-review-strict": "engineering", "git-commit-release": "engineering",
            "security-audit": "engineering", "bug-triage": "engineering", "doc-writer": "engineering",
            "deep-research": "research", "paper-study": "research",
            "art-3d-pipeline": "aigc",
        }
        for directory, body in (
            (self.home / ".gemini" / "skills" / "legacy", "# Legacy\nA Markdown body."),
            (self.home / ".dsh" / "skills" / "notes", "---\nname: notes\ntags: one, two\n---\n\n# Notes"),
        ):
            directory.mkdir(parents=True)
            (directory / "SKILL.md").write_text(body, encoding="utf-8")
        items = skills.list_skills(self.ws_id, self.workspace)
        builtin = {item["slug"]: item for item in items if item["source"] == "builtin"}
        self.assertEqual({name: item["category"] for name, item in builtin.items()}, expected)
        self.assertTrue(all(item["tags"] for item in builtin.values()))
        for name in ("security-audit", "bug-triage", "doc-writer", "deep-research", "paper-study"):
            line_count = len(Path(builtin[name]["path"]).read_text(encoding="utf-8").splitlines())
            self.assertIn(line_count, range(40, 81))
        by_id = {item["id"]: item for item in items}
        self.assertEqual(by_id["ext-gemini:legacy"]["category"], "general")
        self.assertEqual(by_id["ext-gemini:legacy"]["tags"], [])
        self.assertEqual(by_id["ext-dsh:notes"]["tags"], ["one", "two"])
        for skill_id in ("ext-gemini:legacy", "ext-dsh:notes"):
            self.assertFalse(by_id[skill_id]["editable"])
            self.assertFalse(skills.delete_skill(skill_id, self.ws_id, self.workspace))
        self.assertFalse(self.library.exists())

    def test_remote_preview_and_install_rewrite_github_urls(self):
        github = "https://github.com/example/skills/blob/main/SKILL.md#L1"
        root = "https://raw.githubusercontent.com/example/skills/HEAD/SKILL.md"
        directory = "https://raw.githubusercontent.com/example/skills/v1/packs/review/SKILL.md"
        routes = {url: (200, {}, self.raw) for url in (self.base_url, root, directory)}
        with self._mock_github(routes):
            preview = skills.preview_remote_skill(github)
            self.assertEqual(preview, {
                "name": "remote-review", "description": "Readability: check defaults",
                "category": "engineering", "tags": ["review", "docs"],
                "body": "# Review\nRecord the evidence.", "resolved_url": self.base_url, "byte_size": len(self.raw),
            })
            self.assertEqual(skills.preview_remote_skill("https://github.com/example/skills")["resolved_url"], root)
            self.assertEqual(
                skills.preview_remote_skill("https://github.com/example/skills/tree/v1/packs/review/")["resolved_url"],
                directory,
            )
            self.assertFalse(self.library.exists())
            self.assertFalse(self.settings.exists())
            installed = skills.install_remote_skill(github, self.ws_id)

        self.assertEqual(self.requests, [self.base_url, root, directory, self.base_url])
        self.assertEqual(installed["resolved_url"], self.base_url)
        self.assertEqual(installed["name"], preview["name"])
        self.assertEqual(Path(installed["path"]), self.library / "remote-review" / "SKILL.md")
        self.assertEqual(skills._parse_skill_md(Path(installed["path"]))["tags"], ["review", "docs"])
        self.assertIn(installed["id"], skills.load_skills_state()["global_enabled"])

    def test_remote_rejects_disallowed_urls_and_redirects(self):
        with self._mock_github({}) as open_https:
            for url in (
                "http://github.com/example/skills",
                "https://example.org/review/SKILL.md",
                "https://github.com.example.org/example/skills",
                "https://github.com@example.org/example/skills",
                "https://raw.githubusercontent.com:444/example/skills/main/SKILL.md",
            ):
                with self.subTest(url=url), self.assertRaisesRegex(ValueError, "HTTPS"):
                    skills.preview_remote_skill(url)
            open_https.assert_not_called()

        for target in ("http://127.0.0.1/SKILL.md", "https://127.0.0.1/SKILL.md", "https://example.org/SKILL.md"):
            with self.subTest(target=target):
                self.requests.clear()
                with self._mock_github({self.base_url: (302, {"Location": target}, b"")}), self.assertRaises(ValueError):
                    skills.install_remote_skill(self.base_url, self.ws_id)
                self.assertEqual(self.requests, [self.base_url])
        self.assertFalse(self.library.exists())
        self.assertFalse(self.settings.exists())

    def test_remote_redirect_count_and_stream_size(self):
        urls = [f"{self.base_url}?step={n}" for n in range(5)]
        routes = {url: (302, {"Location": urls[n + 1]}, b"") for n, url in enumerate(urls[:-1])}
        with self._mock_github(routes), self.assertRaisesRegex(ValueError, "3 次"):
            skills.preview_remote_skill(urls[0])
        self.assertEqual(self.requests, urls[:4])
        routes[urls[3]] = (200, {}, b"a" * skills.MAX_SKILL_BYTES)
        with self._mock_github(routes):
            preview = skills.preview_remote_skill(urls[0])
            self.assertEqual(preview["resolved_url"], urls[3])
            self.assertEqual(preview["byte_size"], skills.MAX_SKILL_BYTES)
        routes[urls[3]] = (200, {}, b"a" * (skills.MAX_SKILL_BYTES + 1))
        with self._mock_github(routes), self.assertRaisesRegex(ValueError, "128 KB"):
            skills.install_remote_skill(urls[0], self.ws_id)
        self.assertFalse(self.library.exists())

    def test_remote_has_an_overall_deadline(self):
        allow_response = threading.Event()
        completed = threading.Event()

        def blocked_http(*_args):
            try:
                allow_response.wait(3)
                raise OSError("Mock request finished")
            finally:
                completed.set()

        # Pre-warm opener/SSL handler setup so cold Windows CA loading does not consume the short test deadline.
        skills.build_opener(skills.ProxyHandler({}))
        with (
            patch.object(HTTPSHandler, "https_open", side_effect=blocked_http),
            patch.object(skills, "REMOTE_TIMEOUT_SECONDS", 0.5),
        ):
            try:
                with self.assertRaisesRegex(ValueError, "超时"):
                    skills.preview_remote_skill(self.base_url)
                self.assertFalse(completed.is_set())
            finally:
                allow_response.set()
            self.assertTrue(completed.wait(3))
        self.assertFalse(self.library.exists())

    def test_local_import_copies_only_validated_text_and_exports(self):
        source = self.root / "local-pack"
        source.mkdir()
        content = b"---\r\nname: ../../escaped\\review\r\ntags: quality, review\r\n---\r\n\r\n# Local\r\n"
        (source / "SKILL.md").write_bytes(content)
        (source / "helper.py").write_text("# A bundled module\n", encoding="utf-8")
        result = skills.import_local_skill(str(source), self.ws_id)
        target = Path(result["path"])
        self.assertEqual(result["slug"], "escaped-review")
        self.assertTrue(target.resolve().is_relative_to(self.library))
        self.assertEqual(list(target.parent.iterdir()), [target])
        self.assertEqual(target.read_bytes(), content)
        exported = skills.export_skill(result["id"], self.ws_id, self.workspace)
        self.assertEqual(exported["filename"], "SKILL.md")
        metadata = skills._parse_skill_text(exported["content"], "unused")
        self.assertEqual(metadata["category"], "general")
        self.assertEqual(metadata["tags"], ["quality", "review"])
        self.assertEqual(metadata["body"], "# Local")

        filename = source / "other.md"
        filename.write_bytes(b"x" * (skills.MAX_SKILL_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "128 KB"):
            skills.import_local_skill(str(filename), self.ws_id)
        with self.assertRaises(ValueError):
            skills._safe_slug("")
        self.assertEqual(
            skills._safe_slug("中文技能"),
            f"skill-{sha256('中文技能'.encode('utf-8')).hexdigest()[:12]}",
        )

    def test_local_and_destination_links_cannot_escape(self):
        external = self.root / "outside"
        external.mkdir()
        sentinel = external / "SKILL.md"
        sentinel.write_bytes(self.raw)
        self.library.mkdir()

        def link_directory(link):
            try:
                link.symlink_to(external, target_is_directory=True)
            except OSError:
                if os.name != "nt":
                    raise
                # NTFS junctions cover the same resolved-path boundary without Developer Mode.
                result = subprocess.run(
                    ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(external)],
                    capture_output=True, creationflags=config.NO_WINDOW_FLAGS, timeout=5,
                )
                self.assertEqual(result.returncode, 0, "Could not create a directory junction for the test")

        source = self.root / "source"
        source.mkdir()
        selected = source
        try:
            (source / "SKILL.md").symlink_to(sentinel)
        except OSError:
            if os.name != "nt":
                raise
            selected = self.root / "linked-source"
            link_directory(selected)
        link_directory(self.library / "remote-review")
        link_directory(self.workspace / ".agents")
        with self.assertRaisesRegex(ValueError, "符号链接"):
            skills.import_local_skill(str(selected), self.ws_id)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            skills.import_local_skill(str(sentinel), self.ws_id)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            skills.create_skill("new", "", "# New", "workspace", self.workspace, self.ws_id)
        self.assertEqual(sentinel.read_bytes(), self.raw)
        self.assertFalse(self.settings.exists())

    def test_new_skill_actions_use_existing_api_envelope(self):
        handler = server.WorkbenchHandler.__new__(server.WorkbenchHandler)
        handler.path = "/api/skills"
        handler._validate_host_and_origin = Mock(return_value=True)
        handler._authorize = Mock(return_value=True)
        handler._read_body = Mock(side_effect=[
            {"action": "preview_url", "url": self.base_url},
            {"action": "import_url", "url": self.base_url},
            {"action": "export", "id": "user:remote-review"},
        ])
        handler._send_json = Mock()
        workspace = {"id": self.ws_id, "path": str(self.workspace)}
        with (
            patch.object(config, "get_active_workspace", return_value=workspace),
            patch.object(server, "build_snapshot", return_value={"skills": []}) as snapshot,
            self._mock_github({self.base_url: (200, {}, self.raw)}),
        ):
            handler.do_POST()
            self.assertEqual(set(handler._send_json.call_args.args[0]), {"ok", "skill"})
            snapshot.assert_not_called()
            self.assertFalse(self.library.exists())
            handler.do_POST()
            self.assertIn("snapshot", handler._send_json.call_args.args[0])
            handler.do_POST()
            self.assertEqual(handler._send_json.call_args.args[0]["skill"]["filename"], "SKILL.md")
            snapshot.assert_called_once()


class WorkspaceRosterTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        patches = ExitStack()
        self.addCleanup(patches.close)
        isolated = (
            "ROLES_PATH", "ENGINES_PATH", "THREADS_PATH", "MESSAGES_PATH", "STATE_PATH", "WORKSPACES_PATH",
            "SKILLS_STATE_PATH", "NEXT_FOR_CODEX_PATH",
        )
        patches.enter_context(patch.multiple(config, **{name: self.root / name.lower() for name in isolated}))
        self.detect = patches.enter_context(patch.object(adapters, "detect_cli_status", return_value={}))
        patches.enter_context(patch.object(adapters, "load_model_settings", return_value={}))
        patches.enter_context(patch.object(server, "_WS_DISK_CACHE", {}))
        self.active = {"id": "a", "name": "Workspace A", "type": "general", "path": str(self.root)}
        patches.enter_context(patch.object(config, "get_active_workspace", side_effect=lambda: self.active))

    def _post(self, payload, expected_status=200):
        handler = server.WorkbenchHandler.__new__(server.WorkbenchHandler)
        handler.path = "/api/roles"
        handler._validate_host_and_origin = Mock(return_value=True)
        handler._authorize = Mock(return_value=True)
        handler._read_body = Mock(return_value=payload)
        handler._send_json = Mock()
        handler.do_POST()
        reply = handler._send_json.call_args.args
        self.assertEqual(reply[1] if len(reply) > 1 else 200, expected_status, reply[0])
        return reply[0]

    def _add_api_engine(self, name, model):
        return adapters.add_custom_engine({
            "name": name, "kind": "openai-compat", "base_url": "https://example.invalid/v1",
            "default_model": model, "api_key": "fixture-token",
        })["id"]

    def test_empty_environment_reports_unconfigured_slots_even_for_legacy_fake_defaults(self):
        config.write_json(config.ROLES_PATH, {"planner": {"engine": "agy", "model": "old-default"}})
        for roles in (
            adapters.default_role_bindings(),
            adapters.load_role_bindings("a"),
            adapters.recommend_workspace_roster("coding", "a")["roles"],
        ):
            self.assertEqual(set(roles), set(adapters.ROLE_SLOTS))
            for role in roles.values():
                self.assertEqual((role["engine"], role["model"], role["badge"]), ("", "", ""))
        with patch.object(adapters, "get_engine_by_id") as lookup:
            rc, reason = runner.JobManager()._run_slot_blocking("planner", "task", "", str(self.root), ws_id="a")
        self.assertNotEqual(rc, 0)
        self.assertIn("尚未配置", reason)
        lookup.assert_not_called()

    def test_custom_only_defaults_models_badges_and_engine_profiles(self):
        engine_id = self._add_api_engine("DeepSeek", "deepseek-chat")
        other = self._add_api_engine("Ollama Qwen", "qwen2.5:14b")
        self.assertTrue(all(role["engine"] == engine_id for role in adapters.default_role_bindings().values()))
        self.assertTrue(all(role["engine"] in (engine_id, other)
                            for role in adapters.recommend_workspace_roster("art-3d")["roles"].values()))
        adapters.save_role_bindings({"reviewer": {"engine": other, "model": "qwen2.5:14b"}}, "a")
        roles = adapters.load_role_bindings("a")
        self.assertEqual((roles["planner"]["badge"], roles["reviewer"]["badge"]), ("DS", "QWN"))
        badges = {
            "gpt-5.4": "GPT", "gpt-6.2-sol": "GPT", "claude-sonnet-4-5": "CLD", "gemini-2.5-pro": "GEM",
            "gemini-4-neon-high": "GEM", "deepseek-reasoner": "DSR", "deepseek-chat": "DS",
            "qwen2.5:14b": "QWN", "kimi-example": "KMI", "o3": "O3", "o4-mini": "O4M",
            "headless": "DSH", "my-model": "MYMO",
        }
        for model, badge in badges.items():
            with self.subTest(model=model):
                self.assertEqual(adapters.compute_model_badge(engine_id, model), badge)
        self.assertEqual(adapters.compute_model_badge("codex"), "CDX")
        self.assertEqual(adapters.compute_model_badge("", "gpt-5.4"), "")
        for engine in adapters.list_all_engines():
            self.assertTrue(engine["strength_zh"] and engine["strength_en"] and engine["capabilities"])
            self.assertNotIn("api_key", engine)
        self.detect.return_value = {"dsh": {"ready": True, "path": "dsh"}}
        self.assertTrue(all(role["engine"] == "dsh" for role in adapters.default_role_bindings().values()))

    def test_scope_and_scene_isolate_workspaces_through_pipeline_approval(self):
        a = self.active.copy()
        b = {**a, "id": "b", "name": "Workspace B"}
        engine = self._add_api_engine("Workspace Engine", "default-model")
        config.write_json(config.ROLES_PATH, {"planner": {"engine": engine, "custom_label": "Global planner"}})
        self.assertEqual(adapters.load_role_bindings("b")["planner"]["custom_label"], "Global planner")
        global_save = self._post({"scope": "global", "planner": {"custom_label": "Shared planner"}})
        self.assertEqual(global_save["snapshot"]["roles_scope"], "global")
        self.assertEqual(adapters.load_role_bindings("b")["planner"]["custom_label"], "Shared planner")
        roles = {
            slot: {"engine": engine, "model": f"a-{slot}", "system_prompt": f"Workspace A {slot}"}
            for slot in adapters.ROLE_SLOTS
        }
        self._post(roles)
        config.write_json(config.SKILLS_STATE_PATH, {"global_enabled": ["builtin:doc-writer"], "workspace_enabled": {}})
        skills_before = config.SKILLS_STATE_PATH.read_bytes()
        binding_a = adapters.load_role_bindings("a")
        job = runner.JobManager()
        tid = threads.ensure_workspace_thread("a")[0]["id"]
        with (
            patch.object(adapters, "stream_openai_compat", return_value=(0, "Engine reply")) as api,
            patch.object(config, "load_app_settings", return_value={"approve_before_build": True}),
        ):
            job._worker("reviewer", "Single review", False, a, Mock(), thread_id=tid)
            job._worker("planner", "Pipeline", True, a, Mock(), thread_id=tid)
            self.assertEqual(api.call_count, 2)
            self.active = b
            self._post({"roles": {"builder": {"custom_label": "B only"}}})
            self.detect.return_value = {"codex": {"ready": True, "path": "codex"}}
            response = self._post({"action": "apply_scene", "scene": "art-3d"})
            self.assertEqual(response["roles"]["builder"]["engine"], "codex")
            self.assertEqual(response["roles"]["builder"]["custom_label"], "建模与资产")
            self.assertEqual(response["snapshot"]["active_scene"], "art-3d")
            self.assertEqual(response["snapshot"]["roles_scope"], "workspace")
            self.assertEqual(len(response["snapshot"]["scenes"]), 5)
            self.assertEqual(response["recommended_skills"], ["art-3d-pipeline", "aigc-storyboard"])
            self.assertEqual(config.SKILLS_STATE_PATH.read_bytes(), skills_before)
            self.assertEqual(adapters.load_role_bindings("a"), binding_a)
            with patch.object(runner.threading, "Thread", side_effect=lambda **kw: Mock(start=kw["target"])):
                ok, _ = job.approve_pending("", Mock())
            self.assertTrue(ok)
        self.assertEqual(
            [(call.kwargs["model"], call.kwargs["system_prompt"]) for call in api.call_args_list],
            [(f"a-{slot}", f"Workspace A {slot}") for slot in ("reviewer", "planner", "builder", "reviewer")],
        )
        self._post({"action": "reset_workspace"})
        self.assertEqual(adapters.get_workspace_roster("b")["roles_scope"], "global")
        self.assertEqual(adapters.load_role_bindings("a"), binding_a)

    def test_preset_roundtrip_and_validation(self):
        engine = self._add_api_engine("Portable Engine", "qwen2.5:14b")
        applied = self._post({"action": "apply_scene", "scene": "paper-study"})
        preset = self._post({"action": "export_preset"})["preset"]
        self.assertEqual(preset["scene"], "paper-study")
        self.assertEqual(preset["recommended_skills"], ["paper-study", "deep-research"])
        self.assertNotIn("fixture-token", json.dumps(preset))
        self.active = {**self.active, "id": "b"}
        received = self._post({"action": "import_preset", "preset": json.loads(json.dumps(preset))})
        self.assertEqual(received["roles"], applied["roles"])
        self.assertEqual(self._post({"action": "export_preset"})["preset"], preset)
        self.assertFalse(config.SKILLS_STATE_PATH.exists())

        for invalid in (
            [], {**preset, "version": True}, {**preset, "scene": "unregistered"},
            {**preset, "recommended_skills": ["../invalid"]},
            {**preset, "roles": {**preset["roles"], "builder": {"engine": [engine]}}},
            {**preset, "roles": {**preset["roles"], "builder": {"system_prompt": "x" * 2001}}},
            {**preset, "roles": {**preset["roles"], "builder": {"command_template": "foreign"}}},
        ):
            with self.subTest(preset_type=type(invalid).__name__):
                before = config.ROLES_PATH.read_bytes()
                self.assertFalse(self._post({"action": "import_preset", "preset": invalid}, 400)["ok"])
                self.assertEqual(config.ROLES_PATH.read_bytes(), before)
        portable = json.loads(json.dumps(preset))
        portable["roles"]["builder"].update(engine="not-installed", model="foreign-model")
        result = self._post({"action": "import_preset", "preset": portable})
        self.assertEqual((result["roles"]["builder"]["engine"], result["roles"]["builder"]["model"]),
                         (engine, "qwen2.5:14b"))
        self.assertFalse(config.SKILLS_STATE_PATH.exists())

    def test_art_pipeline_and_blender_template_are_discoverable(self):
        builtin = [item for item in skills.list_skills("a", self.root) if item["source"] == "builtin"]
        self.assertEqual(len(builtin), 9)
        art = next(item for item in builtin if item["slug"] == "art-3d-pipeline")
        self.assertEqual(art["category"], "aigc")
        self.assertEqual(art["tags"], ["3d", "blender", "modeling", "concept-art", "assets"])
        self.assertIn(len(Path(art["path"]).read_text(encoding="utf-8").splitlines()), range(45, 76))
        template = next(item for item in mcp_manager.load_mcp_registry()["templates"] if item["id"] == "blender")
        self.assertEqual((template["title"], template["transport"], template["command"], template["args"]),
                         ("Blender 3D 建模桥接", "stdio", "uvx", ["blender-mcp"]))


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
