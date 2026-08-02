"""Poster generation for the Championship app.

Gemini image poster: `gemini-2.5-flash-image` returns an inline image the app
displays and lets the user download (image models require billing).

HTML design: the two approved HTML files (`assets/leaderboard_template.html` and
`assets/matches_template.html`) ARE the design. `render_leaderboard_html` and
`render_matches_html` only substitute the dynamic data (title / table rows /
match cards), so the output matches the reference byte-for-byte. `finalize_html`
adds a button to export the design as JPEG via html-to-image.
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


# ---- Fixed design templates ----
# The posters are the approved HTML files in assets/ (leaderboard_template.html
# and matches_template.html). The render functions read those files verbatim and
# only substitute the dynamic data, so the design matches the references exactly.

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "assets")
_TEMPLATE_CACHE = {}


def _read_template(name):
    if name not in _TEMPLATE_CACHE:
        path = os.path.join(_TEMPLATE_DIR, name)
        with open(path, "r", encoding="utf-8") as f:
            _TEMPLATE_CACHE[name] = f.read()
    return _TEMPLATE_CACHE[name]


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
    """Fixed leaderboard poster: the approved HTML template + data rows."""
    dfcols = [str(c) for c in df.columns]
    selected = []
    for header, aliases, kind in _LB_SPEC:
        col = next((a for a in aliases if a in dfcols), None)
        selected.append((header, col, kind))

    rows = []
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        rank_cls = {1: " rank-1", 2: " rank-2", 3: " rank-3"}.get(i, "")
        tds = []
        for header, col, kind in selected:
            if kind == "rank":
                tds.append(f'<td class="rank{rank_cls}">{i}</td>')
                continue
            if col is None:
                tds.append("<td></td>")
                continue
            v = row[col]
            if kind == "name":
                color = {1: "#ffd700", 2: "#c0c0c0", 3: "#cd7f32"}.get(i)
                style = f' style="color: {color};"' if color else ""
                tds.append(f'<td class="name-col"{style}>{_esc(v)}</td>')
            elif kind == "points":
                if i == 1:
                    tds.append(f'<td><span class="points-badge">{_fmt_int(v)}</span></td>')
                elif i == 2:
                    tds.append(
                        '<td><span class="points-badge" style="background: '
                        f'linear-gradient(135deg, #c0c0c0, #7a7a7a);">{_fmt_int(v)}</span></td>'
                    )
                elif i == 3:
                    tds.append(
                        '<td><span class="points-badge" style="background: '
                        f'linear-gradient(135deg, #cd7f32, #8c521f);">{_fmt_int(v)}</span></td>'
                    )
                else:
                    tds.append(f"<td>{_fmt_int(v)}</td>")
            elif kind == "total":
                tds.append(f'<td class="total-highlight">{_fmt_decimal(v)}</td>')
            elif kind == "decimal":
                tds.append(f"<td>{_fmt_decimal(v)}</td>")
            else:
                tds.append(f"<td>{_fmt_int(v)}</td>")
        cls = f' class="top-row-{i}"' if i <= 3 else ""
        rows.append(f"                    <tr{cls}>" + "".join(tds) + "</tr>")

    return (
        _read_template("leaderboard_template.html")
        .replace("{{TITLE}}", _esc(title))
        .replace("{{LB_ROWS}}", "\n".join(rows))
    )


def _competitor(name, pages, points, side, winner):
    cls = f"competitor {side}" + (" winner" if winner else "")
    star = '<span class="winner-star">★</span>' if winner else ""
    if side == "right-side":
        info = f'<span class="player-name">{_esc(name)}</span>{star}'
    else:
        info = f'{star}<span class="player-name">{_esc(name)}</span>'
    return f"""                <div class="{cls}">
                    <div class="player-info">{info}</div>
                    <div class="player-stats">
                        <span class="stat-badge pages"><span class="label">الصفحات:</span><span class="val">{_fmt_decimal(pages)}</span></span>
                        <span class="stat-badge points"><span class="label">النقاط:</span><span class="val">{_fmt_int(points)}</span></span>
                    </div>
                </div>"""


def render_matches_html(matches, round_name):
    """Fixed matches poster: the approved HTML template + match cards."""
    cards = []
    for m in matches:
        p1 = m["points1"]
        p2 = m["points2"]
        cards.append(
            '            <div class="match-card">\n'
            f'{_competitor(m["s1"], m["pages1"], p1, "right-side", p1 > p2)}'
            '                <div class="vs-badge">ضد</div>\n'
            f'{_competitor(m["s2"], m["pages2"], p2, "left-side", p2 > p1)}'
            "            </div>"
        )

    return (
        _read_template("matches_template.html")
        .replace("{{ROUND_NAME}}", _esc(round_name))
        .replace("{{MATCH_CARDS}}", "\n".join(cards))
    )


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
