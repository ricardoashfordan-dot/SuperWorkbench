import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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

    def test_09_single_cli_default_role_binding(self):
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
