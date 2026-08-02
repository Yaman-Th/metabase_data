"""Poster generation for the Championship app.

Gemini image poster: `gemini-2.5-flash-image` returns an inline image the app
displays and lets the user download (image models require billing).

HTML design: a FIXED, deterministic template (`render_leaderboard_html`,
`render_matches_html`) so the design is always identical and only the data
changes. `finalize_html` adds a button to export the design as JPEG via
html-to-image.
"""

import re
import os
import html
import json
import streamlit as st

try:
    from google import genai
    from google.genai import types

    _HAS_GENAI = True
except Exception:
    genai = None
    types = None
    _HAS_GENAI = False

# Gemini 2.5 Flash Image (Nano Banana) generates images from text prompts via
# the standard generate_content endpoint. Override via the
# GEMINI_IMAGE_MODEL secret if a newer model becomes available.
DEFAULT_IMAGE_MODEL = "gemini-2.5-flash-image"

# Text model for the free-tier HTML design fallback (image models require
# billing; text generation is free). Override via GEMINI_TEXT_MODEL.
# gemini-2.5-flash is deprecated for new API keys (404), so we default to the
# newer 3.5 series.
DEFAULT_TEXT_MODEL = "gemini-3.5-flash"

ASPECT_RATIO = "9:16"  # vertical poster


def _secret_value(*paths):
    try:
        secrets = st.secrets
    except Exception:
        return None
    for path in paths:
        node = secrets
        try:
            for k in path:
                node = node[k]
            if node:
                return node
        except Exception:
            continue
    return None


def gemini_key():
    return _secret_value(("GEMINI_API_KEY",), ("secrets", "GEMINI_API_KEY"))


def gemini_model():
    return _secret_value(("GEMINI_IMAGE_MODEL",), ("secrets", "GEMINI_IMAGE_MODEL")) or DEFAULT_IMAGE_MODEL


def gemini_enabled():
    return _HAS_GENAI and bool(gemini_key())


def friendly_error(e):
    """Translate common API failures into a short, actionable message."""
    text = str(e)
    low = text.lower()
    if "429" in text and ("resource_exhausted" in low or "quota" in low):
        return (
            "Gemini image generation is not enabled for this API key (free tier "
            "has no image quota). Enable billing for the project at "
            "https://aistudio.google.com/apikey, then try again. Text models "
            "stay free."
        )
    if "401" in text or "api key not valid" in low or "invalid api key" in low:
        return "The GEMINI_API_KEY is invalid. Check it at https://aistudio.google.com/apikey."
    return None


def generate_poster(prompt):
    """Call Gemini and return (image_bytes, mime_type) or (None, None)."""
    key = gemini_key()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to Streamlit secrets to enable "
            "AI poster generation."
        )
    if not _HAS_GENAI:
        raise RuntimeError(
            "google-genai is not installed. Add it to requirements.txt and "
            "redeploy."
        )

    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model=gemini_model(),
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=ASPECT_RATIO),
        ),
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            return part.inline_data.data, part.inline_data.mime_type or "image/png"
    return None, None


def gemini_text_model():
    return _secret_value(("GEMINI_TEXT_MODEL",), ("secrets", "GEMINI_TEXT_MODEL")) or DEFAULT_TEXT_MODEL


# ---- Fixed design templates (match the approved leaderboard/matches designs) ----

_LB_FONTS = (
    "https://fonts.googleapis.com/css2?family=Amiri:ital,wght@0,400;0,700;1,400"
    "&family=Cairo:wght@300;400;600;700;800&display=swap"
)
_M_FONTS = (
    "https://fonts.googleapis.com/css2?family=Amiri:ital,wght@0,400;0,700;1,400"
    "&family=Cairo:wght@300;400;500;600;700;800"
    "&family=Reem+Kufi:wght@400;500;600;700&display=swap"
)

