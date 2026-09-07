"""Regression checks for transcript identity and resume lineage extraction.

Run with: python3 -m unittest discover -s tests
"""

import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = (Path(__file__).resolve().parents[1]
          / "skills/resume-lite/scripts/session-transcript")
TRANSCRIPT = runpy.run_path(str(SCRIPT))
IDS = [f"{i:08x}-1111-4111-8111-{i:012x}" for i in range(1, 9)]


def tool_record(command, provider):
    if provider == "claude":
        return {"type": "assistant", "message": {"content": [{
            "type": "tool_use", "name": "Bash", "input": {"command": command},
        }]}}
    return {"type": "response_item", "payload": {
        "type": "function_call", "name": "exec_command",
        "arguments": json.dumps({"cmd": command}),
    }}


def lineage(record, provider):
    session = TRANSCRIPT["Session"](Path("fixture.jsonl"), provider, IDS[-1], [record])
    return TRANSCRIPT["lineage_ids"](session)


class LineageTests(unittest.TestCase):
    def assert_command(self, command, expected):
        for provider in ("claude", "codex"):
            with self.subTest(provider=provider, command=command):
                self.assertEqual(lineage(tool_record(command, provider), provider), expected)

    def test_full_and_quoted_script_paths_keep_all_arguments(self):
        for script in ("./session-transcript",
                       '"/tmp/my skills/resume-lite/scripts/session-transcript"',
                       "'/tmp/my skills/resume-lite/scripts/session-transcript'"):
            self.assert_command(f"python3 {script} " + " ".join(IDS[:6]), IDS[:6])

    def test_skill_paths_are_not_invocations(self):
        for path in ("/tmp/skills/resume-lite/SKILL.md", "/tmp/resume-lite",
                     "./resume-lite/SKILL.md", "/resume-lite/SKILL.md"):
            self.assert_command(f"cat {path} && echo {IDS[0]}", [])

    def test_script_stops_at_shell_boundaries(self):
        for separator in (" && ", "; ", " | ", "\n"):
            self.assert_command(
                f"python3 /tmp/resume-lite/scripts/session-transcript {IDS[0]}"
                f"{separator}echo {IDS[1]}", IDS[:1])

    def test_typed_invocations(self):
        for command in ("/resume-lite", "$resume-lite"):
            prompt = f"Please resume using {command} " + " ".join(IDS[:5]) + " --deep"
            self.assertEqual(lineage({"type": "user", "message": {"content": prompt}},
                                     "claude"), IDS[:5])
            self.assertEqual(lineage({"type": "event_msg", "payload": {
                "type": "user_message", "message": prompt}}, "codex"), IDS[:5])

    def test_typed_invocations_stop_at_shell_boundaries(self):
        self.assert_command(f"/resume-lite {IDS[0]} && echo {IDS[1]}", IDS[:1])

    def test_claude_structured_invocation(self):
        prompt = ("<command-name>/resume-lite</command-name>"
                  f"<command-args>{' '.join(IDS[:5])}</command-args>")
        self.assertEqual(lineage({"type": "user", "message": {"content": prompt}},
                                 "claude"), IDS[:5])

    def test_quoted_ids_and_flags(self):
        self.assert_command(f'python3 ./session-transcript --deep "{IDS[0]}" '
                            f'"{IDS[1]}" --out /tmp/transcript.md', IDS[:2])

    def test_transcript_reads(self):
        self.assert_command(f"cat /tmp/session-transcript/{IDS[0]}/summary.md", IDS[:1])

    def test_codex_json_fields_do_not_supply_extra_parents(self):
        record = tool_record(f"python3 ./session-transcript {IDS[0]}", "codex")
        record["payload"]["arguments"] = json.dumps({
            "cmd": f"python3 ./session-transcript {IDS[0]}",
            "justification": f"Unrelated {IDS[1]}",
        })
        self.assertEqual(lineage(record, "codex"), IDS[:1])

    def test_codex_custom_tool_input(self):
        for command, expected in (
            ("python3 ./session-transcript " + " ".join(IDS[:6]), IDS[:6]),
            (f"cat /tmp/resume-lite/SKILL.md && echo {IDS[0]}", []),
            (f"python3 ./session-transcript {IDS[0]}\necho {IDS[1]}", IDS[:1]),
        ):
            record = {"type": "response_item", "payload": {
                "type": "custom_tool_call", "name": "shell", "input": command}}
            with self.subTest(command=command):
                self.assertEqual(lineage(record, "codex"), expected)

    def test_assistant_prose_and_tool_results_are_ignored(self):
        text = f"/resume-lite {IDS[0]}"
        records = [
            ("claude", {"type": "assistant", "message": {"content": text}}),
            ("claude", {"type": "user", "message": {"content": [
                {"type": "tool_result", "content": text}]}}),
            ("codex", {"type": "event_msg", "payload": {
                "type": "agent_message", "message": text}}),
            ("codex", {"type": "response_item", "payload": {
                "type": "function_call_output", "output": text}}),
        ]
        for provider, record in records:
            with self.subTest(provider=provider, record=record):
                self.assertEqual(lineage(record, provider), [])


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="resume-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = []
        for i, sid in enumerate(IDS):
            path = self.root / f"{sid}.jsonl"
            records = [
                {"type": "session_meta", "timestamp": f"2026-09-0{i + 1}T12:00:00Z",
                 "payload": {"id": sid, "cwd": str(self.root)}},
                {"type": "event_msg", "payload": {
                    "type": "user_message", "message": f"Topic {i}"}},
            ]
            path.write_text("\n".join(map(json.dumps, records)), encoding="utf-8")
            self.paths.append(path)

    def invoke(self, *args):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)], cwd=self.root,
            env={**os.environ, "TMPDIR": str(self.root)},
            text=True, capture_output=True, check=True, timeout=10,
        )
        path = Path(result.stdout.strip().splitlines()[-1])
        return path if path.is_absolute() else self.root / path

    def test_different_combinations_preserve_previous_outputs(self):
        combinations = [
            (self.paths[:2], [self.paths[0], self.paths[2]]),
            (self.paths[:3], [self.paths[0], self.paths[2], self.paths[1]]),
            (self.paths[:5], self.paths[:4] + [self.paths[5]]),
            (self.paths[:6], self.paths[:4] + [self.paths[5], self.paths[4]]),
        ]
        for flags in ([], ["--save"]):
            for left, right in combinations:
                with self.subTest(flags=flags, left=left, right=right):
                    first = self.invoke(*left, *flags)
                    original = first.read_text(encoding="utf-8")
                    second = self.invoke(*right, *flags)
                    self.assertNotEqual(first, second)
                    self.assertEqual(first.read_text(encoding="utf-8"), original)
                    self.assertEqual(self.invoke(*left, *flags), first)

    def test_combined_identity_uses_full_ids(self):
        changed = IDS[1][:-1] + "f"  # same short prefix, different session
        path = TRANSCRIPT["combined_out_path"]
        self.assertNotEqual(path(IDS[:2]), path([IDS[0], changed]))

    def test_absolute_relative_and_symlink_inputs_are_deduplicated(self):
        alias = self.root / "alias.jsonl"
        alias.symlink_to(self.paths[0])
        out = self.invoke(self.paths[0], self.paths[0].name, alias)
        self.assertEqual(out.name, "summary.md")
        self.assertEqual(out.parent.name, IDS[0])
        self.assertEqual(out.read_text(encoding="utf-8").splitlines()[0],
                         f"# Session transcript — `{IDS[0]}`")

    def test_single_session_paths_are_unchanged(self):
        out = self.invoke(self.paths[0])
        self.assertEqual(out.name, "summary.md")
        self.assertEqual(out.parent.name, IDS[0])
        saved = self.invoke(self.paths[0], "--save")
        self.assertRegex(saved.name, r"^2026-09-0[12]-topic-0-00000001\.md$")
        self.assertEqual(saved.parent, self.root / "transcripts")

    def test_explicit_session_order_and_rendering(self):
        out = self.invoke(self.paths[2], self.paths[0], self.paths[1])
        text = out.read_text(encoding="utf-8")
        positions = [text.index(f"# Session {i} of 3 — `{sid}`")
                     for i, sid in enumerate([IDS[2], IDS[0], IDS[1]], 1)]
        self.assertEqual(positions, sorted(positions))
        for i in range(3):
            self.assertIn(f"## 👤 User\n\nTopic {i}", text)

    def test_transitive_lineage_terminates_cycles_and_sorts_by_time(self):
        for i, parent in enumerate([IDS[2], IDS[0], IDS[1]]):
            with self.paths[i].open("a", encoding="utf-8") as stream:
                stream.write("\n" + json.dumps({"type": "event_msg", "payload": {
                    "type": "user_message", "message": f"$resume-lite {parent}"}}))
        load = TRANSCRIPT["load_session"]
        follow = TRANSCRIPT["follow_lineage"]
        lookup = {sid: [(path, "codex")] for sid, path in zip(IDS, self.paths)}
        with patch.dict(follow.__globals__, {
            "session_hits": lambda sid: (sid, lookup.get(sid, [])),
        }), contextlib.redirect_stderr(io.StringIO()):
            sessions, parents = follow([load(self.paths[2], "codex")])
        self.assertEqual(len(sessions), 3)
        sessions.sort(key=TRANSCRIPT["session_start"])
        self.assertEqual([session.id for session in sessions], IDS[:3])
        self.assertEqual(parents, {IDS[0]: [IDS[2]], IDS[1]: [IDS[0]], IDS[2]: [IDS[1]]})
        text = TRANSCRIPT["build_combined"](sessions, True, parents)
        for i, sid in enumerate(IDS[:3], 1):
            self.assertIn(f"# Session {i} of 3 — `{sid}`", text)


if __name__ == "__main__":
    unittest.main()
