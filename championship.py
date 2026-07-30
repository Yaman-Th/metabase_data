import json
import os
import math
from datetime import datetime, date
from config import TEMP_DATA_DIR

DATA_DIR = os.path.join(TEMP_DATA_DIR, "championship")
os.makedirs(DATA_DIR, exist_ok=True)

STUDENTS_FILE = os.path.join(DATA_DIR, "students.json")
ROUNDS_FILE = os.path.join(DATA_DIR, "rounds.json")
MATCHES_FILE = os.path.join(DATA_DIR, "matches.json")
DAILY_FILE = os.path.join(DATA_DIR, "daily.json")

POINTS_DAILY = 2
POINTS_WIN = 3
POINTS_DRAW = 1
POINTS_LOSS = 0


def _load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default or []
    return default or []


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# --- Students ---
def get_students():
    return _load_json(STUDENTS_FILE)


def add_student(name):
    students = get_students()
    if any(s["name"] == name for s in students):
        return False
    sid = max([s["id"] for s in students], default=0) + 1
    students.append({"id": sid, "name": name})
    _save_json(STUDENTS_FILE, students)
    return True


def delete_student(sid):
    students = [s for s in get_students() if s["id"] != sid]
    _save_json(STUDENTS_FILE, students)


def get_student_name(sid, students=None):
    if students is None:
        students = get_students()
    for s in students:
        if s["id"] == sid:
            return s["name"]
    return None


def get_student_homework_defaults(sid, students=None):
    if students is None:
        students = get_students()
    for s in students:
        if s["id"] == sid:
            return (float(s.get("homework_jadeed", 0)), float(s.get("homework_tikrar", 0)))
    return (0.0, 0.0)


def update_student_homework_defaults(sid, hw_j, hw_t):
    students = get_students()
    for s in students:
        if s["id"] == sid:
            s["homework_jadeed"] = hw_j
            s["homework_tikrar"] = hw_t
            _save_json(STUDENTS_FILE, students)
            return True
    return False


# --- Rounds ---
def get_rounds():
    return _load_json(ROUNDS_FILE)


def add_round(name, start_date, end_date, stage="group"):
    rounds = get_rounds()
    rid = max([r["id"] for r in rounds], default=0) + 1
    rounds.append({
        "id": rid,
        "name": name,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "stage": stage,
    })
    _save_json(ROUNDS_FILE, rounds)
    return rid


def delete_round(rid):
    rounds = [r for r in get_rounds() if r["id"] != rid]
    _save_json(ROUNDS_FILE, rounds)
    matches = [m for m in get_matches() if m["round_id"] != rid]
    _save_json(MATCHES_FILE, matches)


# --- Matches ---
def get_matches():
    return _load_json(MATCHES_FILE)


def add_match(round_id, student1_id, student2_id):
    matches = get_matches()
    mid = max([m["id"] for m in matches], default=0) + 1
    matches.append({
        "id": mid,
        "round_id": round_id,
        "student1_id": student1_id,
        "student2_id": student2_id,
    })
    _save_json(MATCHES_FILE, matches)
    return mid


def delete_match(mid):
    matches = [m for m in get_matches() if m["id"] != mid]
    _save_json(MATCHES_FILE, matches)
    daily = [d for d in get_daily() if d["match_id"] != mid]
    _save_json(DAILY_FILE, daily)


# --- Daily Records ---
def get_daily():
    return _load_json(DAILY_FILE)


def upsert_daily(match_id, student_id, rec_date, jadeed, tikrar, homework_jadeed=0.0, homework_tikrar=0.0):
    daily = get_daily()
    key = f"{match_id}_{student_id}_{rec_date}"
    for d in daily:
        dk = f"{d['match_id']}_{d['student_id']}_{d['date']}"
        if dk == key:
            d["jadeed"] = jadeed
            d["tikrar"] = tikrar
            d["homework_jadeed"] = homework_jadeed
            d["homework_tikrar"] = homework_tikrar
            _save_json(DAILY_FILE, daily)
            return
    daily.append({
        "match_id": match_id,
        "student_id": student_id,
        "date": str(rec_date),
        "jadeed": jadeed,
        "tikrar": tikrar,
        "homework_jadeed": homework_jadeed,
        "homework_tikrar": homework_tikrar,
    })
    _save_json(DAILY_FILE, daily)


def delete_daily(mid, sid, rec_date):
    daily = get_daily()
    key = f"{mid}_{sid}_{rec_date}"
    daily = [d for d in daily if f"{d['match_id']}_{d['student_id']}_{d['date']}" != key]
    _save_json(DAILY_FILE, daily)


# --- Calculations ---
def get_student_total_pages(match_id, student_id):
    total = 0.0
    for d in get_daily():
        if d["match_id"] == match_id and d["student_id"] == student_id:
            total += d.get("jadeed", 0) + d.get("tikrar", 0)
    return total


