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
- `PreCompact` flushes queued writes.
- Tool calls are not saved in the MVP.

## Setup

Check that the required Honcho CLI is installed:

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

## Status

Run:

```bash
cd "$PLUGIN_ROOT/scripts"
python3 -m honcho_codex.config
```

Then ask the user to open `/hooks` in Codex if hooks have not been reviewed and trusted.

## Privacy

Do not ask the user to paste API keys into chat.
Do not use or install Honcho MCP for this plugin.
Do not save tool calls, tool outputs, Bash output, file patches, or MCP responses.
