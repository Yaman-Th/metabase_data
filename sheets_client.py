import os
import json
import math
from google.oauth2 import service_account
from googleapiclient.discovery import build
from config import GOOGLE_SHEETS_CREDENTIALS_FILE, GOOGLE_SHEET_ID, GOOGLE_SHEET_RANGE

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _parse_creds_json(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    import re
    m = re.search(r'"private_key":\s*"(.+?)"', raw, re.DOTALL)
    if m:
        raw_key = m.group(1)
        fixed_key = raw_key.replace("\n", "\\n").replace("\r", "")
        raw_fixed = raw[: m.start(1)] + fixed_key + raw[m.end(1) :]
        return json.loads(raw_fixed)
    raise


def get_credentials():
    try:
        import streamlit as st
        creds_json = st.secrets.get("GOOGLE_SHEETS_CREDENTIALS")
        if creds_json:
            info = _parse_creds_json(creds_json)
            return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    except Exception:
        pass

    if os.path.exists(GOOGLE_SHEETS_CREDENTIALS_FILE):
        return service_account.Credentials.from_service_account_file(
            GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=SCOPES
        )

    raise FileNotFoundError(
        "No Google credentials found. Provide credentials.json locally "
        "or set GOOGLE_SHEETS_CREDENTIALS in Streamlit secrets."
    )


def send_to_sheet(data, sheet_id=None, sheet_range=None):
    sheet_id = sheet_id or GOOGLE_SHEET_ID
    sheet_range = sheet_range or GOOGLE_SHEET_RANGE

    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_ID is not configured")

    creds = get_credentials()
    service = build("sheets", "v4", credentials=creds)

    def clean(v):
        if isinstance(v, float) and math.isnan(v):
            return ""
        return v if v is not None else ""

    if not data:
        body = {"values": [["No data"]]}
    else:
        headers = list(data[0].keys())
        rows = [[clean(d.get(h)) for h in headers] for d in data]
        body = {"values": [headers] + rows}

    result = service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=sheet_range,
        valueInputOption="RAW",
        body=body,
    ).execute()

    return result.get("updatedCells", 0)
