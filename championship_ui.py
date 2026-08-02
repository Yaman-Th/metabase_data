import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import requests
import json
import os
import io
from datetime import datetime, date, timedelta
import championship as ch
import dashboard
from config import METABASE_DATASETS, TEMP_DATA_DIR, GOOGLE_SHEET_ID, GOOGLE_SHEET_RANGE, CH_DB_SHEET_ID
from sheets_client import send_to_sheet
from gemini_design import (
    gemini_enabled,
    generate_poster,
    generate_html,
    finalize_html,
    build_leaderboard_prompt,
    build_matches_prompt,
    build_leaderboard_html_prompt,
    build_matches_html_prompt,
    friendly_error,
)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    _HAS_MPL = True
except Exception:
    _HAS_MPL = False

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    _HAS_PLOTLY = True
except Exception:
    _HAS_PLOTLY = False

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    _HAS_ARABIC_SHAPE = True
except Exception:
    _HAS_ARABIC_SHAPE = False

_ARABIC_FP = None
_INITED_MPL = False
_MPL_NATIVE_SHAPING = None

# Font used for Plotly pie charts. On Linux (Streamlit Cloud, fonts-noto package)
# Noto Naskh Arabic is available; on Windows use Arial which includes Arabic glyphs.
_PIE_FONT = "Noto Naskh Arabic" if (os.name == "posix") else "Arial"

_ARABIC_RANGES = (
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0xFB50, 0xFDFF),  # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),  # Arabic Presentation Forms-B
)


def _init_mpl_font():
    global _ARABIC_FP, _INITED_MPL
    if _INITED_MPL or not _HAS_MPL:
        return
    _INITED_MPL = True

    font_dir = os.path.join(os.path.dirname(__file__), "fonts")

    # Amiri has Arabic + Latin glyphs, but we keep the global default as a
    # Latin font (DejaVu Sans). Amiri is appended to the sans-serif chain so
    # Arabic glyphs still fall back correctly, while per-element
    # fontproperties handle Arabic cells explicitly.
    amiri_path = os.path.join(font_dir, "Amiri-Regular.ttf")
    if os.path.exists(amiri_path):
        fm.fontManager.addfont(amiri_path)
        amiri_family = fm.FontProperties(fname=amiri_path).get_name()
        _ARABIC_FP = fm.FontProperties(family=amiri_family)
        families = list(plt.rcParams.get("font.sans-serif", []))
        if amiri_family not in families:
            families.append(amiri_family)
        plt.rcParams["font.sans-serif"] = families
        plt.rcParams["font.family"] = "sans-serif"
        return

    # Fallback: Droid Naskh is Arabic-only — keep fallback chain for Latin
    droid_path = os.path.join(font_dir, "DroidNaskh-Bold.ttf")
    if os.path.exists(droid_path):
        fm.fontManager.addfont(droid_path)
        _ARABIC_FP = fm.FontProperties(fname=droid_path)
        families = list(plt.rcParams.get("font.sans-serif", []))
        fp_name = _ARABIC_FP.get_name()
        if fp_name not in families:
            families.insert(0, fp_name)
        plt.rcParams["font.sans-serif"] = families
        plt.rcParams["font.family"] = "sans-serif"


def _has_arabic(text):
    if not text:
        return False
    for ch in str(text):
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _ARABIC_RANGES):
            return True
    return False


def _apply_arabic_fonts(table):
    if _ARABIC_FP is None:
        return
    for key, cell in table.get_celld().items():
        txt = cell.get_text()
        if _has_arabic(txt.get_text()):
            fp = txt.get_fontproperties().copy()
            fp.set_family(_ARABIC_FP.get_family())
            txt.set_fontproperties(fp)


def _matplotlib_native_shaping():
    """Whether matplotlib applies complex text layout (bidi + Arabic shaping)
    itself via libraqm. Since matplotlib 3.11 compiles libraqm/HarfBuzz into
    the extension, any string is shaped natively, so pre-shaped Arabic would
    be processed twice (resulting in mirrored letters). In that case we must
    pass the raw Arabic text and let matplotlib shape it.
    """
    global _MPL_NATIVE_SHAPING
    if _MPL_NATIVE_SHAPING is not None:
        return _MPL_NATIVE_SHAPING
    result = False
    try:
        import matplotlib.ft2font as _ft2
        v = getattr(_ft2, "__libraqm_version__", "")
        result = bool(v) or hasattr(_ft2.FT2Font, "_layout")
    except Exception:
        result = False
    _MPL_NATIVE_SHAPING = result
    return result


def _shape_arabic(text):
    if not _HAS_ARABIC_SHAPE or _matplotlib_native_shaping():
        return str(text)
    try:
        reshaped = arabic_reshaper.reshape(str(text))
        return get_display(reshaped)
    except Exception:
        return str(text)