_LEADERBOARD_CSS = """
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        body {
            background-color: #03120c;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            font-family: 'Cairo', sans-serif;
            overflow-x: hidden;
        }
        #poster {
            width: 1080px;
            height: 1920px;
            position: relative;
            background-color: #041a12;
            background-image:
                radial-gradient(circle at 50% 30%, #0a3d2b 0%, #041a12 70%),
                url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='80' viewBox='0 0 80 80'%3E%3Cg fill='%23d4af37' fill-opacity='0.03'%3E%3Cpath d='M40 0 L80 40 L40 80 L0 40 Z M40 10 L70 40 L40 70 L10 40 Z'/%3E%3C/g%3E%3C/svg%3E");
            box-shadow: 0 0 80px rgba(0, 0, 0, 0.9);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            align-items: center;
            padding: 90px 60px;
            border: 4px solid #d4af37;
            outline: 20px solid #041a12;
            outline-offset: -24px;
            overflow: hidden;
        }
        #poster::before {
            content: '';
            position: absolute;
            top: 30px;
            bottom: 30px;
            left: 30px;
            right: 30px;
            border: 1px solid rgba(212, 175, 55, 0.3);
            pointer-events: none;
        }
        .corner-design {
            position: absolute;
            width: 80px;
            height: 80px;
            border: 3px solid #d4af37;
            pointer-events: none;
        }
        .top-right { top: 25px; right: 25px; border-bottom: none; border-left: none; }
        .top-left { top: 25px; left: 25px; border-bottom: none; border-right: none; }
        .bottom-right { bottom: 25px; right: 25px; border-top: none; border-left: none; }
        .bottom-left { bottom: 25px; left: 25px; border-top: none; border-right: none; }
        .header-section { text-align: center; width: 100%; z-index: 2; }
        .bismillah {
            font-family: 'Amiri', serif;
            font-size: 28px;
            color: #d4af37;
            letter-spacing: 2px;
            margin-bottom: 25px;
            opacity: 0.9;
        }
        .title-container {
            position: relative;
            display: inline-block;
            padding: 15px 60px;
            margin-bottom: 20px;
        }
        .title-container::before, .title-container::after {
            content: '';
            position: absolute;
            width: 40px;
            height: 100%;
            border: 2px solid #d4af37;
            top: 0;
        }
        .title-container::before { left: 0; border-right: none; }
        .title-container::after { right: 0; border-left: none; }
        .main-title {
            font-family: 'Amiri', serif;
            font-size: 72px;
            font-weight: 700;
            color: #ffffff;
            text-shadow: 0 4px 15px rgba(0, 0, 0, 0.6), 0 0 20px rgba(212, 175, 55, 0.4);
            line-height: 1.2;
        }
        .subtitle {
            font-size: 24px;
            font-weight: 400;
            color: #d4af37;
            letter-spacing: 6px;
            text-transform: uppercase;
            margin-top: 10px;
        }
        .divider {
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 25px auto;
            width: 60%;
        }
        .divider::before, .divider::after {
            content: '';
            flex: 1;
            height: 1px;
            background: linear-gradient(90deg, transparent, #d4af37, transparent);
        }
        .divider-flower { font-size: 24px; color: #d4af37; margin: 0 15px; }
        .table-container {
            width: 100%;
            background: rgba(4, 26, 18, 0.8);
            border: 1px solid rgba(212, 175, 55, 0.25);
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.5);
            backdrop-filter: blur(10px);
            z-index: 2;
        }
        table { width: 100%; border-collapse: collapse; text-align: center; }
        th {
            font-size: 18px;
            font-weight: 700;
            color: #d4af37;
            padding: 18px 10px;
            border-bottom: 2px solid rgba(212, 175, 55, 0.4);
            font-family: 'Cairo', sans-serif;
        }
        td {
            font-size: 18px;
            font-weight: 600;
            color: #e0e0e0;
            padding: 16px 10px;
            border-bottom: 1px solid rgba(212, 175, 55, 0.1);
        }
        tr:last-child td { border-bottom: none; }
        .rank { font-family: 'Amiri', serif; font-size: 22px; font-weight: 700; width: 60px; }
        .rank-1 { color: #ffd700; text-shadow: 0 0 10px rgba(255,215,0,0.4); }
        .rank-2 { color: #c0c0c0; text-shadow: 0 0 10px rgba(192,192,192,0.4); }
        .rank-3 { color: #cd7f32; text-shadow: 0 0 10px rgba(205,127,50,0.4); }
        .name-col { text-align: right; font-weight: 700; padding-right: 20px; color: #ffffff; }
        .points-badge {
            background: linear-gradient(135deg, #d4af37, #aa7c11);
            color: #041a12;
            padding: 4px 12px;
            border-radius: 30px;
            font-weight: 800;
            font-size: 17px;
            display: inline-block;
            box-shadow: 0 4px 10px rgba(212, 175, 55, 0.2);
        }
        .top-row-1 { background: rgba(212, 175, 55, 0.08); }
        .top-row-2 { background: rgba(192, 192, 192, 0.05); }
        .top-row-3 { background: rgba(205, 127, 50, 0.04); }
        .total-highlight { color: #d4af37; font-weight: 700; }
        .footer-section { text-align: center; width: 100%; z-index: 2; }
        .quran-verse {
            font-family: 'Amiri', serif;
            font-size: 32px;
            font-style: italic;
            color: #d4af37;
            margin-bottom: 20px;
            text-shadow: 0 2px 8px rgba(0,0,0,0.5);
        }
        .footer-logo {
            font-size: 16px;
            font-weight: 400;
            color: rgba(255, 255, 255, 0.5);
            letter-spacing: 4px;
        }
"""

