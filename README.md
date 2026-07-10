# light-resume

Resume a previous Claude Code session from a **fast, zero-token "light" transcript** —
just the human ↔ assistant back-and-forth (plus a compact note of which tools ran,
and their targets), parsed straight from the session's saved JSONL. No LLM pass,
no tokens, ~instant.

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

## Install

It's a plain [Agent Skill](https://code.claude.com/docs/en/skills) — no plugin,
no marketplace. Pick either:

**A. Skills CLI**
```shell
npx skills add marinsokol5/light-resume
```

**B. Copy it yourself** (works globally once in your user skills dir)
```shell
git clone https://github.com/marinsokol5/light-resume
cp -R light-resume/skills/light-resume ~/.claude/skills/light-resume
```

**C. Symlink for local development** (edits in the repo go live immediately)
```shell
ln -s "$PWD/skills/light-resume" ~/.claude/skills/light-resume
```

Then start a new session and run `/light-resume`. Requires Python 3 (macOS ships
it; no third-party dependencies).

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

**Keeps:** real user prompts, assistant text replies, and a one-line `🔧 tools:`
trace per turn that names each tool **and its target** — files read/edited, URLs
fetched, search patterns, etc. (`--no-tools` drops the trace for a convo-only view).
**Drops:** assistant thinking, tool *outputs*, subagent (sidechain) chatter, harness plumbing.

It's a memory jog, not a full replay. For exact prior tool results, read the raw
JSONL under `~/.claude/projects/`.

## Claude Code only

This understands Claude Code's own `~/.claude` session format, so it's inherently
Claude-Code-specific — the cross-agent portability of the Agent Skills standard
doesn't apply, but the skill format still gives you a clean one-line install.
