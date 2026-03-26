"""PageSpeed Insights API integration — free, no API key required for basic usage."""

import httpx

PSI_API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


async def get_pagespeed(url: str, strategy: str = "mobile") -> dict:
    """Fetch PageSpeed Insights data for a URL."""
    result = {
        "score": None,
        "lcp": None,
        "cls": None,
        "inp": None,
        "fcp": None,
        "ttfb": None,
        "speed_index": None,
        "total_blocking_time": None,
        "strategy": strategy,
        "opportunities": [],
        "diagnostics": [],
        "error": None,
    }

    params = {
        "url": url,
        "strategy": strategy,
        "category": "performance",
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(PSI_API, params=params)

            if resp.status_code != 200:
                result["error"] = f"PageSpeed API error: {resp.status_code}"
                return result

            data = resp.json()

            # Lighthouse scores
            lh = data.get("lighthouseResult", {})
            categories = lh.get("categories", {})
            perf = categories.get("performance", {})
            result["score"] = round((perf.get("score", 0) or 0) * 100)

            # Core Web Vitals from field data (CrUX)
            loading = data.get("loadingExperience", {}).get("metrics", {})
            if loading:
                lcp_data = loading.get("LARGEST_CONTENTFUL_PAINT_MS", {})
                result["lcp"] = lcp_data.get("percentile")

                cls_data = loading.get("CUMULATIVE_LAYOUT_SHIFT_SCORE", {})
                cls_val = cls_data.get("percentile")
                result["cls"] = cls_val / 100 if cls_val and cls_val > 1 else cls_val

                inp_data = loading.get("INTERACTION_TO_NEXT_PAINT", {})
                result["inp"] = inp_data.get("percentile")

                fcp_data = loading.get("FIRST_CONTENTFUL_PAINT_MS", {})
                result["fcp"] = fcp_data.get("percentile")

                ttfb_data = loading.get("EXPERIMENTAL_TIME_TO_FIRST_BYTE", {})
                result["ttfb"] = ttfb_data.get("percentile")

            # Lab data fallback
            audits = lh.get("audits", {})
            if not result["lcp"]:
                lcp_audit = audits.get("largest-contentful-paint", {})
                result["lcp"] = lcp_audit.get("numericValue")

            if not result["fcp"]:
                fcp_audit = audits.get("first-contentful-paint", {})
                result["fcp"] = fcp_audit.get("numericValue")

            si = audits.get("speed-index", {})
            result["speed_index"] = si.get("numericValue")

            tbt = audits.get("total-blocking-time", {})
            result["total_blocking_time"] = tbt.get("numericValue")

            # Opportunities (things to fix)
            for key, audit in audits.items():
                if audit.get("details", {}).get("type") == "opportunity":
                    savings = audit.get("details", {}).get("overallSavingsMs", 0)
                    if savings and savings > 100:
                        result["opportunities"].append({
                            "title": audit.get("title", key),
                            "savings_ms": round(savings),
                            "description": audit.get("description", "")[:200],
                        })

            # Sort by savings
            result["opportunities"].sort(key=lambda x: x["savings_ms"], reverse=True)
            result["opportunities"] = result["opportunities"][:8]

    except httpx.TimeoutException:
        result["error"] = "PageSpeed API timeout (>60s). Intentá de nuevo."
    except Exception as e:
        result["error"] = f"Error PageSpeed: {str(e)[:200]}"

    return result
