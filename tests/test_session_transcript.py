"""Regression checks for transcript identity and resume lineage extraction.

Run with: python3 -m unittest discover -s tests
"""

import contextlib
import datetime
import filecmp
import io
import json
import os
from pathlib import Path
import re
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

    def test_recaps_are_not_resumes(self):
        # A recap names only the sessions it leaves out.
        self.assert_command(f"python3 ./session-transcript --recent 3 --exclude {IDS[0]}",
                            [])
        self.assert_command(f"python3 ./session-transcript --exclude={IDS[0]} --recent=3",
                            [])

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
        self.assertRegex(saved.name, r"^2026-09-0[12]-topic-0\.md$")
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

    def write_session(self, sid, day, topic, reply="ok", more=()):
        """A Codex session started on 2026-09-<day> with `topic` (or no prompt),
        then `more` (prompt, reply) pairs."""
        records = [{"type": "session_meta", "timestamp": f"2026-09-{day:02d}T12:00:00Z",
                    "payload": {"id": sid, "cwd": str(self.root)}}]
        if topic:
            records.append({"type": "event_msg", "payload": {
                "type": "user_message", "message": topic}})
        records.append({"type": "event_msg", "payload": {
            "type": "agent_message", "message": reply}})
        for prompt, answer in more:
            records += [{"type": "event_msg", "payload": {"type": "user_message", "message": prompt}},
                        {"type": "event_msg", "payload": {"type": "agent_message", "message": answer}}]
        path = self.root / f"{sid}.jsonl"
        path.write_text("\n".join(map(json.dumps, records)), encoding="utf-8")
        return path

    def test_save_names_and_collisions(self):
        ids = [f"a{i:07x}-2222-4222-8222-{i:012x}" for i in range(1, 5)]
        paths = [self.write_session(sid, 5, "Fix the parser") for sid in ids[:3]]
        names = [self.invoke(path, "--save") for path in paths]
        base = self.root / "transcripts" / "2026-09-05-fix-the-parser.md"
        self.assertEqual(names, [base, base.with_name(base.stem + "-2.md"),
                                 base.with_name(base.stem + "-3.md")])
        # Re-exporting a session that moved on refreshes its own file.
        self.write_session(ids[1], 5, "Fix the parser", more=[("and?", "now with more")])
        self.assertEqual(self.invoke(paths[1], "--save"), names[1])
        self.assertIn("now with more", names[1].read_text(encoding="utf-8"))
        for name, sid in zip(names, ids):
            self.assertEqual(TRANSCRIPT["_file_signature"](name),
                             ("single", (sid,), None, "tools"))
        # --to DIR/ follows the same rule; an exact --to FILE stays exact.
        kept = [self.invoke(path, "--to", "kept/") for path in paths[:2]]
        self.assertEqual([p.name for p in kept], [base.name, base.stem + "-2.md"])
        self.assertEqual(self.invoke(paths[0], "--to", "kept/"), kept[0])

    def test_a_file_that_is_not_ours_is_never_overwritten(self):
        sid = "b0000001-2222-4222-8222-000000000001"
        path = self.write_session(sid, 6, "Notes")
        target = self.root / "transcripts" / "2026-09-06-notes.md"
        target.parent.mkdir()
        for content in ("my own notes\n", f"# Session transcript — `{sid}`\nbut no header end"):
            with self.subTest(content=content):
                target.write_text(content, encoding="utf-8")
                for leftover in target.parent.glob("*-2.md"):
                    leftover.unlink()
                self.assertEqual(self.invoke(path, "--save"),
                                 target.with_name("2026-09-06-notes-2.md"))
                self.assertEqual(target.read_text(encoding="utf-8"), content)
        # Not even an exact --to FILE replaces it; an earlier export there, it does.
        exact = self.root / "README.md"
        exact.write_text("my own notes\n", encoding="utf-8")
        self.assert_rejected(path, "--to", "README.md", message="isn't a session transcript")
        self.assertEqual(exact.read_text(encoding="utf-8"), "my own notes\n")
        kept = self.invoke(path, "--to", "kept.md")
        self.assertEqual(self.invoke(path, "--to", "kept.md"), kept)  # its own export
        self.assert_rejected(self.paths[0], "--to", "kept.md",
                             message="another session's, or one with notes added")

    def test_topic_names_the_file(self):
        ids = [f"d{i:07x}-2222-4222-8222-{i:012x}" for i in range(1, 3)]
        paths = [self.write_session(sid, 8, f"opening {i}") for i, sid in enumerate(ids)]
        topic = "Add export-lite & recap-lite skills!"
        first = self.invoke(paths[0], "--save", "--topic", topic)
        self.assertEqual(first.name, "2026-09-08-add-export-lite-recap-lite-skills.md")
        self.assertEqual(self.invoke(paths[0], "--save", "--topic", topic), first)  # again
        self.assertEqual(self.invoke(paths[1], "--save", "--topic", topic).name,
                         "2026-09-08-add-export-lite-recap-lite-skills-2.md")
        self.assertEqual(self.invoke(paths[0], "--to", "kept/", "--topic", "Kept!"),
                         self.root / "kept" / "2026-09-08-kept.md")
        long = self.invoke(paths[0], "--save", "--topic", "word " * 30).stem
        self.assertLessEqual(len(long), len("2026-09-08-") + 48)
        self.assertFalse(long.endswith("-"))
        self.assertEqual(self.invoke(paths[0], "--save", "--topic", "!!!").name,
                         "2026-09-08-opening-0.md")  # nothing left: the opening prompt
        # An exact path stays exact, and a topic needs somewhere to name.
        self.assertEqual(self.invoke(paths[0], "--to", "exact.md", "--topic", "x"),
                         self.root / "exact.md")
        self.assert_rejected(paths[0], "--topic", "x", message="--topic names a kept")

    def test_save_name_dates_the_last_activity(self):
        ids = [f"f{i:07x}-2222-4222-8222-{i:012x}" for i in range(1, 3)]
        older = self.write_session(ids[0], 2, "Old work")
        later = self.write_session(ids[1], 3, "Long work")
        with later.open("a", encoding="utf-8") as stream:  # still going on the 7th
            stream.write("\n" + json.dumps({"type": "event_msg",
                                            "timestamp": "2026-09-07T12:00:00Z",
                                            "payload": {"type": "agent_message",
                                                        "message": "done"}}))
        self.assertEqual(self.invoke(later, "--save").name, "2026-09-07-long-work.md")
        # Several sessions: the latest activity across them, the first's topic.
        self.assertEqual(self.invoke(older, later, "--save").name, "2026-09-07-old-work.md")

    def test_reexport_never_drops_what_the_file_holds(self):
        sid = "e1000001-2222-4222-8222-000000000001"
        path = self.write_session(sid, 9, "Ship it")
        first = self.invoke(path, "--save")
        # Notes the user added to an export survive: the new one takes -2.
        with first.open("a", encoding="utf-8") as stream:
            stream.write("\n## My notes\n\nremember the flag\n")
        self.assertEqual(self.invoke(path, "--save"), first.with_name(first.stem + "-2.md"))
        self.assertIn("remember the flag", first.read_text(encoding="utf-8"))
        # A --no-tools copy doesn't replace the full one either (nor vice versa).
        bare = self.invoke(path, "--save", "--no-tools")
        self.assertEqual(bare, first.with_name(first.stem + "-3.md"))
        self.assertEqual(TRANSCRIPT["_file_signature"](bare)[-1], "no-tools")

    def test_exact_paths_follow_the_same_rule(self):
        sid = "e4000001-2222-4222-8222-000000000001"
        path = self.write_session(sid, 12, "Plan")
        kept = self.invoke(path, "--to", "plan.md")
        self.write_session(sid, 12, "Plan", more=[("next?", "step two")])
        self.assertEqual(self.invoke(path, "--to", "plan.md"), kept)  # grew: refreshed
        with kept.open("a", encoding="utf-8") as stream:
            stream.write("\n_Source: my own reading notes\n")  # looks like ours, isn't
        self.assert_rejected(path, "--to", "plan.md", message="one with notes added")
        self.assertIn("my own reading notes", kept.read_text(encoding="utf-8"))
        # Auto names too: that line is the user's, so the re-export takes -2.
        saved = self.invoke(path, "--save")
        with saved.open("a", encoding="utf-8") as stream:
            stream.write("\n_Source: my own reading notes\n")
        self.assertEqual(self.invoke(path, "--save"), saved.with_name(saved.stem + "-2.md"))

    def test_trimmed_reexports_refresh_in_place(self):
        sid = "e5000001-2222-4222-8222-000000000001"
        turns = [(f"ask {i}", f"answer {i}") for i in range(4)]
        path = self.write_session(sid, 13, "Long one", more=turns)
        first = self.invoke(path, "--save", "--messages", 1)
        self.assertIn("## ✂️", first.read_text(encoding="utf-8"))
        self.write_session(sid, 13, "Long one", more=turns + [("ask 4", "answer 4")])
        self.assertEqual(self.invoke(path, "--save", "--messages", 1), first)
        self.assertIn("answer 4", first.read_text(encoding="utf-8"))

    def test_links_at_an_auto_name_are_never_written_through(self):
        sid = "e6000001-2222-4222-8222-000000000001"
        path = self.write_session(sid, 14, "Linked")
        folder = self.root / "transcripts"
        folder.mkdir()
        outside = self.root / "outside.md"
        (folder / "2026-09-14-linked.md").symlink_to(outside)  # dangling
        out = self.invoke(path, "--save")
        self.assertEqual(out, folder / "2026-09-14-linked-2.md")
        self.assertFalse(outside.exists())
        real = self.invoke(path, "--to", "real.md")  # an export, then a link to it
        (folder / "2026-09-14-linked-2.md").unlink()
        (folder / "2026-09-14-linked-2.md").symlink_to(real)
        before = real.read_text(encoding="utf-8")
        self.assertEqual(self.invoke(path, "--save"), folder / "2026-09-14-linked-3.md")
        self.assertEqual(real.read_text(encoding="utf-8"), before)

    def test_a_running_turn_still_refreshes_its_export(self):
        # Exported mid-turn (this session, typically): later the same turn ran
        # more tools, so its last tools line grew. That's still the same export.
        sid = "e2000001-2222-4222-8222-000000000001"
        meta = {"type": "session_meta", "timestamp": "2026-09-10T12:00:00Z",
                "payload": {"id": sid, "cwd": str(self.root)}}
        ask = {"type": "event_msg", "payload": {"type": "user_message", "message": "Look"}}
        def call(cmd):
            return {"type": "response_item", "payload": {
                "type": "function_call", "name": "exec_command",
                "arguments": json.dumps({"cmd": cmd})}}
        done = {"type": "event_msg", "payload": {"type": "agent_message", "message": "Done."}}
        path = self.root / f"{sid}.jsonl"
        path.write_text("\n".join(map(json.dumps, [meta, ask, call("cat a.py")])),
                        encoding="utf-8")
        first = self.invoke(path, "--save")
        self.assertIn("Read(a.py)_", first.read_text(encoding="utf-8"))
        path.write_text("\n".join(map(json.dumps, [meta, ask, call("cat a.py"),
                                                   call("cat b.py"), done])),
                        encoding="utf-8")
        self.assertEqual(self.invoke(path, "--save"), first)
        self.assertIn("Read(a.py), Read(b.py)_", first.read_text(encoding="utf-8"))

    def test_topics_in_any_language(self):
        slug = TRANSCRIPT["_slugify"]
        self.assertEqual(slug("Ažuriranje čišćenje Đuro"), "azuriranje-ciscenje-duro")
        self.assertEqual(slug("Straße Æble Øre łódź Þing"), "strasse-aeble-ore-lodz-thing")
        path = self.write_session("e3000001-2222-4222-8222-000000000001", 11, "Opening words")
        result = self.run_script(path, "--save", "--topic", "重构")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip().endswith("2026-09-11-opening-words.md"))
        self.assertIn("no letters or digits a file name can keep", result.stderr)
        result = self.run_script(path, "--to", "exact.md", "--topic", "x")
        self.assertIn("--topic 'x' ignored", result.stderr)

    def test_no_topic_names_follow_the_same_rule(self):
        ids = ["c0000001-2222-4222-8222-000000000001", "c0000002-2222-4222-8222-000000000002"]
        names = [self.invoke(self.write_session(sid, 7, None), "--save") for sid in ids]
        self.assertEqual([n.name for n in names],
                         ["2026-09-07-session.md", "2026-09-07-session-2.md"])

    def test_transcript_signature(self):
        signature = TRANSCRIPT["transcript_signature"]
        load = TRANSCRIPT["load_session"]
        one = load(self.paths[0], "codex")
        two = [one, load(self.paths[1], "codex")]
        single = TRANSCRIPT["build_transcript"](one.records, one.id, True, "codex")
        combined = TRANSCRIPT["build_combined"](two, True)
        recap = TRANSCRIPT["build_combined"](
            two, True, None, "> x\n> Trimmed with --messages 3: …", 3,
            "2 most recent Codex sessions")
        bare = TRANSCRIPT["build_transcript"](one.records, one.id, False, "codex",
                                              TRANSCRIPT["EXPORT_BLURB_NO_TOOLS"])
        self.assertEqual(signature(single.splitlines()), ("single", (IDS[0],), None, "tools"))
        self.assertEqual(signature(bare.splitlines()), ("single", (IDS[0],), None, "no-tools"))
        self.assertEqual(signature(combined.splitlines()),
                         ("combined", tuple(IDS[:2]), None, "tools"))
        self.assertEqual(signature(recap.splitlines()), ("recap", tuple(IDS[:2]), 3, "tools"))
        for text in ("", "# Notes\n---\n", "# Session transcript — 2 sessions combined\n---\n",
                     "# Session transcript — something else\n1. `x` — y\n---\n"):
            with self.subTest(text=text):
                self.assertIsNone(signature(text.splitlines()))

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
                for flags in (["--save"], ["--out", "kept/"],
                              ["--to", f"kept-{len(paths)}.md"]):
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


