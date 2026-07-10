---
name: resume-lite
description: Resume a Claude Code or Codex session from a deterministic transcript (human ↔ assistant text plus compact tool traces). Use when the user runs /resume-lite or $resume-lite, or says "light summary of session". Takes an optional session id; with none, it lists this project's Claude and Codex sessions to choose from.
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
   1. **With session id** (from `$ARGUMENTS` or the user's choice) run
   `python3 scripts/session-transcript "<id>"`. It writes the transcript and
   prints its file path as the **last stdout line**. On a missing/ambiguous id
   it exits non-zero with the reason — relay that and ask the user to confirm.

2. **Read the created transcript**, then give a 2–3 line orientation: what the session was
   about, the last thing happening, and the obvious next step. Then wait — don't auto-run anything.
