---
name: export-lite
description: Export a Claude Code or Codex session as a deterministic Markdown transcript (human ↔ assistant text plus compact tool traces) saved into a file in the project, without resuming it. Use when the user runs /export-lite or $export-lite, or asks to export, save, keep or archive a session transcript. Takes one or more session ids, or `this` for the current session; with none, it lists this project's Claude and Codex sessions to choose from.
---

# export-lite

The bundled deterministic
script `scripts/session-transcript` (beside this file, run with `python3`) does
the parsing.

Run it by its **full path** (this skill's base directory + `scripts/session-transcript`)
from the user's **current project directory** — don't `cd` into the skill folder,
since it scopes sessions to the working directory.

```
/export-lite                        # list sessions, ask which
/export-lite <id> [<id> ...]        # → transcripts/<date>-<topic>-<id8>.md
/export-lite this                   # the current session
/export-lite <id> --deep            # include the chain it was resumed from
/export-lite <id> --to <path>       # file = exact name; directory = auto-name inside it
/export-lite <id> --no-tools        # conversation only, no tool trace
```

## Steps

1. **Pick the session(s)**
   1. **No session id provided** Run `python3 scripts/session-transcript` to list
   this project's sessions, show them to the user, and ask which to export — don't
   guess.
   1. **`this`** means the current session. Claude Code fills in its id here:
   `${CLAUDE_SESSION_ID}`. If that reads as a real session id, pass it;
   otherwise pass `this` itself and the script finds the current session. If
   the script then says it can't tell which session is `this`, run it with no
   ids, take the newest session in the listing, and tell the user which id you
   picked.

2. **Run session-transcript script** with all ids in one invocation, plus
   `--save` unless the user gave `--to`:
   `python3 scripts/session-transcript "<id>" ["<id>" ...] --save`.
   - **`--to <path>`** — pass `--to "<path>"` instead of `--save`. A path ending
   in `/`, or an existing directory, gets the auto-generated name inside it
   (created if needed); anything else is the exact file name. If the user means
   a folder that doesn't exist yet, end it with `/`.
   - **`--deep`**, **`--no-tools`** — pass through as given.

   It always writes **one** file (several ids are stitched into a single
   transcript, in the order given) and prints its path as the **last stdout
   line**. On a missing/ambiguous id it exits non-zero with the reason — relay
   that and ask the user to confirm.

3. **Report the path and stop.** Where it applies, tell the user that
   exporting the same session(s) again overwrites that same file, and that with
   `--deep` the auto-generated name comes from the oldest session in the chain,
   not the id they gave.

   Never read the transcript back: exporting keeps a session without spending
   this conversation's context on it. Continuing from a session is
   `/resume-lite` (`$resume-lite` in Codex).
