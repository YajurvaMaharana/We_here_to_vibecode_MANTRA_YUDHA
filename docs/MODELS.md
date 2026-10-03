# AI Models

## Configured Models

- **Primary Model**: `claude-3-5-sonnet-20241022` via Anthropic API (provider-agnostic wrapper supports swappable models).
- **Fallback / Test Model**: `FakeLLM` for offline determinism and CI execution.

## Configuration

Set `LLM_MODEL` in `.env` to swap active providers and models.
