"""Regression checks for transcript identity and resume lineage extraction.

Run with: python3 -m unittest discover -s tests
"""

import contextlib
import filecmp
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


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "skills/resume-lite/scripts/session-transcript"
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
                            f'"{IDS[1]}" --no-tools', IDS[:2])

    def test_exports_are_not_resumes(self):
        # /export-lite keeps a copy of a session; it doesn't continue it.
        for flags in ("--save", "--out /tmp/transcript.md", "--out=notes/",
                      "--to notes/", "--to=notes/x.md", "--deep --save --no-tools",
                      '"--save"', "'--to' notes/", '"--out=notes/"',
                      "\\\n  --save", "--deep \\\r\n --to notes/"):
            self.assert_command(f'python3 ./session-transcript "{IDS[0]}" {flags}', [])
        # Only the invocation's own flags count, not a later command's.
        self.assert_command(f"python3 ./session-transcript {IDS[0]} && echo --save",
                            IDS[:1])
        for prompt in (f"/resume-lite {IDS[0]} --save",
                       "<command-name>/resume-lite</command-name>"
                       f"<command-args>{IDS[0]} --save</command-args>"):
            self.assertEqual(lineage({"type": "user", "message": {"content": prompt}},
                                     "claude"), [])

    def test_codex_code_mode_exec(self):
        # Code mode runs commands from JS: string literals keep `\n` and `\"`
        # escaped inside the record's raw input.
        def exec_record(cmd):
            source = (f"const r = await tools.exec_command({{cmd: {json.dumps(cmd)}}});"
                      "\ntext(r.output);")
            return {"type": "response_item", "payload": {
                "type": "custom_tool_call", "name": "exec", "input": source}}

        script = "python3 ./session-transcript"
        for cmd, expected in (
            (f"{script} {IDS[0]} {IDS[1]}", IDS[:2]),
            (f"{script} {IDS[0]}\necho {IDS[1]}", IDS[:1]),
            (f'{script} "{IDS[0]}" "--save"', []),
            (f"{script} {IDS[0]} --save\nls", []),
            (f"{script} {IDS[0]}\n{script} {IDS[1]} --to notes/", IDS[:1]),
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual(lineage(exec_record(cmd), "codex"), expected)

    def test_line_continuations_keep_one_command(self):
        self.assert_command(f"python3 ./session-transcript {IDS[0]} \\\n  {IDS[1]}",
                            IDS[:2])

    def test_prose_fields_describing_a_tool_call_are_ignored(self):
        # The exported command is filtered out; its prose must not re-add the id.
        command = f"python3 ./session-transcript {IDS[0]} --save"
        prose = f"Export it: session-transcript {IDS[0]}"
        claude = {"type": "assistant", "message": {"content": [{
            "type": "tool_use", "name": "Bash",
            "input": {"command": command, "description": prose}}]}}
        codex = tool_record(command, "codex")
        codex["payload"]["arguments"] = json.dumps({"cmd": command,
                                                    "justification": prose})
        self.assertEqual(lineage(claude, "claude"), [])
        self.assertEqual(lineage(codex, "codex"), [])

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

    def run_script(self, *args, env=None):
        environ = {**os.environ, "TMPDIR": str(self.root)}
        for name in TRANSCRIPT["CURRENT_SESSION_ENV"]:  # don't inherit the
            environ.pop(name, None)  # harness running these tests
        environ.update(env or {})
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)], cwd=self.root,
            env=environ, text=True, capture_output=True, timeout=10,
        )

    def invoke(self, *args, env=None):
        result = self.run_script(*args, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = Path(result.stdout.strip().splitlines()[-1])
        return path if path.is_absolute() else self.root / path

    def assert_rejected(self, *args, message, env=None):
        result = self.run_script(*args, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

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

    def test_out_to_a_directory_uses_the_save_name(self):
        name = self.invoke(self.paths[0], "--save").name
        (self.root / "existing").mkdir()
        absolute = self.root / "absolute"
        for target, folder in (("existing", self.root / "existing"),
                               ("fresh/", self.root / "fresh"),
                               ("nested/deeper/", self.root / "nested/deeper"),
                               (f"{absolute}/", absolute),
                               (".", self.root)):
            with self.subTest(target=target):
                out = self.invoke(self.paths[0], "--out", target)
                self.assertEqual(out, folder / name)
                self.assertEqual(out.read_text(encoding="utf-8").splitlines()[0],
                                 f"# Session transcript — `{IDS[0]}`")
        combined = self.invoke(self.paths[0], self.paths[1], "--save").name
        self.assertEqual(self.invoke(self.paths[0], self.paths[1], "--out", "fresh/"),
                         self.root / "fresh" / combined)

    def test_out_to_a_file_path_is_exact(self):
        for flag in ("--out", "--to"):
            for target in ("exact.md", "sub/dir/exact.md", "no-extension"):
                with self.subTest(flag=flag, target=target):
                    out = self.invoke(self.paths[0], flag, target)
                    self.assertEqual(out, self.root / target)
                    self.assertTrue(out.is_file())

    def test_to_is_an_alias_of_out(self):
        name = self.invoke(self.paths[0], "--save").name
        self.assertEqual(self.invoke(self.paths[0], "--to", "kept/"),
                         self.root / "kept" / name)
        self.assert_rejected(self.paths[0], "--to", "a.md", "--save",
                             message="not allowed with")

    def test_out_expands_home(self):
        home = self.root / "home"
        name = self.invoke(self.paths[0], "--save").name
        out = self.invoke(self.paths[0], "--out", "~/exports/",
                          env={"HOME": str(home)})
        self.assertEqual(out, home / "exports" / name)
        self.assertEqual(self.invoke(self.paths[0], "--out", "~/one.md",
                                     env={"HOME": str(home)}), home / "one.md")

    def test_out_takes_either_windows_separator(self):
        sessions = [TRANSCRIPT["load_session"](self.paths[0], "codex")]
        out_path = TRANSCRIPT["out_path"]
        name = TRANSCRIPT["save_out_path"](sessions).name
        with patch.object(os, "sep", "\\"), patch.object(os, "altsep", "/"):
            for target in ("notes\\", "notes/"):
                with self.subTest(target=target):
                    self.assertEqual(out_path(target, sessions), Path(target) / name)
        if os.altsep is None:  # POSIX: a backslash is just part of a file name
            self.assertEqual(out_path("notes\\", sessions), Path("notes\\"))

    def test_unwritable_out_paths_fail_cleanly(self):
        (self.root / "notes").write_text("not a folder", encoding="utf-8")
        self.assert_rejected(self.paths[0], "--out", "notes/",
                             message="notes/: not a directory")
        self.assert_rejected(self.paths[0], "--out", "notes/inner.md",
                             message="cannot write")
        self.assertEqual((self.root / "notes").read_text(encoding="utf-8"),
                         "not a folder")

    def test_bad_arguments_are_rejected(self):
        self.assert_rejected("", message="empty session id")
        for flag in ("--out", "--to"):
            self.assert_rejected(self.paths[0], flag, "", message="needs a path")
            self.assert_rejected(flag, "x.md", message="need a session id")
        self.assert_rejected("--save", message="need a session id")
        # No abbreviations: `--sa` mustn't quietly mean --save.
        self.assert_rejected(self.paths[0], "--sa", message="unrecognized arguments")
        self.assertFalse((self.root / "transcripts").exists())

    def test_this_is_the_current_session(self):
        home = self.root / "home"
        codex = self.root / "codex"
        (codex / "sessions").mkdir(parents=True)
        (codex / "sessions" / f"rollout-2026-09-01T12-00-00-{IDS[0]}.jsonl") \
            .write_bytes(self.paths[0].read_bytes())
        claude = home / ".claude" / "projects" / "-elsewhere"
        claude.mkdir(parents=True)
        (claude / f"{IDS[1]}.jsonl").write_text(json.dumps({
            "type": "user", "message": {"content": "Claude topic"},
            "timestamp": "2026-09-02T12:00:00Z", "cwd": str(self.root)}),
            encoding="utf-8")
        env = {"HOME": str(home), "CODEX_HOME": str(codex)}
        for word, current, expected in (
            ("this", {"CODEX_THREAD_ID": IDS[0]}, IDS[0]),
            ("This", {"CLAUDE_CODE_SESSION_ID": IDS[1]}, IDS[1]),
            ("THIS", {"CODEX_THREAD_ID": IDS[0], "CLAUDE_CODE_SESSION_ID": IDS[0]},
             IDS[0]),
        ):
            with self.subTest(word=word, current=current):
                out = self.invoke(word, env={**env, **current})
                self.assertEqual(out.parent.name, expected)
        self.assert_rejected("this", env=env, message="CODEX_THREAD_ID")
        self.assert_rejected("this", env={**env, "CODEX_THREAD_ID": " "},
                             message="CLAUDE_CODE_SESSION_ID")

        # Nested harnesses set both: the one writing its session now is inner.
        codex_file = codex / "sessions" / f"rollout-2026-09-01T12-00-00-{IDS[0]}.jsonl"
        claude_file = claude / f"{IDS[1]}.jsonl"
        both = {**env, "CODEX_THREAD_ID": IDS[0], "CLAUDE_CODE_SESSION_ID": IDS[1]}
        for newer, older, expected, name in (
            (claude_file, codex_file, IDS[1], "CLAUDE_CODE_SESSION_ID"),
            (codex_file, claude_file, IDS[0], "CODEX_THREAD_ID"),
        ):
            with self.subTest(expected=expected):
                os.utime(older, (1_000_000, 1_000_000))
                os.utime(newer, (2_000_000, 2_000_000))
                result = self.run_script("this", env=both)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(Path(result.stdout.splitlines()[-1]).parent.name,
                                 expected)
                self.assertIn(f"this: {expected} (from {name}", result.stderr)

    def test_kept_exports_drop_the_resume_instruction(self):
        resume = "continue the work"
        for paths in (self.paths[:1], self.paths[:2]):
            with self.subTest(sessions=len(paths)):
                self.assertIn(resume, self.invoke(*paths).read_text(encoding="utf-8"))
                for flags in (["--save"], ["--out", "kept/"], ["--to", "kept.md"]):
                    text = self.invoke(*paths, *flags).read_text(encoding="utf-8")
                    self.assertIn(TRANSCRIPT["EXPORT_BLURB"], text)
                    self.assertNotIn(resume, text)

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


def frontmatter(text):
    """The `key: value` lines of a SKILL.md's leading `---` block."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        key, sep, value = line.partition(":")
        if sep and not line[:1].isspace():
            fields[key.strip()] = value.strip().strip("'\"")
    return {}  # never closed: not frontmatter


class PackagingTests(unittest.TestCase):
    def test_every_skill_ships_the_same_script(self):
        # Each skill carries a real copy (`npx skills update` compares each
        # skill folder's tree hash, so a symlink would never pick up changes).
        skills = sorted(p.parent for p in (REPO / "skills").glob("*/SKILL.md"))
        self.assertIn(REPO / "skills/export-lite", skills)
        fix = "edit only the resume-lite copy, then run scripts/sync-skill-scripts"
        for skill in skills:
            script = skill / "scripts" / "session-transcript"
            with self.subTest(skill=skill.name):
                self.assertFalse(script.is_symlink(), f"{script} is a symlink; {fix}")
                self.assertTrue(script.is_file(), f"{script} is missing; {fix}")
                self.assertTrue(filecmp.cmp(script, SCRIPT, shallow=False),
                                f"{script} differs from {SCRIPT}; {fix}")
                self.assertTrue(os.access(script, os.X_OK),
                                f"{script} is not executable; {fix}")
                subprocess.run([sys.executable, str(script), "--help"],
                               capture_output=True, check=True, timeout=10)
                text = (skill / "SKILL.md").read_text(encoding="utf-8")
                self.assertEqual(frontmatter(text).get("name"), skill.name)

    def test_frontmatter_parsing(self):
        text = "---\nname: x\ndescription: a --- b: c\n  name: nested\n---\nname: body\n"
        self.assertEqual(frontmatter(text), {"name": "x", "description": "a --- b: c"})
        self.assertEqual(frontmatter("---\nname: x\n"), {})
        self.assertEqual(frontmatter("# no frontmatter\nname: x\n"), {})


if __name__ == "__main__":
    unittest.main()