MESSAGE_RE = re.compile(r"^## (?:👤 User|🤖 Claude|🤖 Codex|📋 Plan)", re.MULTILINE)


def claude_messages(*texts, stamp=lambda i: f"2026-09-01T12:{i:02d}:00Z", cwd="/p"):
    """Claude records alternating user / assistant, each reply then a tool call."""
    records = []
    for i, text in enumerate(texts):
        if i % 2 == 0:
            records.append({"type": "user", "message": {"content": text},
                            "timestamp": stamp(i), "cwd": cwd})
        else:
            records.append({"type": "assistant", "timestamp": stamp(i), "message": {
                "content": [{"type": "text", "text": text}]}})
            records.append({"type": "assistant", "timestamp": stamp(i), "message": {
                "content": [{"type": "tool_use", "name": "Read",
                             "input": {"file_path": f"/p/{text}.py"}}]}})
    return records


def plan(text):
    return {"type": "assistant", "message": {"content": [{
        "type": "tool_use", "name": "ExitPlanMode", "input": {"plan": text}}]}}


class TrimTests(unittest.TestCase):
    def body(self, records, messages):
        return TRANSCRIPT["_transcript_body"](records, True, "claude", messages)[0]

    def test_whole_when_two_m_or_fewer(self):
        for count, keep in ((3, 5), (4, 2), (6, 3), (1, 1)):
            records = claude_messages(*(f"m{i}" for i in range(count)))
            with self.subTest(count=count, keep=keep):
                body = self.body(records, keep)
                self.assertEqual(body, self.body(records, None))
                self.assertEqual(len(MESSAGE_RE.findall(body)), count)
                self.assertNotIn("omitted", body)

    def test_first_and_last_m_around_one_marker(self):
        for count, keep, omitted in ((5, 2, "1 message omitted"),
                                     (10, 2, "6 messages omitted"),
                                     (7, 1, "5 messages omitted")):
            texts = [f"m{i}" for i in range(count)]
            with self.subTest(count=count, keep=keep):
                body = self.body(claude_messages(*texts), keep)
                kept = texts[:keep] + texts[-keep:]
                self.assertEqual(len(MESSAGE_RE.findall(body)), 2 * keep)
                self.assertEqual(body.count("## ✂️"), 1)
                self.assertIn(f"## ✂️ {omitted}", body)
                self.assertIn(f"the first {keep} and last {keep} of this "
                              f"session's {count} messages", body)
                for text in texts:
                    self.assertEqual(f"\n\n{text}\n" in body, text in kept, text)
                head, tail = body.split("## ✂️")
                self.assertTrue(all(f"\n{t}\n" in head for t in texts[:keep]))
                self.assertTrue(all(f"\n{t}\n" in tail for t in texts[-keep:]))

    def test_tool_trace_travels_with_its_message(self):
        body = self.body(claude_messages(*(f"m{i}" for i in range(7))), 2)
        self.assertIn("Read(m1.py)", body)  # after kept reply m1
        self.assertIn("Read(m5.py)", body)  # after kept reply m5
        self.assertNotIn("Read(m3.py)", body)  # after an omitted reply

    def test_tools_run_first_open_the_reply(self):
        # Prompt -> tool -> text -> tool -> text, and a reply of only tools.
        def tool(name):
            return {"type": "assistant", "message": {"content": [{
                "type": "tool_use", "name": "Read", "input": {"file_path": f"/p/{name}"}}]}}

        def text(value):
            return {"type": "assistant", "message": {"content": [
                {"type": "text", "text": value}]}}

        def ask(value):
            return {"type": "user", "message": {"content": value}}

        records = [ask("u1"), tool("a"), text("t1"), tool("b"), text("t2"),
                   ask("u2"), tool("c"), text("t3"),
                   ask("u3"), tool("d")]
        whole = self.body(records, None)
        self.assertEqual(self.body(records, 3), whole)  # 6 messages <= 2 * 3
        self.assertIn("of this session's 6 messages", self.body(records, 2))
        body = self.body(records, 1)
        self.assertIn("## ✂️ 4 messages omitted", body)
        self.assertTrue(body.startswith("## 👤 User\n\nu1\n\n## ✂️"))  # not Read(a)
        self.assertTrue(body.endswith("_🔧 tools: Read(d)_\n"))
        self.assertNotIn("Read(a)", body)
        self.assertNotIn("u3", body)

    def test_plans_count_as_messages(self):
        # A plan alone between prompts is the assistant's reply...
        records = claude_messages("m0", "m1", "m2")
        records.append(plan("p3"))
        body = self.body(records, 1)
        self.assertIn("## ✂️ 2 messages omitted", body)
        self.assertIn("## 📋 Plan (Claude)\n\np3", body)
        # ...and one after the assistant's text belongs to that same reply.
        records = claude_messages("m0", "m1") + [plan("p2")] + claude_messages("m3")
        body = self.body(records, 1)
        self.assertIn("## ✂️ 1 message omitted", body)
        self.assertNotIn("p2", body)

    def test_a_reply_is_one_message_however_many_blocks(self):
        # Claude often answers in a dozen blocks; the last ask must survive.
        def reply(prefix, count):
            return [r for i in range(count)
                    for r in claude_messages("_", f"{prefix}{i}")[1:]]
        records = (claude_messages("ask0") + reply("long", 12)
                   + claude_messages("ask1") + reply("mid", 3)
                   + claude_messages("ask2") + reply("last", 5))
        whole = self.body(records, None)
        self.assertEqual(self.body(records, 3), whole)  # 6 messages <= 2 * 3
        body = self.body(records, 2)
        self.assertIn("## ✂️ 2 messages omitted", body)
        self.assertIn("of this session's 6 messages", body)
        for kept in ["ask0", "ask2"] + [f"long{i}" for i in range(12)] \
                + [f"last{i}" for i in range(5)]:
            self.assertIn(f"\n\n{kept}\n", body)
        for dropped in ["ask1", "mid0", "mid2"]:
            self.assertNotIn(f"\n\n{dropped}\n", body)
        self.assertIn("Read(long11.py)", body)  # tool lines stay with their reply
        self.assertNotIn("Read(mid1.py)", body)
        body = self.body(records, 1)
        self.assertIn("## ✂️ 4 messages omitted", body)
        self.assertEqual(body.count("## 🤖 Claude"), 5)  # the whole last reply

    def test_reading_backwards(self):
        lines_backwards = TRANSCRIPT["_lines_backwards"]
        lines = [b"a" * 10, b"", b"bbb", b"c" * 25, b"d"]
        for ending in (b"", b"\n"):
            data = b"\n".join(lines) + ending
            expected = list(reversed(data.split(b"\n")))
            for step in (1, 2, 3, 4, 7, 64):
                with self.subTest(ending=ending, step=step):
                    self.assertEqual(list(lines_backwards(io.BytesIO(data), step)),
                                     expected)
        self.assertEqual(list(lines_backwards(io.BytesIO(b""))), [])

    def test_last_activity_skips_bad_timestamps(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "s.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in (
                {"timestamp": "2026-09-01T12:00:00Z"},
                {"timestamp": "2026-09-02T12:00:00Z"},
                {"timestamp": "yesterday"},
                {"type": "bridge-session"},
                {"timestamp": "x" * 300_000},
            )) + "\n", encoding="utf-8")
            os.utime(path, (1, 1))
            self.assertEqual(TRANSCRIPT["last_activity"](path),
                             datetime.datetime(2026, 9, 2, 12,
                                               tzinfo=datetime.timezone.utc).timestamp())


