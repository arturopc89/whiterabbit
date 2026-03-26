"""Web crawler — extracts meta tags, headers, images, links, security headers."""

import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


async def crawl_site(url: str) -> dict:
    """Crawl a URL and extract SEO-relevant data."""
    result = {
        "url": url,
        "status_code": None,
        "redirect_chain": [],
        "https": url.startswith("https"),
        "meta": {},
        "headings": {"h1": [], "h2": [], "h3": []},
        "images": {"total": 0, "missing_alt": 0, "missing_alt_srcs": []},
        "links": {"internal": 0, "external": 0, "broken": []},
        "security_headers": {},
        "robots_txt": None,
        "sitemap": None,
        "word_count": 0,
        "errors": [],
    }

    headers = {
        "User-Agent": "WhiteRabbit-SEO-Diagnostic/1.0 (+https://whiterabbit.com.py)"
    }

    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=15, headers=headers
        ) as client:
            # Main page
            resp = await client.get(url)
            result["status_code"] = resp.status_code
            result["redirect_chain"] = [
                str(r.url) for r in resp.history
            ]

            # Security headers
            for h in [
                "strict-transport-security",
                "x-frame-options",
                "x-content-type-options",
                "content-security-policy",
                "x-xss-protection",
            ]:
                val = resp.headers.get(h)
                if val:
                    result["security_headers"][h] = val

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            # Meta tags
            title_tag = soup.find("title")
            result["meta"]["title"] = title_tag.string.strip() if title_tag and title_tag.string else None
            result["meta"]["title_length"] = len(result["meta"]["title"]) if result["meta"]["title"] else 0

            desc = soup.find("meta", attrs={"name": "description"})
            result["meta"]["description"] = desc["content"].strip() if desc and desc.get("content") else None
            result["meta"]["description_length"] = len(result["meta"]["description"]) if result["meta"]["description"] else 0

            # OG tags
            og_tags = {}
            for og in soup.find_all("meta", attrs={"property": re.compile(r"^og:")}):
                og_tags[og.get("property")] = og.get("content", "")
            result["meta"]["og_tags"] = og_tags

            # Canonical
            canonical = soup.find("link", attrs={"rel": "canonical"})
            result["meta"]["canonical"] = canonical["href"] if canonical and canonical.get("href") else None

            # Structured data
            json_lds = soup.find_all("script", attrs={"type": "application/ld+json"})
            result["meta"]["structured_data_count"] = len(json_lds)

            # Viewport
            viewport = soup.find("meta", attrs={"name": "viewport"})
            result["meta"]["has_viewport"] = viewport is not None

            # Headings
            for level in ["h1", "h2", "h3"]:
                tags = soup.find_all(level)
                result["headings"][level] = [t.get_text(strip=True) for t in tags]

            # Images
            images = soup.find_all("img")
            result["images"]["total"] = len(images)
            for img in images:
                alt = img.get("alt", "").strip()
                if not alt:
                    result["images"]["missing_alt"] += 1
                    src = img.get("src", img.get("data-src", "?"))
                    result["images"]["missing_alt_srcs"].append(src[:80])
            # Limit list
            result["images"]["missing_alt_srcs"] = result["images"]["missing_alt_srcs"][:10]

            # Links
            parsed_base = urlparse(url)
            all_links = soup.find_all("a", href=True)
            for a in all_links:
                href = a["href"]
                if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
                    continue
                full = urljoin(url, href)
                parsed = urlparse(full)
                if parsed.netloc == parsed_base.netloc:
                    result["links"]["internal"] += 1
                else:
                    result["links"]["external"] += 1

            # Word count (visible text)
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            result["word_count"] = len(text.split())

            # Robots.txt
            try:
                robots_url = f"{parsed_base.scheme}://{parsed_base.netloc}/robots.txt"
                r = await client.get(robots_url)
                if r.status_code == 200 and "user-agent" in r.text.lower():
                    result["robots_txt"] = "found"
                else:
                    result["robots_txt"] = "not_found"
            except Exception:
                result["robots_txt"] = "error"

            # Sitemap
            try:
                sitemap_url = f"{parsed_base.scheme}://{parsed_base.netloc}/sitemap.xml"
                r = await client.get(sitemap_url)
                if r.status_code == 200 and ("urlset" in r.text.lower() or "sitemapindex" in r.text.lower()):
                    result["sitemap"] = "found"
                else:
                    result["sitemap"] = "not_found"
            except Exception:
                result["sitemap"] = "error"

    except httpx.TimeoutException:
        result["errors"].append("Timeout: el sitio tardó más de 15 segundos en responder")
    except httpx.ConnectError:
        result["errors"].append("No se pudo conectar al sitio. Verificá que la URL sea correcta.")
    except Exception as e:
        result["errors"].append(f"Error al analizar: {str(e)[:200]}")

    return result
