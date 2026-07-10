# light-resume

Resume a previous Claude Code or Codex session from a **fast, zero-token "light" transcript** —
just the human ↔ assistant back-and-forth (plus a compact note of which tools ran,
and their targets), parsed straight from the session's saved JSONL. No LLM pass,
no tokens, ~instant.

It's the deterministic alternative to an LLM-generated summary or compaction for
the common case: open a fresh agent and recover where you left off.

## What you get

```
/light-resume                 # list this project's Claude/Codex sessions
/light-resume <sessionId>     # resume a specific session
```

The `light-resume` skill runs a bundled parser that writes
`$TMPDIR/session-transcript/<sessionId>/summary.md`, reads it back, and
gives you a short orientation before waiting for direction.

The session id determines which store and parser to use automatically.

## Install

It's a plain Agent Skill—no plugin or marketplace required.

**A. Skills CLI**
```shell
npx skills add marinsokol5/light-resume
```

**B. Clone for Codex** (works globally)
```shell
git clone https://github.com/marinsokol5/light-resume "${CODEX_HOME:-$HOME/.codex}/skills/light-resume"
```

**C. Clone for Claude Code** (works globally)
```shell
git clone https://github.com/marinsokol5/light-resume ~/.claude/skills/light-resume
```

**D. Symlink for local development** (choose the agent's skills directory)
```shell
ln -s "$PWD" "${CODEX_HOME:-$HOME/.codex}/skills/light-resume"
ln -s "$PWD" ~/.claude/skills/light-resume
```

Then start a new session and invoke `light-resume`; Claude Code also exposes it
as `/light-resume`. Requires Python 3 and no third-party dependencies.

## The parser (standalone)

You can also run the parser directly:

```shell
./session-transcript                 # list this project's sessions
./session-transcript <sessionId> [--out <file>] [--no-tools] [--stdout]

# seed a fresh interactive session with a transcript:
claude "$(./session-transcript <sessionId> --stdout --out /dev/null 2>/dev/null)"
```

- No argument → prints this project's sessions (`provider · id · time · first prompt`); pick one.
- With a `<sessionId>` → prints the output file path as its final stdout line.
- The list is scoped to the current directory; id lookup searches both stores.

## What it keeps / drops

**Keeps:** real user prompts, assistant text replies, and a one-line `🔧 tools:`
trace per turn that names each tool **and its target** — files read/edited, URLs
fetched, search patterns, etc. (`--no-tools` drops the trace for a convo-only view).
**Drops:** assistant thinking, tool *outputs*, subagent (sidechain) chatter, and
harness plumbing (`isMeta` records — `/context` dumps, local-command caveats, skill
base-dir notices, and "Continue from where you left off." continuations).

For Codex, patch headers provide exact `Edit`/`Write`/`Delete` targets; common
shell commands are classified into deterministic `Read`, `Search`, `Git`, `Run`,
and validation labels, while unrecognized shell plumbing is omitted.

It's a memory jog, not a full replay. For exact prior tool results, inspect the
raw JSONL in either supported session store below.

## Supported session stores

- Claude Code: `~/.claude/projects/<encoded-cwd>/<sessionId>.jsonl`
- Codex: `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-…-<sessionId>.jsonl`
  (normally `~/.codex/sessions/`; archived sessions are also recognized)

The formats use separate adapters and one shared Markdown renderer.
