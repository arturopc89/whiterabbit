"""WhiteRabbit — Branded PDF report generator using fpdf2.

Layout is fully dynamic — no fixed heights. Each section expands to fit content.
"""

from __future__ import annotations

from typing import Optional
from fpdf import FPDF
from datetime import date

# ── Colors ──
CYAN   = (0, 200, 230)
VIOLET = (100, 50, 200)
DARK   = (20, 20, 30)
MUTED  = (110, 110, 130)
LIGHT  = (245, 246, 250)
RED    = (210, 45, 45)
AMBER  = (190, 120, 10)
GREEN  = (25, 150, 70)
WHITE  = (255, 255, 255)
BORDER = (215, 215, 225)

# ── Text sanitizer (Latin-1 / Helvetica safe) ──
_FIXES = {
    "\u2014": "-", "\u2013": "-", "\u2012": "-",
    "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"',
    "\u2026": "...", "\u2022": "-", "\u2192": "->",
    "\u00d7": "x",  "\u2260": "!=",
}

def _s(text, limit=9999):
    if not text:
        return ""
    for c, r in _FIXES.items():
        text = text.replace(c, r)
    return text.encode("latin-1", errors="replace").decode("latin-1")[:limit]


class WR(FPDF):
    def __init__(self, url=""):
        super().__init__()
        self._url = url
        self.set_auto_page_break(auto=True, margin=22)
        self.set_margins(16, 20, 16)

    # Auto-sanitize ALL text
    def cell(self, w=0, h=0, txt="", border=0, ln=0, align="", fill=False, link="", **kw):
        return super().cell(w, h, _s(str(txt)) if txt else "", border, ln, align, fill, link, **kw)

    def multi_cell(self, w, h, txt="", border=0, align="J", fill=False, **kw):
        return super().multi_cell(w, h, _s(str(txt)) if txt else "", border, align, fill, **kw)

    def header(self):
        # Dark header bar
        self.set_fill_color(*DARK)
        self.rect(0, 0, 210, 16, "F")
        self.set_y(4)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(235, 235, 240)
        self.set_x(16)
        self.cell(12, 7, "white", ln=0)
        self.set_text_color(*CYAN)
        self.cell(15, 7, "rabbit", ln=0)
        # URL right-aligned
        self.set_font("Helvetica", "", 7)
        self.set_text_color(140, 140, 160)
        self.cell(0, 7, _s(self._url, 60), align="R", ln=1)
        self.ln(4)

    def footer(self):
        self.set_y(-13)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*MUTED)
        self.cell(0, 6, f"whiterabbit.com.py  |  Pagina {self.page_no()}", align="C")

    # ── Layout helpers ──
    def hrule(self, color=BORDER, thickness=0.3):
        y = self.get_y()
        self.set_draw_color(*color)
        self.set_line_width(thickness)
        self.line(16, y, 194, y)
        self.ln(3)

    def section_heading(self, text, color=DARK):
        self.ln(3)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*color)
        self.cell(0, 6, _s(text), ln=1)
        self.hrule(color, 0.5)

    def left_bar(self, color, x, y, h):
        self.set_fill_color(*color)
        self.rect(x, y, 2.5, h, "F")

    def score_badge(self, score, x, y):
        color = GREEN if score >= 80 else (AMBER if score >= 50 else RED)
        r = 17
        self.set_fill_color(245, 246, 250)
        self.set_draw_color(*color)
        self.set_line_width(2.5)
        self.ellipse(x - r, y - r, r * 2, r * 2, style="FD")
        self.set_font("Helvetica", "B", 22)
        self.set_text_color(*color)
        self.set_xy(x - r, y - 7)
        self.cell(r * 2, 10, str(score), align="C", ln=0)
        self.set_font("Helvetica", "", 6)
        self.set_text_color(*MUTED)
        self.set_xy(x - r, y + 5)
        self.cell(r * 2, 4, "HEALTH SCORE", align="C", ln=0)

    def impact_pill(self, impact, x, y):
        color = RED if impact == "alto" else (AMBER if impact == "medio" else GREEN)
        self.set_fill_color(*color)
        self.rect(x, y, 16, 5.5, "F")
        self.set_font("Helvetica", "B", 5.5)
        self.set_text_color(*WHITE)
        self.set_xy(x, y + 0.5)
        self.cell(16, 4.5, impact.upper(), align="C", ln=0)