# Real-shaped, anonymized Codex rollouts. Newer Codex writes no `user_message`
# events: every user turn is a `response_item` user message, and the harness
# files its own context the same way.
GHOST = "99999999-1111-4111-8111-999999999999"  # named only by injected text
AGENTS_MD = ("# AGENTS.md instructions for /work/app\n\n<INSTRUCTIONS>\n"
             f"# Prompt prefixes\nRun session-transcript {GHOST} first.\n</INSTRUCTIONS>")
ENV_CONTEXT = ("<environment_context>\n  <cwd>/work/app</cwd>\n  <shell>zsh</shell>\n"
               "</environment_context>")
SKILL_BLOCK = ("<skill>\n<name>resume-lite</name>\n<path>/home/u/.agents/skills/"
               "resume-lite/SKILL.md</path>\n---\nname: resume-lite\n</skill>")
PLUGINS = "<recommended_plugins>\nAvailable, not installed:\n- Dropbox\n</recommended_plugins>"
BROWSER = ('<in-app-browser-context source="ambient-ui-state">\nThis block is '
           "automatically supplied ambient UI state.\n# In app browser:\n- Current URL: "
           "http://127.0.0.1:8774/\n</in-app-browser-context>")
MENTION = "[$resume-lite](/home/u/.agents/skills/resume-lite/SKILL.md)"


def stamped(record, minute=0):
    return {"timestamp": f"2026-10-06T11:{minute:02d}:00Z", **record}


def codex_user(*texts):
    """A user `response_item`; None stands for an attached image."""
    return {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_image", "image_url": "data:image/png;base64,AA"}
                        if text is None else {"type": "input_text", "text": text}
                        for text in texts]}}


def codex_reply(text, phase="final_answer"):
    """An assistant message, mirrored first by an item_completed AgentMessage."""
    return [{"type": "event_msg", "payload": {"type": "item_completed", "item": {
                "type": "AgentMessage", "id": "m", "phase": phase,
                "content": [{"type": "Text", "text": text}]}}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                "phase": phase, "content": [{"type": "output_text", "text": text}]}}]


def codex_mirror(text):
    return {"type": "event_msg", "payload": {"type": "item_completed", "item": {
        "type": "UserMessage", "id": "u", "content": [{"type": "text", "text": text}]}}}


def codex_call(name, args, call_id, output):
    return [{"type": "response_item", "payload": {"type": "function_call", "name": name,
                "arguments": json.dumps(args), "call_id": call_id}},
            {"type": "response_item", "payload": {"type": "function_call_output",
                "call_id": call_id, "output": output}}]