def get_student_daily_bonus_days(match_id, student_id, round_start, round_end):
    """Count days where BOTH homework types are met (jadeed >= hw_j AND tikrar >= hw_t)."""
    days = 0
    start = datetime.strptime(str(round_start), "%Y-%m-%d").date() if isinstance(round_start, str) else round_start
    end = datetime.strptime(str(round_end), "%Y-%m-%d").date() if isinstance(round_end, str) else round_end
    for d in get_daily():
        if d["match_id"] == match_id and d["student_id"] == student_id:
            d_date = datetime.strptime(d["date"], "%Y-%m-%d").date()
            if not (start <= d_date <= end):
                continue
            hw_j = d.get("homework_jadeed", 0)
            hw_t = d.get("homework_tikrar", 0)
            if hw_j <= 0 and hw_t <= 0:
                continue
            if d.get("jadeed", 0) >= hw_j and d.get("tikrar", 0) >= hw_t:
                days += 1
    return days


def compute_match_result(match, round_obj):
    s1_total = get_student_total_pages(match["id"], match["student1_id"])
    s2_total = get_student_total_pages(match["id"], match["student2_id"])
    days1 = get_student_daily_bonus_days(match["id"], match["student1_id"], round_obj["start_date"], round_obj["end_date"])
    days2 = get_student_daily_bonus_days(match["id"], match["student2_id"], round_obj["start_date"], round_obj["end_date"])

    if s1_total > s2_total:
        match_result = "win1"
    elif s2_total > s1_total:
        match_result = "win2"
    else:
        match_result = "draw"

    points1 = POINTS_DAILY * days1
    points2 = POINTS_DAILY * days2

    if match_result == "win1":
        points1 += POINTS_WIN
        points2 += POINTS_LOSS
    elif match_result == "win2":
        points1 += POINTS_LOSS
        points2 += POINTS_WIN
    else:
        points1 += POINTS_DRAW
        points2 += POINTS_DRAW

    return {
        "student1_id": match["student1_id"],
        "student2_id": match["student2_id"],
        "total_pages1": s1_total,
        "total_pages2": s2_total,
        "jadeed1": sum(d.get("jadeed", 0) for d in get_daily() if d["match_id"] == match["id"] and d["student_id"] == match["student1_id"]),
        "tikrar1": sum(d.get("tikrar", 0) for d in get_daily() if d["match_id"] == match["id"] and d["student_id"] == match["student1_id"]),
        "jadeed2": sum(d.get("jadeed", 0) for d in get_daily() if d["match_id"] == match["id"] and d["student_id"] == match["student2_id"]),
        "tikrar2": sum(d.get("tikrar", 0) for d in get_daily() if d["match_id"] == match["id"] and d["student_id"] == match["student2_id"]),
        "daily_days1": days1,
        "daily_days2": days2,
        "result": match_result,
        "points1": points1,
        "points2": points2,
    }


def get_leaderboard(round_id=None, stage=None):
    students = get_students()
    matches = get_matches()
    rounds = get_rounds()

    all_matches = matches
    if round_id is not None:
        all_matches = [m for m in all_matches if m["round_id"] == round_id]
    if stage:
        round_ids = [r["id"] for r in rounds if r.get("stage") == stage]
        all_matches = [m for m in all_matches if m["round_id"] in round_ids]

    leaderboard = {}
    for s in students:
        leaderboard[s["id"]] = {
            "name": s["name"],
            "points": 0,
            "jadeed": 0.0,
            "tikrar": 0.0,
            "total_pages": 0.0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "daily_days": 0,
        }

    for m in all_matches:
        r = next((rnd for rnd in rounds if rnd["id"] == m["round_id"]), None)
        if not r:
            continue
        res = compute_match_result(m, r)

        for key in ["student1_id", "student2_id"]:
            sid = m[key]
            if sid not in leaderboard:
                continue
            idx = 1 if key == "student1_id" else 2
            lb = leaderboard[sid]
            lb["points"] += res[f"points{idx}"]
            lb["jadeed"] += res.get(f"jadeed{idx}", 0)
            lb["tikrar"] += res.get(f"tikrar{idx}", 0)
            lb["daily_days"] += res.get(f"daily_days{idx}", 0)
            lb["total_pages"] = lb["jadeed"] + lb["tikrar"]

            if res["result"] == f"win{idx}":
                lb["wins"] += 1
            elif res["result"] == "draw":
                lb["draws"] += 1
            else:
                lb["losses"] += 1

    return sorted(
        leaderboard.values(),
        key=lambda x: (-x["points"], -x["jadeed"], -x["tikrar"]),
    )
