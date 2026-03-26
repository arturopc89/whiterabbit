"""FastAPI backend for WhiteRabbit web diagnostic tool."""

import re
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from crawler import crawl_site
from pagespeed import get_pagespeed
from ai_analyzer import analyze_with_claude
from chatbot import chat_response

app = FastAPI(title="WhiteRabbit Diagnostic API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://whiterabbit.com.py",
        "https://www.whiterabbit.com.py",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:5500",
    ],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)


class DiagnoseRequest(BaseModel):
    url: str


def normalize_url(url: str) -> str:
    """Ensure URL has scheme and is valid."""
    url = url.strip()
    if not url:
        raise ValueError("URL vacía")

    if not re.match(r"^https?://", url):
        url = "https://" + url

    parsed = urlparse(url)
    if not parsed.netloc or "." not in parsed.netloc:
        raise ValueError("URL inválida")

    # Block local/private IPs
    hostname = parsed.hostname or ""
    blocked = ["localhost", "127.0.0.1", "0.0.0.0", "::1"]
    if hostname in blocked or hostname.startswith("192.168.") or hostname.startswith("10.") or hostname.startswith("172."):
        raise ValueError("No se pueden analizar URLs locales/privadas")

    return url


@app.post("/api/diagnose")
async def diagnose(req: DiagnoseRequest):
    """Run full diagnostic on a URL."""
    try:
        url = normalize_url(req.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Run crawl and PageSpeed in parallel
    import asyncio
    crawl_task = asyncio.create_task(crawl_site(url))
    pagespeed_task = asyncio.create_task(get_pagespeed(url, strategy="mobile"))

    crawl_data = await crawl_task
    pagespeed_data = await pagespeed_task

    # If crawl had fatal errors, return early
    if crawl_data.get("errors") and not crawl_data.get("status_code"):
        return {
            "success": False,
            "error": crawl_data["errors"][0],
            "crawl": crawl_data,
            "pagespeed": pagespeed_data,
            "report": None,
        }

    # Send to Claude for analysis
    try:
        report = await analyze_with_claude(crawl_data, pagespeed_data)
    except Exception as e:
        report = {
            "health_score": None,
            "summary": f"Error al generar análisis IA: {str(e)[:200]}",
            "critical_issues": [],
            "opportunities": [],
            "automation_proposals": [],
            "traffic_estimate": "No disponible",
        }

    return {
        "success": True,
        "crawl": crawl_data,
        "pagespeed": pagespeed_data,
        "report": report,
    }


class ChatRequest(BaseModel):
    messages: list[dict]


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Chat with WhiteRabbit AI assistant."""
    if not req.messages or len(req.messages) > 20:
        raise HTTPException(status_code=400, detail="Mensajes inválidos")

    # Validate message format
    for msg in req.messages:
        if msg.get("role") not in ("user", "assistant"):
            raise HTTPException(status_code=400, detail="Rol inválido")
        if not msg.get("content") or len(msg["content"]) > 1000:
            raise HTTPException(status_code=400, detail="Mensaje inválido")

    try:
        reply = await chat_response(req.messages)
        return {"reply": reply}
    except Exception as e:
        return {"reply": "Perdón, tuve un problema técnico. Escribinos por WhatsApp y te ayudamos al toque."}


@app.get("/health")
async def health():
    return {"status": "ok"}
