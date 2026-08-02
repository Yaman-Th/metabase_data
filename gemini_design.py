"""Poster generation for the Championship app.

Gemini image poster: `gemini-2.5-flash-image` returns an inline image the app
displays and lets the user download (image models require billing).

HTML design: a FIXED, deterministic template (`render_leaderboard_html`,
`render_matches_html`) so the design is always identical and only the data
changes. `finalize_html` adds a button to export the design as JPEG via
html-to-image.
"""

import re
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


def _design_css():
    return """
*{margin:0;padding:0;box-sizing:border-box}
body{background:#efe9d8}
#poster{
  background:
    radial-gradient(circle at 50% -6%, rgba(212,175,55,.22), transparent 46%),
    linear-gradient(180deg,#0b3d2e 0%,#0f4d38 32%,#f7f2e3 32%,#f7f2e3 100%);
  color:#2c3a2c;padding:0 0 40px;
}
.top{padding:42px 44px 30px;color:#fff;text-align:center;position:relative}
.top::before{content:"";position:absolute;inset:16px;border:2px solid rgba(212,175,55,.6);border-radius:18px;pointer-events:none}
.top::after{content:"";position:absolute;inset:25px;border:1px dashed rgba(212,175,55,.45);border-radius:12px;pointer-events:none}
.basmala{color:#e3c76a;font-size:30px;font-weight:700;margin-top:8px}
.title{font-size:62px;font-weight:900;color:#fdf6e3;text-shadow:0 3px 10px rgba(0,0,0,.35);margin:12px 0 6px;line-height:1.2}
.subtitle{font-size:28px;color:#cfe8d8;font-weight:600}
.rule{width:240px;height:6px;margin:22px auto 0;background:linear-gradient(90deg,transparent,#e3c76a,transparent);border-radius:3px}
.content{padding:32px 44px 16px}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:18px;overflow:hidden;box-shadow:0 14px 34px rgba(20,60,40,.18)}
thead th{background:linear-gradient(90deg,#0f4d38,#14532d);color:#fdf6e3;font-size:21px;font-weight:700;padding:16px 10px}
tbody td{padding:15px 10px;font-size:23px;text-align:center;border-bottom:1px solid #eee2c4;font-weight:600}
tbody tr:nth-child(even){background:#fbf6e8}
tbody tr:last-child td{border-bottom:none}
tbody tr:nth-child(1) td{color:#8a6d0f;background:#fff6d9}
tbody tr:nth-child(2) td{color:#4b5563;background:#f1f3f5}
tbody tr:nth-child(3) td{color:#7c4d1b;background:#f7ead8}
.match-card{background:#fff;border-radius:18px;box-shadow:0 14px 34px rgba(20,60,40,.16);padding:26px 28px;margin-bottom:24px;border-right:8px solid #c9a227}
.match-head{display:flex;align-items:center;justify-content:space-between;gap:12px}
.pitcher{flex:1;text-align:center}
.pitcher .name{font-size:30px;font-weight:900;color:#123c2c}
.pitcher .pages{font-size:26px;color:#c9a227;font-weight:700;margin-top:8px}
.vs{font-size:28px;font-weight:900;color:#8aa89a;background:#f1f5f1;width:66px;height:66px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.match-result{margin-top:18px;background:#f6f9f4;border:1px dashed #c9dcc9;border-radius:12px;padding:12px;text-align:center;font-size:24px;font-weight:700;color:#14532d}
.foot{padding:26px 0 10px;text-align:center;color:#7a8b7a;font-size:22px}
.foot .orn{color:#c9a227;font-size:22px}
"""


def _esc(v):
    return html.escape(str(v), quote=True)


def _fmt_num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return _esc(v)
    if f == int(f):
        return f"{int(f):,}"
    return f"{f:,.1f}"


def _design_document(title, subtitle, content):
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&family=Tajawal:wght@400;500;700;800&display=swap">
<style>
{_design_css()}
</style>
</head>
<body>
<div id="poster">
  <div class="top">
    <div class="basmala">بسم الله الرحمن الرحيم</div>
    <h1 class="title">{_esc(title)}</h1>
    <p class="subtitle">{_esc(subtitle)}</p>
    <div class="rule"></div>
  </div>
  <div class="content">
  {content}
  </div>
  <div class="foot"><span class="orn">◆</span> وفق الله الجميع <span class="orn">◆</span></div>
