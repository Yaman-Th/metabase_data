import json
import os
import streamlit as st
from googleapiclient.discovery import build
from sheets_client import get_credentials
from config import GOOGLE_SHEET_ID, CH_DB_SHEET_ID, TEMP_DATA_DIR


def _db_sheet_id():
    try:
        secret = st.secrets.get("CH_DB_SHEET_ID")
        if secret:
            return secret
    except Exception:
        pass
    return CH_DB_SHEET_ID or GOOGLE_SHEET_ID


DB_SHEET_ID = _db_sheet_id()
DB_TAB_PREFIX = "ch_"
COLLECTIONS = ("students", "rounds", "matches", "daily")
CHUNK_SIZE = 40000

_CACHE_DIR = os.path.join(TEMP_DATA_DIR, "championship")
os.makedirs(_CACHE_DIR, exist_ok=True)


def _cache_path(name):
    return os.path.join(_CACHE_DIR, f"{name}.json")


def _tab(name):
    return f"{DB_TAB_PREFIX}{name}"


def _service():
    return build("sheets", "v4", credentials=get_credentials())


def _ensure_tabs(service):
    meta = service.spreadsheets().get(
        spreadsheetId=DB_SHEET_ID,
        fields="sheets(properties(title))",
    ).execute()
    existing = {s["properties"]["title"] for s in meta.get("sheets", [])}
    missing = [_tab(n) for n in COLLECTIONS if _tab(n) not in existing]
    if missing:
        requests = [{"addSheet": {"properties": {"title": t}}} for t in missing]
        service.spreadsheets().batchUpdate(
            spreadsheetId=DB_SHEET_ID, body={"requests": requests}
        ).execute()


@st.cache_data(ttl=30, show_spinner=False)
def load_all():
    return {name: _load_collection_raw(name) for name in COLLECTIONS}


def get_collection(name):
    return load_all().get(name, [])


def _load_collection_raw(name):
    try:
        service = _service()
        _ensure_tabs(service)
        result = service.spreadsheets().values().get(
            spreadsheetId=DB_SHEET_ID,
            range=f"{_tab(name)}!A1:A",
            valueRenderOption="FORMATTED_VALUE",
        ).execute()
        vals = [r[0] for r in result.get("values", []) if r]
        if not vals:
            return []
        return json.loads("".join(vals))
    except Exception:
        return _load_local(name)


def _load_local(name):
    path = _cache_path(name)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_collection(name, rows):
    _save_local(name, rows)
    try:
        text = json.dumps(rows, ensure_ascii=False)
        chunks = [text[i:i + CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE)]
        values = [[c] for c in chunks] if chunks else [[""]]
        service = _service()
        _ensure_tabs(service)
        tab = _tab(name)
        service.spreadsheets().values().clear(
            spreadsheetId=DB_SHEET_ID, range=f"{tab}!A:A"
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=DB_SHEET_ID,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            body={"values": values},
        ).execute()
        load_all.clear()
        try:
            st.session_state.pop("ch_storage_error", None)
        except Exception:
            pass
    except Exception as e:
        try:
            st.session_state["ch_storage_error"] = f"{name}: {e}"
        except Exception:
            print(f"[storage] sync failed for {name}: {e}")


def _save_local(name, rows):
    with open(_cache_path(name), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
