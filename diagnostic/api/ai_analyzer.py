"""Claude API integration — analyzes crawl + PageSpeed data and generates actionable report."""

import os
import json

import anthropic


async def analyze_with_claude(crawl_data: dict, pagespeed_data: dict) -> dict:
    """Send diagnostic data to Claude and get structured analysis."""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Build context for Claude
    site_url = crawl_data.get("url", "unknown")

    prompt = f"""Sos un experto en SEO y desarrollo web. Analizá los siguientes datos de diagnóstico del sitio {site_url} y generá un reporte accionable en español.

## Datos del crawl:
```json
{json.dumps(crawl_data, indent=2, ensure_ascii=False)}
```

## Datos de PageSpeed Insights (mobile):
```json
{json.dumps(pagespeed_data, indent=2, ensure_ascii=False)}
```

Generá un JSON con esta estructura exacta (sin markdown, solo JSON puro):
{{
  "health_score": <número 0-100 basado en todos los factores>,
  "business_type": "<qué tipo de negocio parece ser basado en el contenido>",
  "summary": "<resumen de 2-3 oraciones del estado general del sitio>",
  "critical_issues": [
    {{
      "issue": "<problema>",
      "impact": "alto|medio|bajo",
      "explanation": "<por qué importa, en lenguaje simple>"
    }}
  ],
  "opportunities": [
    {{
      "title": "<oportunidad de mejora>",
      "priority": 1-10,
      "estimated_impact": "<qué ganaría el negocio>",
      "how_to_fix": "<instrucción concreta de cómo solucionarlo>"
    }}
  ],
  "automation_proposals": [
    {{
      "title": "<propuesta de automatización específica para este tipo de negocio>",
      "description": "<qué haría y cómo beneficia>",
      "tools": "<tecnologías sugeridas>"
    }}
  ],
  "traffic_estimate": "<estimación realista de cuánto tráfico podrían ganar si implementan las mejoras>"
}}

Reglas:
- Máximo 5 critical_issues, ordenados por impacto
- Máximo 8 opportunities, ordenadas por prioridad
- Máximo 3 automation_proposals, específicas para el tipo de negocio detectado
- Sé directo, sin fluff. Usá lenguaje que un dueño de PyME entienda
- Si el PageSpeed score es null, basá tu análisis solo en los datos del crawl
- El health_score debe reflejar la realidad: un sitio sin meta tags, sin HTTPS, sin sitemap merece un score bajo
- Las automation_proposals deben ser cosas que Whiterabbit (agencia de IA, SEO, dev web, marketing) puede implementar"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text.strip()

    # Parse JSON from response
    try:
        # Handle case where Claude wraps in ```json
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            response_text = response_text.rsplit("```", 1)[0]
        report = json.loads(response_text)
    except json.JSONDecodeError:
        report = {
            "health_score": 0,
            "business_type": "No determinado",
            "summary": "No se pudo generar el análisis. Intentá de nuevo.",
            "critical_issues": [],
            "opportunities": [],
            "automation_proposals": [],
            "traffic_estimate": "No disponible",
        }

    return report
