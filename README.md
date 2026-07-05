# light-resume

Resume a previous Claude Code session from a **fast, zero-token "light" transcript** —
just the human ↔ assistant back-and-forth (plus a compact note of which tools ran),
parsed straight from the session's saved JSONL. No LLM pass, no tokens, ~instant.

It's the cheap alternative to `/summarize` for the common case: you open a fresh
`claude` and just want to remember where you left off and keep going.

## What you get

```
/light-resume                 # resume the most recent session in this project
/light-resume <sessionId>     # resume a specific session
```

The `light-resume` skill runs a bundled parser that writes
`$TMPDIR/claude-code-session-transcript/<sessionId>/summary.md`, reads it back, and
gives you a short orientation before waiting for direction.

Session ids are the `.jsonl` filenames under `~/.claude/projects/<encoded-cwd>/`.

## Install (Claude Code plugin)

```shell
/plugin marketplace add marinsokol/claude-session-summarize
/plugin install light-resume@claude-session-tools
```

To develop/use it from a local clone instead of GitHub:

```shell
/plugin marketplace add /path/to/claude-session-summarize
/plugin install light-resume@claude-session-tools
```

Requires Python 3 (macOS ships it; no third-party dependencies).

## The parser (standalone)

You can also run the parser directly — e.g. to seed a brand-new session:

```shell
skills/light-resume/claude-code-session-transcript <sessionId | path.jsonl | last> \
  [--project <cwd-or-encoded-dir>] [--out <file>] [--no-tools] [--stdout]

# seed a fresh interactive session with the transcript:
claude "$(skills/light-resume/claude-code-session-transcript last --stdout --out /dev/null 2>/dev/null)"
```

- `last` / `latest` → newest session in the current project (else newest anywhere).
- Prints the output file path as its final stdout line.

## What it keeps / drops

**Keeps:** real user prompts, assistant text replies, a one-line `🔧 tools:` trace per turn.
**Drops:** assistant thinking, tool inputs/outputs, subagent (sidechain) chatter, harness plumbing.

It's a memory jog, not a full replay. For exact prior tool results, read the raw
JSONL under `~/.claude/projects/`.

## Why not `npx skills add`?

This only understands Claude Code's own `~/.claude` session format, so the
cross-agent Agent Skills standard buys nothing here — it ships as a Claude Code
plugin only.
