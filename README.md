# Agentic Test Project

Workspace wrapping the **Iron Abacus Translator** — a Classical Chinese literature translation pipeline.

## Structure

- **`iron_abacus_translator/`** — The pipeline product (processors, utils, scripts, CLI, etc.)
- **`dev/`** — Development tooling (test scripts, demos, evals, admin utilities)
- **`docs/`** — Workspace-level documentation
- **`.claude/agents/`** — Agent definitions for Claude Code

## Quick Start

```bash
cd iron_abacus_translator
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Translate a work
python scripts/orchestrate_translation_pipeline.py D1379

# Run tests
pytest tests/test_sanity.py
```

See `iron_abacus_translator/README.md` for full pipeline documentation.
