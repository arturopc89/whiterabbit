"""FastAPI backend for WhiteRabbit web diagnostic tool."""

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
# ── DASHBOARD ──
# ══════════════════════════════════════════════════════════

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WhiteRabbit — Mensajes</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800&family=DM+Sans:wght@300;400;500;600&family=Space+Mono&display=swap" rel="stylesheet">
<style>
:root{--bg:#030305;--surface:#08080d;--card:#0c0c14;--border:rgba(255,255,255,0.05);--white:#eeeef3;--muted:#55556a;--dim:#2a2a3a;--cyan:#00e8ff;--violet:#8b3dff;--magenta:#ff3d8b;--green:#22c55e;--display:'Syne',sans-serif;--body:'DM Sans',sans-serif;--mono:'Space Mono',monospace}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--white);font-family:var(--body);min-height:100vh}
a{color:var(--cyan);text-decoration:none}

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

/* App layout */
.app{display:none;max-width:900px;margin:0 auto;padding:1.5rem}
.app-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:2rem;flex-wrap:wrap;gap:1rem}
.app-header h1{font-family:var(--display);font-size:1.3rem}
.app-header h1 span{color:var(--cyan)}
.badge{display:inline-flex;align-items:center;justify-content:center;background:var(--cyan);color:var(--bg);font-size:0.7rem;font-weight:700;min-width:22px;height:22px;border-radius:11px;padding:0 6px;margin-left:8px}
.btn-logout{padding:0.45rem 1rem;background:transparent;border:1px solid var(--border);border-radius:6px;color:var(--muted);font-family:var(--body);font-size:0.78rem;cursor:pointer;transition:all 0.3s}
.btn-logout:hover{border-color:var(--magenta);color:var(--magenta)}

/* Message cards */
.msg-list{display:flex;flex-direction:column;gap:0.8rem}
.msg-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:1.2rem 1.4rem;cursor:pointer;transition:all 0.3s;border-left:3px solid transparent}
.msg-card.unread{border-left-color:var(--cyan)}
.msg-card:hover{background:var(--surface);border-color:rgba(255,255,255,0.08)}
.msg-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:0.4rem;gap:1rem}
.msg-name{font-weight:600;font-size:0.95rem}
.msg-date{color:var(--dim);font-size:0.75rem;font-family:var(--mono);white-space:nowrap}
.msg-email{color:var(--muted);font-size:0.8rem;margin-bottom:0.5rem}
.msg-preview{color:var(--muted);font-size:0.85rem;line-height:1.5;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* Expanded */
.msg-card.expanded .msg-preview{white-space:normal;color:var(--white)}
.msg-detail{display:none;margin-top:1rem;padding-top:1rem;border-top:1px solid var(--border)}
.msg-card.expanded .msg-detail{display:block}
.msg-replied-info{margin-top:0.8rem;padding:0.8rem;background:rgba(0,232,255,0.03);border:1px solid rgba(0,232,255,0.08);border-radius:8px}
.msg-replied-info .label{font-size:0.75rem;color:var(--cyan);font-weight:600;margin-bottom:0.3rem}
.msg-replied-info .text{font-size:0.85rem;color:var(--muted);line-height:1.5}

/* Reply form */
.reply-area{margin-top:1rem}
.reply-area textarea{width:100%;padding:0.75rem;background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--white);font-family:var(--body);font-size:0.85rem;resize:vertical;min-height:80px;outline:none}
.reply-area textarea:focus{border-color:rgba(0,232,255,0.3)}
.reply-btns{display:flex;gap:0.6rem;margin-top:0.6rem}
.btn-reply{padding:0.55rem 1.2rem;background:linear-gradient(135deg,var(--cyan),var(--violet));border:none;border-radius:6px;color:var(--bg);font-weight:600;font-size:0.82rem;cursor:pointer;transition:all 0.3s;font-family:var(--body)}
.btn-reply:hover{transform:translateY(-1px)}
.btn-reply:disabled{opacity:0.5;cursor:not-allowed;transform:none}
.btn-cancel{padding:0.55rem 1.2rem;background:transparent;border:1px solid var(--border);border-radius:6px;color:var(--muted);font-size:0.82rem;cursor:pointer;font-family:var(--body)}
.reply-feedback{font-size:0.8rem;margin-top:0.4rem;min-height:1.1em}
.reply-feedback.success{color:var(--green)}
.reply-feedback.error{color:var(--magenta)}

.empty-state{text-align:center;padding:4rem 2rem;color:var(--dim)}
.empty-state p{font-size:1.1rem;margin-bottom:0.5rem}

