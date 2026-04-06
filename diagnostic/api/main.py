"""FastAPI backend for WhiteRabbit web diagnostic tool."""

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr

from crawler import crawl_site
from pagespeed import get_pagespeed
from ai_analyzer import analyze_with_claude
from chatbot import chat_response

# ── Config ──
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "whiterabbit-admin-2024")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
DB_PATH = os.getenv("DB_PATH", "messages.db")

# ── Email HTML Templates ──

def email_base(content: str) -> str:
    """Wrap content in WhiteRabbit branded email template."""
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{{margin:0;padding:0;background:#030305;font-family:'Helvetica Neue',Arial,sans-serif;color:#eeeef3}}
  .wrapper{{max-width:600px;margin:0 auto;padding:0}}
  .header{{background:linear-gradient(135deg,#030305 0%,#0c0c14 100%);padding:32px 40px;text-align:center;border-bottom:1px solid rgba(0,232,255,0.15)}}
  .logo-row{{display:inline-flex;align-items:center;gap:10px}}
  .logo-img{{width:32px;height:32px}}
  .logo-text{{font-size:24px;font-weight:700;letter-spacing:-0.5px}}
  .logo-white{{color:#eeeef3}}.logo-cyan{{color:#00e8ff}}
  .body-content{{background:#08080d;padding:40px}}
  .body-content p{{color:#b0b0c0;font-size:15px;line-height:1.7;margin-bottom:16px}}
  .body-content h2{{color:#eeeef3;font-size:20px;font-weight:600;margin-bottom:20px}}
  .highlight{{color:#00e8ff;font-weight:600}}
  .quote-box{{background:#0c0c14;border-left:3px solid #8b3dff;padding:16px 20px;margin:24px 0;border-radius:0 8px 8px 0}}
  .quote-box p{{color:#55556a;font-size:13px;margin:0;font-style:italic}}
  .cta-btn{{display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#00e8ff 0%,#8b3dff 100%);color:#030305;text-decoration:none;font-weight:700;font-size:14px;border-radius:8px;margin-top:8px}}
  .footer{{background:#030305;padding:32px 40px;text-align:center;border-top:1px solid rgba(255,255,255,0.05)}}
  .footer p{{color:#55556a;font-size:12px;line-height:1.6;margin:0}}
  .footer a{{color:#00e8ff;text-decoration:none}}
  .divider{{height:1px;background:linear-gradient(90deg,transparent,rgba(0,232,255,0.3),transparent);margin:24px 0}}
</style></head>
<body><div class="wrapper">
  <div class="header">
    <div class="logo-row"><img src="https://www.whiterabbit.com.py/wr_iso_logo.png" alt="WhiteRabbit" class="logo-img"><div class="logo-text"><span class="logo-white">white</span><span class="logo-cyan">rabbit</span></div></div>
  </div>
  <div class="body-content">
    {content}
  </div>
  <div class="footer">
    <p>WhiteRabbit — Automatización & IA en Paraguay</p>
    <p style="margin-top:8px"><a href="https://www.whiterabbit.com.py">www.whiterabbit.com.py</a> · <a href="https://wa.me/595XXXXXXXXX">WhatsApp</a></p>
  </div>
</div></body></html>"""


def email_welcome(name: str) -> str:
    """Auto-reply welcome email when someone sends a message."""
    return email_base(f"""
    <h2>¡Hola {name}! 👋</h2>
    <p>Recibimos tu mensaje y ya estamos en ello. Nuestro equipo te va a responder lo antes posible.</p>
    <div class="divider"></div>
    <p>Mientras tanto, si querés agendar algo más directo:</p>
    <p style="text-align:center;margin-top:24px">
      <a href="https://wa.me/595XXXXXXXXX?text=Hola%20WhiteRabbit!%20Acabo%20de%20dejarles%20un%20mensaje%20en%20la%20web" class="cta-btn">💬 Escribinos por WhatsApp</a>
    </p>
    <div class="divider"></div>
    <p style="color:#55556a;font-size:13px">Este es un mensaje automático. Un humano real te va a responder pronto — probablemente con café en mano ☕</p>
    """)


def email_reply(name: str, reply_text: str, original_message: str) -> str:
    """Branded reply email from the dashboard."""
    return email_base(f"""
    <h2>Hola {name} 👋</h2>
    <p>{reply_text.replace(chr(10), '<br>')}</p>
    <div class="quote-box">
      <p>Tu mensaje original: "{original_message[:300]}{'...' if len(original_message) > 300 else ''}"</p>
    </div>
    <div class="divider"></div>
    <p>¿Querés seguir la conversación?</p>
    <p style="text-align:center;margin-top:16px">
      <a href="https://wa.me/595XXXXXXXXX" class="cta-btn">💬 Respondenos por WhatsApp</a>
    </p>
    <p style="text-align:center;margin-top:12px">
      <span style="color:#55556a;font-size:13px">O simplemente respondé este email</span>
    </p>
    """)

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
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── SQLite setup ──
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            read INTEGER DEFAULT 0,
            replied INTEGER DEFAULT 0,
            reply_text TEXT,
            replied_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS diagnostics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            health_score INTEGER,
            report_json TEXT,
            crawl_summary TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


@app.on_event("startup")
async def startup():
    init_db()


def verify_token(authorization: str | None):
    if not authorization or authorization != f"Bearer {DASHBOARD_TOKEN}":
        raise HTTPException(status_code=401, detail="No autorizado")


# ── Existing: Diagnose ──

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

    # Save diagnostic to database
    try:
        now = datetime.now(timezone.utc).isoformat()
        health = report.get("health_score") if isinstance(report, dict) else None
        summary = report.get("summary", "") if isinstance(report, dict) else ""
        report_str = json.dumps(report, ensure_ascii=False) if report else "{}"
        conn = get_db()
        conn.execute(
            "INSERT INTO diagnostics (url, health_score, report_json, crawl_summary, created_at) VALUES (?, ?, ?, ?, ?)",
            (url, health, report_str, summary[:500], now),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DIAG SAVE ERROR] {e}")

    return {
        "success": True,
        "crawl": crawl_data,
        "pagespeed": pagespeed_data,
        "report": report,
    }


# ── Existing: Chat ──

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


# ══════════════════════════════════════════════════════════
# ── CONTACT FORM & MESSAGES ──
# ══════════════════════════════════════════════════════════

class ContactRequest(BaseModel):
    name: str
    email: EmailStr
    message: str


@app.post("/api/contact")
async def contact(req: ContactRequest):
    """Receive contact form submission."""
    name = req.name.strip()[:200]
    email = req.email.strip()[:200]
    message = req.message.strip()[:5000]

    if not name or not email or not message:
        raise HTTPException(status_code=400, detail="Todos los campos son obligatorios")

    now = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    conn.execute(
        "INSERT INTO messages (name, email, message, created_at) VALUES (?, ?, ?, ?)",
        (name, email, message, now),
    )
    conn.commit()
    conn.close()

    # Send auto-reply welcome email
    if RESEND_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                    json={
                        "from": "WhiteRabbit <hola@whiterabbit.com.py>",
                        "to": [email],
                        "subject": "¡Recibimos tu mensaje! — WhiteRabbit",
                        "html": email_welcome(name),
                    },
                    timeout=10,
                )
                print(f"[EMAIL WELCOME] to={email} status={resp.status_code} body={resp.text}")
        except Exception as e:
            print(f"[EMAIL WELCOME ERROR] {e}")

    # Notify admin about new message
    if RESEND_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                    json={
                        "from": "WhiteRabbit <hola@whiterabbit.com.py>",
                        "to": ["info@whiterabbit.com.py"],
                        "subject": f"Nuevo lead: {name}",
                        "html": email_base(f"""
                            <h2>Nuevo mensaje desde la landing</h2>
                            <p><span class="highlight">Nombre:</span> {name}</p>
                            <p><span class="highlight">Email:</span> {email}</p>
                            <div class="quote-box"><p>{message}</p></div>
                            <p style="margin-top:24px">
                                <a href="https://whiterabbit-diagnostic-production.up.railway.app/dashboard" class="cta-btn">Ver en el dashboard</a>
                            </p>
                        """),
                    },
                    timeout=10,
                )
                print(f"[EMAIL ADMIN NOTIFY] new lead from {email}")
        except Exception as e:
            print(f"[EMAIL ADMIN NOTIFY ERROR] {e}")

    return {"success": True, "message": "Mensaje recibido. Te respondemos pronto!"}


@app.get("/api/messages")
async def list_messages(authorization: str | None = Header(default=None)):
    """List all messages (auth required)."""
    verify_token(authorization)

    conn = get_db()
    rows = conn.execute("SELECT * FROM messages ORDER BY created_at DESC").fetchall()
    conn.close()

    return [dict(r) for r in rows]


@app.patch("/api/messages/{msg_id}/read")
async def mark_read(msg_id: int, authorization: str | None = Header(default=None)):
    """Mark a message as read."""
    verify_token(authorization)

    conn = get_db()
    cur = conn.execute("UPDATE messages SET read = 1 WHERE id = ?", (msg_id,))
    conn.commit()
    if cur.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")
    conn.close()
    return {"success": True}


class ReplyRequest(BaseModel):
    reply_text: str


@app.post("/api/messages/{msg_id}/reply")
async def reply_message(msg_id: int, req: ReplyRequest, authorization: str | None = Header(default=None)):
    """Reply to a message via email (Resend)."""
    verify_token(authorization)

    reply_text = req.reply_text.strip()[:5000]
    if not reply_text:
        raise HTTPException(status_code=400, detail="Respuesta vacía")

    conn = get_db()
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")

    msg = dict(row)
    now = datetime.now(timezone.utc).isoformat()

    # Try sending email via Resend
    email_sent = False
    if RESEND_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {RESEND_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": "WhiteRabbit <hola@whiterabbit.com.py>",
                        "to": [msg["email"]],
                        "subject": f"Re: Tu mensaje a WhiteRabbit",
                        "html": email_reply(msg["name"], reply_text, msg["message"]),
                    },
                    timeout=10,
                )
                email_sent = resp.status_code in (200, 201)
                print(f"[EMAIL REPLY] to={msg['email']} status={resp.status_code} body={resp.text}")
        except Exception as e:
            print(f"[EMAIL REPLY ERROR] {e}")
            email_sent = False

    conn.execute(
        "UPDATE messages SET replied = 1, reply_text = ?, replied_at = ?, read = 1 WHERE id = ?",
        (reply_text, now, msg_id),
    )
    conn.commit()
    conn.close()

    return {
        "success": True,
        "email_sent": email_sent,
        "message": "Respuesta guardada" + (" y email enviado" if email_sent else " (email no configurado)"),
    }


# ══════════════════════════════════════════════════════════
# ── DIAGNOSTICS & STATS API ──
# ══════════════════════════════════════════════════════════

@app.get("/api/diagnostics")
async def list_diagnostics(authorization: str | None = Header(default=None)):
    """List all diagnostics (auth required)."""
    verify_token(authorization)
    conn = get_db()
    rows = conn.execute("SELECT id, url, health_score, crawl_summary, created_at FROM diagnostics ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/diagnostics/{diag_id}")
async def get_diagnostic(diag_id: int, authorization: str | None = Header(default=None)):
    """Get full diagnostic report (auth required)."""
    verify_token(authorization)
    conn = get_db()
    row = conn.execute("SELECT * FROM diagnostics WHERE id = ?", (diag_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Diagnostico no encontrado")
    return dict(row)


@app.get("/api/stats")
async def get_stats(authorization: str | None = Header(default=None)):
    """Return overview stats (auth required)."""
    verify_token(authorization)
    conn = get_db()
    total_leads = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    total_diagnostics = conn.execute("SELECT COUNT(*) FROM diagnostics").fetchone()[0]
    unread_messages = conn.execute("SELECT COUNT(*) FROM messages WHERE read = 0").fetchone()[0]
    total_replied = conn.execute("SELECT COUNT(*) FROM messages WHERE replied = 1").fetchone()[0]
    response_rate = round((total_replied / total_leads * 100), 1) if total_leads > 0 else 0
    conn.close()
    return {
        "total_leads": total_leads,
        "total_diagnostics": total_diagnostics,
        "unread_messages": unread_messages,
        "response_rate": response_rate,
    }


# ══════════════════════════════════════════════════════════
# ── DASHBOARD ──
# ══════════════════════════════════════════════════════════

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WhiteRabbit — Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800&family=DM+Sans:wght@300;400;500;600&family=Space+Mono&display=swap" rel="stylesheet">
<style>
:root{--bg:#030305;--surface:#08080d;--card:#0c0c14;--border:rgba(255,255,255,0.05);--white:#eeeef3;--muted:#55556a;--dim:#2a2a3a;--cyan:#00e8ff;--violet:#8b3dff;--magenta:#ff3d8b;--green:#22c55e;--yellow:#facc15;--display:'Syne',sans-serif;--body:'DM Sans',sans-serif;--mono:'Space Mono',monospace;--sidebar-w:260px}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--white);font-family:var(--body);min-height:100vh}
a{color:var(--cyan);text-decoration:none}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--dim);border-radius:3px}

/* Login */
.login-wrap{display:flex;align-items:center;justify-content:center;min-height:100vh;padding:2rem}
.login-box{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:2.5rem;max-width:380px;width:100%;text-align:center}
.login-box h1{font-family:var(--display);font-size:1.4rem;margin-bottom:0.5rem}
.login-box p{color:var(--muted);font-size:0.85rem;margin-bottom:1.5rem}
.login-box input{width:100%;padding:0.75rem 1rem;background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--white);font-family:var(--mono);font-size:0.85rem;outline:none;margin-bottom:1rem}
.login-box input:focus{border-color:rgba(0,232,255,0.3)}
.login-box button{width:100%;padding:0.75rem;background:linear-gradient(135deg,var(--cyan),var(--violet));border:none;border-radius:8px;color:var(--bg);font-weight:600;font-family:var(--body);cursor:pointer;font-size:0.9rem;transition:all 0.3s}
.login-box button:hover{transform:translateY(-1px);box-shadow:0 0 25px rgba(0,232,255,0.2)}
.login-error{color:var(--magenta);font-size:0.8rem;margin-top:0.5rem;min-height:1.2em}

/* Layout */
.app{display:none}
.sidebar{position:fixed;top:0;left:0;width:var(--sidebar-w);height:100vh;background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;z-index:100;transition:transform 0.3s ease}
.sidebar-header{padding:1.5rem 1.2rem;display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--border)}
.sidebar-header img{width:32px;height:32px;border-radius:6px}
.sidebar-logo{font-family:var(--display);font-size:1.1rem;letter-spacing:-0.3px}
.sidebar-logo .w{color:var(--white)}.sidebar-logo .c{color:var(--cyan)}
.sidebar-nav{flex:1;padding:1rem 0;overflow-y:auto}
.nav-item{display:flex;align-items:center;gap:12px;padding:0.7rem 1.2rem;margin:2px 8px;border-radius:8px;cursor:pointer;font-size:0.88rem;color:var(--muted);transition:all 0.2s;border-left:3px solid transparent;position:relative}
.nav-item:hover{background:rgba(255,255,255,0.03);color:var(--white)}
.nav-item.active{color:var(--cyan);background:rgba(0,232,255,0.04);border-left-color:var(--cyan)}
.nav-item .icon{font-size:1.1rem;width:22px;text-align:center}
.nav-item .badge-sm{position:absolute;right:12px;background:var(--cyan);color:var(--bg);font-size:0.65rem;font-weight:700;min-width:18px;height:18px;border-radius:9px;display:flex;align-items:center;justify-content:center;padding:0 5px}
.nav-section{padding:0.5rem 1.2rem;margin-top:0.8rem;font-size:0.7rem;text-transform:uppercase;letter-spacing:1px;color:var(--dim);font-weight:600}
.nav-coming{font-size:0.6rem;background:rgba(139,61,255,0.15);color:var(--violet);padding:2px 6px;border-radius:4px;margin-left:auto}
.sidebar-footer{padding:1rem 1.2rem;border-top:1px solid var(--border)}
.btn-logout{width:100%;padding:0.5rem;background:transparent;border:1px solid var(--border);border-radius:6px;color:var(--muted);font-family:var(--body);font-size:0.78rem;cursor:pointer;transition:all 0.3s}
.btn-logout:hover{border-color:var(--magenta);color:var(--magenta)}

/* Mobile hamburger */
.hamburger{display:none;position:fixed;top:1rem;left:1rem;z-index:200;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:0.6rem;cursor:pointer;color:var(--white);font-size:1.2rem;line-height:1}
.overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:90}

/* Main content */
.main{margin-left:var(--sidebar-w);min-height:100vh;padding:2rem 2.5rem}
.page{display:none;animation:fadeIn 0.25s ease}
.page.active{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}

/* Page header */
.page-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:2rem;flex-wrap:wrap;gap:1rem}
.page-header h1{font-family:var(--display);font-size:1.5rem;font-weight:700}
.page-header h1 span{color:var(--cyan)}

/* Stat cards */
.stats-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:2rem}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:1.3rem 1.5rem;transition:all 0.3s}
.stat-card:hover{border-color:rgba(255,255,255,0.1);transform:translateY(-2px)}
.stat-label{font-size:0.78rem;color:var(--muted);margin-bottom:0.5rem;display:flex;align-items:center;gap:6px}
.stat-value{font-family:var(--mono);font-size:1.8rem;font-weight:700;color:var(--white)}
.stat-value.cyan{color:var(--cyan)}
.stat-value.green{color:var(--green)}
.stat-value.violet{color:var(--violet)}
.stat-value.magenta{color:var(--magenta)}

/* Activity feed */
.section-title{font-family:var(--display);font-size:1.1rem;margin-bottom:1rem;display:flex;align-items:center;gap:8px}
.activity-list{display:flex;flex-direction:column;gap:0.6rem;margin-bottom:2rem}
.activity-item{display:flex;align-items:flex-start;gap:12px;background:var(--card);border:1px solid var(--border);border-radius:10px;padding:1rem 1.2rem;transition:all 0.2s}
.activity-item:hover{background:var(--surface)}
.activity-icon{width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:1rem;flex-shrink:0}
.activity-icon.msg{background:rgba(0,232,255,0.08);color:var(--cyan)}
.activity-icon.diag{background:rgba(139,61,255,0.08);color:var(--violet)}
.activity-body{flex:1;min-width:0}
.activity-title{font-size:0.88rem;font-weight:500;margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.activity-meta{font-size:0.75rem;color:var(--muted)}
.activity-date{font-size:0.72rem;color:var(--dim);font-family:var(--mono);white-space:nowrap;margin-top:2px}

/* Quick actions */
.quick-actions{display:flex;gap:0.8rem;margin-bottom:2rem;flex-wrap:wrap}
.qa-btn{padding:0.6rem 1.2rem;background:var(--card);border:1px solid var(--border);border-radius:8px;color:var(--white);font-size:0.85rem;cursor:pointer;transition:all 0.3s;font-family:var(--body)}
.qa-btn:hover{border-color:var(--cyan);color:var(--cyan);background:rgba(0,232,255,0.04)}

/* Messages */
.filter-bar{display:flex;gap:0.8rem;margin-bottom:1.2rem;flex-wrap:wrap;align-items:center}
.filter-bar input{flex:1;min-width:200px;padding:0.6rem 1rem;background:var(--card);border:1px solid var(--border);border-radius:8px;color:var(--white);font-family:var(--body);font-size:0.85rem;outline:none}
.filter-bar input:focus{border-color:rgba(0,232,255,0.3)}
.filter-bar select{padding:0.6rem 1rem;background:var(--card);border:1px solid var(--border);border-radius:8px;color:var(--white);font-family:var(--body);font-size:0.85rem;outline:none;cursor:pointer}
.filter-bar select option{background:var(--card);color:var(--white)}
.msg-count{font-size:0.8rem;color:var(--muted)}

.msg-list{display:flex;flex-direction:column;gap:0.8rem}
.msg-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:1.2rem 1.4rem;cursor:pointer;transition:all 0.3s;border-left:3px solid transparent}
.msg-card.unread{border-left-color:var(--cyan)}
.msg-card:hover{background:var(--surface);border-color:rgba(255,255,255,0.08)}
.msg-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:0.4rem;gap:1rem}
.msg-name{font-weight:600;font-size:0.95rem}
.msg-date{color:var(--dim);font-size:0.75rem;font-family:var(--mono);white-space:nowrap}
.msg-email{color:var(--muted);font-size:0.8rem;margin-bottom:0.5rem;display:flex;align-items:center;gap:8px}
.msg-preview{color:var(--muted);font-size:0.85rem;line-height:1.5;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.status-badge{display:inline-block;font-size:0.68rem;font-weight:600;padding:2px 8px;border-radius:4px;text-transform:uppercase;letter-spacing:0.5px}
.status-badge.nuevo{background:rgba(0,232,255,0.12);color:var(--cyan)}
.status-badge.leido{background:rgba(85,85,106,0.2);color:var(--muted)}
.status-badge.respondido{background:rgba(34,197,94,0.12);color:var(--green)}

.msg-card.expanded .msg-preview{white-space:normal;color:var(--white)}
.msg-detail{display:none;margin-top:1rem;padding-top:1rem;border-top:1px solid var(--border)}
.msg-card.expanded .msg-detail{display:block}
.msg-replied-info{margin-top:0.8rem;padding:0.8rem;background:rgba(0,232,255,0.03);border:1px solid rgba(0,232,255,0.08);border-radius:8px}
.msg-replied-info .label{font-size:0.75rem;color:var(--cyan);font-weight:600;margin-bottom:0.3rem}
.msg-replied-info .text{font-size:0.85rem;color:var(--muted);line-height:1.5}
.reply-area{margin-top:1rem}
.reply-area textarea{width:100%;padding:0.75rem;background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--white);font-family:var(--body);font-size:0.85rem;resize:vertical;min-height:80px;outline:none}
.reply-area textarea:focus{border-color:rgba(0,232,255,0.3)}
.reply-btns{display:flex;gap:0.6rem;margin-top:0.6rem}
.btn-primary{padding:0.55rem 1.2rem;background:linear-gradient(135deg,var(--cyan),var(--violet));border:none;border-radius:6px;color:var(--bg);font-weight:600;font-size:0.82rem;cursor:pointer;transition:all 0.3s;font-family:var(--body)}
.btn-primary:hover{transform:translateY(-1px)}
.btn-primary:disabled{opacity:0.5;cursor:not-allowed;transform:none}
.btn-secondary{padding:0.55rem 1.2rem;background:transparent;border:1px solid var(--border);border-radius:6px;color:var(--muted);font-size:0.82rem;cursor:pointer;font-family:var(--body)}
.reply-feedback{font-size:0.8rem;margin-top:0.4rem;min-height:1.1em}
.reply-feedback.success{color:var(--green)}
.reply-feedback.error{color:var(--magenta)}

/* Diagnostics */
.diag-list{display:flex;flex-direction:column;gap:0.8rem}
.diag-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:1.2rem 1.4rem;cursor:pointer;transition:all 0.3s}
.diag-card:hover{background:var(--surface);border-color:rgba(255,255,255,0.08)}
.diag-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;gap:1rem}
.diag-url{font-weight:600;font-size:0.92rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.diag-score{display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;border-radius:50%;font-family:var(--mono);font-size:0.85rem;font-weight:700;flex-shrink:0}
.diag-score.good{background:rgba(34,197,94,0.12);color:var(--green);border:2px solid rgba(34,197,94,0.3)}
.diag-score.mid{background:rgba(250,204,21,0.12);color:var(--yellow);border:2px solid rgba(250,204,21,0.3)}
.diag-score.bad{background:rgba(255,61,139,0.12);color:var(--magenta);border:2px solid rgba(255,61,139,0.3)}
.diag-score.na{background:rgba(85,85,106,0.12);color:var(--muted);border:2px solid rgba(85,85,106,0.3)}
.diag-summary{color:var(--muted);font-size:0.83rem;line-height:1.5;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.diag-meta{display:flex;gap:1rem;align-items:center;margin-top:0.5rem}
.diag-date{font-size:0.72rem;color:var(--dim);font-family:var(--mono)}
.diag-detail{display:none;margin-top:1rem;padding-top:1rem;border-top:1px solid var(--border)}
.diag-card.expanded .diag-detail{display:block}
.diag-card.expanded .diag-summary{white-space:normal;color:var(--white)}
.diag-report-section{margin-bottom:1rem}
.diag-report-section h4{font-size:0.82rem;color:var(--cyan);margin-bottom:0.5rem;font-family:var(--display)}
.diag-report-section ul{list-style:none;padding:0}
.diag-report-section li{font-size:0.82rem;color:var(--muted);padding:0.3rem 0;padding-left:1rem;position:relative}
.diag-report-section li::before{content:'';position:absolute;left:0;top:0.65rem;width:4px;height:4px;border-radius:50%;background:var(--dim)}
.diag-loading{text-align:center;padding:1rem;color:var(--muted);font-size:0.85rem}

/* Coming soon */
.coming-soon{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:4rem 2rem;text-align:center}
.coming-soon .icon-big{font-size:3rem;margin-bottom:1rem;opacity:0.5}
.coming-soon h2{font-family:var(--display);font-size:1.3rem;margin-bottom:0.5rem}
.coming-soon p{color:var(--muted);font-size:0.9rem;max-width:400px;line-height:1.6}
.coming-tag{display:inline-block;margin-top:1rem;padding:0.4rem 1rem;background:linear-gradient(135deg,rgba(139,61,255,0.15),rgba(0,232,255,0.1));border:1px solid rgba(139,61,255,0.2);border-radius:20px;font-size:0.78rem;color:var(--violet);font-weight:600}

.empty-state{text-align:center;padding:4rem 2rem;color:var(--dim)}
.empty-state p{font-size:1rem;margin-bottom:0.5rem}

@media(max-width:768px){
  .sidebar{transform:translateX(-100%)}
  .sidebar.open{transform:translateX(0)}
  .hamburger{display:block}
  .overlay.show{display:block}
  .main{margin-left:0;padding:1.2rem;padding-top:3.5rem}
  .stats-row{grid-template-columns:1fr 1fr}
  .page-header h1{font-size:1.2rem}
}
@media(max-width:480px){
  .stats-row{grid-template-columns:1fr}
  .main{padding:1rem;padding-top:3.5rem}
}
</style>
</head>
<body>

<!-- Login -->
<div class="login-wrap" id="loginWrap">
  <div class="login-box">
    <h1>WhiteRabbit</h1>
    <p>Ingresa el token de administrador</p>
    <input type="password" id="tokenInput" placeholder="Token" autofocus>
    <button onclick="doLogin()">Entrar</button>
    <div class="login-error" id="loginError"></div>
  </div>
</div>

<!-- App -->
<div class="app" id="app">

  <!-- Mobile hamburger -->
  <div class="hamburger" id="hamburger" onclick="toggleSidebar()">&#9776;</div>
  <div class="overlay" id="overlay" onclick="toggleSidebar()"></div>

  <!-- Sidebar -->
  <div class="sidebar" id="sidebar">
    <div class="sidebar-header">
      <img src="https://www.whiterabbit.com.py/wr_iso_logo.png" alt="WR">
      <div class="sidebar-logo"><span class="w">white</span><span class="c">rabbit</span></div>
    </div>
    <div class="sidebar-nav">
      <div class="nav-section">Principal</div>
      <div class="nav-item active" data-page="overview" onclick="navigate('overview')">
        <span class="icon">&#127968;</span><span>Overview</span>
      </div>
      <div class="nav-item" data-page="mensajes" onclick="navigate('mensajes')">
        <span class="icon">&#128233;</span><span>Mensajes</span>
        <span class="badge-sm" id="navUnread" style="display:none">0</span>
      </div>
      <div class="nav-item" data-page="diagnosticos" onclick="navigate('diagnosticos')">
        <span class="icon">&#128269;</span><span>Diagnosticos</span>
      </div>
      <div class="nav-section">Integraciones</div>
      <div class="nav-item" data-page="analytics" onclick="navigate('analytics')">
        <span class="icon">&#128202;</span><span>Analytics</span>
        <span class="nav-coming">Pronto</span>
      </div>
      <div class="nav-item" data-page="campanas" onclick="navigate('campanas')">
        <span class="icon">&#128226;</span><span>Campanas</span>
        <span class="nav-coming">Pronto</span>
      </div>
    </div>
    <div class="sidebar-footer">
      <button class="btn-logout" onclick="doLogout()">Cerrar sesion</button>
    </div>
  </div>

  <!-- Main content -->
  <div class="main">

    <!-- OVERVIEW PAGE -->
    <div class="page active" id="page-overview">
      <div class="page-header"><h1>&#128075; Bienvenido al <span>Dashboard</span></h1></div>
      <div class="stats-row" id="statsRow">
        <div class="stat-card"><div class="stat-label">&#128233; Total Leads</div><div class="stat-value cyan" id="statLeads">--</div></div>
        <div class="stat-card"><div class="stat-label">&#128269; Diagnosticos Corridos</div><div class="stat-value violet" id="statDiags">--</div></div>
        <div class="stat-card"><div class="stat-label">&#128172; Mensajes Sin Leer</div><div class="stat-value magenta" id="statUnread">--</div></div>
        <div class="stat-card"><div class="stat-label">&#9989; Tasa de Respuesta</div><div class="stat-value green" id="statRate">--%</div></div>
      </div>
      <div class="quick-actions">
        <button class="qa-btn" onclick="navigate('mensajes')">&#128233; Ver todos los mensajes</button>
        <button class="qa-btn" onclick="navigate('diagnosticos')">&#128269; Ver diagnosticos</button>
      </div>
      <div class="section-title">Actividad reciente</div>
      <div class="activity-list" id="activityList">
        <div class="empty-state"><p>Cargando...</p></div>
      </div>
    </div>

    <!-- MENSAJES PAGE -->
    <div class="page" id="page-mensajes">
      <div class="page-header">
        <h1>&#128233; <span>Mensajes</span></h1>
        <div class="msg-count" id="msgCount"></div>
      </div>
      <div class="filter-bar">
        <input type="text" id="msgSearch" placeholder="Buscar por nombre o email..." oninput="renderMessages()">
        <select id="msgFilter" onchange="renderMessages()">
          <option value="all">Todos</option>
          <option value="unread">Sin leer</option>
          <option value="read">Leidos</option>
          <option value="replied">Respondidos</option>
        </select>
      </div>
      <div class="msg-list" id="msgList"></div>
    </div>

    <!-- DIAGNOSTICOS PAGE -->
    <div class="page" id="page-diagnosticos">
      <div class="page-header"><h1>&#128269; <span>Diagnosticos</span></h1></div>
      <div class="diag-list" id="diagList">
        <div class="empty-state"><p>Cargando...</p></div>
      </div>
    </div>

    <!-- ANALYTICS PAGE -->
    <div class="page" id="page-analytics">
      <div class="coming-soon">
        <div class="icon-big">&#128202;</div>
        <h2>Google Analytics</h2>
        <p>Conecta tu cuenta de GA4 para ver trafico, conversiones y metricas clave directamente en el dashboard.</p>
        <div class="coming-tag">Proximamente</div>
      </div>
    </div>

    <!-- CAMPANAS PAGE -->
    <div class="page" id="page-campanas">
      <div class="coming-soon">
        <div class="icon-big">&#128226;</div>
        <h2>Meta Ads &amp; Campanas</h2>
        <p>Gestiona y monitorea tus campanas de Facebook e Instagram Ads con reportes automatizados y alertas inteligentes.</p>
        <div class="coming-tag">Proximamente</div>
      </div>
    </div>

  </div><!-- /main -->
</div><!-- /app -->

<script>
const API = window.location.origin;
let TOKEN = localStorage.getItem('wr_token') || '';
let messages = [];
let diagnostics = [];
let stats = {};
let currentPage = 'overview';

if (TOKEN) { tryInit(); } else { document.getElementById('loginWrap').style.display = 'flex'; }

document.getElementById('tokenInput').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });

async function doLogin() {
  const input = document.getElementById('tokenInput');
  TOKEN = input.value.trim();
  if (!TOKEN) return;
  const ok = await tryInit();
  if (!ok) {
    document.getElementById('loginError').textContent = 'Token invalido';
    TOKEN = '';
    localStorage.removeItem('wr_token');
  }
}

function doLogout() {
  TOKEN = '';
  localStorage.removeItem('wr_token');
  document.getElementById('app').style.display = 'none';
  document.getElementById('loginWrap').style.display = 'flex';
  document.getElementById('tokenInput').value = '';
  document.getElementById('loginError').textContent = '';
}

async function tryInit() {
  try {
    const resp = await fetch(API + '/api/messages', { headers: { 'Authorization': 'Bearer ' + TOKEN } });
    if (!resp.ok) return false;
    messages = await resp.json();
    localStorage.setItem('wr_token', TOKEN);
    document.getElementById('loginWrap').style.display = 'none';
    document.getElementById('app').style.display = 'block';
    loadAll();
    return true;
  } catch { return false; }
}

async function loadAll() {
  renderMessages();
  // Load stats + diagnostics in parallel
  try {
    const [sResp, dResp] = await Promise.all([
      fetch(API + '/api/stats', { headers: { 'Authorization': 'Bearer ' + TOKEN } }),
      fetch(API + '/api/diagnostics', { headers: { 'Authorization': 'Bearer ' + TOKEN } })
    ]);
    if (sResp.ok) { stats = await sResp.json(); renderStats(); }
    if (dResp.ok) { diagnostics = await dResp.json(); renderDiagnostics(); renderActivity(); }
  } catch(e) { console.error('loadAll error', e); }
  updateUnreadBadge();
}

function updateUnreadBadge() {
  const c = messages.filter(m => !m.read).length;
  const badge = document.getElementById('navUnread');
  if (c > 0) { badge.style.display = 'flex'; badge.textContent = c; }
  else { badge.style.display = 'none'; }
}

function renderStats() {
  document.getElementById('statLeads').textContent = stats.total_leads ?? '--';
  document.getElementById('statDiags').textContent = stats.total_diagnostics ?? '--';
  document.getElementById('statUnread').textContent = stats.unread_messages ?? '--';
  document.getElementById('statRate').textContent = (stats.response_rate ?? 0) + '%';
}

function renderActivity() {
  const list = document.getElementById('activityList');
  const items = [];
  messages.slice(0, 5).forEach(m => items.push({ type: 'msg', title: m.name + ' — ' + (m.message || '').substring(0, 80), date: m.created_at, meta: m.email }));
  diagnostics.slice(0, 5).forEach(d => items.push({ type: 'diag', title: d.url, date: d.created_at, meta: d.health_score !== null ? 'Score: ' + d.health_score : 'Sin score' }));
  items.sort((a, b) => new Date(b.date) - new Date(a.date));
  const display = items.slice(0, 8);
  if (!display.length) { list.innerHTML = '<div class="empty-state"><p>No hay actividad reciente</p></div>'; return; }
  list.innerHTML = display.map(i => {
    const icon = i.type === 'msg' ? '<div class="activity-icon msg">&#128233;</div>' : '<div class="activity-icon diag">&#128269;</div>';
    return '<div class="activity-item">' + icon + '<div class="activity-body"><div class="activity-title">' + esc(i.title) + '</div><div class="activity-meta">' + esc(i.meta) + '</div></div><div class="activity-date">' + fmtDate(i.date) + '</div></div>';
  }).join('');
}

function renderMessages() {
  const list = document.getElementById('msgList');
  const search = (document.getElementById('msgSearch')?.value || '').toLowerCase();
  const filter = document.getElementById('msgFilter')?.value || 'all';
  let filtered = messages;
  if (search) filtered = filtered.filter(m => m.name.toLowerCase().includes(search) || m.email.toLowerCase().includes(search));
  if (filter === 'unread') filtered = filtered.filter(m => !m.read);
  else if (filter === 'read') filtered = filtered.filter(m => m.read && !m.replied);
  else if (filter === 'replied') filtered = filtered.filter(m => m.replied);

  const unread = messages.filter(m => !m.read).length;
  const countEl = document.getElementById('msgCount');
  if (countEl) countEl.textContent = filtered.length + ' mensaje' + (filtered.length !== 1 ? 's' : '') + (unread > 0 ? ' (' + unread + ' sin leer)' : '');
  updateUnreadBadge();

  if (!filtered.length) {
    list.innerHTML = '<div class="empty-state"><p>No hay mensajes' + (search || filter !== 'all' ? ' con ese filtro' : ' todavia') + '</p></div>';
    return;
  }

  list.innerHTML = filtered.map(m => {
    const d = new Date(m.created_at);
    const dateStr = d.toLocaleDateString('es-PY', { day:'2-digit', month:'short', year:'numeric' }) + ' ' + d.toLocaleTimeString('es-PY', { hour:'2-digit', minute:'2-digit' });
    const unreadCls = m.read ? '' : ' unread';
    let statusBadge = '';
    if (m.replied) statusBadge = '<span class="status-badge respondido">Respondido</span>';
    else if (m.read) statusBadge = '<span class="status-badge leido">Leido</span>';
    else statusBadge = '<span class="status-badge nuevo">Nuevo</span>';

    const repliedHtml = m.replied ? '<div class="msg-replied-info"><div class="label">Respondido' + (m.replied_at ? ' el ' + new Date(m.replied_at).toLocaleDateString('es-PY', { day:'2-digit', month:'short' }) : '') + '</div><div class="text">' + esc(m.reply_text || '') + '</div></div>' :
      '<div class="reply-area" id="replyArea-' + m.id + '"><textarea id="replyText-' + m.id + '" placeholder="Escribir respuesta..." onclick="event.stopPropagation()"></textarea><div class="reply-btns"><button class="btn-primary" id="replyBtn-' + m.id + '" onclick="sendReply(' + m.id + ')">Enviar respuesta</button><button class="btn-secondary" onclick="collapseMsg(' + m.id + ')">Cancelar</button></div><div class="reply-feedback" id="replyFb-' + m.id + '"></div></div>';

    return '<div class="msg-card' + unreadCls + '" id="msg-' + m.id + '" onclick="expandMsg(' + m.id + ')"><div class="msg-top"><div class="msg-name">' + esc(m.name) + '</div><div class="msg-date">' + dateStr + '</div></div><div class="msg-email">' + esc(m.email) + ' ' + statusBadge + '</div><div class="msg-preview">' + esc(m.message) + '</div><div class="msg-detail">' + repliedHtml + '</div></div>';
  }).join('');
}

function renderDiagnostics() {
  const list = document.getElementById('diagList');
  if (!diagnostics.length) {
    list.innerHTML = '<div class="empty-state"><p>No hay diagnosticos todavia</p><p style="font-size:0.85rem;margin-top:0.5rem">Los diagnosticos se guardaran automaticamente cuando alguien use la herramienta</p></div>';
    return;
  }
  list.innerHTML = diagnostics.map(d => {
    const score = d.health_score;
    let scoreClass = 'na';
    if (score !== null && score !== undefined) { if (score >= 70) scoreClass = 'good'; else if (score >= 40) scoreClass = 'mid'; else scoreClass = 'bad'; }
    const scoreText = score !== null && score !== undefined ? score : '--';
    return '<div class="diag-card" id="diag-' + d.id + '" onclick="expandDiag(' + d.id + ')"><div class="diag-top"><div class="diag-url">' + esc(d.url) + '</div><div class="diag-score ' + scoreClass + '">' + scoreText + '</div></div><div class="diag-summary">' + esc(d.crawl_summary || 'Sin resumen') + '</div><div class="diag-meta"><div class="diag-date">' + fmtDate(d.created_at) + '</div></div><div class="diag-detail" id="diagDetail-' + d.id + '"><div class="diag-loading">Cargando reporte completo...</div></div></div>';
  }).join('');
}

async function expandDiag(id) {
  const card = document.getElementById('diag-' + id);
  if (card.classList.contains('expanded')) { card.classList.remove('expanded'); return; }
  document.querySelectorAll('.diag-card.expanded').forEach(c => c.classList.remove('expanded'));
  card.classList.add('expanded');
  const detail = document.getElementById('diagDetail-' + id);
  // Load full report
  try {
    const resp = await fetch(API + '/api/diagnostics/' + id, { headers: { 'Authorization': 'Bearer ' + TOKEN } });
    if (!resp.ok) { detail.innerHTML = '<div class="diag-loading">Error al cargar</div>'; return; }
    const data = await resp.json();
    let report = {};
    try { report = JSON.parse(data.report_json || '{}'); } catch { report = {}; }
    let html = '';
    if (report.summary) html += '<div class="diag-report-section"><h4>Resumen</h4><p style="font-size:0.85rem;color:var(--muted);line-height:1.6">' + esc(report.summary) + '</p></div>';
    if (report.critical_issues && report.critical_issues.length) html += '<div class="diag-report-section"><h4>&#128308; Problemas Criticos</h4><ul>' + report.critical_issues.map(i => '<li>' + esc(typeof i === 'string' ? i : (i.issue || i.title || JSON.stringify(i))) + '</li>').join('') + '</ul></div>';
    if (report.opportunities && report.opportunities.length) html += '<div class="diag-report-section"><h4>&#128161; Oportunidades</h4><ul>' + report.opportunities.map(i => '<li>' + esc(typeof i === 'string' ? i : (i.title || i.opportunity || JSON.stringify(i))) + '</li>').join('') + '</ul></div>';
    if (report.automation_proposals && report.automation_proposals.length) html += '<div class="diag-report-section"><h4>&#9889; Propuestas de Automatizacion</h4><ul>' + report.automation_proposals.map(i => '<li>' + esc(typeof i === 'string' ? i : (i.title || i.proposal || JSON.stringify(i))) + '</li>').join('') + '</ul></div>';
    if (!html) html = '<div class="diag-loading">No hay datos detallados del reporte</div>';
    detail.innerHTML = html;
  } catch { detail.innerHTML = '<div class="diag-loading">Error de conexion</div>'; }
}

async function expandMsg(id) {
  const card = document.getElementById('msg-' + id);
  if (card.classList.contains('expanded')) return;
  document.querySelectorAll('.msg-card.expanded').forEach(c => c.classList.remove('expanded'));
  card.classList.toggle('expanded');
  const msg = messages.find(m => m.id === id);
  if (msg && !msg.read) {
    msg.read = 1;
    card.classList.remove('unread');
    updateUnreadBadge();
    fetch(API + '/api/messages/' + id + '/read', { method: 'PATCH', headers: { 'Authorization': 'Bearer ' + TOKEN } });
  }
}

function collapseMsg(id) {
  event.stopPropagation();
  document.getElementById('msg-' + id).classList.remove('expanded');
}

async function sendReply(id) {
  event.stopPropagation();
  const text = document.getElementById('replyText-' + id).value.trim();
  const btn = document.getElementById('replyBtn-' + id);
  const fb = document.getElementById('replyFb-' + id);
  if (!text) return;
  btn.disabled = true; btn.textContent = 'Enviando...';
  fb.className = 'reply-feedback'; fb.textContent = '';
  try {
    const resp = await fetch(API + '/api/messages/' + id + '/reply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOKEN },
      body: JSON.stringify({ reply_text: text })
    });
    const data = await resp.json();
    if (resp.ok) {
      fb.className = 'reply-feedback success'; fb.textContent = data.message;
      const msg = messages.find(m => m.id === id);
      if (msg) { msg.replied = 1; msg.reply_text = text; msg.replied_at = new Date().toISOString(); }
      setTimeout(() => renderMessages(), 1500);
    } else { fb.className = 'reply-feedback error'; fb.textContent = data.detail || 'Error al enviar'; }
  } catch { fb.className = 'reply-feedback error'; fb.textContent = 'Error de conexion'; }
  finally { btn.disabled = false; btn.textContent = 'Enviar respuesta'; }
}

function navigate(page) {
  currentPage = page;
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const target = document.getElementById('page-' + page);
  if (target) target.classList.add('active');
  const nav = document.querySelector('.nav-item[data-page="' + page + '"]');
  if (nav) nav.classList.add('active');
  // Close mobile sidebar
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('overlay').classList.remove('show');
}

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('overlay').classList.toggle('show');
}

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('es-PY', { day:'2-digit', month:'short' }) + ' ' + d.toLocaleTimeString('es-PY', { hour:'2-digit', minute:'2-digit' });
}

function esc(s) { if (!s) return ''; const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
</script>
</body>
</html>"""


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the messages dashboard."""
    return DASHBOARD_HTML