def _get_arabic_font():
    _init_mpl_font()
    return _ARABIC_FP


_init_mpl_font()

LB_HEADERS = {
    "#": "#",
    "Name": "الاسم",
    "Points": "النقاط",
    "Jadeed": "جديد",
    "Tikrar": "تكرار",
    "Total": "المجموع",
    "Days Met": "أيام الإنجاز",
    "W": "فوز",
    "D": "تعادل",
    "L": "خسارة",
    "Student 1": "الطالب 1",
    "Student 2": "الطالب 2",
    "Pages S1": "صفحات 1",
    "Pages S2": "صفحات 2",
    "Result": "النتيجة",
    "Pts S1": "نقاط 1",
    "Pts S2": "نقاط 2",
}


def _map_headers(cols):
    return [LB_HEADERS.get(c, c) for c in cols]


def _fig_to_jpeg(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="jpeg", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _target_pie_fig(achieved, target, title, color):
    if not _HAS_PLOTLY:
        return None
    achieved_c = max(min(achieved, target), 0.0)
    remaining = max(target - achieved_c, 0.0)
    pct = (achieved / target * 100.0) if target else 0.0

    fig = go.Figure(go.Pie(
        labels=[f"تحقق {achieved_c:,.0f}", f"متبقٍ {remaining:,.0f}"],
        values=[achieved_c, remaining],
        hole=0.45,
        marker=dict(colors=[color, "#d9d9d9"]),
        textinfo="label+percent",
        textfont=dict(size=13, family=_PIE_FONT),
        insidetextorientation="horizontal",
        hovertemplate="%{label}: %{value:,.1f}<extra></extra>",
    ))
    fig.update_layout(
        title=f"{title}: {achieved_c:,.0f} / {target:,.0f} ({pct:.0f}%)",
        title_font=dict(size=15, family=_PIE_FONT),
        font=dict(family=_PIE_FONT),
        height=360,
        margin=dict(l=10, r=10, t=60, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


def _combined_pie_fig(fig1, fig2):
    t1 = fig1.layout.title.text if fig1.layout.title else ""
    t2 = fig2.layout.title.text if fig2.layout.title else ""
    fig = make_subplots(
        rows=1, cols=2,
        specs=[[{"type": "pie"}, {"type": "pie"}]],
        subplot_titles=[t1, t2],
    )
    fig.add_trace(fig1.data[0], row=1, col=1)
    fig.add_trace(fig2.data[0], row=1, col=2)
    fig.update_layout(
        font=dict(family=_PIE_FONT),
        height=400,
        margin=dict(l=10, r=10, t=60, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    fig.update_annotations(font=dict(size=13, family=_PIE_FONT))
    return fig


def _fig_to_png_bytes(fig, width=920, scale=2):
    try:
        height = int(fig.layout.height or 400)
        return fig.to_image(format="png", width=width, height=height, scale=scale)
    except Exception:
        return None


def _pie_export_controls(fig, filename, prefix):
    if not _HAS_PLOTLY:
        return
    if st.button("Export PNG", key=f"{prefix}_gen"):
        png = _fig_to_png_bytes(fig)
        if png:
            st.session_state[f"{prefix}_png"] = png
        else:
            st.session_state.pop(f"{prefix}_png", None)
            st.warning("PNG export is unavailable here (kaleido not installed). Use the chart's camera button.")
    png = st.session_state.get(f"{prefix}_png")
    if png:
        st.download_button("Download PNG", data=png, file_name=filename, mime="image/png", key=f"{prefix}_dl")


def _render_poster(key_prefix, build_prompt, default_filename, label="AI Poster"):
    st.markdown(f"**{label}**")
    if not gemini_enabled():
        st.caption("Set `GEMINI_API_KEY` in Streamlit secrets to enable AI poster generation.")
        return
    img_key = f"{key_prefix}_img"
    mime_key = f"{key_prefix}_mime"
    if st.button("Generate poster (Gemini)", key=f"{key_prefix}_btn"):
        with st.spinner("Gemini is designing the poster..."):
            try:
                img_bytes, mime = generate_poster(build_prompt())
                if img_bytes:
                    st.session_state[img_key] = img_bytes
                    st.session_state[mime_key] = mime or "image/png"
                else:
                    st.error("Gemini returned no image. Try again.")
            except Exception as e:
                msg = friendly_error(e)
                st.error(msg if msg else f"Poster generation failed: {e}")
    img = st.session_state.get(img_key)
    if img:
        st.image(img)
        mime = st.session_state.get(mime_key, "image/png")
        ext = {"image/png": "png", "image/jpeg": "jpg"}.get(mime, "png")
        fname = default_filename.rsplit(".", 1)[0] + "." + ext
        st.download_button(
            "Download poster",
            data=img,
            file_name=fname,
            mime=mime,
            key=f"{key_prefix}_dl",
        )


def _render_html_design(key_prefix, build_prompt, default_filename, label="HTML Design (Gemini)"):
    st.markdown(f"**{label}**")
    if not gemini_enabled():
        st.caption("Set `GEMINI_API_KEY` in Streamlit secrets to enable AI design generation.")
        return
    html_key = f"{key_prefix}_html"
    if st.button("Generate HTML design (Gemini)", key=f"{key_prefix}_html_btn"):
        with st.spinner("Gemini is writing the design..."):
            try:
                raw = generate_html(build_prompt())
                if raw and raw.strip():
                    st.session_state[html_key] = finalize_html(raw, default_filename)
                else:
                    st.error("Gemini returned no content. Try again.")
            except Exception as e:
                msg = friendly_error(e)
                st.error(msg if msg else f"Design generation failed: {e}")
    html = st.session_state.get(html_key)
    if html:
        components.html(html, height=900, scrolling=True)
        col_d, col_c = st.columns(2)
        col_d.download_button(
            "Download HTML",
            data=html.encode("utf-8"),
            file_name=default_filename,
            mime="text/html",
            key=f"{key_prefix}_html_dl",
        )
        col_c.caption("Open the HTML in a browser, then click **Export as JPEG** to save the design as an image.")


def _leaderboard_to_image(df, title="Leaderboard"):
    if not _HAS_MPL:
        return None
    _init_mpl_font()
    data = [[_shape_arabic(str(v)) for v in row] for row in df.values]
    cols = [_shape_arabic(str(c)) for c in df.columns.tolist()]

    # RTL reading direction: render columns right-to-left
    data = [list(reversed(row)) for row in data]
    cols = list(reversed(cols))

    fig, ax = plt.subplots(figsize=(10, 0.5 + 0.5 * len(data)))
    ax.axis("off")

    table = ax.table(cellText=data, colLabels=cols, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.5)

    for i in range(len(cols)):
        table[0, i].set_facecolor("#1f77b4")
        table[0, i].set_text_props(color="white", fontweight="bold")
    for i in range(1, len(data) + 1):
        bg = "#f5f5f5" if i % 2 == 0 else "white"
        for j in range(len(cols)):
            table[i, j].set_facecolor(bg)

    for key, cell in table.get_celld().items():
        cell.set_edgecolor("#cccccc")
        cell.set_linewidth(0.5)

    _apply_arabic_fonts(table)
    ax.set_title(_shape_arabic(title), fontsize=16, fontweight="bold", pad=20, color="#1f77b4")
    return _fig_to_jpeg(fig)


def _matches_to_image(matches, round_name):
    if not _HAS_MPL or not matches:
        return None
    _init_mpl_font()
    rows = []
    for m in matches:
        rows.append([
            _shape_arabic(m["s1"]), _shape_arabic(m["s2"]),
            f"{m['pages1']:.0f}", f"{m['pages2']:.0f}",
            _shape_arabic(m["result_text"]), f"{m['points1']}", f"{m['points2']}",
        ])
    cols = _map_headers(["Student 1", "Student 2", "Pages S1", "Pages S2", "Result", "Pts S1", "Pts S2"])
    cols = [_shape_arabic(c) for c in cols]

    # RTL reading direction: render columns right-to-left
    rows = [list(reversed(r)) for r in rows]
    cols = list(reversed(cols))

    fig, ax = plt.subplots(figsize=(10, 0.5 + 0.5 * len(rows)))
    ax.axis("off")

    table = ax.table(cellText=rows, colLabels=cols, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.5)

    for i in range(len(cols)):
        table[0, i].set_facecolor("#2ca02c")
        table[0, i].set_text_props(color="white", fontweight="bold")
    for i in range(1, len(rows) + 1):
        bg = "#f5f5f5" if i % 2 == 0 else "white"
        for j in range(len(cols)):
            table[i, j].set_facecolor(bg)

    for key, cell in table.get_celld().items():
        cell.set_edgecolor("#cccccc")
        cell.set_linewidth(0.5)

    _apply_arabic_fonts(table)
    ax.set_title(_shape_arabic(f"{round_name} - Match Results"), fontsize=16, fontweight="bold", pad=20, color="#2ca02c")
    return _fig_to_jpeg(fig)


def _fetch_dataset(url, label):
    cpath = os.path.join(TEMP_DATA_DIR, f"ch_{label}.json")
    if os.path.exists(cpath):
        try:
            with open(cpath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            os.remove(cpath)
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    with open(cpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data


def _clear_metabase_cache():
    """Drop cached Metabase dataset files so the next fetch is fresh."""
    for f in os.listdir(TEMP_DATA_DIR):
        if f.startswith("ch_") and f.endswith(".json"):
            try:
                os.remove(os.path.join(TEMP_DATA_DIR, f))
            except OSError:
                pass


def _extract_value(df, student_name, entry_date, page_patterns=None):
    if df is None or df.empty or not student_name:
        return None

    cols = list(df.columns)
    student_col = None
    for c in cols:
        cl = c.lower()
        if "student" in cl and cl.endswith("name"):
            student_col = c
            break
    if not student_col:
        for c in cols:
            cl = c.lower().strip()
            if cl == "name" and "reciter" not in c:
                student_col = c
                break
    if not student_col:
        return None

    date_col = None
    for c in cols:
        cl = c.lower()
        if "date" in cl or "day" in cl:
            date_col = c
            break
    if not date_col:
        return None

    day_str = entry_date.strftime("%Y-%m-%d") if hasattr(entry_date, "strftime") else str(entry_date)[:10]
    mask = df[student_col].astype(str).str.strip() == student_name
    mask &= df[date_col].astype(str).str[:10] == day_str
    row = df[mask]

    if row.empty:
        return None

    total = 0.0
    for c in cols:
        if not pd.api.types.is_numeric_dtype(df[c]):
            continue
        if page_patterns:
            cl = c.lower().replace(" ", "")
            if not any(p in cl for p in page_patterns):
                continue
        total += float(row[c].sum())
    return total


def _fetch_from_metabase(student_name, entry_date):
    if not student_name:
        return None, None
    jadeed = tikrar = None
    for label, url in METABASE_DATASETS.items():
        raw = _fetch_dataset(url, label)
        df = pd.DataFrame(raw)
        ll = label.lower()
        if any(x in ll for x in ["jadeed", "جديد"]):
            patterns = ["sumofnewpages", "newpages", "new", "جديد"]
        else:
            patterns = ["sumofoldpages", "oldpages", "old", "تكرار", "tikrar"]
        val = _extract_value(df, student_name, entry_date, patterns)
        if any(x in ll for x in ["jadeed", "جديد"]):
            jadeed = val
        else:
            tikrar = val
    if jadeed is None and tikrar is None:
        return None, None
    return (jadeed or 0.0), (tikrar or 0.0)


def render():
    st.title("Championship")

    if "ch_storage_error" in st.session_state:
        st.warning(
            "Could not sync to Google Sheets, so changes are only saved "
            f"locally (will be lost on app restart): {st.session_state['ch_storage_error']}"
        )
        del st.session_state["ch_storage_error"]

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Students", "Rounds & Matches", "Daily Entry", "Leaderboard", "Dashboard", "Export"
    ])

    all_students = ch.get_students()
    all_rounds = ch.get_rounds()

    # =========================================================
    # TAB 1: STUDENTS
    # =========================================================
    with tab1:
        st.subheader("Manage Students")

        col1, col2 = st.columns([2, 1])
        with col1:
            new_name = st.text_input("Student name", key="ch_st_name")
        with col2:
            if st.button("Add Student", width='stretch') and new_name.strip():
                if ch.add_student(new_name.strip()):
                    st.rerun()
                else:
                    st.warning("Student already exists")

        if all_students:
            st.markdown("**Default homework targets** (pre-fill for daily entry)")
            for s in all_students:
                hw_j, hw_t = ch.get_student_homework_defaults(s["id"], all_students)
                cols = st.columns([2, 1, 1, 1])
                cols[0].write(s["name"])
                nj = cols[1].number_input("Jadeed HW", value=float(hw_j), min_value=0.0, step=0.5, key=f"hwj_{s['id']}", label_visibility="collapsed")
                nt = cols[2].number_input("Tikrar HW", value=float(hw_t), min_value=0.0, step=0.5, key=f"hwt_{s['id']}", label_visibility="collapsed")
                if cols[3].button("Delete", key=f"del_{s['id']}"):
                    ch.delete_student(s["id"])
                    st.rerun()
                if nj != hw_j or nt != hw_t:
                    ch.update_student_homework_defaults(s["id"], nj, nt)

            st.divider()
            df_s = pd.DataFrame(all_students)
            st.dataframe(df_s[["id", "name"]], width='stretch', hide_index=True)
        else:
            st.info("No students yet. Add some above.")

    # =========================================================
    # TAB 2: ROUNDS & MATCHES
    # =========================================================
    with tab2:
        st.subheader("Rounds")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            rname = st.text_input("Round name", key="ch_rname", placeholder="e.g. Round 1")
        with col2:
            rs = st.date_input("Start", key="ch_rs")
        with col3:
            re = st.date_input("End", key="ch_re")
        with col4:
            stage = st.selectbox("Stage", ["group", "quarter", "semi", "final"], key="ch_stage")

        if st.button("Add Round") and rname.strip():
            ch.add_round(rname.strip(), rs, re, stage)
            st.rerun()

        if all_rounds:
            for rnd in all_rounds:
                with st.expander(f"{rnd['name']} ({rnd['start_date']} → {rnd['end_date']}) - {rnd['stage']}"):
                    col_a, col_b = st.columns([1, 4])
                    col_a.button("Delete Round", key=f"del_rnd_{rnd['id']}", on_click=lambda rid=rnd["id"]: ch.delete_round(rid))
                    if col_b.button("Auto-fetch ALL matches from Metabase", key=f"fetch_all_{rnd['id']}"):
                        _batch_fetch_round(rnd)
                        st.rerun()

                    st.subheader("Matches")
                    matches = [m for m in ch.get_matches() if m["round_id"] == rnd["id"]]

                    if matches:
                        for m in matches:
                            s1 = ch.get_student_name(m["student1_id"], all_students)
                            s2 = ch.get_student_name(m["student2_id"], all_students)
                            res = ch.compute_match_result(m, rnd)

                            cols = st.columns([1.5, 1, 1, 0.5])
                            cols[0].write(f"**{s1}** vs **{s2}**")

                            if res["result"] == "win1":
                                rt = f"🏆 {s1} wins"
                            elif res["result"] == "win2":
                                rt = f"🏆 {s2} wins"
                            else:
                                rt = "🤝 Draw"
                            cols[1].write(f"Pages: {res['total_pages1']:.1f} / {res['total_pages2']:.1f}")
                            cols[2].write(f"{rt} ({res['points1']}p / {res['points2']}p)")
                            cols[3].button("🗑", key=f"del_m_{m['id']}", on_click=lambda mid=m["id"]: ch.delete_match(mid))
                            st.caption(
                                f"Days both met: {res['daily_days1']} / {res['daily_days2']}"
                            )
                            st.divider()
                        if matches:
                            _matches_jpeg_args = []
                            for m in matches:
                                s1 = ch.get_student_name(m["student1_id"], all_students)
                                s2 = ch.get_student_name(m["student2_id"], all_students)
                                res = ch.compute_match_result(m, rnd)
                                if res["result"] == "win1":
                                    rt = f"{s1} wins"
                                elif res["result"] == "win2":
                                    rt = f"{s2} wins"
                                else:
                                    rt = "Draw"
                                _matches_jpeg_args.append({
                                    "s1": s1, "s2": s2,
                                    "pages1": res["total_pages1"], "pages2": res["total_pages2"],
                                    "result_text": rt,
                                    "points1": res["points1"], "points2": res["points2"],
                                })
                            jpeg_m = _matches_to_image(_matches_jpeg_args, rnd["name"])
                            if jpeg_m:
                                st.download_button(
                                    "Download Matches as JPEG",
                                    data=jpeg_m,
                                    file_name=f"{rnd['name']}_matches.jpeg",
                                    mime="image/jpeg",
                                    key=f"jpeg_m_{rnd['id']}",
                                )
                            _render_poster(
                                key_prefix=f"poster_rnd_{rnd['id']}",
                                build_prompt=lambda args=_matches_jpeg_args, rr=rnd: build_matches_prompt(args, rr["name"]),
                                default_filename=f"{rnd['name']}_poster.png",
                                label="AI Poster (Gemini)",
                            )
                            _render_html_design(
                                key_prefix=f"html_rnd_{rnd['id']}",
                                build_prompt=lambda args=_matches_jpeg_args, rr=rnd: build_matches_html_prompt(args, rr["name"]),
                                default_filename=f"{rnd['name']}_design.html",
                                label="HTML Design (free tier)",
                            )
                    else:
                        st.info("No matches yet.")

                    st.subheader("Add Match")
                    if len(all_students) >= 2:
                        col_a, col_b = st.columns(2)
                        s1_id = col_a.selectbox(
                            "Student 1",
                            options=[(s["id"], s["name"]) for s in all_students],
                            format_func=lambda x: x[1],
                            key=f"m_s1_{rnd['id']}",
                        )
                        s2_id = col_b.selectbox(
                            "Student 2",
                            options=[(s["id"], s["name"]) for s in all_students],
                            format_func=lambda x: x[1],
                            key=f"m_s2_{rnd['id']}",
                        )
                        if st.button("Add Match", key=f"add_m_{rnd['id']}"):
                            if s1_id[0] == s2_id[0]:
                                st.error("Cannot match a student with themselves")
                            else:
                                ch.add_match(rnd["id"], s1_id[0], s2_id[0])
                                st.rerun()
                    else:
                        st.warning("Add at least 2 students first")
        else:
            st.info("No rounds yet")

    # =========================================================
    # TAB 3: DAILY ENTRY
    # =========================================================
    with tab3:
        st.subheader("Daily Homework Entry")

        col_a, col_b = st.columns(2)
        with col_a:
            entry_date = st.date_input("Date", value=date.today())
        with col_b:
            matches_all = ch.get_matches()
            if matches_all:
                match_opts = []
                for m in matches_all:
                    s1 = ch.get_student_name(m["student1_id"], all_students)
                    s2 = ch.get_student_name(m["student2_id"], all_students)
                    match_opts.append((m["id"], f"{s1} vs {s2}"))
                selected_match = st.selectbox(
                    "Match",
                    options=match_opts,
                    format_func=lambda x: x[1],
                    key="daily_match",
                )
            else:
                st.warning("No matches created yet")
                selected_match = None

        if selected_match:
            mid = selected_match[0]
            match_obj = next((m for m in matches_all if m["id"] == mid), None)
            if match_obj:
                for label, sid in [("Student 1", match_obj["student1_id"]), ("Student 2", match_obj["student2_id"])]:
                    sname = ch.get_student_name(sid, all_students)
                    st.markdown(f"**{label}: {sname}**")

                    existing = None
                    for d in ch.get_daily():
                        if d["match_id"] == mid and d["student_id"] == sid and d["date"] == str(entry_date):
                            existing = d
                            break

                    existing_hw = None
                    for h in ch.get_homework():
                        if h["match_id"] == mid and h["student_id"] == sid and h["date"] == str(entry_date):
                            existing_hw = h
                            break

                    if existing_hw:
                        def_hw_j = existing_hw.get("homework_jadeed", 0.0)
                        def_hw_t = existing_hw.get("homework_tikrar", 0.0)
                    else:
                        def_hw_j, def_hw_t = ch.get_student_homework_defaults(sid, all_students)

                    col_j, col_t, col_hj, col_ht, col_s, col_del = st.columns([1, 1, 1, 1, 1, 1])
                    with col_j:
                        jadeed = col_j.number_input("Jadeed", value=float(existing["jadeed"]) if existing else 0.0, min_value=0.0, key=f"j_{mid}_{sid}_{entry_date}")
                    with col_t:
                        tikrar = col_t.number_input("Tikrar", value=float(existing["tikrar"]) if existing else 0.0, min_value=0.0, key=f"t_{mid}_{sid}_{entry_date}")
                    with col_hj:
                        hw_j = col_hj.number_input("Jadeed HW", value=def_hw_j, min_value=0.0, key=f"hwj_{mid}_{sid}_{entry_date}")
                    with col_ht:
                        hw_t = col_ht.number_input("Tikrar HW", value=def_hw_t, min_value=0.0, key=f"hwt_{mid}_{sid}_{entry_date}")
                    with col_s:
                        if st.button("Save", key=f"sv_{mid}_{sid}_{entry_date}"):
                            ch.upsert_daily(mid, sid, entry_date, jadeed, tikrar)
                            ch.upsert_homework(mid, sid, entry_date, hw_j, hw_t)
                            st.rerun()
                    with col_del:
                        if existing and st.button("Clear", key=f"cl_{mid}_{sid}_{entry_date}"):
                            ch.delete_daily(mid, sid, entry_date)
                            ch.delete_homework(mid, sid, entry_date)
                            st.rerun()

        st.divider()
        st.subheader("Recent Records")

        all_daily = ch.get_daily()
        all_hw = ch.get_homework()
        hw_map = {(h["match_id"], h["student_id"], h["date"]): h for h in all_hw}

        if all_daily:
            recent = sorted(all_daily, key=lambda x: x["date"], reverse=True)[:50]
            rows = []
            for d in recent:
                sname = ch.get_student_name(d["student_id"], all_students)
                h = hw_map.get((d["match_id"], d["student_id"], d["date"]))
                if h:
                    hw_j = h.get("homework_jadeed", 0)
                    hw_t = h.get("homework_tikrar", 0)
                else:
                    hw_j = d.get("homework_jadeed", 0)
                    hw_t = d.get("homework_tikrar", 0)
                j = d.get("jadeed", 0)
                t = d.get("tikrar", 0)
                ok = j >= hw_j and t >= hw_t
                rows.append({
                    "Date": d["date"],
                    "Student": sname,
                    "Jadeed": j,
                    "Tikrar": t,
                    "Jadeed HW": f"{j}/{hw_j}",
                    "Tikrar HW": f"{t}/{hw_t}",
                    "Done": "✅" if ok else "❌",
                })
            st.markdown("**Daily pages (fetched from Metabase / entered)**")
            st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
        else:
            st.info("No daily records yet")

        if all_hw:
            recent_hw = sorted(all_hw, key=lambda x: x["date"], reverse=True)[:50]
            rows_hw = []
            for h in recent_hw:
                sname = ch.get_student_name(h["student_id"], all_students)
                rows_hw.append({
                    "Date": h["date"],
                    "Student": sname,
                    "Jadeed HW": h.get("homework_jadeed", 0),
                    "Tikrar HW": h.get("homework_tikrar", 0),
                })
            st.markdown("**Homework targets (manually entered)**")
            st.dataframe(pd.DataFrame(rows_hw), width='stretch', hide_index=True)
        else:
            st.info("No homework records yet")

    # =========================================================
    # TAB 4: LEADERBOARD
    # =========================================================
    with tab4:
        st.subheader("Leaderboard")

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filter_round = st.selectbox(
                "Filter by round",
                options=[("all", "All Rounds")] + [(r["id"], r["name"]) for r in all_rounds],
                format_func=lambda x: x[1],
            )
        with col_f2:
            filter_stage = st.selectbox(
                "Filter by stage",
                options=["all", "group", "quarter", "semi", "final"],
            )

        round_id = filter_round[0] if filter_round[0] != "all" else None
        stage_filter = filter_stage if filter_stage != "all" else None
        lb = ch.get_leaderboard(round_id=round_id, stage=stage_filter)

        if lb:
            df = pd.DataFrame(lb)
            df["rank"] = range(1, len(df) + 1)
            df = df[["rank", "name", "points", "jadeed", "tikrar", "total_pages", "daily_days", "wins", "draws", "losses"]]
            eng_cols = ["#", "Name", "Points", "Jadeed", "Tikrar", "Total", "Days Met", "W", "D", "L"]
            df.columns = _map_headers(eng_cols)

            st.dataframe(df, width='stretch', hide_index=True)
            csv = df.to_csv(index=False).encode("utf-8")
            col_j1, col_j2 = st.columns(2)
            col_j1.download_button("Download as CSV", data=csv, file_name="leaderboard.csv", mime="text/csv")
            jpeg = _leaderboard_to_image(df, title="Leaderboard")
            if jpeg:
                col_j2.download_button("Download as JPEG", data=jpeg, file_name="leaderboard.jpeg", mime="image/jpeg")
            else:
                col_j2.info("matplotlib not available")

            st.divider()
            _render_poster(
                key_prefix="lb_poster",
                build_prompt=lambda: build_leaderboard_prompt(df, title="لوحة المتصدرين"),
                default_filename="leaderboard_poster.png",
                label="AI Poster (Gemini)",
            )
            _render_html_design(
                key_prefix="lb_html",
                build_prompt=lambda: build_leaderboard_html_prompt(df, title="لوحة المتصدرين"),
                default_filename="leaderboard_design.html",
                label="HTML Design (free tier)",
            )
        else:
            st.info("No data yet")

    # =========================================================
    # TAB 5: DASHBOARD
    # =========================================================
    with tab5:
        st.subheader("Dashboard")
        st.caption("Statistics from Metabase between two dates (both dates included).")

        col_d1, col_d2 = st.columns(2)
        with col_d1:
            d_from = st.date_input("From", value=dashboard.TARGET_START, key="dash_from")
        with col_d2:
            d_to = st.date_input("To", value=dashboard.TARGET_END, key="dash_to")

        if st.button("Compute Statistics", key="dash_compute", type="primary"):
            with st.spinner("Fetching Metabase data..."):
                try:
                    dashboard.clear_cache()
                    student_names = [s["name"] for s in all_students] if all_students else None
                    st.session_state["dash_stats"] = dashboard.compute_stats(d_from, d_to, student_names=student_names)
                    st.session_state["dash_period"] = f"{d_from} → {d_to}"
                    st.session_state["dash_students"] = len(student_names or [])
                except Exception as e:
                    st.error(f"Failed to load statistics: {e}")
                    st.session_state.pop("dash_stats", None)

        stats = st.session_state.get("dash_stats")
        if not stats:
            st.info("Choose a date range and click **Compute Statistics**.")
        else:
            period = st.session_state.get("dash_period", "")
            n_students = st.session_state.get("dash_students", 0)
            if period:
                st.markdown(f"**Period:** {period}  |  **Students:** {n_students}")

            st.divider()
            st.markdown("**1) Daily totals**")
            df_daily = pd.DataFrame(stats["daily"])
            if df_daily.empty:
                st.info("No data in this period.")
            else:
                df_daily = df_daily.rename(columns={
                    "date": "التاريخ", "tikrar": "التكرار", "jadeed": "الجديد", "total": "الإجمالي",
                })
                st.dataframe(df_daily, width='stretch', hide_index=True)
                st.download_button(
                    "Download daily CSV", data=df_daily.to_csv(index=False).encode("utf-8"),
                    file_name="daily_totals.csv", mime="text/csv", key="dash_dl_daily",
                )

            st.divider()
            st.markdown("**2) Totals per student**")
            df_students = pd.DataFrame(stats["students"])
            if df_students.empty:
                st.info("No data in this period.")
            else:
                df_students = df_students.rename(columns={
                    "name": "الطالب", "tikrar": "التكرار", "jadeed": "الجديد", "total": "الإجمالي",
                })
                st.dataframe(df_students, width='stretch', hide_index=True)
                st.download_button(
                    "Download students CSV", data=df_students.to_csv(index=False).encode("utf-8"),
                    file_name="student_totals.csv", mime="text/csv", key="dash_dl_students",
                )

            st.divider()
            tgt = stats["target"]
            st.markdown(f"**3) Target progress** (static period: {dashboard.TARGET_START} → {dashboard.TARGET_END})")
            fig1 = _target_pie_fig(tgt["tikrar_achieved"], tgt["tikrar_target"], "التكرار", "#2ca02c")
            fig2 = _target_pie_fig(tgt["jadeed_achieved"], tgt["jadeed_target"], "الجديد", "#1f77b4")
            if fig1 is None or fig2 is None:
                st.info("plotly not available")
            else:
                col_p1, col_p2 = st.columns(2)
                with col_p1:
                    st.plotly_chart(fig1, width='stretch')
                    _pie_export_controls(fig1, "tikrar_target.png", "dash_p1")
                with col_p2:
                    st.plotly_chart(fig2, width='stretch')
                    _pie_export_controls(fig2, "jadeed_target.png", "dash_p2")

                st.markdown("**Combined view (both charts in one image)**")
                fig_all = _combined_pie_fig(fig1, fig2)
                st.plotly_chart(fig_all, width='stretch')
                _pie_export_controls(fig_all, "targets_combined.png", "dash_all")

    # =========================================================
    # TAB 6: EXPORT
    # =========================================================
    with tab6:
        st.subheader("Export to Google Sheets")
        st.caption("Exports go to the Championship DB spreadsheet (Sheet1), separate from the Data Viewer sheet.")
        sheet_id = st.text_input("Google Sheet ID", value=CH_DB_SHEET_ID or GOOGLE_SHEET_ID)
        sheet_range = st.text_input("Sheet Range", value="Sheet1")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Export Leaderboard", width='stretch', type="primary"):
                _do_export(sheet_id, sheet_range)
        with col2:
            if st.button("Export All Data", width='stretch'):
                _do_export(sheet_id, sheet_range)


def _do_export(sheet_id, sheet_range):
    sid_val = sheet_id or CH_DB_SHEET_ID or GOOGLE_SHEET_ID
    if not sid_val:
        st.error("No sheet ID configured")
        return
    with st.spinner("Exporting..."):
        try:
            lb = ch.get_leaderboard()
            df = pd.DataFrame(lb)
            df["rank"] = range(1, len(df) + 1)
            df = df[["rank", "name", "points", "jadeed", "tikrar", "total_pages", "daily_days", "wins", "draws", "losses"]]
            data = df.to_dict(orient="records")
            updated = send_to_sheet(data, sheet_id=sid_val, sheet_range=sheet_range)
            st.success(f"Exported {len(data)} rows ({updated} cells)")
        except Exception as e:
            st.error(f"Error: {e}")


def _batch_fetch_round(rnd):
    _clear_metabase_cache()
    matches = [m for m in ch.get_matches() if m["round_id"] == rnd["id"]]
    if not matches:
        st.warning("No matches in this round")
        return

    start = datetime.strptime(rnd["start_date"], "%Y-%m-%d").date()
    end = datetime.strptime(rnd["end_date"], "%Y-%m-%d").date()
    total_dates = (end - start).days + 1

    progress = st.progress(0, text="Fetching...")
    total_ops = len(matches) * 2 * total_dates
    done = 0
    fetched = 0
    records = []
    existing_keys = {(d["match_id"], d["student_id"], d["date"]) for d in ch.get_daily()}

    for m in matches:
        for sid in [m["student1_id"], m["student2_id"]]:
            sname = ch.get_student_name(sid)
            for i in range(total_dates):
                d = start + timedelta(days=i)
                j, t = _fetch_from_metabase(sname, d)
                if j is not None:
                    records.append({
                        "match_id": m["id"],
                        "student_id": sid,
                        "date": str(d),
                        "jadeed": j,
                        "tikrar": t,
                    })
                    fetched += 1
                else:
                    key = (m["id"], sid, str(d))
                    if key not in existing_keys:
                        records.append({
                            "match_id": m["id"],
                            "student_id": sid,
                            "date": str(d),
                            "jadeed": 0.0,
                            "tikrar": 0.0,
                        })
                done += 1
                if done % 10 == 0:
                    progress.progress(done / total_ops, text=f"Fetched {fetched} records...")

    if records:
        ch.upsert_daily_batch(records)
    progress.empty()
    if records:
        missing = len(records) - fetched
        st.success(
            f"Round {rnd['name']}: {len(records)} daily records synced "
            f"({fetched} from Metabase, {missing} set to 0 pages for days with no Metabase row)"
        )
    else:
        st.info("No daily data for this round")