</div>
</body>
</html>
"""


def render_leaderboard_html(df, title="لوحة المتصدرين"):
    """Fixed, deterministic leaderboard poster from a DataFrame."""
    thead = "".join(f"<th>{_esc('الترتيب' if c == '#' else c)}</th>" for c in df.columns)
    rows = []
    for _, row in df.iterrows():
        tds = "".join(f"<td>{_fmt_num(v)}</td>" for v in row.tolist())
        rows.append(f"<tr>{tds}</tr>")
    table = f'<table><thead><tr>{thead}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
    return _design_document(title, "لوحة المتصدرين", table)


def render_matches_html(matches, round_name):
    """Fixed, deterministic matches poster from a list of match dicts."""
    cards = []
    for m in matches:
        cards.append(
            '<div class="match-card">'
            '<div class="match-head">'
            f'<div class="pitcher"><div class="name">{_esc(m["s1"])}</div>'
            f'<div class="pages">{_fmt_num(m["pages1"])}</div></div>'
            '<div class="vs">ضد</div>'
            f'<div class="pitcher"><div class="name">{_esc(m["s2"])}</div>'
            f'<div class="pages">{_fmt_num(m["pages2"])}</div></div>'
            "</div>"
            f'<div class="match-result">النتيجة: {_esc(m["result_text"])} • '
            f'النقاط: {_fmt_num(m["points1"])} - {_fmt_num(m["points2"])}</div>'
            "</div>"
        )
    return _design_document(round_name, "مواجهات المسابقة", "\n".join(cards))


def finalize_html(html, export_filename):
    """Make Gemini's HTML self-contained and add the 'Export as JPEG' button.

    Ensures a `<div id="poster">` wrapper exists, then injects html2canvas and
    a floating button that downloads the poster as a JPEG.
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


def _export_tool_html(filename):
    jname = json.dumps(filename.rsplit(".", 1)[0] + ".jpeg")
    # html-to-image renders via SVG foreignObject, which keeps native text
    # shaping (correct Arabic). html2canvas can break Arabic letter joining.
    fonts_link = (
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        "family=Cairo:wght@400;600;700;900&family=Tajawal:wght@400;500;700;800"
        '&display=swap">'
    )
    portrait_css = (
        "<style>"
        "#poster{box-sizing:border-box!important;max-width:1080px!important;"
        "width:auto!important;min-height:1920px!important;margin:0 auto!important;}"
        "#poster,#poster *{font-family:'Cairo','Tajawal','Noto Naskh Arabic',"
        "'Amiri','Segoe UI',Tahoma,sans-serif!important;}"
        "html,body{margin:0!important;padding:0!important;background:#ffffff;}"
        "</style>"
    )
    return (
        fonts_link
        + portrait_css
        + '<div style="position:fixed;top:12px;right:12px;z-index:99999;direction:ltr;">'
        '<button id="export-jpeg" style="background:#1f77b4;color:#fff;border:none;'
        'padding:10px 16px;border-radius:8px;font-size:14px;cursor:pointer;'
        'font-family:Arial,sans-serif;box-shadow:0 2px 6px rgba(0,0,0,.3);">'
        'Export as JPEG</button>'
        "</div>"
        '<script src="https://cdn.jsdelivr.net/npm/html-to-image@1.11.11/dist/html-to-image.js"></script>'
        "<script>"
        'document.addEventListener("DOMContentLoaded",function(){'
        'var b=document.getElementById("export-jpeg");'
        'if(b){b.addEventListener("click",function(){'
        'var el=document.getElementById("poster")||document.body;'
        'if(typeof htmlToImage==="undefined"){alert("Export library failed to load. Check your internet connection.");return;}'
        'document.fonts.ready.then(function(){'
        'return htmlToImage.toJpeg(el,{pixelRatio:2,backgroundColor:"#ffffff",quality:0.95});'
        "}).then(function(url){"
        'var a=document.createElement("a");'
        'a.download=' + jname + ";"
        'a.href=url;document.body.appendChild(a);a.click();'
        "}).catch(function(e){alert('Export failed: '+e.message);});"
        "});});}"
        "});"
        "</script>"
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
