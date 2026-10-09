# resume-lite Agent Skills

Light, deterministic transcripts of **Claude Code and Codex** sessions. Just
the human ↔ agent back-and-forth and tools invocations, parsed from the
session's saved JSONL. No LLM summary. No tokens spent. Near instant.

| Skill | Use it to |
| ----- | --------- |
| [`resume-lite`](#resume-lite) | pick a session back up where it left off |
| [`export-lite`](#export-lite) | save a session's transcript into the project, to keep or commit |
| [`recap-lite`](#recap-lite) | catch up on this project's most recent sessions, and what's still in flight |

Because the output is a plain Markdown transcript, it's also a cross-provider
handoff. Feed a Claude session to Codex, or a Codex session to Claude.

## Why

It's the fast, deterministic alternative to `/compact`, made to be lighter than `--resume`.

Random Claude Code session:

| Source                 |  Tokens |
| ---------------------- | ------: |
| `--resume`             | 365,850 |
| `/export`              |  27,165 |
| /resume-lite          |  12,350 |
| /resume-lite `--no-tools`  |  11,311 |

## Install

Plain Agent Skills, need Python 3.

```bash
# Install all of them via Agent Skills CLI
npx skills add marinsokol5/resume-lite --skill '*'

# Or only the ones you want
npx skills add marinsokol5/resume-lite --skill export-lite --skill recap-lite
npx skills add marinsokol5/resume-lite --list   # what's in the repo

# Later you can update them through
npx skills update resume-lite export-lite recap-lite
```

Each works as `/name` in Claude Code and `$name` in Codex.

Used `/resume-lite --save`? Saving moved to export-lite:
`npx skills add marinsokol5/resume-lite --skill export-lite`.

## resume-lite

```
/resume-lite <sessionId> [<sessionId> ...]
```

It runs the bundled `session-transcript` parser, writes the transcript to
`$TMPDIR/session-transcript/<sessionId>/summary.md`, reads it back, and gives a
short orientation. With no id, it lists this project's Claude and Codex
sessions to pick from.

Pass several ids and they're stitched into a **single** file, in the order
given, each session under its own heading — one conversation continued across
sessions stays one thing to read (written to
`$TMPDIR/session-transcript/<id1+id2+...>-<hash>/combined.md`). The hash covers
all full session ids in transcript order, so different combinations stay separate.

If that session was itself resumed from an earlier one, `--deep` walks the
chain back — transitively, and across providers — and lays it out oldest-first
in the same single file, so naming the most recent chat is enough:

```
/resume-lite <sessionId> --deep
# --deep: 6927fbaf resumed from 01a02f7d
```

It's deterministic, not a guess: a chat started with `/resume-lite <id>` records
that id in its own transcript, so the parser reads it straight back out.

An id can be shortened to its first 8 or more characters — the short id a
recap shows — as long as only one session starts that way (here, and for
export-lite).

## export-lite

**Keep** a session instead of resuming it: the transcript is written into the
project as `transcripts/<date>-<topic>.md`, so it can be committed alongside
the work it describes. Run with no arguments it exports the session you're in;
the words you give it name the file. It reports the path and stops — it never
reads the transcript back, so exporting costs the conversation next to nothing.

```
/export-lite                          # this session; the agent picks a short topic
/export-lite <topic words…>           # this session → transcripts/<date>-<topic>.md
/export-lite <id> [<id>…] [topic…]    # other session(s)
/export-lite … path/to/file.md        # exact path, no date (a dir/ → <date>-<topic>.md inside it)
/export-lite … --deep | --no-tools
```

```
/export-lite add export-lite and recap-lite skills
# transcripts/2026-10-09-add-export-lite-and-recap-lite-skills.md
```

- **Arguments sort themselves:** session ids (full, or their first 8+
  characters) and `this` pick sessions; a destination — a word ending in `/`
  or `.md`, or starting with `./`, `../`, `~/` or `/` — is the path; every
  other word is the topic. So `/export-lite fix README.md typos` names the
  file after the words: an existing file that isn't a transcript is never
  overwritten, even when given as the path.
- **Naming.** The date the first session started, then the topic: your words
  (they always win), else a short one the agent picks for the session you're
  in, else another session's opening prompt. With `--deep` the date is the
  oldest session's in the chain.
- **Re-exporting** the same session(s) overwrites that same file — handy to
  refresh an export once the session has moved on. Anything else already under
  that name (a different session, another combination, a recap, a trimmed or
  `--no-tools` copy, an export you've added notes to, a file of your own) is
  left alone, and the new export takes `-2`, `-3`, …
- **A path** ending in `.md` is used exactly as given (no date). It replaces
  a file there only if that's an earlier export of the same session(s) that
  the new one just extends — never another session's, one you've added notes
  to, or any other file. A directory — one that exists, or any path
  ending in `/` (created) — gets `<date>-<topic>.md` inside it, by the same
  rules.
- **Topics in any language** are spelled out in plain letters
  (`čišćenje Đuro` → `ciscenje-duro`); one with nothing left (`重构`) falls back
  to the opening prompt, with a warning.
- **`this`** is the session you're in. Claude Code hands the skill its id; in
  Codex (or anywhere it isn't handed over) the parser reads it from
  `CODEX_THREAD_ID` or `CLAUDE_CODE_SESSION_ID`.

Exported files get a neutral header (no "continue the work" line), and running
an export doesn't make the exporting chat count as resumed from it for `--deep`.

## recap-lite

**Catch up** on what's been happening in this project: the most recent Claude
Code and Codex sessions go into one transcript, which the agent reads to tell
you, per session, when it was last active (local time), its provider and
short id, what it was about and where it ended — then a short list of what's still in flight, each item with the id
to `/resume-lite`. It reports and waits; it doesn't act on any of it.

```
/recap-lite                 # 3 most recent sessions, Claude + Codex, read in full
/recap-lite 10              # the 10 most recent
/recap-lite --messages 5    # only the first 5 and last 5 messages of each
/recap-lite --claude        # only Claude Code sessions (--codex: only Codex)
```

- **Most recent** means the last recorded activity in each session, not the
  file's modified time (reopening an old chat touches the file, not its
  conversation).
- **Passed over:** the session you're recapping from, Codex's own side
  threads (subagents, guardian reviews), sessions with no conversation, and
  sessions that only ran these skills (a bare `/resume-lite` listing, an
  earlier recap). A session where you went on to type anything else stays.
- **`--messages M`** keeps the first and last M messages of each session. A
  message is one prompt, or the assistant's whole reply to it (all its text
  and tool lines up to the next prompt), so the cut never splits a reply.
  Read in full, a session is usually a few thousand tokens, the largest
  ~60k; `--messages 5` is the cheap read.

## Run the parser directly

It's bundled in each skill's folder as `scripts/session-transcript` — for a
global install, `~/.agents/skills/resume-lite/scripts/session-transcript`. Run
it from the project directory — sessions are scoped to the working directory.
The transcript's path is the last line it prints.

```shell
~/.agents/skills/resume-lite/scripts/session-transcript                     # list this project's sessions
~/.agents/skills/resume-lite/scripts/session-transcript <sessionId> [...]   # write ONE transcript, print its path
~/.agents/skills/resume-lite/scripts/session-transcript <sessionId> --save  # keep it in transcripts/
~/.agents/skills/resume-lite/scripts/session-transcript --recent 3          # this project's 3 most recent, ONE file
```

Flags: `--deep` (add the chain they were resumed from), `--no-tools` (drop the
tool trace), `--stdout` (also print it), `--save` (keep it in `transcripts/`),
`--out <path>` / `--to <path>` (file = exact name; directory = auto-name
inside it), `--topic TEXT` (name a kept transcript after TEXT). Run from an agent's shell, `this` stands for that agent's own
session (read from `CODEX_THREAD_ID` or `CLAUDE_CODE_SESSION_ID`). An id can
be any unique prefix of 8+ characters.

Instead of ids, `--recent N` takes the N most recent sessions (newest first,
by last activity), passing over Codex side threads, empty sessions and ones
that only ran these skills:

- `--provider claude|codex` — one provider only.
- `--exclude <id>` — leave a session out: a full id, a unique prefix of 4+
  characters, or `this`. Repeatable; one that matches nothing is reported and
  ignored.
- It takes no ids and no `--deep`.

`--messages M` (with ids or `--recent`) keeps the first and last M messages of
each session and marks the cut. A message is one user prompt, or the
assistant's whole reply to it — every assistant and plan block up to the next
prompt, with their tool lines (tools alone make a reply too). A session with
2M messages or fewer is kept whole.

Names never collide with a full or resumed transcript:

- A recap: `$TMPDIR/session-transcript/recent-<id1+id2+...>-<hash>/recent.md`.
- Trimmed with `--messages M`: `-m<M>` before `.md` (`summary-m5.md`,
  `recent-m5.md`).
- Kept with `--save` or `--to DIR/`, everything is `<date>-<topic>.md`
  (`--topic TEXT` sets the topic; else the first session's opening prompt): saving
  the same thing again (same sessions, same kind — one, combined or recap —
  same `--messages`) overwrites it; anything else takes the first free `-2`,
  `-3`, …, and a file that isn't one of these transcripts is never touched.


## How it works

**Keeps:** user prompts, agent replies, and a one-line `🔧 tools:` trace per
turn naming each tool and its target (files, URLs, search patterns, commands).

**Drops:** thinking / encrypted reasoning, tool outputs, duplicate records,
subagent chatter, token telemetry, and harness noise.

For example, one opening turn from a Codex session. The raw `.jsonl` that `--resume` reads.

```jsonl
{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"ss: create a separate worktree called codex-support"}]}}
{"type":"event_msg","payload":{"type":"user_message","message":"ss: create a separate worktree called codex-support"}}
{"type":"response_item","payload":{"type":"reasoning","encrypted_content":"gAAAAABqUKpTCloFSqS9BhTQ9nk3n0mv...<~1 KB blob>..."}}
{"type":"event_msg","payload":{"type":"agent_message","message":"I’ll create a sibling worktree and branch named `codex-support` from the current `HEAD`."}}
{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"I’ll create a sibling worktree..."}]}}
{"type":"response_item","payload":{"type":"custom_tool_call","name":"exec","input":"...git worktree list --porcelain && git branch --list codex-support && test ! -e ../codex-support..."}}
{"type":"response_item","payload":{"type":"custom_tool_call_output","output":[{"type":"input_text","text":"worktree /Users/.../claude-session-summarize\nHEAD a949ee3...\n"}]}}
{"type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"input_tokens":14834,...}}}}
```

The same turn as a light transcript:

```markdown
## 👤 User

ss: create a separate worktree called codex-support

## 🤖 Codex

I'll create a sibling worktree and branch named `codex-support` from the current `HEAD`.

_🔧 tools: Git(worktree list), Git(branch codex-support), Git(worktree add codex-support)_

## 🤖 Codex

Created worktree `/Users/marinsokol/projects/codex-support` on branch `codex-support`.
```

It's a memory jog, not a full replay.

## Contributing

- One parser serves every skill, and each skill ships its own copy of it. Edit
  only `skills/resume-lite/scripts/session-transcript`, then run
  `scripts/sync-skill-scripts` to copy it into the others. Copies, not
  symlinks: `npx skills update` compares each skill folder's git tree hash, so
  a symlinked sibling would never pick up a change.
- Tests: `python3 -m unittest discover -s tests` (they also fail when a copy
  has drifted).
- Token counts like the table above: `eval/anthropic-evaluate <sessionId>`.
