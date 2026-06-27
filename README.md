# ActGuard CLI

Local EU compliance CLI — scans your codebase, generates markdown compliance artifacts, and applies fixes with your approval. Grounded in official legal text via RAG.

Covers: **AI Act**, **NIS2**, **DSA**, **GDPR**, and **Data Act**.

**Your source code stays on your machine.** Bring your own LLM key (Mistral, Ollama, or LM Studio).

## Install

```bash
pip install actguard
# or from source:
git clone https://github.com/silatech00/actguard-cli.git
cd actguard-cli
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
```

## Quick start

```bash
cp env.example .env   # set MISTRAL_API_KEY
actguard setup

cd /path/to/your/project
actguard scan .
actguard questions
actguard answer
actguard generate report
```

## À la carte artifacts

| Command | Output |
|---------|--------|
| `actguard generate report` | `compliance_report.md` |
| `actguard generate implement` | `implementation_guide.md` + `agent_prompt.md` |
| `actguard generate rollout` | `rollout_guide.md` |
| `actguard generate privacy` | `privacy_policy.md` |
| `actguard generate tos` | `terms_of_service.md` |
| `actguard generate extras` | `founder_extras.json` |
| `actguard plan` | All of the above |

## Fix workflow

```bash
actguard generate implement
actguard fix --next --dry-run
actguard fix --next --yes
```

## Cursor MCP

```bash
actguard mcp
```

See [`docs/cursor-mcp.md`](docs/cursor-mcp.md).

## Publish to PyPI

```bash
pip install build twine
python -m build
twine upload dist/*
```

## Disclaimer

Automated self-assessment is **not legal advice**. Review all output before use.
