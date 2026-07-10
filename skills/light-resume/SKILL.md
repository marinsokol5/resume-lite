---
name: light-resume
description: Resume a previous Claude Code session from a fast, zero-token "light" transcript (human ↔ assistant text only, no LLM summarization). Use when the user runs /light-resume, wants to continue/pick up a past session, or says "resume session <id>", "load where we left off", "light summary of session". Takes an optional session id; with none, it lists this project's sessions to choose from.
---

# light-resume

Reconstruct just enough context to continue a previous session, **without** the
slow, token-heavy `/summarize`. A bundled script parses the raw session JSONL
and writes a light markdown transcript (user ↔ assistant text + a compact trace
of which tools ran); you then read that file and carry on.

## Steps

1. **Locate the bundled parser.** The script sits next to this `SKILL.md`, but the
   skill's install root varies (`~/.claude/skills` for a user install, a
   project's `.claude/skills`), so find it by searching the standard skill roots:

   ```bash
   SCRIPT="$(find -L ~/.claude/skills "$PWD/.claude/skills" \
        -path '*/light-resume/session-transcript' 2>/dev/null | sort | tail -1)"
   ```

2. **Pick the session.**
   - If the user gave a session id in their args (`$ARGUMENTS`), use it.
   - If they gave **nothing**, run `"$SCRIPT"` with no argument to print the list
     of this project's sessions (`id · time · first prompt`), show it to the user,
     and ask which to resume. Don't guess — wait for them to choose an id.

3. **Run the parser with the chosen id:** `"$SCRIPT" "<sessionId>"`. It prints the
   output file path as its last stdout line, e.g.
   `$TMPDIR/session-transcript/<sessionId>/summary.md`. It writes no tokens and
   returns near-instantly.

4. **Read that file** with the Read tool.

5. **Give the user a 2–3 line orientation**: what the session was about, the
   last thing that was happening, and the obvious next step — then wait for
   direction (don't auto-run anything).

## Notes

- The transcript names each tool call and its target (file read/edited, URL
  fetched, ...) but omits tool *outputs* and assistant *thinking* — it's a memory
  jog, not a full replay. If you need exact prior tool results, the raw JSONL is
  under `~/.claude/projects/<encoded-cwd>/`.
- Flags: `--no-tools` drops the `🔧 tools:` trace (convo-only mode); `--stdout`
  also prints the transcript; `--out <file>` overrides the output path.
- Sessions are scoped to the current directory's project. If an id isn't found,
  the script exits non-zero with a message — relay it and ask the user to confirm
  the id (session ids are the `.jsonl` filenames under `~/.claude/projects/`).
