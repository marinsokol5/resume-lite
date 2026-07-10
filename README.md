# resume-lite Agent Skill

Resume a **Claude Code or Codex** session from a
deterministic transcript. Just the human ↔ agent
back-and-forth and tools invocations,
parsed from the session's saved JSONL. No LLM summary. No tokens spent. Near instant.

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

Plain Agent Skill, needs Python 3.

```bash
# Install via Agent Skills CLI
npx skills add marinsokol5/resume-lite

# Later you can update it through
npx skills update resume-lite
```

## Use it

As a skill (`/resume-lite` in Claude Code, `$resume-lite` in Codex):

```
/resume-lite <sessionId>
```

It runs the bundled `session-transcript` parser, writes the transcript to
`$TMPDIR/session-transcript/<sessionId>/summary.md`, reads it back, and gives a
short orientation.

Or run the parser directly:

```shell
skills/resume-lite/scripts/session-transcript <sessionId>   # write the transcript, print its path
```

Flags: `--no-tools` (drop the tool trace), `--stdout` (also print it),
`--out <file>` (override the path).


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
