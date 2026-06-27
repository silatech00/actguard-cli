SAMPLE_PLAIN = """## What This Means For You (Plain Language Summary)

This project is a healthcare chatbot using AI recommendations.

### Which EU rules apply to you, in plain terms

- AI Act applies because the app uses machine learning for recommendations.
- GDPR applies because you process health-related user data.

### What to do first

1. Document your AI system's intended purpose.
2. Review data processing agreements with cloud providers.
3. Add transparency notices for AI-generated advice.
"""

SAMPLE_TECHNICAL = """## EU AI Act (Regulation 2024/1689)
- **Applicability**: Applies — uses transformers and OpenAI API
- **Risk classification**: Limited-risk — recommendation system without high-risk Annex III match
- **Key gaps**:
  - No documented AI transparency notice in README
  - Missing human oversight procedure for medical-adjacent advice
- **Priority actions**:
  - Add Art. 50 transparency disclosure before deployment
  - Document intended purpose per Art. 11

## NIS2 Directive (Directive 2022/2555)
- **Applicability**: Unclear — cloud hosting detected
- **Key gaps**:
  - No documented incident response plan
- **Priority actions**:
  - Assess whether entity qualifies as essential/important

## DSA — Digital Services Act (Regulation 2022/2065)
- **Applicability**: Not in scope — no intermediary platform patterns
- **Key gaps**:
  - N/A
- **Priority actions**:
  - Monitor if user-generated content features are added

## GDPR (Regulation 2016/679)
- **Applicability**: Applies — health data fields detected in models.py
- **Key gaps**:
  - No DPIA evidence for special category processing
- **Priority actions**:
  - Conduct DPIA per Art. 35

## Overall priority matrix
1. Conduct GDPR DPIA for health data processing
2. Add AI Act transparency notices
3. Document cloud security controls for NIS2 assessment
4. Review third-party AI provider contracts
5. Establish human review for medical-adjacent outputs
"""

SAMPLE_FULL = SAMPLE_PLAIN + "\n\n<!-- TECHNICAL_REPORT -->\n\n" + SAMPLE_TECHNICAL
