import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from config import GOOGLE_SHEETS_CREDENTIALS_FILE, GOOGLE_SHEET_ID, GOOGLE_SHEET_RANGE

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_credentials():
    try:
        import streamlit as st
        creds_json = st.secrets.get("GOOGLE_SHEETS_CREDENTIALS")
        if creds_json:
            info = json.loads(creds_json)
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

    if not data:
        body = {"values": [["No data"]]}
    else:
        headers = list(data[0].keys())
        rows = [[d.get(h, "") for h in headers] for d in data]
        body = {"values": [headers] + rows}

    result = service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=sheet_range,
        valueInputOption="RAW",
        body=body,
    ).execute()

    return result.get("updatedCells", 0)