def generate_report_pdf(url: str, report: dict, pagespeed: Optional[dict] = None) -> bytes:

    health_score   = int(report.get("health_score") or 0)
    business_type  = _s(report.get("business_type", ""), 80)
    summary        = _s(report.get("summary", ""), 400)
    issues         = report.get("critical_issues", []) or []
    opps           = report.get("opportunities", []) or []
    proposals      = report.get("automation_proposals", []) or []
    traffic        = _s(report.get("traffic_estimate", ""), 200)

    pdf = WR(url=url)
    pdf.add_page()

    # ═══════════════════════════════════
    # TITLE
    # ═══════════════════════════════════
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 9, "Reporte de Diagnostico Web", ln=1)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, f"Analisis realizado el {date.today().strftime('%d/%m/%Y')}  |  whiterabbit.com.py", ln=1)
    pdf.ln(4)

    # ═══════════════════════════════════
    # SCORE ROW
    # ═══════════════════════════════════
    score_y = pdf.get_y()

    # Score circle (left)
    pdf.score_badge(health_score, 38, score_y + 22)

    # Text (right of circle)
    rx = 72
    if business_type:
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(*CYAN)
        pdf.set_xy(rx, score_y)
        pdf.multi_cell(120, 5, f"Negocio detectado: {business_type}", align="L")

    if summary:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*DARK)
        pdf.set_xy(rx, pdf.get_y() + 1)
        pdf.multi_cell(120, 4.5, summary, align="L")

    # Make sure we're below the score circle
    pdf.set_y(max(pdf.get_y(), score_y + 46))
    pdf.ln(4)
    pdf.hrule()

    # ═══════════════════════════════════
    # PAGESPEED
    # ═══════════════════════════════════
    ps = pagespeed or {}
    if ps.get("score") is not None:
        pdf.section_heading("Rendimiento tecnico (PageSpeed Mobile)", VIOLET)

        labels = ["Performance", "LCP", "CLS", "INP"]
        vals = [
            f"{ps.get('score', '-')}/100",
            f"{round(ps['lcp']/1000, 1)}s" if ps.get("lcp") else "-",
            f"{round(ps['cls'], 2)}" if ps.get("cls") is not None else "-",
            f"{ps['inp']}ms" if ps.get("inp") else "-",
        ]

        my = pdf.get_y()
        mw = 42
        for i, (label, val) in enumerate(zip(labels, vals)):
            cx = 16 + i * (mw + 3)
            pdf.set_fill_color(*LIGHT)
            pdf.set_draw_color(*BORDER)
            pdf.set_line_width(0.2)
            pdf.rect(cx, my, mw, 18, "FD")
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(*DARK)
            pdf.set_xy(cx, my + 2)
            pdf.cell(mw, 7, _s(val), align="C", ln=0)
            pdf.set_font("Helvetica", "", 6)
            pdf.set_text_color(*MUTED)
            pdf.set_xy(cx, my + 11)
            pdf.cell(mw, 4, label.upper(), align="C", ln=0)

        pdf.set_y(my + 22)

    # ═══════════════════════════════════
    # CRITICAL ISSUES
    # ═══════════════════════════════════
    if issues:
        pdf.section_heading(f"Problemas criticos ({len(issues)} encontrados)", RED)

        for issue in issues[:5]:
            if pdf.get_y() > 265:
                pdf.add_page()

            start_y = pdf.get_y()
            impact = issue.get("impact", "medio")

            # Impact pill
            pdf.impact_pill(impact, 16, start_y + 1)

            # Issue title
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.set_text_color(*DARK)
            pdf.set_xy(35, start_y)
            pdf.multi_cell(159, 5, _s(issue.get("issue", ""), 100), align="L")

            # Explanation
            pdf.set_font("Helvetica", "", 7.5)
            pdf.set_text_color(*MUTED)
            pdf.set_xy(35, pdf.get_y())
            pdf.multi_cell(159, 4.5, _s(issue.get("explanation", ""), 180), align="L")

            pdf.ln(3)
            # Light separator
            sep_y = pdf.get_y()
            pdf.set_draw_color(*BORDER)
            pdf.set_line_width(0.15)
            pdf.line(35, sep_y, 194, sep_y)
            pdf.ln(3)

    # ═══════════════════════════════════
    # OPPORTUNITIES
    # ═══════════════════════════════════
    if opps:
        if pdf.get_y() > 220:
            pdf.add_page()
        pdf.section_heading(f"Oportunidades de mejora (top {min(len(opps), 6)})", (0, 150, 180))

        for opp in opps[:6]:
            if pdf.get_y() > 265:
                pdf.add_page()

            start_y = pdf.get_y()

            # Cyan left bar
            pdf.left_bar(CYAN, 16, start_y, 1)  # placeholder height

            # Title
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.set_text_color(*DARK)
            pdf.set_xy(22, start_y)
            pdf.multi_cell(172, 5, _s(opp.get("title", ""), 90), align="L")

            # Impact
            pdf.set_font("Helvetica", "I", 7.5)
            pdf.set_text_color(*CYAN)
            pdf.set_xy(22, pdf.get_y())
            pdf.multi_cell(172, 4.5, _s(opp.get("estimated_impact", ""), 100), align="L")

            # Fix
            pdf.set_font("Helvetica", "", 7.5)
            pdf.set_text_color(*MUTED)
            pdf.set_xy(22, pdf.get_y())
            pdf.multi_cell(172, 4.5, _s(opp.get("how_to_fix", ""), 150), align="L")

            end_y = pdf.get_y()
            # Draw left bar with actual height
            pdf.left_bar(CYAN, 16, start_y, end_y - start_y)

            pdf.ln(4)

    # ═══════════════════════════════════
    # AUTOMATION PROPOSALS
    # ═══════════════════════════════════
    if proposals:
        if pdf.get_y() > 210:
            pdf.add_page()
        pdf.section_heading("Lo que WhiteRabbit puede hacer por vos", VIOLET)

        for prop in proposals[:3]:
            if pdf.get_y() > 260:
                pdf.add_page()

            start_y = pdf.get_y()

            # Title
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.set_text_color(*DARK)
            pdf.set_xy(22, start_y)
            pdf.multi_cell(172, 5, _s(prop.get("title", ""), 90), align="L")

            # Description
            pdf.set_font("Helvetica", "", 7.5)
            pdf.set_text_color(*MUTED)
            pdf.set_xy(22, pdf.get_y())
            pdf.multi_cell(172, 4.5, _s(prop.get("description", ""), 200), align="L")

            end_y = pdf.get_y()
            pdf.left_bar(VIOLET, 16, start_y, end_y - start_y)
            pdf.ln(4)

    # ═══════════════════════════════════
    # TRAFFIC ESTIMATE
    # ═══════════════════════════════════
    if traffic:
        if pdf.get_y() > 255:
            pdf.add_page()
        pdf.ln(2)
        pdf.set_fill_color(240, 255, 245)
        pdf.set_draw_color(25, 150, 70)
        pdf.set_line_width(0.3)
        est_y = pdf.get_y()
        # Draw background rectangle (approximate height)
        pdf.rect(16, est_y, 178, 14, "FD")
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*GREEN)
        pdf.set_xy(20, est_y + 2)
        pdf.cell(0, 4, "Potencial de crecimiento estimado:", ln=1)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_text_color(*DARK)
        pdf.set_xy(20, pdf.get_y())
        pdf.multi_cell(170, 4.5, traffic, align="L")
        pdf.ln(4)

    # ═══════════════════════════════════
    # CTA PAGE
    # ═══════════════════════════════════
    pdf.add_page()
    pdf.ln(25)

    cta_y = pdf.get_y()
    pdf.set_fill_color(*DARK)
    pdf.set_draw_color(*CYAN)
    pdf.set_line_width(0.8)
    pdf.rect(16, cta_y, 178, 78, "FD")

    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*WHITE)
    pdf.set_xy(16, cta_y + 12)
    pdf.cell(178, 9, "Queres que solucionemos esto?", align="C", ln=1)

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(180, 180, 200)
    pdf.set_xy(16, cta_y + 24)
    pdf.cell(178, 6, "La consulta inicial es 100% gratis.", align="C", ln=1)
    pdf.set_xy(16, cta_y + 31)
    pdf.cell(178, 6, "En menos de 48hs tenes una propuesta concreta.", align="C", ln=1)

    # WA button
    pdf.set_fill_color(37, 200, 100)
    pdf.set_draw_color(37, 200, 100)
    pdf.rect(66, cta_y + 44, 78, 13, "F")
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(*WHITE)
    pdf.set_xy(66, cta_y + 47)
    pdf.cell(78, 7, "Escribinos por WhatsApp", align="C", ln=1)

    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*CYAN)
    pdf.set_xy(16, cta_y + 62)
    pdf.cell(178, 5, "wa.me/595971185578  |  hola@whiterabbit.com.py  |  whiterabbit.com.py", align="C", ln=1)

    return bytes(pdf.output())
