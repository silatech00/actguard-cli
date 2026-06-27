# ActGuard — Cursor MCP setup

ActGuard exposes tools via a local MCP server. Cursor launches it as a subprocess; scans and report generation run on your machine with **your LLM API key**.

## Prerequisites

```bash
pip install actguard
# or: pip install -e . from the repo root

cp env.example .env   # set MISTRAL_API_KEY
actguard setup
```

## Cursor configuration

Add to **Cursor Settings → MCP** (or `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "actguard": {
      "command": "actguard",
      "args": ["mcp"],
      "env": {
        "MISTRAL_API_KEY": "your_key_here"
      }
    }
  }
}
```

For a dev install from source, point `command` at your venv Python:

```json
{
  "mcpServers": {
    "actguard": {
      "command": "/absolute/path/to/ACTGUARD/venv/bin/python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/absolute/path/to/ACTGUARD",
      "env": {
        "MISTRAL_API_KEY": "your_key_here"
      }
    }
  }
}
```

## MCP tools

| Tool | Description |
|------|-------------|
| `actguard_scan` | Scan workspace locally |
| `actguard_get_questions` | List Q&A questions |
| `actguard_submit_answers` | Submit answers as JSON |
| `actguard_generate_report` | Generate compliance report markdown |
| `actguard_generate_artifact` | Generate any artifact (`report`, `implement`, `rollout`, `privacy`, `tos`, `extras`, `all`) |
| `actguard_status` | Session + LLM status |

## Typical chat flow

1. "Run an EU compliance scan on this project" → `actguard_scan`
2. Agent asks questions → `actguard_get_questions` → user answers → `actguard_submit_answers`
3. "Generate the compliance report" → `actguard_generate_report`
4. Optional: `actguard_generate_artifact` with `implement`, `privacy`, etc.

Reports are saved as markdown in the project root (e.g. `compliance_report.md`).
