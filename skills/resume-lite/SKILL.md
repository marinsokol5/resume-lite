---
name: resume-lite
description: Resume a Claude Code or Codex session from a deterministic transcript (human ↔ assistant text plus compact tool traces), or save that transcript into the project to keep. Use when the user runs /resume-lite or $resume-lite, says "light summary of session", or asks to save/keep/archive a session transcript. Takes one or more optional session ids; with none, it lists this project's Claude and Codex sessions to choose from.
---

# resume-lite

The bundled deterministic
script `scripts/session-transcript` (beside this file, run with `python3`) does
the parsing; see its `--help` for modes and flags.

Run it by its **full path** (this skill's base directory + `scripts/session-transcript`)
from the user's **current project directory** — don't `cd` into the skill folder,
since it scopes sessions to the working directory.

## Steps

1. **Run session-transcript script**
   1. **No session id provided** Run `python3 scripts/session-transcript` to list this
   project's sessions, show them to the user, and ask which to resume — don't
   guess. 
   1. **With session id(s)** (from `$ARGUMENTS` or the user's choice) run
   `python3 scripts/session-transcript "<id>" ["<id>" ...]` — pass all ids in
   one invocation. It always writes **one** file (several ids are stitched into
   a single transcript, in the order given) and prints its path as the **last
   stdout line**. On a missing/ambiguous id it exits non-zero with the reason —
   relay that and ask the user to confirm.
   1. **Saving instead of resuming** — when the user asks to keep, save or
   archive a session rather than continue it, add `--save`. The transcript then
   lands in the project as `transcripts/<date>-<topic>-<id>.md`, ready to
   commit, instead of in a temp dir.

2. **Read the transcript file**, then give a 2–3 line orientation — what it was
   about, the last thing happening, and the obvious next step; one such
   orientation per session when it holds several. Then wait — don't auto-run
   anything.

   **Except with `--save`**: report the path and stop. Archiving a session is
   not resuming it, and reading it back would spend the context the save was
   meant to avoid — only read it if the user also asks to continue from it.
