SAMPLE_IMPLEMENTATION_GUIDE = """# Compliance Implementation Guide

## Project context

Healthcare chatbot using Python/FastAPI with OpenAI API integration. Processes health-related user data in models.py.

## How to use this guide

Work through tasks in priority order. For AI coding agents, copy the Agent prompt section below.

## Prioritized backlog

### P0 — Conduct GDPR DPIA for health data
- **Regulation:** GDPR
- **Type:** process
- **Why:** Special category health data detected without DPIA evidence
- **Files / areas:** models.py, data/patient_records.py
- **Implementation steps:**
  1. Document all health data fields and processing purposes
  2. Assess risks and mitigations
  3. Record DPIA outcome in docs/compliance/
- **Acceptance criteria:**
  - DPIA document exists covering all health data fields
  - Legal review slot scheduled
- **Effort:** medium

### P1 — Add AI transparency notice to recommendation UI
- **Regulation:** AI Act
- **Type:** code
- **Why:** No documented AI transparency notice in README or UI
- **Files / areas:** src/components/RecommendationCard.tsx, README.md
- **Implementation steps:**
  1. Add visible "AI-generated" badge to recommendation cards
  2. Update README with AI system description
- **Acceptance criteria:**
  - Badge visible on all AI recommendation surfaces
  - README documents AI use case
- **Effort:** small

## Agent prompt

```
You are implementing EU compliance fixes for HealthBot (Python/FastAPI + React).

Work through these tasks in priority order. Match existing code conventions.

P0 — Conduct GDPR DPIA for health data (GDPR)
Files: models.py, data/patient_records.py
Steps: Document health fields, assess risks, record in docs/compliance/
Acceptance: DPIA document exists; legal review scheduled

P1 — Add AI transparency notice (AI Act)
Files: src/components/RecommendationCard.tsx, README.md
Steps: Add AI-generated badge; update README
Acceptance: Badge on all recommendation surfaces

Tasks under Notes for legal review need lawyer input — implement scaffolding only.
```

## Notes for legal review

- Final DPIA sign-off requires qualified data protection counsel
- AI Act conformity assessment if risk classification changes to high-risk
"""
