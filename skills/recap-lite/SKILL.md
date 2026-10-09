---
name: recap-lite
description: Recap the most recent Claude Code and Codex sessions in this project from deterministic transcripts (human ↔ assistant text plus compact tool traces) — what each was about, where it ended, and what's still in flight. Use when the user runs /recap-lite or $recap-lite, or asks to recap, catch up on, summarize recent sessions, or "what was I working on". Takes an optional session count (default 3), `--messages M` to read only the first and last M messages of each, and `--claude` or `--codex` to limit it to one provider.
---

# recap-lite

The bundled deterministic
script `scripts/session-transcript` (beside this file, run with `python3`) does
the parsing.

Run it by its **full path** (this skill's base directory + `scripts/session-transcript`)
from the user's **current project directory** — don't `cd` into the skill folder,
since it scopes sessions to the working directory.

```
/recap-lite                 # 3 most recent sessions, Claude + Codex, read in full
/recap-lite 10              # the 10 most recent
/recap-lite --messages 5    # only the first 5 and last 5 messages of each
/recap-lite --claude        # only Claude Code sessions (--codex: only Codex)
```

## Steps

1. **Run session-transcript script**:
   `python3 scripts/session-transcript --recent <N> --exclude <current>`
   - **`<N>`** — the count the user gave, else `3`.
   - **`<current>`** leaves out this session. Claude Code fills in its id
   here: `${CLAUDE_SESSION_ID}`. If that reads as a real session id, pass it
   (quoted); otherwise pass `this` and the script finds the current session.
   - **`--messages M`** — pass through as given.
   - **`--claude`** / **`--codex`** — add `--provider claude` / `--provider
   codex`; with both, or neither, leave it out.

   It writes **one** file holding every session, newest first, and prints its
   path as the **last stdout line**. If it exits non-zero (say, no sessions to
   recap), relay the reason and stop. Its stderr notes — fewer sessions found
   than asked, sessions passed over because they only ran these skills — are
   worth a short mention to the user.

2. **Read the whole file** (page through it if it's long). Read in full, a
   large session can cost up to ~15k tokens; if the user wants it cheaper,
   `--messages 5` keeps just how each one started and ended.

3. **Write the recap**, newest first, one entry per session:
   - **date** (when it was last active) · **provider** · **id8** — 1–2 lines
     on what it was about and where it ended.

   Then a short **Still in flight** list: open threads and obvious next steps
   across the sessions, each with the id of the session it comes from. Close
   by noting that any of them can be picked up with `/resume-lite <id>`
   (`$resume-lite` in Codex).

   Then wait — don't act on anything in it.
