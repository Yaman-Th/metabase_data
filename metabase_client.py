import requests
import json
import os
from datetime import datetime
from config import METABASE_URL, TEMP_DATA_DIR

os.makedirs(TEMP_DATA_DIR, exist_ok=True)

CACHE_FILE = os.path.join(TEMP_DATA_DIR, "cached_data.json")


def fetch_all_data(use_cache=True):
    if use_cache and os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    all_data = []
    offset = 0
    limit = 20000

    while True:
        resp = requests.get(METABASE_URL, params={"limit": limit, "offset": offset}, timeout=120)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        all_data.extend(batch)
        offset += limit
        print(f"Fetched {len(batch)} rows (total: {len(all_data)})")

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False)

    return all_data


def get_unique_groups(data):
    groups = sorted(set(
        d.get("Groups → Slug", "") for d in data if d.get("Groups → Slug")
    ))
    return groups


def get_date_range(data):
    dates = [
        d.get("Repeat Records → Date: Day") for d in data
        if d.get("Repeat Records → Date: Day")
    ]
    if not dates:
        return None, None
    return min(dates), max(dates)


def filter_data(data, date_from=None, date_to=None, groups=None):
    filtered = []
    for d in data:
        row_date = d.get("Repeat Records → Date: Day", "")
        row_group = d.get("Groups → Slug", "")

        if date_from and row_date < date_from:
            continue
        if date_to and row_date > date_to:
            continue
        if groups and row_group not in groups:
            continue

        filtered.append(d)

    return filtered
