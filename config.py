METABASE_DATASETS = {
    "TIKRAR (تكرار)": "https://tarteeby-metabase.webmyidea.com/api/public/card/a8bee5a2-3c9a-45d0-b693-b4166ed9b539/query/json",
    "JADEED (جديد)": "https://tarteeby-metabase.webmyidea.com/api/public/card/2d44814f-9ca5-4e86-b8b6-81291be1119a/query/json",
}

METABASE_URL = list(METABASE_DATASETS.values())[0]

GOOGLE_SHEETS_CREDENTIALS_FILE = "metabasedata-503908-2cf03946f049.json"
GOOGLE_SHEET_ID = "1Icsxjetw-rLX-9fEkmBQB5z0dwT18c3vd7GKDqcIv5s"
GOOGLE_SHEET_RANGE = "Sheet8"

# Dedicated spreadsheet used by the Championship online storage (data survives
# app restarts). Falls back to GOOGLE_SHEET_ID if not set. Can be overridden
# with the CH_DB_SHEET_ID secret.
CH_DB_SHEET_ID = "1oYVjFpwAJ_gWdzN8o7cVtaD4ivNPJV_sIi4vF9K8hw4"

TEMP_DATA_DIR = "data_cache"
