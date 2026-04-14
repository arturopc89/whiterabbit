"""WhiteRabbit — Branded PDF report generator using fpdf2.

Generates a professional diagnostic report PDF with WhiteRabbit branding.
Uses a clean white/light design (not dark — dark doesn't print well).
Cyan and violet accents match the brand.
"""

from __future__ import annotations

import io
from typing import Optional
from fpdf import FPDF

# ── Brand colors (RGB) ──
CYAN = (0, 200, 230)        # Lighter cyan for print
VIOLET = (100, 50, 200)     # Violet
DARK = (15, 15, 25)         # Near-black text
MUTED = (100, 100, 120)     # Secondary text
LIGHT_BG = (245, 246, 250)  # Card backgrounds
RED = (220, 50, 50)
AMBER = (200, 130, 20)
GREEN = (30, 160, 80)
WHITE = (255, 255, 255)


class WRReport(FPDF):
    """Custom FPDF subclass with WhiteRabbit header/footer."""

    def __init__(self, site_url: str = ""):
        super().__init__()
        self.site_url = site_url
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(18, 18, 18)

    def header(self):
        # White background strip
        self.set_fill_color(*DARK)
        self.rect(0, 0, 210, 18, 'F')

        # Logo text — "white" + "rabbit"
        self.set_y(5)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(240, 240, 243)
        self.set_x(18)
        self.cell(22, 8, "white", ln=0)
        self.set_text_color(*CYAN)
        self.cell(22, 8, "rabbit", ln=0)

        # Right side — site URL
        self.set_font("Helvetica", "", 7)
        self.set_text_color(150, 150, 170)
        self.cell(0, 8, self.site_url, align="R", ln=1)

        self.ln(6)

    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*MUTED)
        self.cell(0, 8, f"whiterabbit.com.py  ·  Página {self.page_no()}", align="C")

    # ── Helpers ──
    def section_title(self, text: str, color: tuple = DARK):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*color)
        self.cell(0, 7, text, ln=1)
        # Underline
        x = self.get_x()
        y = self.get_y()
        self.set_draw_color(*color)
        self.set_line_width(0.4)
        self.line(18, y, 192, y)
        self.ln(4)

    def card(self, x: float, y: float, w: float, h: float, fill: tuple = LIGHT_BG):
        self.set_fill_color(*fill)
        self.set_draw_color(220, 220, 230)
        self.set_line_width(0.2)
        self.round_rect(x, y, w, h, 3, 'FD')

    def score_circle(self, score: int, x: float, y: float):
        """Draw the health score circle."""
        color = GREEN if score >= 80 else (AMBER if score >= 50 else RED)
        r = 18
        # Outer ring
        self.set_draw_color(*color)
        self.set_line_width(2.5)
        self.circle(x, y, r * 2)
        # Score number
        self.set_font("Helvetica", "B", 22)
        self.set_text_color(*color)
        self.set_xy(x - r, y - r * 0.55)
        self.cell(r * 2, r, str(score), align="C")
        # Label
        self.set_font("Helvetica", "", 6)
        self.set_text_color(*MUTED)
        self.set_xy(x - r, y + r * 0.4)
        self.cell(r * 2, 5, "HEALTH SCORE", align="C")

    def impact_badge(self, impact: str) -> tuple:
        """Return color for impact badge."""
        if impact == "alto":
            return RED
        elif impact == "medio":
            return AMBER
        return GREEN


