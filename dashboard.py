"""Dashboard statistics for the Championship app.

Pulls the two public Metabase datasets (TIKRAR + JADEED), aggregates tikrar /
jadeed / total pages between two user-selected dates (inclusive), and computes
competition-target progress over a static period (2026-06-01 .. 2026-08-15)
for the pie charts (tikrar target 5000, jadeed target 300).
"""

import os
import json
import requests
import pandas as pd
from datetime import date, timedelta

from config import METABASE_DATASETS, TEMP_DATA_DIR

TARGET_START = date(2026, 6, 1)
TARGET_END = date(2026, 8, 15)
TIKRAR_TARGET = 5000.0
JADEED_TARGET = 300.0

_TIKRAR_PATTERNS = ["sumofoldpages", "oldpages", "old", "تكرار", "tikrar"]
_JADEED_PATTERNS = ["sumofnewpages", "newpages", "new", "جديد"]


def _load_dataset(url, label):
    """Fetch a Metabase dataset with a local JSON cache (fresh once fetched)."""
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


def clear_cache():
    for f in os.listdir(TEMP_DATA_DIR):
        if f.startswith("ch_") and f.endswith(".json"):
            try:
                os.remove(os.path.join(TEMP_DATA_DIR, f))
            except OSError:
                pass


def _student_col(df):
    for c in df.columns:
        cl = c.lower()
        if "student" in cl and cl.endswith("name"):
            return c
    for c in df.columns:
        cl = c.lower().strip()
        if cl == "name" and "reciter" not in c:
            return c
    for c in df.columns:
        cl = c.lower()
        if "reciter" in cl and "name" in cl:
            return c
    return None


def _date_col(df):
    for c in df.columns:
        cl = c.lower()
        if "date" in cl or "day" in cl:
            return c
    return None


def _value_cols(df, patterns):
    out = []
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            continue
        cl = c.lower().replace(" ", "")
        if any(p in cl for p in patterns):
            out.append(c)
    return out


def _extract(label, url):
    """Return ([(date, student, value), ...], kind) for one dataset."""
    raw = _load_dataset(url, label)
    if not raw:
        return [], ""
    df = pd.DataFrame(raw)
    sc = _student_col(df)
    dc = _date_col(df)
    if sc is None or dc is None:
        return [], ""
    ll = label.lower()
    if any(x in ll for x in ["jadeed", "جديد"]):
        patterns, kind = _JADEED_PATTERNS, "jadeed"
    else:
        patterns, kind = _TIKRAR_PATTERNS, "tikrar"
    vcols = _value_cols(df, patterns)
    if not vcols:
        return [], kind

    records = []
    for _, row in df.iterrows():
        if pd.isna(row[sc]) or pd.isna(row[dc]):
            continue
        d = str(row[dc])[:10]
        s = str(row[sc])
        try:
            v = float(sum(row[c] for c in vcols if pd.notna(row[c])))
        except Exception:
            v = 0.0
        if v:
            records.append((d, s, v))
    return records, kind


def _as_date(d):
    try:
        return date.fromisoformat(d)
    except Exception:
        try:
            return pd.to_datetime(d).date()
        except Exception:
            return None


def compute_stats(date_from, date_to, student_names=None):
    """Aggregate tikrar/jadeed between two inclusive dates.

    If `student_names` is given (iterable of names), only records belonging to
    those students are included (i.e. the Championship students tab list).
    """
    daily = {}
    students = {}
    all_records = []
    allowed = set(student_names) if student_names is not None else None

    for label, url in METABASE_DATASETS.items():
        records, kind = _extract(label, url)
        if not kind:
            continue
        idx = 0 if kind == "tikrar" else 1
        for d, s, v in records:
            if allowed is not None and s not in allowed:
                continue
            daily.setdefault(d, [0.0, 0.0])[idx] += v
            students.setdefault(s, [0.0, 0.0])[idx] += v
            all_records.append((d, s, v, kind))

    daily_rows = []
    cur = date_from
    while cur <= date_to:
        d = str(cur)
        t, j = daily.get(d, [0.0, 0.0])
        daily_rows.append({
            "date": d,
            "tikrar": round(t, 1),
            "jadeed": round(j, 1),
            "total": round(t + j, 1),
        })
        cur += timedelta(days=1)

    student_rows = []
    for s in sorted(students, key=lambda n: -(students[n][0] + students[n][1])):
        t, j = students[s]
        student_rows.append({
            "name": s,
            "tikrar": round(t, 1),
            "jadeed": round(j, 1),
            "total": round(t + j, 1),
        })

    t_ach = 0.0
    j_ach = 0.0
    for d, _, v, kind in all_records:
        dd = _as_date(d)
        if dd is None or not (TARGET_START <= dd <= TARGET_END):
            continue
        if kind == "tikrar":
            t_ach += v
        else:
            j_ach += v

    return {
        "daily": daily_rows,
        "students": student_rows,
        "target": {
            "start": str(TARGET_START),
            "end": str(TARGET_END),
            "tikrar_achieved": round(t_ach, 1),
            "tikrar_target": TIKRAR_TARGET,
            "jadeed_achieved": round(j_ach, 1),
            "jadeed_target": JADEED_TARGET,
        },
    }
