# resume-lite Agent Skills

Light, deterministic transcripts of **Claude Code and Codex** sessions. Just
the human ↔ agent back-and-forth and tools invocations, parsed from the
session's saved JSONL. No LLM summary. No tokens spent. Near instant.

| Skill | Use it to |
| ----- | --------- |
| [`resume-lite`](#resume-lite) | pick a session back up where it left off |
| [`export-lite`](#export-lite) | save a session's transcript into the project, to keep or commit |

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
npx skills add marinsokol5/resume-lite --skill export-lite
npx skills add marinsokol5/resume-lite --list   # what's in the repo

# Later you can update them through
npx skills update resume-lite export-lite
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

## export-lite

**Keep** a session instead of resuming it: the transcript is written into the
project, named to be recognizable in a repo listing, so it can be committed
alongside the work it describes. The skill reports the path and stops — it
never reads the transcript back, so exporting costs the current conversation
next to nothing.

```
/export-lite                        # list sessions, ask which
/export-lite <id> [<id> ...]        # → transcripts/<date>-<topic>-<id8>.md
/export-lite this                   # the current session
/export-lite <id> --deep            # include the chain it was resumed from
/export-lite <id> --to <path>       # file = exact name; directory = auto-name inside it
/export-lite <id> --no-tools        # conversation only, no tool trace
```

```
/export-lite <sessionId>
# transcripts/2026-09-07-let-s-support-multiple-session-ids-provided-one-48f4b8ff.md
```

- **Naming.** Date and opening prompt of the first session, then its short id.
  Several sessions add `+<n>more-<hash>`, where `<n>` counts the sessions after
  the first (3 sessions → `+2more`), so another combination with the same
  opening session doesn't replace the earlier file. With `--deep` the name
  comes from the oldest session in the chain, not the one you named.
- **Re-exporting** the same session(s) overwrites that same file — handy to
  refresh an export once the session has moved on.
- **`--to`** takes a file path as the exact name. A directory — one that
  exists, or any path ending in `/` (created) — gets the auto-generated name
  inside it: `--to notes/` → `notes/<date>-<topic>-<id8>.md`.
- **`this`** is the session you're in. Claude Code hands the skill its id; in
  Codex (or anywhere it isn't handed over) the parser reads it from
  `CODEX_THREAD_ID` or `CLAUDE_CODE_SESSION_ID`.

Exported files get a neutral header (no "continue the work" line), and running
an export doesn't make the exporting chat count as resumed from it for `--deep`.

## Run the parser directly

It's bundled in each skill's folder as `scripts/session-transcript` — for a
global install, `~/.agents/skills/resume-lite/scripts/session-transcript`. Run
it from the project directory — sessions are scoped to the working directory.
The transcript's path is the last line it prints.

```shell
~/.agents/skills/resume-lite/scripts/session-transcript                     # list this project's sessions
~/.agents/skills/resume-lite/scripts/session-transcript <sessionId> [...]   # write ONE transcript, print its path
~/.agents/skills/resume-lite/scripts/session-transcript <sessionId> --save  # keep it in transcripts/
```

Flags: `--deep` (add the chain they were resumed from), `--no-tools` (drop the
tool trace), `--stdout` (also print it), `--save` (keep it in `transcripts/`),
`--out <path>` / `--to <path>` (file = exact name; directory = auto-name
inside it). Run from an agent's shell, `this` stands for that agent's own
session (read from `CODEX_THREAD_ID` or `CLAUDE_CODE_SESSION_ID`).


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