@media(max-width:600px){
  .app{padding:1rem}
  .msg-card{padding:1rem}
  .app-header h1{font-size:1.1rem}
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
  <div class="app-header">
    <h1>WhiteRabbit — <span>Mensajes</span><span class="badge" id="unreadBadge">0</span></h1>
    <button class="btn-logout" onclick="doLogout()">Cerrar sesion</button>
  </div>
  <div class="msg-list" id="msgList"></div>
</div>

<script>
const API = window.location.origin;
let TOKEN = localStorage.getItem('wr_token') || '';
let messages = [];

// Init
if (TOKEN) {
  tryLoadMessages();
} else {
  document.getElementById('loginWrap').style.display = 'flex';
}

document.getElementById('tokenInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') doLogin();
});

async function doLogin() {
  const input = document.getElementById('tokenInput');
  TOKEN = input.value.trim();
  if (!TOKEN) return;
  const ok = await tryLoadMessages();
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

async function tryLoadMessages() {
  try {
    const resp = await fetch(API + '/api/messages', {
      headers: { 'Authorization': 'Bearer ' + TOKEN }
    });
    if (!resp.ok) return false;
    messages = await resp.json();
    localStorage.setItem('wr_token', TOKEN);
    document.getElementById('loginWrap').style.display = 'none';
    document.getElementById('app').style.display = 'block';
    renderMessages();
    return true;
  } catch {
    return false;
  }
}

function renderMessages() {
  const list = document.getElementById('msgList');
  const unread = messages.filter(m => !m.read).length;
  document.getElementById('unreadBadge').textContent = unread;

  if (!messages.length) {
    list.innerHTML = '<div class="empty-state"><p>No hay mensajes todavia</p></div>';
    return;
  }

  list.innerHTML = messages.map(m => {
    const d = new Date(m.created_at);
    const dateStr = d.toLocaleDateString('es-PY', { day:'2-digit', month:'short', year:'numeric' }) + ' ' + d.toLocaleTimeString('es-PY', { hour:'2-digit', minute:'2-digit' });
    const unreadCls = m.read ? '' : ' unread';
    const repliedHtml = m.replied ? `
      <div class="msg-replied-info">
        <div class="label">Respondido${m.replied_at ? ' el ' + new Date(m.replied_at).toLocaleDateString('es-PY', { day:'2-digit', month:'short' }) : ''}</div>
        <div class="text">${esc(m.reply_text || '')}</div>
      </div>` : `
      <div class="reply-area" id="replyArea-${m.id}">
        <textarea id="replyText-${m.id}" placeholder="Escribir respuesta..."></textarea>
        <div class="reply-btns">
          <button class="btn-reply" id="replyBtn-${m.id}" onclick="sendReply(${m.id})">Enviar respuesta</button>
          <button class="btn-cancel" onclick="collapseMsg(${m.id})">Cancelar</button>
        </div>
        <div class="reply-feedback" id="replyFb-${m.id}"></div>
      </div>`;

    return `<div class="msg-card${unreadCls}" id="msg-${m.id}" onclick="expandMsg(${m.id})">
      <div class="msg-top">
        <div class="msg-name">${esc(m.name)}</div>
        <div class="msg-date">${dateStr}</div>
      </div>
      <div class="msg-email">${esc(m.email)}</div>
      <div class="msg-preview">${esc(m.message)}</div>
      <div class="msg-detail">${repliedHtml}</div>
    </div>`;
  }).join('');
}

async function expandMsg(id) {
  const card = document.getElementById('msg-' + id);
  if (card.classList.contains('expanded')) return;

  // Collapse others
  document.querySelectorAll('.msg-card.expanded').forEach(c => c.classList.remove('expanded'));
  card.classList.toggle('expanded');

  // Mark as read
  const msg = messages.find(m => m.id === id);
  if (msg && !msg.read) {
    msg.read = 1;
    card.classList.remove('unread');
    document.getElementById('unreadBadge').textContent = messages.filter(m => !m.read).length;
    fetch(API + '/api/messages/' + id + '/read', {
      method: 'PATCH',
      headers: { 'Authorization': 'Bearer ' + TOKEN }
    });
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

  btn.disabled = true;
  btn.textContent = 'Enviando...';
  fb.className = 'reply-feedback';
  fb.textContent = '';

  try {
    const resp = await fetch(API + '/api/messages/' + id + '/reply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOKEN },
      body: JSON.stringify({ reply_text: text })
    });
    const data = await resp.json();
    if (resp.ok) {
      fb.className = 'reply-feedback success';
      fb.textContent = data.message;
      // Update local state and re-render after a beat
      const msg = messages.find(m => m.id === id);
      if (msg) { msg.replied = 1; msg.reply_text = text; msg.replied_at = new Date().toISOString(); }
      setTimeout(() => renderMessages(), 1500);
    } else {
      fb.className = 'reply-feedback error';
      fb.textContent = data.detail || 'Error al enviar';
    }
  } catch {
    fb.className = 'reply-feedback error';
    fb.textContent = 'Error de conexion';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Enviar respuesta';
  }
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
</script>
</body>
</html>"""


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the messages dashboard."""
    return DASHBOARD_HTML
