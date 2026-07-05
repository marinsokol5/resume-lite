---
name: light-resume
description: Resume a previous Claude Code session from a fast, zero-token "light" transcript (human ↔ assistant text only, no LLM summarization). Use when the user runs /light-resume, wants to continue/pick up a past session, or says "resume session <id>", "load where we left off", "light summary of session". Takes an optional session id (defaults to the most recent session).
---

# light-resume

Reconstruct just enough context to continue a previous session, **without** the
slow, token-heavy `/summarize`. A bundled script parses the raw session JSONL
and writes a light markdown transcript (user ↔ assistant text + a compact trace
of which tools ran); you then read that file and carry on.

## Steps

1. **Resolve the session id** from the user's args (`$ARGUMENTS`). If they gave
   an id, use it. If they said nothing / "last" / "latest", pass `last`.

2. **Run the bundled parser.** `CLAUDE_PLUGIN_ROOT` is *not* reliably set in the
   skill's shell, so locate the script robustly — use the env var if present,
   otherwise find the installed copy in the plugin cache:

   ```bash
   SCRIPT="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/skills/light-resume/claude-code-session-transcript}"
   [ -x "$SCRIPT" ] || SCRIPT="$(find ~/.claude/plugins -path '*light-resume*/claude-code-session-transcript' 2>/dev/null | sort | tail -1)"
   "$SCRIPT" "<sessionId-or-last>"
   ```

   It prints the output file path as its last stdout line, e.g.
   `/tmp/claude-code-session-transcript/<sessionId>/summary.md`. It writes no
   tokens and returns near-instantly.

3. **Read that file** with the Read tool.

4. **Give the user a 2–3 line orientation**: what the session was about, the
   last thing that was happening, and the obvious next step — then wait for
   direction (don't auto-run anything).

## Notes

- The transcript deliberately omits tool *inputs/outputs* and assistant
  *thinking* — it's a memory jog, not a full replay. If you need exact prior
  tool results, the raw JSONL is under `~/.claude/projects/<encoded-cwd>/`.
- Flags: `--no-tools` hides the `🔧 tools:` trace; `--stdout` also prints the
  transcript; `--out <file>` overrides the output path; `--project <path>`
  scopes the search to a specific project.
- If the id isn't found, the script exits non-zero with a message — relay it and
  ask the user to confirm the id (session ids are the `.jsonl` filenames under
  `~/.claude/projects/`).
