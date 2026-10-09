---
name: export-lite
description: Export a Claude Code or Codex session as a deterministic Markdown transcript (human ↔ assistant text plus compact tool traces) saved into the project as transcripts/<date>-<topic>.md, without resuming it. Use when the user runs /export-lite or $export-lite, or asks to export, save, keep or archive a session transcript. With no arguments it exports the current session; words name the file; session ids export other sessions; a path picks the file.
---

# export-lite

The bundled deterministic
script `scripts/session-transcript` (beside this file, run with `python3`) does
the parsing.

Run it by its **full path** (this skill's base directory + `scripts/session-transcript`)
from the user's **current project directory** — don't `cd` into the skill folder,
since it scopes sessions to the working directory.

```
/export-lite                          # this session; you pick a short topic
/export-lite <topic words…>           # this session → transcripts/<date>-<topic>.md
/export-lite <id> [<id>…] [topic…]    # other session(s)
/export-lite … path/to/file.md        # exact path, no date (a dir/ → <date>-<topic>.md inside it)
/export-lite … --deep | --no-tools
```

## Steps

1. **Sort the arguments.** Each one is:
   - a **session** — a session id, full or its first 8+ characters (the script
     resolves it), or `this`;
   - a **path** — only a destination the user plainly gives: a word ending in
     `/` or `.md`, or starting with `./`, `../`, `~/` or `/`. A `.md` word that
     names an existing file other than an earlier export (`fix README.md
     typos`) is a topic word, never a path; so is a `/` inside a word
     (`CI/CD pipeline`);
   - a **flag** — `--deep`, `--no-tools`;
   - otherwise a **topic word**: all of them, in order, make the topic.

   No session given means the current one. Claude Code fills in its id here:
   `${CLAUDE_SESSION_ID}`. If that reads as a real session id, use it;
   otherwise use `this` and the script finds the current session.

2. **Pick the topic.** The user's own words always win — they name things
   better. With none, for the current session choose a concise 3–6 word topic
   saying what it was about; for another session leave the topic out (the file
   is then named after its opening prompt) rather than read it to find out.

3. **Run session-transcript script**, all sessions in one invocation:
   `python3 scripts/session-transcript "<id>" ["<id>" ...] --save --topic "<topic>"`
   - **A path** — `--to "<path>"` instead of `--save`. A file path is used
     exactly as given, with no date. A directory (an existing one, or a path
     ending in `/`) gets `<date>-<topic>.md` inside it.
   - **Flags** — pass through as given.

   It always writes **one** file (several sessions are stitched into a single
   transcript, in the order given) and prints its path as the **last stdout
   line**. When it exits non-zero:
   - **a word you took for a session isn't one** — an 8+ character hex or
     digit word (a commit hash, `20261009`): run again with it as a topic word;
   - **a missing or ambiguous id** otherwise — relay the reason and ask the
     user to confirm;
   - **it won't replace a file** that's there already (not an earlier export
     of these sessions) — never work around that; ask for another path, or
     drop it and use `--save`;
   - **it can't tell which session is `this`** — run it with no arguments to
     list this project's sessions, take the newest, and tell the user which id
     you picked.

4. **Report the path and stop**, saying which topic you chose if the user
   didn't give one. Where it applies, tell them that exporting the same
   session(s) again overwrites that file, while a different session that gets
   the same name is saved as `-2`, `-3`, …; and that with `--deep` the date
   comes from the oldest session in the chain.

   Never read the transcript back: exporting keeps a session without spending
   this conversation's context on it. Continuing from a session is
   `/resume-lite` (`$resume-lite` in Codex).
