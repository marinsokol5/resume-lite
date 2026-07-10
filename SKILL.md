---
name: light-resume
description: Resume a previous Claude Code or Codex session from a fast, zero-token "light" transcript (human ↔ assistant text plus compact tool traces, no LLM summarization). Use when the user runs /light-resume or $light-resume, wants to continue or inspect a past agent session, or says "resume session SESSION_ID", "load where we left off", or "light summary of session". Takes an optional session id; with none, it lists this project's Claude and Codex sessions to choose from.
---

# light-resume

Reconstruct enough context to continue a previous session **without** an LLM
summary or compaction pass. A bundled script parses Claude Code or Codex JSONL,
writes user ↔ assistant text plus compact tool traces to Markdown, and lets you
read the deterministic result.

## Steps

1. **Locate the bundled parser.** The script sits next to this `SKILL.md`, but the
   skill's install root varies, so find it in the standard Codex and Claude roots:

   ```bash
   SCRIPT="$(find -L "${CODEX_HOME:-$HOME/.codex}/skills" \
        "$PWD/.codex/skills" ~/.claude/skills "$PWD/.claude/skills" \
        -path '*/light-resume/session-transcript' 2>/dev/null | sort | tail -1)"
   ```

2. **Pick the session.**
   - If the user gave a session id in their args (`$ARGUMENTS`), use it.
   - If they gave **nothing**, run `"$SCRIPT"` with no argument to print the list
     of this project's sessions (`provider · id · time · first prompt`), show it
     to the user, and ask which to resume. Don't guess; wait for an id.

3. **Run the parser with the chosen id:** `"$SCRIPT" "<sessionId>"`. It prints the
   output file path as its last stdout line, e.g.
   `$TMPDIR/session-transcript/<sessionId>/summary.md`. The matching storage
   location automatically selects the Claude or Codex adapter.

4. **Read that file** with the Read tool.

5. **Give the user a 2–3 line orientation**: what the session was about, the
   last thing that was happening, and the obvious next step — then wait for
   direction (don't auto-run anything).

## Notes

- The transcript names each tool call and its target when available, but omits
  tool *outputs* and assistant *thinking*. For exact details, inspect raw JSONL
  under `~/.claude/projects/<encoded-cwd>/` or
  `$CODEX_HOME/sessions/YYYY/MM/DD/` (normally `~/.codex/sessions/`).
- For Codex, derive exact edit targets from patch headers and classify common
  shell commands deterministically; omit unrecognized shell plumbing instead of
  generating an LLM summary.
- Flags: `--no-tools` drops the `🔧 tools:` trace (convo-only mode); `--stdout`
  also prints the transcript; `--out <file>` overrides the output path.
- Session listing is scoped to the current directory; lookup by id searches both
  stores globally. If an id is missing or ambiguous, relay the non-zero error and
  ask the user to confirm it.