def generate_report_pdf(
    url: str,
    report: dict,
    pagespeed: Optional[dict] = None,
) -> bytes:
    """Generate a branded PDF report. Returns PDF bytes."""

    health_score = report.get("health_score", 0) or 0
    business_type = report.get("business_type", "")
    summary = report.get("summary", "")
    critical_issues = report.get("critical_issues", []) or []
    opportunities = report.get("opportunities", []) or []
    automation_proposals = report.get("automation_proposals", []) or []
    traffic_estimate = report.get("traffic_estimate", "")

    pdf = WRReport(site_url=url)
    pdf.add_page()

    # ── TITLE SECTION ──
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 10, "Reporte de Diagnóstico Web", ln=1)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    from datetime import date
    pdf.cell(0, 5, f"Análisis realizado el {date.today().strftime('%d/%m/%Y')}  ·  whiterabbit.com.py", ln=1)
    pdf.ln(4)

    # ── SCORE + SUMMARY CARD ──
    card_y = pdf.get_y()
    pdf.card(18, card_y, 174, 44)

    # Score circle on left
    pdf.score_circle(health_score, 42, card_y + 22)

    # Summary on right
    if business_type:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*CYAN)
        pdf.set_xy(75, card_y + 5)
        pdf.cell(115, 5, f"Tipo de negocio detectado: {business_type}", ln=1)

    if summary:
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*DARK)
        pdf.set_xy(75, card_y + 13)
        pdf.multi_cell(115, 5, summary[:300], align="L")

    pdf.set_y(card_y + 48)

    # ── PAGESPEED METRICS ──
    if pagespeed and pagespeed.get("score") is not None:
        pdf.ln(2)
        pdf.section_title("Rendimiento técnico (PageSpeed Mobile)", VIOLET)

        metrics = [
            ("Performance", f"{pagespeed.get('score', '—')}/100"),
            ("LCP", f"{round(pagespeed['lcp']/1000, 1)}s" if pagespeed.get("lcp") else "—"),
            ("CLS", f"{round(pagespeed['cls'], 2)}" if pagespeed.get("cls") is not None else "—"),
            ("INP", f"{pagespeed['inp']}ms" if pagespeed.get("inp") else "—"),
        ]

        mx = 18
        mw = 40
        my = pdf.get_y()
        for i, (label, val) in enumerate(metrics):
            cx = mx + i * (mw + 4)
            pdf.card(cx, my, mw, 20)
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(*DARK)
            pdf.set_xy(cx, my + 3)
            pdf.cell(mw, 8, str(val), align="C", ln=0)
            pdf.set_font("Helvetica", "", 6.5)
            pdf.set_text_color(*MUTED)
            pdf.set_xy(cx, my + 13)
            pdf.cell(mw, 5, label.upper(), align="C", ln=0)

        pdf.set_y(my + 26)

    # ── CRITICAL ISSUES ──
    if critical_issues:
        pdf.ln(2)
        pdf.section_title(f"Problemas críticos ({len(critical_issues)} encontrados)", RED)

        for issue in critical_issues[:5]:
            impact = issue.get("impact", "medio")
            impact_color = pdf.impact_badge(impact)
            issue_y = pdf.get_y()

            pdf.card(18, issue_y, 174, 18)

            # Impact badge
            pdf.set_fill_color(*impact_color)
            pdf.set_draw_color(*impact_color)
            pdf.round_rect(21, issue_y + 3, 18, 6, 1.5, 'F')
            pdf.set_font("Helvetica", "B", 6)
            pdf.set_text_color(*WHITE)
            pdf.set_xy(21, issue_y + 4)
            pdf.cell(18, 4, impact.upper(), align="C", ln=0)

            # Issue title
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.set_text_color(*DARK)
            pdf.set_xy(43, issue_y + 3)
            pdf.cell(147, 5, issue.get("issue", "")[:80], ln=1)

            # Explanation
            pdf.set_font("Helvetica", "", 7.5)
            pdf.set_text_color(*MUTED)
            pdf.set_xy(43, issue_y + 9)
            pdf.cell(147, 5, issue.get("explanation", "")[:100], ln=1)

            pdf.set_y(issue_y + 21)

    # ── OPPORTUNITIES ──
    if opportunities:
        pdf.ln(2)
        if pdf.get_y() > 230:
            pdf.add_page()

        pdf.section_title(f"Oportunidades de mejora (top {min(len(opportunities), 6)})", (0, 150, 180))

        for opp in opportunities[:6]:
            opp_y = pdf.get_y()
            if opp_y > 255:
                pdf.add_page()
                opp_y = pdf.get_y()

            pdf.card(18, opp_y, 174, 20)

            # Cyan left bar
            pdf.set_fill_color(*CYAN)
            pdf.rect(18, opp_y, 2.5, 20, 'F')

            # Title
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.set_text_color(*DARK)
            pdf.set_xy(24, opp_y + 3)
            pdf.cell(168, 5, opp.get("title", "")[:85], ln=1)

            # Impact
            pdf.set_font("Helvetica", "I", 7.5)
            pdf.set_text_color(*CYAN)
            pdf.set_xy(24, opp_y + 9)
            pdf.cell(168, 4, opp.get("estimated_impact", "")[:90], ln=1)

            # Fix
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*MUTED)
            pdf.set_xy(24, opp_y + 14)
            pdf.cell(168, 4, opp.get("how_to_fix", "")[:100], ln=1)

            pdf.set_y(opp_y + 23)

    # ── AUTOMATION PROPOSALS ──
    if automation_proposals:
        pdf.ln(2)
        if pdf.get_y() > 220:
            pdf.add_page()

        pdf.section_title("Lo que WhiteRabbit puede hacer por vos", VIOLET)

        for prop in automation_proposals[:3]:
            prop_y = pdf.get_y()
            if prop_y > 255:
                pdf.add_page()
                prop_y = pdf.get_y()

            pdf.card(18, prop_y, 174, 22)

            # Violet left bar
            pdf.set_fill_color(*VIOLET)
            pdf.rect(18, prop_y, 2.5, 22, 'F')

            pdf.set_font("Helvetica", "B", 8.5)
            pdf.set_text_color(*DARK)
            pdf.set_xy(24, prop_y + 3)
            pdf.cell(168, 5, prop.get("title", "")[:85], ln=1)

            pdf.set_font("Helvetica", "", 7.5)
            pdf.set_text_color(*MUTED)
            pdf.set_xy(24, prop_y + 10)
            pdf.multi_cell(162, 4, prop.get("description", "")[:150])

            pdf.set_y(prop_y + 25)

    # ── TRAFFIC ESTIMATE ──
    if traffic_estimate:
        pdf.ln(2)
        if pdf.get_y() > 250:
            pdf.add_page()

        est_y = pdf.get_y()
        pdf.card(18, est_y, 174, 18, fill=(240, 255, 245))
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(*GREEN)
        pdf.set_xy(22, est_y + 3)
        pdf.cell(0, 5, "Potencial de crecimiento estimado:", ln=1)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*DARK)
        pdf.set_xy(22, est_y + 10)
        pdf.cell(166, 5, str(traffic_estimate)[:120], ln=1)
        pdf.set_y(est_y + 22)

    # ── CTA PAGE ──
    pdf.add_page()
    pdf.ln(20)

    # Big CTA card
    pdf.set_fill_color(*DARK)
    pdf.set_draw_color(*CYAN)
    pdf.set_line_width(0.5)
    pdf.round_rect(18, pdf.get_y(), 174, 80, 6, 'FD')

    cta_y = pdf.get_y()
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*WHITE)
    pdf.set_xy(18, cta_y + 12)
    pdf.cell(174, 10, "¿Querés que solucionemos esto?", align="C", ln=1)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(180, 180, 200)
    pdf.set_xy(18, cta_y + 25)
    pdf.cell(174, 7, "La consulta inicial es 100% gratis.", align="C", ln=1)
    pdf.set_xy(18, cta_y + 32)
    pdf.cell(174, 7, "En menos de 48hs tenés una propuesta concreta.", align="C", ln=1)

    # WA button
    pdf.set_fill_color(37, 211, 102)
    pdf.set_draw_color(37, 211, 102)
    pdf.round_rect(64, cta_y + 45, 82, 14, 4, 'F')
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*WHITE)
    pdf.set_xy(64, cta_y + 48)
    pdf.cell(82, 8, "Escribinos por WhatsApp", align="C", ln=1)

    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(*CYAN)
    pdf.set_xy(18, cta_y + 63)
    pdf.cell(174, 6, "wa.me/595971185578  ·  hola@whiterabbit.com.py  ·  whiterabbit.com.py", align="C", ln=1)

    # Return as bytes
    return bytes(pdf.output())
