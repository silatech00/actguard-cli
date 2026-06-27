---
name: actguard
description: Run EU compliance scans (AI Act, NIS2, DSA, GDPR, Data Act) on the open workspace via ActGuard MCP tools.
---

# ActGuard EU Compliance

Use when the user asks for EU compliance, AI Act audit, GDPR assessment, or ActGuard scan on their project.

## Prerequisites

- ActGuard MCP server configured (`actguard` in mcpServers)
- `MISTRAL_API_KEY` (or Ollama) set in MCP env — no login required

## Workflow

1. **Scan** — `actguard_scan` with `workspace_path` set to the project root (usually `.`)
2. **Questions** — `actguard_get_questions`, present questions clearly to the user
3. **Answers** — collect answers, call `actguard_submit_answers` with JSON `{"key": "answer", ...}`
4. **Artifacts** — pick à la carte:
   - `actguard_generate_report` — compliance report (plain + legal language)
   - `actguard_generate_artifact` with `implement`, `rollout`, `privacy`, `tos`, `extras`, or `all`

## Privacy

- Source code is scanned **locally** — not uploaded
- LLM calls use the user's own API key

## Output

Point the user to markdown files in their project folder:

| Artifact | File |
|----------|------|
| Report | `compliance_report.md` |
| Implementation | `implementation_guide.md`, `agent_prompt.md` |
| Rollout | `rollout_guide.md` |
| Privacy | `privacy_policy.md` |
| ToS | `terms_of_service.md` |
| Extras | `founder_extras.json` |

## Troubleshooting

| Issue | Action |
|-------|--------|
| No session | Run `actguard_scan` first |
| Q&A incomplete | `actguard_submit_answers` before generate |
| Missing API key | Set `MISTRAL_API_KEY` in MCP env or `.env` |
| implement/rollout fails | Run `actguard_generate_report` first |
