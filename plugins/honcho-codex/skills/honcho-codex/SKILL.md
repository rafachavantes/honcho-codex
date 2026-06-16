---
name: honcho-codex
description: Use when configuring, debugging, or verifying Honcho memory integration in Codex. Helps inspect hook status, setup user-specific config, and confirm recall/upload behavior.
---

# Honcho Codex

Honcho memory integration for Codex via lifecycle hooks.

## Core Behavior

- `SessionStart` loads Honcho recall and injects it as Codex context.
- `UserPromptSubmit` saves the user prompt. It does not inject recall by default, keeping hook context out of the UI.
- `Stop` saves the assistant's final response for the turn.
- `PreCompact` flushes queued writes before compaction.
- `PostCompact` flushes queued writes after compaction without injecting memory.
- Tool calls are not saved in the MVP.

## Operating Rules

- This plugin is REST-only. It talks to Honcho through the bundled Python client, not through MCP.
- Do not use `mcp__honcho` for this plugin, even if an unrelated Honcho MCP server is available in the Codex session.
- Do not guess `peer_id`, `assistantPeer`, workspace, or session names.
- Before debugging or doing any explicit Honcho lookup, read the resolved plugin config:

```bash
PROJECT_CWD="$PWD"
cd "$PLUGIN_ROOT/scripts"
python3 -m honcho_codex.config --cwd "$PROJECT_CWD"
```

Use the reported `userPeer`, `assistantPeer`, `workspace`, and `exampleSession` as the source of truth.

For a REST-based status/context lookup, run:

```bash
PROJECT_CWD="$PWD"
cd "$PLUGIN_ROOT/scripts"
python3 -m honcho_codex.status --cwd "$PROJECT_CWD"
```

This prints the resolved config, current session name, session context, and peer card using the same REST path as the hooks.

## Setup

The memory hooks talk to Honcho directly over HTTP (no CLI needed at runtime).
The Honcho CLI is only used for diagnostics/setup below; if it's installed you
can check connectivity with:

```bash
command -v honcho
honcho doctor --json
```

Check whether `HONCHO_API_KEY` is available:

```bash
test -n "$HONCHO_API_KEY" && echo configured || echo missing
```

If missing, tell the user to set it outside the chat:

```bash
export HONCHO_API_KEY="your-key"
```

Optional user config lives at `~/.honcho/codex/config.json`.

To opt back into prompt-time context injection, set:

```json
{
  "injectUserPromptContext": true
}
```

To control memory injection after the CLI compacts context (default `slim` — a one-line pointer so the compaction summary isn't refilled):

```json
{
  "injectOnCompact": "slim"
}
```

Valid values: `full` (re-inject everything), `slim`, `off`.

## Status

Run:

```bash
PROJECT_CWD="$PWD"
cd "$PLUGIN_ROOT/scripts"
python3 -m honcho_codex.config --cwd "$PROJECT_CWD"
```

Then ask the user to open `/hooks` in Codex if hooks have not been reviewed and trusted.

## Privacy

Do not ask the user to paste API keys into chat.
Do not use or install Honcho MCP for this plugin.
Do not save tool calls, tool outputs, Bash output, file patches, or MCP responses.
