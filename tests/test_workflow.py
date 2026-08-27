#!/usr/bin/env python3
"""Minimal regression tests for gate-check, working set, grep, and budget."""

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, SCRIPTS)

import working_set  # noqa: E402
import workspace_init  # noqa: E402
import statem_driver  # noqa: E402
import viking_bridge  # noqa: E402
import statem_supervisor  # noqa: E402


class IsolatedWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="viking-test-")
        self.cwd = os.getcwd()
        os.chdir(self.tmp)
        working_set.set_project_root(self.tmp)
        workspace_init.generate_runbook_yaml(
            "demo", "reverse_engineering", 'crack "Foo" Pro', self.tmp
        )
        self.runbook = os.path.join(self.tmp, "runbook.yaml")

    def tearDown(self):
        os.chdir(self.cwd)
        working_set.set_project_root(None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _stdout(self, fn, *args, **kwargs):
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            result = fn(*args, **kwargs)
        return result, buf.getvalue()


class TestGateCheck(IsolatedWorkspace):
    def test_status_shows_task_name_and_gate(self):
        _, out = self._stdout(statem_driver.show_status, self.runbook)
        self.assertIn("demo_reverse_engineering", out)
        self.assertNotIn("Unnamed Task", out)
        self.assertIn("Thin binary and frameworks extracted in work/", out)

    def test_empty_advance_is_blocked(self):
        ok, failures, _ = statem_driver.evaluate_gate(self.runbook)
        self.assertFalse(ok)
        self.assertTrue(any("work/" in f or "evidence" in f for f in failures))
        with self.assertRaises(SystemExit) as cm:
            self._stdout(statem_driver.advance_state, self.runbook, check_gate=True)
        self.assertEqual(cm.exception.code, 1)
        data = statem_driver.load_runbook(self.runbook)
        self.assertEqual(data["current_state"], "unpack_and_extract")

    def test_gate_check_flag_exists(self):
        import subprocess
        proc = subprocess.run(
            [
                sys.executable,
                os.path.join(SCRIPTS, "statem_driver.py"),
                "--advance",
                "--gate-check",
                "--runbook",
                self.runbook,
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotIn("unrecognized arguments", proc.stderr)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Gate check", proc.stdout)

    def test_advance_after_evidence(self):
        os.makedirs(os.path.join(self.tmp, "work"))
        with open(os.path.join(self.tmp, "work", "thin.bin"), "w") as fh:
            fh.write("x")
        working_set.merge_checkpoint(confirmed=["thin binary at work/thin.bin"])
        ok, failures, _ = statem_driver.evaluate_gate(self.runbook)
        self.assertTrue(ok, failures)
        self._stdout(statem_driver.advance_state, self.runbook, check_gate=True)
        data = statem_driver.load_runbook(self.runbook)
        self.assertEqual(data["current_state"], "symbol_and_disasm")

    def test_second_advance_needs_new_evidence(self):
        os.makedirs(os.path.join(self.tmp, "work"))
        with open(os.path.join(self.tmp, "work", "thin.bin"), "w") as fh:
            fh.write("x")
        working_set.merge_checkpoint(confirmed=["thin binary at work/thin.bin"])
        self._stdout(statem_driver.advance_state, self.runbook, check_gate=True)
        ok, failures, _ = statem_driver.evaluate_gate(self.runbook)
        self.assertFalse(ok)
        self.assertTrue(any("no new working-set evidence" in f for f in failures))

    def test_force_skips_gate(self):
        self._stdout(statem_driver.advance_state, self.runbook, check_gate=True, force=True)
        data = statem_driver.load_runbook(self.runbook)
        self.assertEqual(data["current_state"], "symbol_and_disasm")

    def test_yaml_prompt_quotes(self):
        data = statem_driver.load_runbook(self.runbook)
        self.assertEqual(data.get("description"), 'crack "Foo" Pro')


class TestWorkingSet(IsolatedWorkspace):
    def test_long_facts_are_clipped(self):
        blob = "x" * 2000
        working_set.merge_checkpoint(confirmed=[blob], next_action="n" * 800)
        data = working_set.load_checkpoint()
        self.assertLessEqual(len(data["confirmed"][0]["fact"]), working_set.MAX_FACT_LEN)
        self.assertTrue(data["confirmed"][0]["fact"].endswith("…"))
        self.assertLessEqual(len(data["next_action"]), working_set.MAX_NEXT_ACTION_LEN)
        slice_txt = working_set.checkpoint_prompt_slice()
        self.assertNotIn("x" * 500, slice_txt)

    def test_checkpoint_dedup_and_paths_use_project_root(self):
        working_set.merge_checkpoint(confirmed=["addr 0x1000"])
        working_set.merge_checkpoint(confirmed=["addr 0x1000"])
        data = working_set.load_checkpoint()
        self.assertEqual(len(data["confirmed"]), 1)
        self.assertTrue(working_set.checkpoint_file().startswith(self.tmp))

    def test_cwd_does_not_steal_state(self):
        working_set.merge_checkpoint(confirmed=["root fact"])
        nested = os.path.join(self.tmp, "work", "nested")
        os.makedirs(nested)
        os.chdir(nested)
        self.assertEqual(working_set.project_root(), self.tmp)
        data = working_set.load_checkpoint()
        self.assertEqual(data["confirmed"][0]["fact"], "root fact")

    def test_auto_synthesize_skips_auto_hits(self):
        working_set.append_discovery("auto", "tbnz w8, #0, 0x1000", source="objdump")
        working_set.append_discovery("confirmed", "gate at 0x2000", source="note")
        data = working_set.auto_synthesize_checkpoint(reason="test")
        facts = [c.get("fact") for c in data["confirmed"]]
        self.assertIn("gate at 0x2000", facts)
        self.assertTrue(all("tbnz" not in (f or "") for f in facts))

    def test_sprint_budget_drain_and_yield(self):
        working_set.reset_sprint_budget()
        statuses = [working_set.sprint_guard() for _ in range(8)]
        self.assertEqual(statuses[:5], ["ok"] * 5)
        self.assertEqual(statuses[5:7], ["drain", "drain"])
        self.assertEqual(statuses[7], "yield")
        self.assertEqual(working_set.read_sprint_count(), 8)


class TestBridge(IsolatedWorkspace):
    def setUp(self):
        super().setUp()
        self._vfs = os.path.join(self.tmp, "ov_backup")
        os.makedirs(self._vfs, exist_ok=True)
        self._vfs_patch = mock.patch.object(viking_bridge, "LOCAL_VFS_BACKUP", self._vfs)
        self._vfs_patch.start()

    def tearDown(self):
        self._vfs_patch.stop()
        super().tearDown()

    def test_vfs_relpath_rejects_traversal(self):
        with self.assertRaises(ValueError):
            viking_bridge.vfs_relpath("viking://../../etc/passwd")
        rel = viking_bridge.vfs_relpath("viking://knowledge/demo/a.txt")
        self.assertEqual(rel, os.path.join("knowledge", "demo", "a.txt"))

    def test_grep_exit_codes(self):
        rel = os.path.join(self.tmp, ".viking_vfs", "knowledge", "sample.txt")
        os.makedirs(os.path.dirname(rel), exist_ok=True)
        with open(rel, "w", encoding="utf-8") as f:
            f.write("hello Unlicensed world\nsecond line\n")
        uri = "viking://knowledge/sample.txt"
        working_set.reset_sprint_budget()
        with mock.patch.object(viking_bridge, "_http_request", return_value={"error": "offline"}):
            code_hit, _ = self._stdout(viking_bridge.grep_vfs, uri, "Unlicensed")
            working_set.reset_sprint_budget()
            code_miss, _ = self._stdout(viking_bridge.grep_vfs, uri, "definitely-not-here-xyz")
            working_set.reset_sprint_budget()
            code_bad, _ = self._stdout(viking_bridge.grep_vfs, uri, "(")
            working_set.reset_sprint_budget()
            code_missing, _ = self._stdout(viking_bridge.grep_vfs, "viking://knowledge/nope.txt", "x")
        self.assertEqual(code_hit, 0)
        self.assertEqual(code_miss, 1)
        self.assertEqual(code_bad, 2)
        self.assertEqual(code_missing, 1)

    def test_run_failure_does_not_record_artifact(self):
        working_set.reset_sprint_budget()
        code, _ = self._stdout(
            viking_bridge.run_command,
            "exit 7",
            "viking://knowledge/failed.txt",
        )
        self.assertEqual(code, 7)
        self.assertEqual(working_set.load_checkpoint().get("artifacts"), [])

    def test_run_success_records_artifact(self):
        working_set.reset_sprint_budget()
        code, _ = self._stdout(
            viking_bridge.run_command,
            "echo hello",
            "viking://knowledge/ok.txt",
        )
        self.assertEqual(code, 0)
        self.assertIn("viking://knowledge/ok.txt", working_set.load_checkpoint()["artifacts"])

    def test_run_timeout(self):
        working_set.reset_sprint_budget()
        code, out = self._stdout(
            viking_bridge.run_command,
            "sleep 30",
            "viking://knowledge/slow.txt",
            timeout_sec=1,
        )
        self.assertEqual(code, 124)
        self.assertIn("timed out", out)

    def test_grep_streams_without_get_vfs(self):
        rel = os.path.join(self.tmp, ".viking_vfs", "knowledge", "big.txt")
        os.makedirs(os.path.dirname(rel), exist_ok=True)
        with open(rel, "w", encoding="utf-8") as f:
            f.write("noise\n" * 5000)
            f.write("needle Unlicensed here\n")
            f.write("noise\n" * 5000)
        uri = "viking://knowledge/big.txt"
        working_set.reset_sprint_budget()
        with mock.patch.object(viking_bridge, "get_vfs", side_effect=AssertionError("must not slurp")):
            code, out = self._stdout(viking_bridge.grep_vfs, uri, "Unlicensed")
        self.assertEqual(code, 0)
        self.assertIn("Unlicensed", out)
        self.assertLess(out.count("noise"), 20)

    def test_run_offload_does_not_inline_body(self):
        working_set.reset_sprint_budget()
        code, out = self._stdout(
            viking_bridge.run_command,
            "python3 -c \"[print(i) for i in range(80)]\"",
            "viking://knowledge/many.txt",
            max_lines=40,
        )
        self.assertEqual(code, 0)
        self.assertIn("VIKING INTERCEPTOR", out)
        self.assertNotIn("\n  50\n", "\n" + out)
        dest = viking_bridge.resolve_local_node("viking://knowledge/many.txt")
        self.assertTrue(dest and os.path.isfile(dest))
        with open(dest, encoding="utf-8") as f:
            self.assertGreaterEqual(sum(1 for _ in f), 80)

    def test_get_previews_large_node(self):
        path = os.path.join(self._vfs, "knowledge", "huge.txt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for i in range(100):
                f.write(f"line-{i}\n")
        code, out = self._stdout(viking_bridge.print_vfs_preview, "viking://knowledge/huge.txt")
        self.assertEqual(code, 0)
        self.assertIn("too large to dump", out)
        self.assertIn("line-0", out)
        self.assertNotIn("line-50", out)

    def test_sprint_done_prints_four_lines(self):
        code, out = self._stdout(
            viking_bridge.sprint_done,
            "DONE",
            confirmed=["gate at 0x1000"],
            next_action="xref next",
        )
        self.assertEqual(code, 0)
        lines = [ln for ln in out.splitlines() if ln.startswith(
            ("SPRINT_STATUS:", "CONFIRMED:", "REJECTED:", "NEXT:")
        )]
        self.assertEqual(len(lines), 4)
        self.assertTrue(out.strip().endswith("NEXT: xref next"))
        self.assertIn("gate at 0x1000", working_set.load_checkpoint()["confirmed"][0]["fact"])


class TestSupervisor(unittest.TestCase):
    def test_permission_denied_is_recoverable(self):
        cat, _, _ = statem_supervisor.classify_error("open: Permission denied")
        self.assertEqual(cat, "RECOVERABLE")

    def test_exit_zero_without_sprint_status_is_not_done(self):
        self.assertEqual(statem_supervisor._sprint_status_from_output("ok\n", 0), "UNKNOWN")
        self.assertEqual(
            statem_supervisor._sprint_status_from_output("SPRINT_STATUS: DONE\n", 0),
            "DONE",
        )


class TestParentHalt(IsolatedWorkspace):
    def test_supervisor_prints_parent_halt(self):
        _, out = self._stdout(
            statem_supervisor.supervise_phase, self.runbook, sprint_goal="unpack only"
        )
        self.assertIn("PARENT HALT", out)
        self.assertIn("Do NOT: bash / sleep / list_agents", out)
        self.assertIn("PROMPT_FILE:", out)
        self.assertIn("DISPATCH_PROMPT:", out)
        self.assertNotIn("Working set (do not re-derive", out)
        prompt_path = working_set.sprint_prompt_file()
        self.assertTrue(os.path.isfile(prompt_path))
        with open(prompt_path, encoding="utf-8") as f:
            body = f.read()
        self.assertIn("Working set (do not re-derive", body)
        self.assertIn("unpack only", body)
        self.assertIn("sprint-done", body)


if __name__ == "__main__":
    unittest.main()
