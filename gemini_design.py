"""Generate poster images from Championship data using the Gemini API.

Requires a GEMINI_API_KEY secret (top-level or under a `secrets` table) and
the `google-genai` package (added to requirements.txt). Uses the
`gemini-2.5-flash-image` model which returns an inline image that the app can
display and let the user download.

Also provides a free-tier fallback: `gemini-2.5-flash` (text) writes a
self-contained, styled HTML poster whose page includes a button to export the
design as JPEG (via html2canvas). Text generation works on the free tier, so
this works even when image generation requires billing.
"""

import re
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


def generate_html(prompt):
    """Ask the free-tier text model to write a standalone styled HTML poster."""
    key = gemini_key()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to Streamlit secrets to enable "
            "AI design generation."
        )
    if not _HAS_GENAI:
        raise RuntimeError(
            "google-genai is not installed. Add it to requirements.txt and "
            "redeploy."
        )

    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model=gemini_text_model(),
        contents=prompt,
    )
    text = response.text or ""
    m = re.search(r"```(?:html)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    return text


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
    portrait_css = (
        "<style>"
        "#poster{box-sizing:border-box!important;max-width:1080px!important;"
        "width:auto!important;margin:0 auto!important;min-height:1600px!important;}"
        "html,body{margin:0!important;padding:0!important;}"
        "</style>"
    )
    return (
        portrait_css
        + '<div style="position:fixed;top:12px;right:12px;z-index:99999;direction:ltr;">'
        '<button id="export-jpeg" style="background:#1f77b4;color:#fff;border:none;'
        'padding:10px 16px;border-radius:8px;font-size:14px;cursor:pointer;'
        'font-family:Arial,sans-serif;box-shadow:0 2px 6px rgba(0,0,0,.3);">'
        'Export as JPEG</button>'
        "</div>"
        '<script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>'
        "<script>"
        'document.addEventListener("DOMContentLoaded",function(){'
        'var b=document.getElementById("export-jpeg");'
        'if(b){b.addEventListener("click",function(){'
        'var el=document.getElementById("poster")||document.body;'
        'html2canvas(el,{scale:2,backgroundColor:"#ffffff"}).then(function(c){'
        'var a=document.createElement("a");'
        'a.download=' + jname + ";"
        'a.href=c.toDataURL("image/jpeg",0.95);'
        'document.body.appendChild(a);a.click();'
        "});});}"
        "});"
        "</script>"
    )


def _table_text(df):
    headers = [str(c) for c in df.columns]
    lines = [" | ".join(headers)]
    for _, row in df.iterrows():
        lines.append(" | ".join("" if v is None else str(v) for v in row.tolist()))
    return "\n".join(lines)


def _html_prompt(title, table):
    return f"""أنشئ صفحة HTML كاملة ومستقلة (بدون أي مكتبات خارجية) لتصميم بوستر عمودي فاخر لمسابقة تحفيظ القرآن الكريم، مصمم للشاشات الطويلة (مثل منشورات السوشيال ميديا).

المتطلبات:
- كل التنسيقات داخل وسم <style> داخل الصفحة. يُسمح فقط بخطوط Google Fonts عبر <link> إن أردت.
- التصميم باللغة العربية ومن اليمين إلى اليسار (dir="rtl").
- التصميم عمودي (Portrait): العرض أضيق بكثير من الارتفاع، بنسبة تقارب 9:16 (مثال: 1080×1920).
- اجعل محتوى التصميم كاملاً داخل وسم <div id="poster">...</div>، واجعله بعرض لا يزيد عن 1080px وبمركز الصفحة (margin: auto)، وبارتفاع لا يقل عن ضعف العرض تقريباً.
- رتّب المحتوى عمودياً من الأعلى إلى الأسفل: العنوان الكبير في الأعلى، ثم البطاقات/الجدول في المنتصف، ثم الخاتمة أو الشعار في الأسفل، مع تباعد عمودي مريح بين الأقسام.
- استخدم جماليات إسلامية أنيقة (أخضر وذهبي، زخارف هندسية خفيفة، تدرجات ناعمة، بطاقات حديثة).
- اعرض البيانات التالية بدقة وبشكل واضح (جدول أو بطاقات أنيقة) مع الحفاظ على الأسماء والأرقام كما هي تماماً.
- لا تضع أي نص أو عناصر خارج <div id="poster"> (لا شريط أدوات، لا أزرار، لا هوامش إضافية).
- أخرج كود HTML فقط بدون أي تعليقات أو أسطر إضافية.

عنوان البوستر: "{title}"

البيانات:
{table}
"""


def build_leaderboard_html_prompt(df, title="لوحة المتصدرين"):
    return _html_prompt(title, _table_text(df))


def build_matches_html_prompt(matches, round_name):
    lines = []
    for m in matches:
        lines.append(
            f"{m['s1']} ضد {m['s2']} | صفحات: {m['pages1']:.1f} مقابل "
            f"{m['pages2']:.1f} | النتيجة: {m['result_text']} | نقاط: "
            f"{m['points1']} مقابل {m['points2']}"
        )
    return _html_prompt(round_name, "\n".join(lines))


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