def codex_rollout(sid, cwd, version, *records):
    desktop = version >= "0.160"
    meta = {"type": "session_meta", "payload": {
        "id": sid, "session_id": sid, "cwd": cwd, "cli_version": version,
        "originator": "Codex Desktop" if desktop else "codex-tui",
        "source": "vscode" if desktop else "cli", "thread_source": "user"}}
    flat = [meta] + [r for item in records
                     for r in (item if isinstance(item, list) else [item])]
    return [stamped(record, i % 60) for i, record in enumerate(flat)]


def old_tui_rollout(sid=IDS[6], cwd="/work/app"):
    """codex-tui 0.153: context first, a typed `$resume-lite`, the skill body."""
    typed = f"review last 3 commits\n\n$resume-lite {IDS[0]} to understand"
    return codex_rollout(
        sid, cwd, "0.153.4",
        codex_user(AGENTS_MD, ENV_CONTEXT),
        codex_user(typed), codex_mirror(typed),
        codex_user(SKILL_BLOCK),
        codex_reply("I'll read that session first.", "commentary"),
        codex_call("exec_command", {"cmd": "git log -3"}, "c0", "abc123"),
        codex_reply("Found four issues."),
        codex_user("gcm!"), codex_mirror("gcm!"),
        codex_reply("Committed."),
    )


def desktop_rollout(sid=IDS[7], cwd="/work/app"):
    """Codex Desktop 0.160: plugin hints, browser state, questions, subagents."""
    request = f"{BROWSER}\n\n## My request:\nmake the shrimp icon less realistic"
    return codex_rollout(
        sid, cwd, "0.160.0",
        codex_user(PLUGINS, AGENTS_MD, ENV_CONTEXT),
        codex_user('<external_codex_apps_open_page>{"page_id":null}'
                   "</external_codex_apps_open_page>"),
        codex_user(request), codex_mirror(request),
        codex_reply("On it.", "commentary"),
        {"type": "response_item", "payload": {  # inter-agent traffic, encrypted
            "type": "agent_message", "author": "/root/designer", "recipient": "/root",
            "content": [{"type": "input_text", "text": "Message Type: MESSAGE\n"},
                        {"type": "encrypted_content", "encrypted_content": "gAAAA"}]}},
        codex_user("<subagent_notification>\n{\"agent\": \"designer\", \"text\": "
                   f"\"ran session-transcript {GHOST}\"}}\n</subagent_notification>"),
        codex_call("request_user_input_async", {"questions": [
            {"title": "Which style?", "options": ["Flat", "Ghibli"]}]}, "c1", "queued"),
        codex_user('<send_user_message_question_reply>\n[{"questionItemId":"x",'
                   '"question":"Which style?","answer":"Ghibli, softer"}]\n'
                   "</send_user_message_question_reply>"),
        codex_user("<turn_aborted>\nThe user interrupted the previous turn on purpose."
                   "\n</turn_aborted>"),
        codex_user("\n# Files mentioned by the user:\n\n## shot.png: /tmp/shot.png\n\n"
                   "## My request:\ncompare with this",
                   '<image name=[Image #1] path="/tmp/shot.png">', None, "</image>"),
        codex_user("<user_shell_command>\n<command>\nnode --version\n</command>\n"
                   "<result>\nExit code: 0\nOutput:\nv22\n</result>\n</user_shell_command>"),
        codex_call("request_user_input", {"questions": [{"id": "q", "question": "Bundle deps?",
            "options": [{"label": "Yes"}, {"label": "No (Recommended)"}]}]}, "c2",
            json.dumps({"answers": {"q": {"answers": ["No (Recommended)"]}}})),
        codex_user(f"{MENTION} {IDS[1]} --deep"),
        codex_reply("Done, shrimp redrawn."),
    )


def turns(records):
    return [(kind, text) for kind, text in TRANSCRIPT["normalized_events"](records, "codex")
            if kind != "tool"]


NOTICE = ("<task-notification>\n<task-id>t1</task-id>\n<status>completed</status>\n"
          f"<result>ran session-transcript {GHOST}</result>\n</task-notification>")
REMINDER = ("<system-reminder>\nThe user started this session without choosing a "
            "project folder.\n</system-reminder>")


def claude_user(content, **extra):
    return {"type": "user", "message": {"content": content}, **extra}


def queued(prompt, kind="human", mode="prompt"):
    return {"type": "attachment", "attachment": {
        "type": "queued_command", "commandMode": mode, "origin": {"kind": kind},
        "prompt": prompt}}


class ClaudeHarnessTests(unittest.TestCase):
    def turns(self, records):
        return [(kind, text) for kind, text in
                TRANSCRIPT["normalized_events"](records, "claude") if kind != "tool"]

    def test_harness_text_is_not_a_user_turn(self):
        records = [
            claude_user(f"{REMINDER}\nwhat does this mean", origin={"kind": "human"}),
            claude_user(NOTICE, origin={"kind": "task-notification"}),
            claude_user(f"{NOTICE}\nThe cloud review produced these findings: []",
                        origin={"kind": "task-notification"}),
            queued(NOTICE, kind="task-notification", mode="task-notification"),
            queued('<agent-message from="a1">\nreport\n</agent-message>', kind="peer"),
            claude_user("<bash-input>git status</bash-input><bash-stdout>clean"
                        "</bash-stdout><bash-stderr></bash-stderr>"),
            queued("ss: and check the README too"),  # typed while Claude worked
            claude_user("gcm!"), queued("gcm!"),  # the same command, typed again
            claude_user([{"type": "text", "text": REMINDER},
                         {"type": "text", "text": "two blocks, one typed"}]),
        ]
        self.assertEqual(self.turns(records), [
            ("user", "what does this mean"),
            ("user", "!git status"),
            ("user", "ss: and check the README too"),
            ("user", "gcm!"),
            ("user", "gcm!"),
            ("user", "two blocks, one typed"),
        ])

    def test_queued_prompts_without_an_origin(self):
        # Older Claude Code files no origin: tell a notice by its shape.
        def bare(prompt):
            record = queued(prompt)
            del record["attachment"]["origin"]
            return record
        self.assertEqual(self.turns([bare("typed mid-turn"), bare(NOTICE),
                                     bare('<agent-message from="a1">\nhi\n</agent-message>')]),
                         [("user", "typed mid-turn")])

    def test_snippet_from_a_queued_first_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "s.jsonl"
            records = [queued(NOTICE, kind="task-notification", mode="task-notification"),
                       queued("first thing I typed"), claude_user("second")]
            path.write_text("\n".join(map(json.dumps, records)), encoding="utf-8")
            self.assertEqual(TRANSCRIPT["first_user_snippet"](path, "claude"),
                             "first thing I typed")

    def test_the_same_tags_typed_by_the_user_are_kept(self):
        for text in ("what does <system-reminder> do?",
                     "<task-notification> blocks show up as turns, drop them",
                     "parse <system-reminder>x</system-reminder> inline",
                     "it wrote <system-reminder>x</system-reminder>",
                     "<pasted_content id=\"a1\">\nmy notes\n</pasted_content>"):
            with self.subTest(text=text):
                self.assertEqual(self.turns([claude_user(text)]), [("user", text)])

    def test_lineage_skips_notices_and_reads_queued_prompts(self):
        records = [claude_user(NOTICE, origin={"kind": "task-notification"}),
                   queued(f"/resume-lite {IDS[0]}")]
        session = TRANSCRIPT["Session"](Path("x.jsonl"), "claude", IDS[7], records)
        self.assertEqual(TRANSCRIPT["lineage_ids"](session), IDS[:1])

    def test_short_ids_in_argument_lists_are_lineage(self):
        self.assert_lineage(f"python3 ./session-transcript {IDS[0][:8]} {IDS[1][:8]}",
                            [IDS[0][:8], IDS[1][:8]])
        self.assert_lineage(f"python3 ./session-transcript {IDS[7][:8]}", [])  # itself
        prompt = ("<command-name>/resume-lite</command-name>"
                  f"<command-args>{IDS[0][:8]}</command-args>")
        self.assertEqual(lineage(claude_user(prompt), "claude"), [IDS[0][:8]])
        # Free typed text names a session only by its full id (8 hex chars
        # there may be a commit), and prose to another agent names none.
        self.assertEqual(lineage(claude_user(f"/resume-lite {IDS[0]} then 5b9d23b4"),
                                 "claude"), IDS[:1])
        for name, key in (("SendMessage", "message"), ("Agent", "prompt")):
            record = {"type": "assistant", "message": {"content": [{
                "type": "tool_use", "name": name,
                "input": {key: f"run `session-transcript {IDS[0][:8]}` for me"}}]}}
            with self.subTest(tool=name):
                self.assertEqual(lineage(record, "claude"), [])

    def assert_lineage(self, command, expected):
        for provider in ("claude", "codex"):
            with self.subTest(provider=provider, command=command):
                self.assertEqual(lineage(tool_record(command, provider), provider),
                                 expected)


