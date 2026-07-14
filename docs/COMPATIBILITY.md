# Compatibility

## Runtime requirements

- Python 3.10 through 3.14.
- A writable ATLAS home directory, normally `~/.atlas-skill`.
- Windows and Linux are exercised by CI. Other Python-supported platforms may
  work but are not release-gated yet.

## Codex

- The conversation host must support Codex hooks and allow the installed hooks.
- Project and user hook files are supported.
- Native taxonomy learning requires a runnable `codex` CLI with an authenticated
  session. The desktop app alone does not guarantee that background CLI access
  is available.
- Run `atlas-doctor --codex` after installation. A native-backend CLI or auth
  failure is an error, not a warning.

## Claude Code

- The installed Claude Code build must expose the hook event and blocking
  contracts checked by `atlas-doctor --claude-code`.
- Native taxonomy learning requires a runnable, authenticated `claude` CLI and
  the non-interactive `claude -p` surface.
- ATLAS verifies `claude auth status` without making a taxonomy model call.

## Credentials and usage

Native interactive workers reuse the signed-in host CLI. They do not require
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or a second external provider account.
They can still consume the host account's included usage or billed usage under
that host's normal terms.

Provider-backed project installs and direct runtime integrations continue to
support OpenAI-compatible, Anthropic, Gemini, and AWS Bedrock credentials.
Credential values are read from the environment and are never written to the
ATLAS config.

## Current limitations

- Hooks cannot inject a completion notice into an idle conversation. The notice
  is delivered exactly once at the next host lifecycle event.
- Codex uses a compact single-pass Stop checkpoint because a continued desktop
  turn is not guaranteed to invoke Stop again.
- Taxonomy rollback and task-group selection are configuration/runtime controls;
  there is no graphical management surface yet.
- Automatic redaction is enabled by default, but traces can still contain
  sensitive task content. Do not place secrets in prompts or tool output.