_MATCHES_CSS = """
        * { box-sizing: border-box; }
        body {
            margin: 0;
            padding: 40px 0;
            background-color: #020b08;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            font-family: 'Cairo', sans-serif;
            overflow-x: hidden;
        }
        #poster {
            width: 1080px;
            height: 1920px;
            background-color: #04231c;
            background-image:
                radial-gradient(circle at 50% 30%, #0c4d3f 0%, #041c16 80%),
                url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='80' viewBox='0 0 80 80'%3E%3Cpath d='M40 0l10 30 30 10-30 10-10 30-10-30-30-10 30-10z' fill='%23d4af37' fill-opacity='0.025'/%3E%3C/svg%3E");
            position: relative;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            align-items: center;
            padding: 100px 80px;
            box-shadow: 0 35px 70px rgba(0, 0, 0, 0.7);
            overflow: hidden;
        }
        #poster::after {
            content: '';
            position: absolute;
            top: 30px;
            left: 30px;
            right: 30px;
            bottom: 30px;
            border: 3px solid #d4af37;
            pointer-events: none;
            opacity: 0.9;
            z-index: 2;
        }
        #poster::before {
            content: '';
            position: absolute;
            top: 42px;
            left: 42px;
            right: 42px;
            bottom: 42px;
            border: 1.5px solid rgba(212, 175, 55, 0.4);
            pointer-events: none;
            z-index: 2;
        }
        .corner-decoration {
            position: absolute;
            width: 50px;
            height: 50px;
            border: 4px solid #d4af37;
            z-index: 10;
        }
        .corner-decoration::after {
            content: '';
            position: absolute;
            width: 16px;
            height: 16px;
            background: #d4af37;
            transform: rotate(45deg);
        }
        .corner-decoration.tl { top: 38px; left: 38px; border-right: none; border-bottom: none; }
        .corner-decoration.tl::after { top: -8px; left: -8px; }
        .corner-decoration.tr { top: 38px; right: 38px; border-left: none; border-bottom: none; }
        .corner-decoration.tr::after { top: -8px; right: -8px; }
        .corner-decoration.bl { bottom: 38px; left: 38px; border-right: none; border-top: none; }
        .corner-decoration.bl::after { bottom: -8px; left: -8px; }
        .corner-decoration.br { bottom: 38px; right: 38px; border-left: none; border-top: none; }
        .corner-decoration.br::after { bottom: -8px; right: -8px; }
        .glow-circle {
            position: absolute;
            width: 600px;
            height: 600px;
            background: radial-gradient(circle, rgba(13, 77, 63, 0.35) 0%, rgba(13, 77, 63, 0) 70%);
            pointer-events: none;
            z-index: 1;
        }
        .glow-1 { top: 10%; left: -200px; }
        .glow-2 { bottom: 10%; right: -200px; }
        .header { text-align: center; z-index: 5; width: 100%; }
        .header-logo {
            font-family: 'Reem Kufi', sans-serif;
            color: #d4af37;
            font-size: 22px;
            letter-spacing: 6px;
            margin-bottom: 12px;
            font-weight: 600;
        }
        .header-logo::before, .header-logo::after { content: " ✦ "; color: #f3e5ab; }
        .main-title {
            font-family: 'Amiri', serif;
            font-size: 76px;
            font-weight: 700;
            color: #ffffff;
            background: linear-gradient(to bottom, #ffffff 40%, #e6be4e 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin: 0 0 15px 0;
            filter: drop-shadow(0 4px 10px rgba(0,0,0,0.5));
        }
        .header-ornament { display: flex; align-items: center; justify-content: center; gap: 15px; margin-top: 5px; }
        .header-ornament .line {
            width: 120px;
            height: 1px;
            background: linear-gradient(to right, rgba(212, 175, 55, 0), rgba(212, 175, 55, 0.8), rgba(212, 175, 55, 0));
        }
        .header-ornament .diamond { width: 10px; height: 10px; background: #d4af37; transform: rotate(45deg); }
        .matches-container { width: 100%; display: flex; flex-direction: column; gap: 22px; margin: auto 0; z-index: 5; }
        .match-card {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: linear-gradient(135deg, rgba(13, 77, 63, 0.45) 0%, rgba(5, 33, 27, 0.7) 100%);
            border: 1.5px solid rgba(212, 175, 55, 0.25);
            border-radius: 20px;
            padding: 22px 40px;
            box-shadow: 0 12px 35px rgba(0, 0, 0, 0.35);
            position: relative;
        }
        .match-card::before {
            content: '';
            position: absolute;
            top: 5px; left: 5px; right: 5px; bottom: 5px;
            border: 1px solid rgba(212, 175, 55, 0.08);
            border-radius: 15px;
            pointer-events: none;
        }
        .competitor { flex: 1; display: flex; flex-direction: column; }
        .competitor.right-side { align-items: flex-start; text-align: right; }
        .competitor.left-side { align-items: flex-end; text-align: left; }
        .player-info { display: flex; align-items: center; gap: 10px; }
        .player-name { font-size: 26px; font-weight: 600; color: #d1e2de; margin: 0; }
        .winner .player-name {
            color: #ffffff;
            font-weight: 800;
            background: linear-gradient(to left, #ffffff, #f7ebb8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .competitor.left-side.winner .player-name {
            background: linear-gradient(to right, #ffffff, #f7ebb8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .winner-star {
            color: #d4af37;
            filter: drop-shadow(0 0 5px #d4af37);
            font-size: 22px;
            margin: 0 6px;
        }
        .player-stats { display: flex; gap: 14px; margin-top: 10px; }
        .stat-badge {
            padding: 4px 14px;
            border-radius: 8px;
            font-size: 14px;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .stat-badge.pages { background: rgba(13, 77, 63, 0.6); border: 1px solid rgba(143, 174, 168, 0.3); }
        .stat-badge.points { background: rgba(212, 175, 55, 0.12); border: 1px solid rgba(212, 175, 55, 0.35); }
        .label { color: #8faea8; font-weight: 400; }
        .val { color: #ffffff; font-weight: 700; }
        .winner .stat-badge.points .val { color: #ffd863; }
        .vs-badge {
            width: 55px;
            height: 55px;
            background: linear-gradient(135deg, #d4af37 0%, #aa7c11 100%);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: 'Reem Kufi', sans-serif;
            font-weight: bold;
            color: #04231c;
            font-size: 19px;
            box-shadow: 0 0 20px rgba(212, 175, 55, 0.45);
            margin: 0 30px;
            flex-shrink: 0;
            z-index: 5;
        }
        .footer { text-align: center; z-index: 5; width: 100%; }
        .quran-verse {
            font-family: 'Amiri', serif;
            font-size: 34px;
            color: #f3e5ab;
            margin-bottom: 15px;
            text-shadow: 0 3px 6px rgba(0,0,0,0.6);
            font-weight: bold;
        }
        .footer-sub {
            font-family: 'Cairo', sans-serif;
            font-size: 18px;
            color: #8faea8;
            letter-spacing: 3px;
            font-weight: 500;
        }
"""


