import streamlit as st
import pandas as pd
import requests
import json
import os

from config import METABASE_DATASETS, TEMP_DATA_DIR
from config import GOOGLE_SHEET_ID, GOOGLE_SHEET_RANGE
from sheets_client import send_to_sheet
import championship_ui

os.makedirs(TEMP_DATA_DIR, exist_ok=True)

STATE_FILE = os.path.join(TEMP_DATA_DIR, "app_state.json")


def load_state():
    defaults = {
        "dataset": list(METABASE_DATASETS.keys())[0],
        "date_from": None,
        "date_to": None,
        "groups": [],
        "view_mode": "Raw Data",
        "metrics": [],
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                defaults.update(saved)
        except Exception:
            pass
    return defaults


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception:
        pass


if "app_state_loaded" not in st.session_state:
    st.session_state.app_state_loaded = True
    saved = load_state()
    for k, v in saved.items():
        st.session_state[k] = v


def cache_path(label):
    clean = "".join(c for c in label if c.isalnum() or c in " _-")
    return os.path.join(TEMP_DATA_DIR, f"cached_{clean}.json")


def _clear_cache_files():
    for f in os.listdir(TEMP_DATA_DIR):
        if f.startswith("cached_"):
            os.remove(os.path.join(TEMP_DATA_DIR, f))


def fetch_data(url, label):
    cpath = cache_path(label)
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


def find_col(df, *patterns):
    for pat in patterns:
        for c in df.columns:
            if pat.lower() in c.lower():
                return c
    return None


def get_date_col(df):
    return find_col(df, "Date", "Day")


def get_group_col(df):
    return find_col(df, "Groups → Slug", "Slug")


def get_student_col(df):
    return find_col(df, "Student → Name", "Name")


def get_reciter_col(df):
    return find_col(df, "Reciter → Name", "Reciter")


def get_numeric_cols(df):
    return list(df.select_dtypes(include=["int64", "float64"]).columns)


st.set_page_config(page_title="Metabase Data Viewer", layout="wide")

# Load Metabase data once, share across pages
if "metabase_data" not in st.session_state:
    with st.spinner("Loading Metabase data..."):
        try:
            default_url = list(METABASE_DATASETS.values())[0]
            default_label = list(METABASE_DATASETS.keys())[0]
            st.session_state.metabase_data = fetch_data(default_url, default_label)
            st.session_state.metabase_df = pd.DataFrame(st.session_state.metabase_data)
        except Exception as e:
            st.session_state.metabase_data = []
            st.session_state.metabase_df = pd.DataFrame()

page = st.sidebar.selectbox("Page", ["Data Viewer", "Championship"], key="page_select")

if page == "Championship":
    championship_ui.render()
    st.stop()

st.title("Metabase Data Viewer")

# --- Sidebar ---
with st.sidebar:
    st.header("Settings")

    dataset_label = st.selectbox(
        "Dataset",
        options=list(METABASE_DATASETS.keys()),
        index=list(METABASE_DATASETS.keys()).index(st.session_state.dataset)
        if st.session_state.dataset in METABASE_DATASETS
        else 0,
        key="dataset_select",
    )
    # Persist dataset choice
    if dataset_label != st.session_state.dataset:
        st.session_state.dataset = dataset_label
        _clear_cache_files()
        save_state(dict(st.session_state))

    metabase_url = METABASE_DATASETS[dataset_label]

    st.divider()
    st.header("Filters")

    with st.spinner("Loading data..."):
        try:
            raw_data = fetch_data(metabase_url, dataset_label)
            df = pd.DataFrame(raw_data)
            st.session_state.metabase_data = raw_data
            st.session_state.metabase_df = df
            st.success(f"Loaded {len(df)} rows, {len(df.columns)} columns")
        except Exception as e:
            st.error(f"Failed to load data: {e}")
            st.stop()

    group_col = get_group_col(df)
    date_col = get_date_col(df)
    student_col = get_student_col(df)
    numeric_cols = get_numeric_cols(df)

    selected_groups = []
    if group_col:
        groups = sorted(df[group_col].dropna().unique())
        default_groups = [g for g in st.session_state.groups if g in groups]
        selected_groups = st.multiselect(
            f"Group ({group_col})",
            options=groups,
            default=default_groups,
        )

    date_from = date_to = None
    if date_col:
        dates = pd.to_datetime(df[date_col].dropna())
        min_date = dates.min()
        max_date = dates.max()

        from_val = st.session_state.date_from
        if from_val:
            try:
                from_val = pd.to_datetime(from_val).date()
                if from_val < min_date.date():
                    from_val = min_date.date()
            except Exception:
                from_val = min_date.date()
        else:
            from_val = min_date.date()

        to_val = st.session_state.date_to
        if to_val:
            try:
                to_val = pd.to_datetime(to_val).date()
                if to_val > max_date.date():
                    to_val = max_date.date()
            except Exception:
                to_val = max_date.date()
        else:
            to_val = max_date.date()

        date_from = st.date_input("Date from", value=from_val, min_value=min_date, max_value=max_date)
        date_to = st.date_input("Date to", value=to_val, min_value=min_date, max_value=max_date)

    st.divider()
    st.header("Aggregation")

    agg_options = ["Raw Data"]
    if date_col:
        agg_options.append("Sum by Date")
    if student_col:
        agg_options.append("Sum by Student")

    default_view = st.session_state.view_mode if st.session_state.view_mode in agg_options else agg_options[0]
    view_mode = st.radio("View mode", options=agg_options, horizontal=True, index=agg_options.index(default_view))

    default_metrics = [m for m in st.session_state.metrics if m in numeric_cols] or numeric_cols
    selected_metrics = st.multiselect(
        "Metrics to aggregate",
        options=numeric_cols,
        default=default_metrics,
    )

    show_send = st.checkbox("Show Google Sheets options", value=False)

# --- Persist state ---
state_update = {
    "dataset": dataset_label,
    "date_from": str(date_from) if date_from else None,
    "date_to": str(date_to) if date_to else None,
    "groups": selected_groups,
    "view_mode": view_mode,
    "metrics": selected_metrics,
}
needs_save = any(st.session_state.get(k) != v for k, v in state_update.items())
for k, v in state_update.items():
    st.session_state[k] = v
if needs_save:
    save_state(state_update)

# --- Filter ---
filtered = df.copy()

if selected_groups and group_col:
    filtered = filtered[filtered[group_col].isin(selected_groups)]

if date_col and date_from and date_to:
    mask = pd.to_datetime(filtered[date_col]).dt.date.between(date_from, date_to)
    filtered = filtered[mask]

st.subheader(f"Filtered: {len(filtered)} rows")

# --- Aggregate ---
if view_mode == "Sum by Date" and date_col:
    if selected_metrics:
        result = filtered.groupby(date_col)[selected_metrics].sum().reset_index()
    else:
        result = filtered.groupby(date_col).size().reset_index(name="Count")

elif view_mode == "Sum by Student" and student_col:
    if selected_metrics:
        result = filtered.groupby(student_col)[selected_metrics].sum().reset_index()
    else:
        result = filtered.groupby(student_col).size().reset_index(name="Count")

else:
    result = filtered

st.dataframe(result, width="stretch", hide_index=True)

# --- Send to Sheets ---
if show_send:
    st.divider()
    st.subheader("Send to Google Sheets")

    sheet_id = st.text_input("Google Sheet ID", value=GOOGLE_SHEET_ID or "")
    sheet_range = st.text_input("Sheet Range", value=GOOGLE_SHEET_RANGE)

    if st.button("Send to Google Sheets", type="primary"):
        sheet_id_val = sheet_id or GOOGLE_SHEET_ID
        if not sheet_id_val:
            st.error("Google Sheet ID not configured. Set it in config.py or enter above.")
        else:
            with st.spinner("Sending..."):
                try:
                    rows_data = result.to_dict(orient="records")
                    updated = send_to_sheet(rows_data, sheet_id=sheet_id_val, sheet_range=sheet_range)
                    st.success(f"Sent {len(rows_data)} rows ({updated} cells updated)")
                except Exception as e:
                    st.error(f"Error: {e}")