class CodexRolloutTests(unittest.TestCase):
    def test_old_tui_rollout(self):
        self.assertEqual(turns(old_tui_rollout()), [
            ("user", f"review last 3 commits\n\n$resume-lite {IDS[0]} to understand"),
            ("assistant", "I'll read that session first."),
            ("assistant", "Found four issues."),
            ("user", "gcm!"),
            ("assistant", "Committed."),
        ])

    def test_desktop_rollout(self):
        self.assertEqual(turns(desktop_rollout()), [
            ("user", "make the shrimp icon less realistic"),
            ("assistant", "On it."),
            ("assistant", "Which style?\n- Flat\n- Ghibli"),
            ("user", "Ghibli, softer"),
            ("user", "compare with this\n[Image #1]"),
            ("user", "!node --version"),
            ("assistant", "Bundle deps?\n- Yes\n- No (Recommended)"),
            ("user", "No (Recommended)"),
            ("user", f"$resume-lite {IDS[1]} --deep"),
            ("assistant", "Done, shrimp redrawn."),
        ])
        body = TRANSCRIPT["_transcript_body"](desktop_rollout(), True, "codex")[0]
        for injected in ("AGENTS.md", "Dropbox", "<cwd>", "page_id", "In app browser",
                         "designer", "Message Type", "interrupted", "Exit code", "v22",
                         "SKILL.md", "/tmp/shot.png", "request_user_input"):
            self.assertNotIn(injected, body)

    def test_family_ids_need_eight_hex_characters(self):
        family = TRANSCRIPT["_family_invocation"]
        self.assertTrue(family("/resume-lite 48f4b8ff"))
        self.assertTrue(family(f"$resume-lite {IDS[0]} --deep"))
        typed = TRANSCRIPT["_codex_typed_item"]  # how Codex mentions reach it
        self.assertTrue(family(typed(f"{MENTION} deadbeef")))
        self.assertFalse(family("/resume-lite decade"))  # a word, not an id
        self.assertFalse(family("/resume-lite facade please"))

    def test_typed_part_of_a_mixed_item_is_kept(self):
        typed = TRANSCRIPT["_codex_typed_item"]
        self.assertEqual(typed(f"looks good\n\n{BROWSER}"), "looks good")
        self.assertEqual(typed(f"{AGENTS_MD}\n\nand then this"), "and then this")
        self.assertEqual(typed(f"{ENV_CONTEXT}\n{SKILL_BLOCK}"), "")
        self.assertEqual(typed("# Context from my IDE setup:\n\n## Open tabs:\n- a.py\n\n"
                               "## My request for Codex:\nfix a.py"), "fix a.py")
        self.assertEqual(typed("<user_shell_command>\n<command>\nls\n</command>\n<result>\n"
                               "ok\n</result>\n</user_shell_command>\nwhy is it empty?"),
                         "!ls\nwhy is it empty?")

    def test_the_same_words_typed_by_the_user_are_kept(self):
        # Only the exact shape Codex writes is cut: tags written or pasted by
        # the user (mid-sentence, unclosed, a draft AGENTS.md, other links) stay.
        typed = TRANSCRIPT["_codex_typed_item"]
        for text in (
            "what does a <skill> tag do?",
            "<skill> blocks show up as user turns, filter them",
            "please parse <skill><name>x</name></skill> and report",
            "<skill>x</skill> is what it injects",
            "# AGENTS.md instructions\n\nhere is my draft:\n- be terse",
            "see [@john](https://github.com/john) and [docs](https://x.dev/SKILL)",
        ):
            with self.subTest(text=text):
                self.assertEqual(typed(text), text)
        self.assertEqual(typed("ask [@Booking.com](plugin://booking-com@curated) and "
                               "[$Gmail](app://gmail)"), "ask @Booking.com and $Gmail")

    def test_mentions_only_unwrapped_in_codex_text(self):
        # A Codex transcript pasted into Claude names no parent of the Claude chat.
        pasted = f"from codex:\n{MENTION} {IDS[0]} --deep"
        self.assertEqual(lineage({"type": "user", "message": {"content": pasted}},
                                 "claude"), [])
        self.assertEqual(lineage(codex_user(pasted), "codex"), IDS[:1])

    def test_lineage_reads_only_typed_turns(self):
        # Genuine resumes, typed or as a Desktop mention; never ids that only
        # appear in AGENTS.md or a subagent notice.
        for records, expected in ((old_tui_rollout(), [IDS[0]]),
                                  (desktop_rollout(), [IDS[1]])):
            session = TRANSCRIPT["Session"](Path("x.jsonl"), "codex", records[0]["payload"]["id"],
                                            records)
            with self.subTest(version=records[0]["payload"]["cli_version"]):
                self.assertEqual(TRANSCRIPT["lineage_ids"](session), expected)

    def test_snippet_and_save_topic(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rollout.jsonl"
            first = codex_user(f"{MENTION} {IDS[1]} --deep")
            records = codex_rollout(IDS[5], "/work/app", "0.160.0",
                                    codex_user(AGENTS_MD, ENV_CONTEXT), first,
                                    codex_user(SKILL_BLOCK), codex_reply("Read it."),
                                    codex_user("now fix the parser"), codex_reply("Fixed."))
            path.write_text("\n".join(map(json.dumps, records)), encoding="utf-8")
            snippet = TRANSCRIPT["first_user_snippet"]
            self.assertEqual(snippet(path, "codex"), f"$resume-lite {IDS[1]} --deep")
            self.assertEqual(snippet(path, "codex", skip_commands=True), "now fix the parser")

    def test_trimming_counts_typed_turns_only(self):
        body = TRANSCRIPT["_transcript_body"](old_tui_rollout(), True, "codex", 1)[0]
        self.assertTrue(body.startswith("## 👤 User\n\nreview last 3 commits"))
        self.assertIn("## ✂️ 2 messages omitted", body)  # 4 messages, 1 + 1 kept


class RecentTests(unittest.TestCase):
    """--recent selection, filters, output naming, and --messages end to end."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="recent-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.cwd = os.path.realpath(self.project)
        self.home = self.root / "home"
        self.codex = self.root / "codex"
        self.claude_dir = (self.home / ".claude" / "projects"
                           / TRANSCRIPT["encode_cwd"](self.cwd))
        self.claude_dir.mkdir(parents=True)
        (self.codex / "sessions" / "2026").mkdir(parents=True)
        self.files = {}

    def add(self, sid, provider, day, count=2, mtime=None, extra=()):
        """A session whose last message is on 2026-09-<day>."""
        stamp = lambda i: f"2026-09-{day:02d}T12:{i:02d}:00Z"
        texts = [f"{sid[:8]} message {i}" for i in range(count)]
        if provider == "claude":
            records = claude_messages(*texts, stamp=stamp, cwd=self.cwd)
            path = self.claude_dir / f"{sid}.jsonl"
        else:
            records = [{"type": "session_meta", "timestamp": stamp(0),
                        "payload": {"id": sid, "cwd": self.cwd}}]
            for i, text in enumerate(texts):
                kind = "user_message" if i % 2 == 0 else "agent_message"
                records.append({"type": "event_msg", "timestamp": stamp(i),
                                "payload": {"type": kind, "message": text}})
            path = self.codex / "sessions" / "2026" / f"rollout-x-{sid}.jsonl"
        records += list(extra)
        path.write_text("\n".join(map(json.dumps, records)) + "\n", encoding="utf-8")
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        self.files[sid] = path
        return path

    def run_script(self, *args, env=None):
        environ = {**os.environ, "TMPDIR": str(self.root), "HOME": str(self.home),
                   "CODEX_HOME": str(self.codex)}
        for name in TRANSCRIPT["CURRENT_SESSION_ENV"]:
            environ.pop(name, None)
        environ.update(env or {})
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)], cwd=self.project,
            env=environ, text=True, capture_output=True, timeout=10)

    def recap(self, *args, env=None):
        result = self.run_script(*args, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = Path(result.stdout.strip().splitlines()[-1])
        out = out if out.is_absolute() else self.project / out
        return out, out.read_text(encoding="utf-8"), result.stderr

    def picked(self, text):
        return re.findall(r"^# Session \d+ of \d+ — `([^`]+)`", text, re.MULTILINE)

    def assert_rejected(self, *args, message, env=None):
        result = self.run_script(*args, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_newest_first_across_providers(self):
        for sid, provider, day in ((IDS[0], "claude", 1), (IDS[1], "codex", 3),
                                   (IDS[2], "claude", 2), (IDS[3], "codex", 4)):
            self.add(sid, provider, day)
        out, text, _ = self.recap("--recent", 3)
        self.assertEqual(self.picked(text), [IDS[3], IDS[1], IDS[2]])
        self.assertEqual(out.name, "recent.md")
        self.assertTrue(out.parent.name.startswith(
            f"recent-{IDS[3][:8]}+{IDS[1][:8]}+{IDS[2][:8]}-"))
        self.assertTrue(text.startswith("# Session transcript — 3 most recent sessions\n"))
        self.assertIn("> The 3 most recent sessions in this project, newest first.", text)
        self.assertNotIn("continue the work", text)

    def test_recency_is_last_activity_not_mtime(self):
        # Reopening an old chat appends untimestamped bookkeeping (bumping
        # mtime); that's not activity.
        bookkeeping = [{"type": "bridge-session", "sessionId": IDS[0]}]
        self.add(IDS[0], "claude", 1, mtime=2_000_000_000, extra=bookkeeping)
        self.add(IDS[1], "claude", 5, mtime=1_000_000_000)
        self.add(IDS[2], "codex", 3, mtime=1_500_000_000)
        _, text, _ = self.recap("--recent", 3)
        self.assertEqual(self.picked(text), [IDS[1], IDS[2], IDS[0]])

    def test_listing_sorts_and_shows_last_activity(self):
        bookkeeping = [{"type": "bridge-session", "sessionId": IDS[0]}]
        self.add(IDS[0], "claude", 1, mtime=2_000_000_000, extra=bookkeeping)
        self.add(IDS[1], "codex", 5, mtime=1_000_000_000)
        self.add(IDS[2], "claude", 3, mtime=1_500_000_000)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [line.split() for line in result.stdout.splitlines()
                if line.startswith("  ")]
        self.assertEqual([row[1] for row in rows], [IDS[1], IDS[2], IDS[0]])
        for row, day in zip(rows, (5, 3, 1)):  # each one's last message, local time
            last = datetime.datetime(2026, 9, day, 12, 1, tzinfo=datetime.timezone.utc)
            self.assertEqual(f"{row[2]} {row[3]}", datetime.datetime.fromtimestamp(
                last.timestamp()).strftime("%Y-%m-%d %H:%M"))

    def test_provider_filter(self):
        self.add(IDS[0], "claude", 1)
        self.add(IDS[1], "codex", 2)
        self.add(IDS[2], "claude", 3)
        _, text, _ = self.recap("--recent", 5, "--provider", "claude")
        self.assertEqual(self.picked(text), [IDS[2], IDS[0]])
        self.assertIn("> The 2 most recent Claude Code sessions", text)
        _, text, _ = self.recap("--recent", 5, "--provider", "codex")
        self.assertEqual(self.picked(text), [IDS[1]])
        self.assertTrue(text.startswith(
            "# Session transcript — 1 most recent Codex session\n"))
        self.assert_rejected("--recent", 1, "--provider", "gemini",
                             message="invalid choice")

    def test_exclude(self):
        ids = IDS[:3] + ["abcdef12-1111-4111-8111-abcdefabcdef"]
        for i, day in enumerate((1, 2, 3, 4)):
            self.add(ids[i], "claude" if i % 2 else "codex", day)
        _, text, _ = self.recap("--recent", 2, "--exclude", ids[3])
        self.assertEqual(self.picked(text), [ids[2], ids[1]])
        _, text, _ = self.recap("--recent", 2, "--exclude", ids[3].upper(),
                                "--exclude", ids[2], "--exclude", "not-a-session")
        self.assertEqual(self.picked(text), [ids[1], ids[0]])
        # `this`, resolved like the session argument.
        _, text, err = self.recap("--recent", 2, "--exclude", "This",
                                  env={"CODEX_THREAD_ID": ids[2]})
        self.assertEqual(self.picked(text), [ids[3], ids[1]])
        self.assertIn(f"--exclude this: {ids[2]} (from CODEX_THREAD_ID)", err)
        # Unresolvable `this` warns and excludes nothing rather than failing.
        _, text, err = self.recap("--recent", 1, "--exclude", "this")
        self.assertEqual(self.picked(text), [ids[3]])
        self.assertIn("nothing is excluded", err)

    def test_fewer_than_n_none_and_empty_sessions(self):
        self.assert_rejected("--recent", 3, message="no Claude Code or Codex sessions")
        self.add(IDS[0], "claude", 1)
        self.add(IDS[1], "codex", 2)
        self.add(IDS[2], "claude", 3, count=0)  # opened, never used
        _, text, err = self.recap("--recent", 10)
        self.assertEqual(self.picked(text), [IDS[1], IDS[0]])
        self.assertIn("--recent 10: only 2 sessions found", err)
        self.assert_rejected("--recent", 3, "--exclude", IDS[0], "--exclude", IDS[1],
                             message="(after --exclude)")
        self.assert_rejected("--recent", 3, "--provider", "claude", "--exclude", IDS[0],
                             message="no Claude Code sessions")

    def test_bad_combinations_are_rejected(self):
        self.add(IDS[0], "claude", 1)
        self.assert_rejected("--recent", 2, IDS[0], message="give it no session ids")
        self.assert_rejected("--recent", 2, "--deep", message="doesn't combine with --recent")
        self.assert_rejected(IDS[0], "--provider", "codex", message="only go with --recent")
        self.assert_rejected(IDS[0], "--exclude", "this", message="only go with --recent")
        self.assert_rejected("--provider", "codex", message="only go with --recent")
        for flag in ("--recent", "--messages"):
            for value, message in (("0", "must be 1 or more"), ("-2", "must be 1 or more"),
                                   ("abc", "whole number"), ("1.5", "whole number")):
                with self.subTest(flag=flag, value=value):
                    args = (flag, value) if flag == "--recent" else (IDS[0], flag, value)
                    self.assert_rejected(*args, message=message)

    def test_paths_never_collide_with_resume(self):
        self.add(IDS[0], "claude", 1)
        self.add(IDS[1], "codex", 2)
        recap, _, _ = self.recap("--recent", 2)
        resume, _, _ = self.recap(IDS[1], IDS[0])
        self.assertEqual(resume.name, "combined.md")
        self.assertNotEqual(recap.parent, resume.parent)
        single_recap, _, _ = self.recap("--recent", 1)
        single_resume, _, _ = self.recap(IDS[1])
        self.assertEqual(single_resume, self.root / "session-transcript" / IDS[1]
                         / "summary.md")
        self.assertNotEqual(single_recap.parent, single_resume.parent)

    def write(self, sid, provider, day, prompts, reply="Done."):
        """A session of typed prompts, each answered with `reply`."""
        records, stamp = [], f"2026-09-{day:02d}T12:00:00Z"
        if provider == "claude":
            for prompt in prompts:
                records += [
                    {"type": "user", "timestamp": stamp, "cwd": self.cwd,
                     "message": {"content": prompt}},
                    {"type": "user", "isMeta": True, "timestamp": stamp,
                     "message": {"content": "Base directory for this skill: /s"}},
                    {"type": "assistant", "timestamp": stamp,
                     "message": {"content": [{"type": "text", "text": reply}]}},
                ]
            path = self.claude_dir / f"{sid}.jsonl"
        else:
            records.append({"type": "session_meta", "timestamp": stamp,
                            "payload": {"id": sid, "cwd": self.cwd}})
            for prompt in prompts:
                records += [{"type": "event_msg", "timestamp": stamp, "payload": {
                                "type": "user_message", "message": prompt}},
                            {"type": "event_msg", "timestamp": stamp, "payload": {
                                "type": "agent_message", "message": reply}}]
            path = self.codex / "sessions" / "2026" / f"rollout-x-{sid}.jsonl"
        path.write_text("\n".join(map(json.dumps, records)) + "\n", encoding="utf-8")

    def test_sessions_that_only_ran_this_family_are_passed_over(self):
        def command(name, args=""):
            return (f"<command-message>{name[1:]}</command-message>\n"
                    f"<command-name>{name}</command-name>\n"
                    f"<command-args>{args}</command-args>")
        skipped = {
            "a0000000-1111-4111-8111-000000000001": ("claude", [command("/resume-lite")]),
            "a0000000-1111-4111-8111-000000000002": (
                "claude", [command("/recap-lite", "10 --messages 5 --codex")]),
            "a0000000-1111-4111-8111-000000000003": ("codex", ["$recap-lite"]),
            "a0000000-1111-4111-8111-000000000004": (
                "codex", [f"$resume-lite {IDS[0]} --deep", "/export-lite this --to notes/"]),
        }
        kept = {
            "b0000000-1111-4111-8111-000000000001": (
                "claude", [command("/resume-lite", IDS[0]), "now fix the failing test"]),
            "b0000000-1111-4111-8111-000000000002": (
                "claude", [command("/resume-lite", f"{IDS[0]} and fix the bug")]),
            "b0000000-1111-4111-8111-000000000003": ("claude", [command("/review")]),
            "b0000000-1111-4111-8111-000000000004": (
                "codex", [f"$resume-lite {IDS[0]}", "keep going"]),
        }
        for day, (sid, (provider, prompts)) in enumerate(
                list(skipped.items()) + list(kept.items()), 1):
            self.write(sid, provider, day, prompts)
        _, text, err = self.recap("--recent", 10)
        self.assertEqual(sorted(self.picked(text)), sorted(kept))
        self.assertIn("passed over 4 sessions that only ran resume-lite, "
                      "recap-lite or export-lite", err)

    def write_rollout(self, sid, day, *records):
        rows = codex_rollout(sid, self.cwd, "0.160.0", *records)
        for row in rows:
            row["timestamp"] = f"2026-09-{day:02d}T12:00:00Z"
        path = self.codex / "sessions" / "2026" / f"rollout-x-{sid}.jsonl"
        path.write_text("\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")

    def test_real_codex_sessions_that_only_ran_this_family(self):
        # Injected AGENTS.md and skill bodies are not user input.
        ids = [f"c0000000-1111-4111-8111-00000000000{i}" for i in (1, 2, 3)]
        context = codex_user(AGENTS_MD, ENV_CONTEXT)
        self.write_rollout(ids[0], 1, context, codex_user("$resume-lite"),
                           codex_user(SKILL_BLOCK), codex_reply("Pick one."))
        self.write_rollout(ids[1], 2, context, codex_user(f"{MENTION} {IDS[0]}"),
                           codex_user(SKILL_BLOCK), codex_reply("Picked up."))
        self.write_rollout(ids[2], 3, context, codex_user(f"{MENTION} {IDS[0]}"),
                           codex_user(SKILL_BLOCK), codex_reply("Picked up."),
                           codex_user("keep going"), codex_reply("Done."))
        _, text, err = self.recap("--recent", 5)
        self.assertEqual(self.picked(text), [ids[2]])
        self.assertIn("passed over 2 sessions that only ran", err)
        self.assertNotIn("AGENTS.md", text)

    def test_ids_can_be_shortened(self):
        self.add(IDS[0], "claude", 1)
        self.add(IDS[1], "codex", 2)
        for sid in IDS[:2]:  # the id8 a recap shows, for either store
            with self.subTest(sid=sid):
                out, text, _ = self.recap(sid[:8])
                self.assertEqual(out.parent.name, sid)  # named by the full id
                self.assertIn(f"# Session transcript — `{sid}`", text)
        out, _, _ = self.recap(IDS[1][:8], "--save")
        self.assertEqual(TRANSCRIPT["_file_signature"](out), ("single", (IDS[1],), None, "tools"))
        twins = ["abcdef12-1111-4111-8111-000000000001", "abcdef12-2222-4111-8111-000000000002"]
        for day, sid in enumerate(twins, 3):
            self.add(sid, "codex", day)
        result = self.run_script("abcdef12")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("session id prefix 'abcdef12' is ambiguous", result.stderr)
        for sid in twins:
            self.assertIn(sid, result.stderr)
        out, _, _ = self.recap("ABCDEF12-2")
        self.assertEqual(out.parent.name, twins[1])
        self.assert_rejected("abcdef1", message="needs at least 8 characters")

    def test_colliding_short_ids_prefer_user_threads_then_this_project(self):
        def rollout(sid, cwd, day, **meta):
            rows = codex_rollout(sid, cwd, "0.160.0", codex_user(f"task {day}"),
                                 codex_reply("ok"))
            rows[0]["payload"].update(meta)
            for row in rows:
                row["timestamp"] = f"2026-09-{day:02d}T12:00:00Z"
            (self.codex / "sessions" / "2026" / f"rollout-x-{sid}.jsonl").write_text(
                "\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")

        user, side = "e0000000-1111-4111-8111-000000000001", "e0000000-2222-4111-8111-000000000002"
        rollout(user, self.cwd, 1)
        rollout(side, self.cwd, 2, thread_source="subagent", parent_thread_id=user,
                source={"subagent": {"thread_spawn": {"parent_thread_id": user}}})
        out, _, _ = self.recap("e0000000")
        self.assertEqual(out.parent.name, user)  # not the subagent it spawned
        here, there = "f0000000-1111-4111-8111-000000000001", "f0000000-2222-4111-8111-000000000002"
        rollout(here, self.cwd, 3)
        rollout(there, "/elsewhere", 4)
        out, _, _ = self.recap("f0000000")
        self.assertEqual(out.parent.name, here)  # this project's, not elsewhere
        twin = "f0000000-3333-4111-8111-000000000003"
        rollout(twin, self.cwd, 5)
        self.assert_rejected("f0000000", message="is ambiguous")

    def test_deep_follows_a_short_id_resume(self):
        self.add(IDS[0], "claude", 1)
        self.add(IDS[1], "codex", 2)
        command = {"type": "assistant", "timestamp": "2026-09-03T12:30:00Z", "message": {
            "content": [{"type": "tool_use", "name": "Bash", "input": {
                "command": f"python3 /s/session-transcript {IDS[0][:8]} {IDS[1][:8]}"}}]}}
        self.add(IDS[2], "claude", 3, extra=[command])
        _, text, err = self.recap(IDS[2], "--deep")
        self.assertEqual(self.picked(text), [IDS[0], IDS[1], IDS[2]])
        self.assertIn(f"--deep: {IDS[2][:8]} resumed from {IDS[0][:8]}", err)

    def test_deep_from_a_short_id_follows_full_ids(self):
        self.add(IDS[0], "claude", 1)
        self.add(IDS[2], "claude", 2,
                 extra=[{"type": "user", "message": {"content": f"/resume-lite {IDS[0]}"},
                         "timestamp": "2026-09-02T13:00:00Z"}])
        out, text, err = self.recap(IDS[2][:8], "--deep")
        self.assertEqual(self.picked(text), [IDS[0], IDS[2]])
        self.assertIn(f"--deep: {IDS[2][:8]} resumed from {IDS[0][:8]}", err)

    def test_recaps_show_local_last_active_time(self):
        self.add(IDS[0], "claude", 1)
        self.add(IDS[1], "codex", 2)
        local = TRANSCRIPT["_local_time"]
        _, text, _ = self.recap("--recent", 2)
        for sid, day in ((IDS[1], 2), (IDS[0], 1)):
            last = datetime.datetime(2026, 9, day, 12, 1, tzinfo=datetime.timezone.utc)
            note = f" · last active {local(last.timestamp())}"
            self.assertEqual(text.count(note), 2, sid)  # index line and its meta line
        _, resumed, _ = self.recap(IDS[1], IDS[0])  # resume/export output unchanged
        self.assertNotIn("last active", resumed)

    def test_codex_side_threads_are_not_listed(self):
        kinds = {
            "d0000000-1111-4111-8111-000000000001": {},  # the user's own thread
            "d0000000-1111-4111-8111-000000000002": {  # a user fork: still theirs
                "forked_from_id": "d0000000-1111-4111-8111-000000000001"},
            "d0000000-1111-4111-8111-000000000003": {  # a spawned subagent
                "thread_source": "subagent", "parent_thread_id": "p",
                "source": {"subagent": {"thread_spawn": {"parent_thread_id": "p"}}}},
            "d0000000-1111-4111-8111-000000000004": {  # a guardian review
                "thread_source": "guardian_review", "parent_thread_id": "p",
                "source": {"subagent": {"other": "guardian"}}},
            "d0000000-1111-4111-8111-000000000005": {  # older spawn shape
                "source": {"thread_spawn": {"parent_thread_id": "p"}}},
        }
        for day, (sid, meta) in enumerate(kinds.items(), 1):
            rows = codex_rollout(sid, self.cwd, "0.160.0",
                                 codex_user(f"task {day}"), codex_reply("ok"))
            rows[0]["payload"].update(meta)
            for row in rows:
                row["timestamp"] = f"2026-09-{day:02d}T12:00:00Z"
            (self.codex / "sessions" / "2026" / f"rollout-x-{sid}.jsonl").write_text(
                "\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")
        users = list(kinds)[:2]
        listing = self.run_script().stdout
        self.assertEqual(re.findall(r"^  codex\s+(\S+)", listing, re.MULTILINE),
                         users[::-1])
        _, text, _ = self.recap("--recent", 10)
        self.assertEqual(self.picked(text), users[::-1])
        for sid in list(kinds)[2:]:  # still reachable by id
            out, text, _ = self.recap(sid)
            self.assertEqual(out.parent.name, sid)

    def test_exclude_prefixes_need_four_characters(self):
        self.add("abcdef12-1111-4111-8111-000000000001", "codex", 1)
        _, text, err = self.recap("--recent", 1, "--exclude", "abc")
        self.assertIn("--exclude abc: too short, give at least 4 characters", err)
        self.assertEqual(len(self.picked(text)), 1)
        self.assert_rejected("--recent", 1, "--exclude", "abcd",
                             message="no Claude Code or Codex sessions")

    def test_header_names_what_was_excluded(self):
        for day in range(1, 6):
            self.add(IDS[day - 1], "claude", day)  # IDS[4] is the newest
        current = {"CLAUDE_CODE_SESSION_ID": IDS[4]}
        for excludes, env, note in (
            (["this"], current, " (excluding the current session)"),
            ([IDS[3][:8]], None, " (1 excluded)"),
            (["this", IDS[3], IDS[2]], current,
             " (excluding the current session and 2 others)"),
            ([IDS[0]], None, ""),  # older than both picks: excluded nothing
        ):
            with self.subTest(excludes=excludes):
                args = [arg for sid in excludes for arg in ("--exclude", sid)]
                _, text, _ = self.recap("--recent", 2, *args, env=env)
                self.assertIn("\n> The 2 most recent sessions in this project, "
                              f"newest first{note}.\n", text)

    def test_exclude_prefixes_and_warnings(self):
        ids = ["abcdef12-1111-4111-8111-000000000001",
               "abcdef34-1111-4111-8111-000000000002",
               "12345678-1111-4111-8111-000000000003"]
        for day, sid in enumerate(ids, 1):
            self.add(sid, "codex", day)
        _, text, err = self.recap("--recent", 3, "--exclude", "12345678",
                                  "--exclude", "ABCDEF12")
        self.assertEqual(self.picked(text), [ids[1]])
        self.assertEqual(err.count("ignored"), 0)
        _, text, err = self.recap("--recent", 3, "--exclude", "abcdef",
                                  "--exclude", "fedcba98")
        self.assertEqual(self.picked(text), list(reversed(ids)))
        self.assertIn("--exclude abcdef: matches 2 sessions, give more of the id; ignored",
                      err)
        self.assertIn("--exclude fedcba98: matches no session in this project; ignored",
                      err)

    def test_recap_saves_never_replace_an_export(self):
        self.add(IDS[0], "claude", 1)
        self.add(IDS[1], "codex", 2)
        # All named after the same first session: each kind keeps its own file.
        export, _, _ = self.recap(IDS[1], IDS[0], "--save")
        recap, _, _ = self.recap("--recent", 2, "--save")
        self.assertEqual(recap, export.with_name(export.stem + "-2.md"))
        single, _, _ = self.recap(IDS[1], "--save")
        self.assertEqual(single, export.with_name(export.stem + "-3.md"))
        self.assertEqual(self.recap("--recent", 2, "--save")[0], recap)  # again: same file
        trimmed, _, _ = self.recap("--recent", 2, "--save", "--messages", 1)
        self.assertEqual(trimmed, export.with_name(export.stem + "-4.md"))
        signature = TRANSCRIPT["_file_signature"]
        self.assertEqual(signature(export), ("combined", (IDS[1], IDS[0]), None, "tools"))
        self.assertEqual(signature(recap), ("recap", (IDS[1], IDS[0]), None, "tools"))
        self.assertEqual(signature(trimmed), ("recap", (IDS[1], IDS[0]), 1, "tools"))

    def test_messages_needs_ids_or_recent(self):
        self.add(IDS[0], "claude", 1)
        self.assert_rejected("--messages", 2,
                             message="--messages needs a session id or --recent")

    def test_messages_names_and_explicit_ids(self):
        self.add(IDS[0], "claude", 1, count=9)
        self.add(IDS[1], "codex", 2, count=4)
        full, full_text, _ = self.recap(IDS[0])
        trimmed, text, _ = self.recap(IDS[0], "--messages", 2)
        self.assertEqual(trimmed, full.with_name("summary-m2.md"))
        self.assertEqual(full.read_text(encoding="utf-8"), full_text)  # untouched
        self.assertIn("## ✂️ 5 messages omitted", text)
        self.assertIn("> Trimmed with --messages 2: the first and last 2 messages", text)
        combined, text, _ = self.recap(IDS[0], IDS[1], "--messages", 2)
        self.assertEqual(combined.name, "combined-m2.md")
        self.assertEqual(text.count("## ✂️"), 1)  # the 4-message session is whole
        recap, text, _ = self.recap("--recent", 2, "--messages", 2)
        self.assertEqual(recap.name, "recent-m2.md")
        self.assertEqual(text.count("## ✂️"), 1)
        saved, _, _ = self.recap(IDS[0], "--save")
        saved_trim, _, _ = self.recap(IDS[0], "--save", "--messages", 2)
        self.assertEqual(saved_trim, saved.with_name(saved.stem + "-2.md"))  # by header
        exact, _, _ = self.recap(IDS[0], "--to", "exact.md", "--messages", 2)
        self.assertEqual(exact, self.project / "exact.md")


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
        for name in ("resume-lite", "export-lite", "recap-lite"):
            self.assertIn(REPO / "skills" / name, skills)
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