def _esc(v):
    return html.escape(str(v), quote=True)


def _fmt_int(v):
    try:
        return f"{int(round(float(v)))}"
    except (TypeError, ValueError):
        return _esc(v)


def _fmt_decimal(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return _esc(v)
    if f == int(f):
        return f"{f:.1f}"
    return str(f)


def _design_document(css, fonts_href, content, title_text=""):
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{_esc(title_text)}</title>
    <link href="{fonts_href}" rel="stylesheet">
    <style>
{css}
    </style>
</head>
<body>
{content}
</body>
</html>
"""


_LB_SPEC = [
    ("#", ("#", "الترتيب"), "rank"),
    ("الاسم", ("الاسم", "Name"), "name"),
    ("النقاط", ("النقاط", "Points"), "points"),
    ("جديد", ("جديد", "Jadeed"), "decimal"),
    ("تكرار", ("تكرار", "Tikrar"), "decimal"),
    ("المجموع", ("المجموع", "Total"), "total"),
    ("الأيام", ("أيام الإنجاز", "الأيام", "Days Met"), "int"),
    ("فوز", ("فوز", "W"), "int"),
    ("تعادل", ("تعادل", "D"), "int"),
    ("خسارة", ("خسارة", "L"), "int"),
]


def render_leaderboard_html(df, title="لوحة المتصدرين"):
    """Fixed leaderboard poster matching the approved design."""
    dfcols = [str(c) for c in df.columns]
    selected = []
    for header, aliases, kind in _LB_SPEC:
        col = next((a for a in aliases if a in dfcols), None)
        if col is not None:
            selected.append((header, col, kind))

    thead = "".join(f"<th>{_esc(h)}</th>" for h, _, _ in selected)
    tbody = []
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        rank_cls = {1: " rank-1", 2: " rank-2", 3: " rank-3"}.get(i, "")
        row_cls = f" top-row-{i}" if i <= 3 else ""
        tds = []
        for header, col, kind in selected:
            v = row[col]
            if kind == "rank":
                tds.append(f'<td class="rank{rank_cls}">{i}</td>')
            elif kind == "name":
                color = {1: "#ffd700", 2: "#c0c0c0", 3: "#cd7f32"}.get(i)
                style = f' style="color: {color};"' if color else ""
                tds.append(f'<td class="name-col"{style}>{_esc(v)}</td>')
            elif kind == "points":
                inner = _fmt_int(v)
                if i == 2:
                    inner = f'<span class="points-badge" style="background: linear-gradient(135deg, #c0c0c0, #7a7a7a);">{inner}</span>'
                elif i == 3:
                    inner = f'<span class="points-badge" style="background: linear-gradient(135deg, #cd7f32, #8c521f);">{inner}</span>'
                else:
                    inner = f'<span class="points-badge">{inner}</span>'
                tds.append(f"<td>{inner}</td>")
            elif kind == "total":
                tds.append(f'<td class="total-highlight">{_fmt_decimal(v)}</td>')
            elif kind == "decimal":
                tds.append(f"<td>{_fmt_decimal(v)}</td>")
            else:
                tds.append(f"<td>{_fmt_int(v)}</td>")
        tbody.append(f'<tr class="{row_cls.strip()}">' + "".join(tds) + "</tr>")

    content = f"""<div id="poster">
    <div class="corner-design top-right"></div>
    <div class="corner-design top-left"></div>
    <div class="corner-design bottom-right"></div>
    <div class="corner-design bottom-left"></div>

    <div class="header-section">
        <div class="bismillah">بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ</div>
        <div class="title-container">
            <div class="main-title">{_esc(title)}</div>
        </div>
        <div class="subtitle">مسابقة تحفيظ القرآن الكريم الكبرى</div>
        <div class="divider">
            <span class="divider-flower">❖</span>
        </div>
    </div>

    <div class="table-container">
        <table>
            <thead><tr>{thead}</tr></thead>
            <tbody>{''.join(tbody)}</tbody>
        </table>
    </div>

    <div class="footer-section">
        <div class="quran-verse">"وَفِي ذَٰلِكَ فَلْيَتَنَافَسِ الْمُتَنَافِسُونَ"</div>
        <div class="footer-logo">اللجنة التنظيمية للمسابقة</div>
    </div>
</div>
"""
    return _design_document(_LEADERBOARD_CSS, _LB_FONTS, content, title)


def _competitor(name, pages, points, side, winner):
    cls = f"competitor {side}" + (" winner" if winner else "")
    star = '<span class="winner-star">★</span>' if winner else ""
    if side == "right-side":
        info = f'<span class="player-name">{_esc(name)}</span>{star}'
    else:
        info = f'{star}<span class="player-name">{_esc(name)}</span>'
    return f"""<div class="{cls}">
        <div class="player-info">{info}</div>
        <div class="player-stats">
            <span class="stat-badge pages"><span class="label">الصفحات:</span><span class="val">{_fmt_decimal(pages)}</span></span>
            <span class="stat-badge points"><span class="label">النقاط:</span><span class="val">{_fmt_int(points)}</span></span>
        </div>
    </div>"""


def render_matches_html(matches, round_name):
    """Fixed matches poster matching the approved design."""
    cards = []
    for m in matches:
        p1 = m["points1"]
        p2 = m["points2"]
        cards.append(
            '<div class="match-card">'
            f'{_competitor(m["s1"], m["pages1"], p1, "right-side", p1 > p2)}'
            '<div class="vs-badge">ضد</div>'
            f'{_competitor(m["s2"], m["pages2"], p2, "left-side", p2 > p1)}'
            "</div>"
        )

    content = f"""<div id="poster">
    <div class="glow-circle glow-1"></div>
    <div class="glow-circle glow-2"></div>

    <div class="corner-decoration tl"></div>
    <div class="corner-decoration tr"></div>
    <div class="corner-decoration bl"></div>
    <div class="corner-decoration br"></div>

    <div class="header">
        <div class="header-logo">مُسَابَقَةُ تَحْفِيظِ القُرْآنِ الكَرِيمِ</div>
        <h1 class="main-title">{_esc(round_name)}</h1>
        <div class="header-ornament">
            <div class="line"></div>
            <div class="diamond"></div>
            <div class="line"></div>
        </div>
    </div>

    <div class="matches-container">
{''.join(cards)}
    </div>

    <div class="footer">
        <div class="header-ornament" style="margin-bottom: 25px;">
            <div class="line" style="width: 180px;"></div>
            <div class="diamond"></div>
            <div class="line" style="width: 180px;"></div>
        </div>
        <div class="quran-verse">« وَفِي ذَٰلِكَ فَلْيَتَنَافَسِ الْمُتَنَافِسُونَ »</div>
        <div class="footer-sub">مُسَابَقَةُ تَرْتِيلِ الوَحْيَيْنِ العَطِرَةِ</div>
    </div>
</div>
"""
    return _design_document(_MATCHES_CSS, _M_FONTS, content, round_name)


def finalize_html(html, export_filename):
    """Make the design HTML self-contained and add the 'Export as JPEG' button.

    Ensures a `<div id="poster">` wrapper exists, then injects the vendored
    html-to-image library and a floating button that downloads the poster as a
    JPEG (also handles export from inside the Streamlit component iframe).
    """
    if not html or not html.strip():
        return ""

    if 'id="poster"' not in html and "id='poster'" not in html:
        html = re.sub(
            r"<body([^>]*)>(.*?)</body>",
            lambda m: f"<body{m.group(1)}><div id=\"poster\">{m.group(2)}</div></body>",
            html,
            flags=re.S,
        )
    if 'id="poster"' not in html and "id='poster'" not in html:
        html = f"<html><body dir=\"rtl\"><div id=\"poster\">{html}</div></body></html>"

    tool = _export_tool_html(export_filename)
    if "</body>" in html:
        html = html.replace("</body>", tool + "</body>")
    else:
        html = html + tool
    return html


_HTML_TO_IMAGE_LIB = None


def _html_to_image_lib():
    """Read the vendored html-to-image library once and return its source.

    Vendored (assets/html-to-image.min.js) so the export never depends on a
    CDN that may be blocked or slow.
    """
    global _HTML_TO_IMAGE_LIB
    if _HTML_TO_IMAGE_LIB is None:
        path = os.path.join(os.path.dirname(__file__), "assets", "html-to-image.min.js")
        try:
            with open(path, "r", encoding="utf-8") as f:
                _HTML_TO_IMAGE_LIB = f.read()
        except Exception:
            _HTML_TO_IMAGE_LIB = ""
    return _HTML_TO_IMAGE_LIB


def _export_tool_html(filename):
    jname = json.dumps(filename.rsplit(".", 1)[0] + ".jpeg")
    # html-to-image renders via SVG foreignObject, which keeps native text
    # shaping (correct Arabic). html2canvas can break Arabic letter joining.
    portrait_css = (
        "<style>"
        "#poster{box-sizing:border-box!important;max-width:1080px!important;"
        "width:auto!important;margin:0 auto!important;min-height:1600px!important;}"
        "html,body{margin:0!important;padding:0!important;}"
        "</style>"
    )
    lib = _html_to_image_lib().replace("</script>", "<\\/script>")
    script = (
        "<script>"
        "document.addEventListener('DOMContentLoaded',function(){"
        "var b=document.getElementById('export-jpeg');"
        "if(!b){return;}"
        "b.addEventListener('click',function(){"
        "var el=document.getElementById('poster')||document.body;"
        "if(typeof htmlToImage==='undefined'){alert('Export library failed to load.');return;}"
        "var btn=this;btn.disabled=true;btn.textContent='Exporting...';"
        "var oldCss=el.style.cssText;"
        "el.style.setProperty('width','1080px','important');"
        "el.style.setProperty('max-width','1080px','important');"
        "el.style.setProperty('margin','0 auto','important');"
        "el.style.setProperty('left','0','important');"
        "document.fonts.ready.then(function(){"
        "var w=el.offsetWidth,h=el.offsetHeight;"
        "return htmlToImage.toJpeg(el,{width:w,height:h,pixelRatio:2,backgroundColor:'#03120c',quality:0.95,cacheBust:true});"
        "}).then(function(url){"
        "el.style.cssText=oldCss;"
        "var fname=" + jname + ";"
        "function dl(doc){var a=doc.createElement('a');a.download=fname;a.href=url;"
        "doc.body.appendChild(a);a.click();a.remove();}"
        "var done=false;"
        "try{if(window.parent&&window.parent.document){dl(window.parent.document);done=true;}}catch(e){}"
        "if(!done){try{dl(document);done=true;}catch(e){}}"
        "if(!done){window.open(url,'_blank');}"
        "btn.disabled=false;btn.textContent='Export as JPEG';"
        "}).catch(function(e){"
        "el.style.cssText=oldCss;"
        "btn.disabled=false;btn.textContent='Export as JPEG';"
        "alert('Export failed: '+e.message);"
        "});"
        "});"
        "});"
        "</script>"
    )
    return (
        portrait_css
        + '<div style="position:fixed;top:12px;right:12px;z-index:99999;direction:ltr;">'
        '<button id="export-jpeg" style="background:#1f77b4;color:#fff;border:none;'
        'padding:10px 16px;border-radius:8px;font-size:14px;cursor:pointer;'
        'font-family:Arial,sans-serif;box-shadow:0 2px 6px rgba(0,0,0,.3);">'
        'Export as JPEG</button>'
        "</div>"
        f"<script>{lib}</script>"
        + script
    )


def _prompt(title, table):
    return f"""أنشئ بوستر/إنفوجرافيك جميل وعمودي لمنافسة تحفيظ القرآن الكريم.

التصميم يجب أن يكون باللغة العربية، فخم وأنيق واحتفالي. استخدم جماليات إسلامية
(أخضر وذهبي، زخارف هندسية خفيفة، تدرجات ناعمة)، تخطيط عصري، تسلسل واضح،
ومساحات مريحة. لا تضع أي نص بخلاف العنوان والبيانات المقدمة.

عنوان البوستر: "{title}"

أدرج البيانات التالية في جدول نظيف وواضح مع الحفاظ على الأسماء والأرقام تماماً
كما هي. اتجاه القراءة من اليمين إلى اليسار.

البيانات:
{table}
"""


def build_leaderboard_prompt(df, title="لوحة المتصدرين"):
    headers = [str(c) for c in df.columns]
    lines = [" | ".join(headers)]
    for _, row in df.iterrows():
        lines.append(" | ".join("" if v is None else str(v) for v in row.tolist()))
    return _prompt(title, "\n".join(lines))


def build_matches_prompt(matches, round_name):
    lines = []
    for m in matches:
        lines.append(
            f"{m['s1']} ضد {m['s2']} | صفحات: {m['pages1']:.1f} مقابل "
            f"{m['pages2']:.1f} | النتيجة: {m['result_text']} | نقاط: "
            f"{m['points1']} مقابل {m['points2']}"
        )
    return _prompt(round_name, "\n".join(lines))
