import math
from datetime import datetime, date
import storage

POINTS_DAILY = 2
POINTS_WIN = 3
POINTS_DRAW = 1
POINTS_LOSS = 0

_CACHE = None


def _load_cache():
    global _CACHE
    if _CACHE is None:
        _CACHE = storage.load_all()
        for name in storage.COLLECTIONS:
            _CACHE.setdefault(name, [])
    return _CACHE


def _get(name):
    return _load_cache().get(name, [])


def _save(name, rows):
    _load_cache()[name] = rows
    storage.save_collection(name, rows)


# --- Students ---
def get_students():
    return _get("students")


def add_student(name):
    students = get_students()
    if any(s["name"] == name for s in students):
        return False
    sid = max([s["id"] for s in students], default=0) + 1
    students.append({"id": sid, "name": name})
    _save("students", students)
    return True


def delete_student(sid):
    students = [s for s in get_students() if s["id"] != sid]
    _save("students", students)
    homework = [h for h in get_homework() if h["student_id"] != sid]
    _save("homework", homework)


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
            _save("students", students)
            return True
    return False


# --- Rounds ---
def get_rounds():
    return _get("rounds")


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
    _save("rounds", rounds)
    return rid


def delete_round(rid):
    round_matches = [m for m in get_matches() if m["round_id"] == rid]
    rounds = [r for r in get_rounds() if r["id"] != rid]
    _save("rounds", rounds)
    matches = [m for m in get_matches() if m["round_id"] != rid]
    _save("matches", matches)
    del_ids = {m["id"] for m in round_matches}
    daily = [d for d in get_daily() if d["match_id"] not in del_ids]
    _save("daily", daily)


# --- Matches ---
def get_matches():
    return _get("matches")


def add_match(round_id, student1_id, student2_id):
    matches = get_matches()
    mid = max([m["id"] for m in matches], default=0) + 1
    matches.append({
        "id": mid,
        "round_id": round_id,
        "student1_id": student1_id,
        "student2_id": student2_id,
    })
    _save("matches", matches)
    return mid


def delete_match(mid):
    matches = [m for m in get_matches() if m["id"] != mid]
    _save("matches", matches)
    daily = [d for d in get_daily() if d["match_id"] != mid]
    _save("daily", daily)


# --- Daily Records (pages, fetched from Metabase or entered manually) ---
def get_daily():
    return _get("daily")


def upsert_daily(match_id, student_id, rec_date, jadeed, tikrar):
    daily = get_daily()
    key = f"{match_id}_{student_id}_{rec_date}"
    for d in daily:
        dk = f"{d['match_id']}_{d['student_id']}_{d['date']}"
        if dk == key:
            d["jadeed"] = jadeed
            d["tikrar"] = tikrar
            _save("daily", daily)
            return
    daily.append({
        "match_id": match_id,
        "student_id": student_id,
        "date": str(rec_date),
        "jadeed": jadeed,
        "tikrar": tikrar,
    })
    _save("daily", daily)


def upsert_daily_batch(records):
    """records: list of dicts with keys match_id, student_id, date, jadeed,
    tikrar. Persists all records in one write to avoid a Sheets API call per
    record. Only touches the daily (pages) table; homework targets live in the
    homework table and are never overwritten here."""
    daily = get_daily()
    by_key = {f"{d['match_id']}_{d['student_id']}_{d['date']}": d for d in daily}
    for r in records:
        key = f"{r['match_id']}_{r['student_id']}_{r['date']}"
        if key in by_key:
            by_key[key].update({"jadeed": r.get("jadeed", 0), "tikrar": r.get("tikrar", 0)})
        else:
            daily.append({
                "match_id": r["match_id"],
                "student_id": r["student_id"],
                "date": str(r["date"]),
                "jadeed": r.get("jadeed", 0),
                "tikrar": r.get("tikrar", 0),
            })
    _save("daily", daily)


def delete_daily(mid, sid, rec_date):
    daily = get_daily()
    key = f"{mid}_{sid}_{rec_date}"
    daily = [d for d in daily if f"{d['match_id']}_{d['student_id']}_{d['date']}" != key]
    _save("daily", daily)


# --- Homework Records (per student + date, manually entered, never
# overwritten by the Metabase pages fetch) ---
def get_homework():
    return _get("homework")


def get_homework_by_date(student_id, rec_date):
    """Return the homework target record for a student on a given date (or
    None). Homework is global per student+date (not tied to a match). If legacy
    per-match records exist for the same date, the last one wins."""
    day = str(rec_date)
    found = None
    for h in get_homework():
        if h.get("student_id") == student_id and h.get("date") == day:
            found = h
    return found


def upsert_homework(student_id, rec_date, homework_jadeed, homework_tikrar):
    homework = get_homework()
    key = f"{student_id}_{rec_date}"
    for h in homework:
        hk = f"{h.get('student_id')}_{h['date']}"
        if hk == key:
            h["homework_jadeed"] = homework_jadeed
            h["homework_tikrar"] = homework_tikrar
            _save("homework", homework)
            return
    homework.append({
        "student_id": student_id,
        "date": str(rec_date),
        "homework_jadeed": homework_jadeed,
        "homework_tikrar": homework_tikrar,
    })
    _save("homework", homework)


def delete_homework(student_id, rec_date):
    homework = get_homework()
    key = f"{student_id}_{rec_date}"
    homework = [h for h in homework if f"{h.get('student_id')}_{h['date']}" != key]
    _save("homework", homework)


# --- Calculations ---
def get_student_total_pages(match_id, student_id, round_start=None, round_end=None):
    """Sum pages (jadeed + tikrar) for the student in the match, restricted to
    the round's date range when provided (so results cover exactly the round)."""
    total = 0.0
    start = datetime.strptime(str(round_start), "%Y-%m-%d").date() if round_start else None
    end = datetime.strptime(str(round_end), "%Y-%m-%d").date() if round_end else None
    for d in get_daily():
        if d["match_id"] == match_id and d["student_id"] == student_id:
            d_date = datetime.strptime(d["date"], "%Y-%m-%d").date()
            if start and d_date < start:
                continue
            if end and d_date > end:
                continue
            total += d.get("jadeed", 0) + d.get("tikrar", 0)
    return total


def get_student_daily_bonus_days(match_id, student_id, round_start, round_end):
    """Count days where BOTH homework types are met (jadeed >= hw_j AND
    tikrar >= hw_t). A 0-page homework target is always met, so a student with
    no homework (0/0) who recites nothing is counted as done. Homework targets
    come from the homework table (manual entry, keyed by student + date);
    legacy daily records with embedded homework fields are honored, then
    student defaults."""
    days = 0
    start = datetime.strptime(str(round_start), "%Y-%m-%d").date() if isinstance(round_start, str) else round_start
    end = datetime.strptime(str(round_end), "%Y-%m-%d").date() if isinstance(round_end, str) else round_end
    hw_by_date = {}
    for h in get_homework():
        if h.get("student_id") == student_id:
            hw_by_date[h["date"]] = (h.get("homework_jadeed", 0), h.get("homework_tikrar", 0))
    def_hw_j, def_hw_t = get_student_homework_defaults(student_id)
    for d in get_daily():
        if d["match_id"] == match_id and d["student_id"] == student_id:
            d_date = datetime.strptime(d["date"], "%Y-%m-%d").date()
            if not (start <= d_date <= end):
                continue
            hw_j, hw_t = hw_by_date.get(d["date"], (d.get("homework_jadeed", 0), d.get("homework_tikrar", 0)))
            if hw_j <= 0 and hw_t <= 0:
                hw_j, hw_t = def_hw_j, def_hw_t
            if d.get("jadeed", 0) >= hw_j and d.get("tikrar", 0) >= hw_t:
                days += 1
    return days


def compute_match_result(match, round_obj):
    s1_total = get_student_total_pages(match["id"], match["student1_id"], round_obj["start_date"], round_obj["end_date"])
    s2_total = get_student_total_pages(match["id"], match["student2_id"], round_obj["start_date"], round_obj["end_date"])
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

    start = datetime.strptime(str(round_obj["start_date"]), "%Y-%m-%d").date()
    end = datetime.strptime(str(round_obj["end_date"]), "%Y-%m-%d").date()

    def _records(sid):
        for d in get_daily():
            if d["match_id"] != match["id"] or d["student_id"] != sid:
                continue
            d_date = datetime.strptime(d["date"], "%Y-%m-%d").date()
            if start <= d_date <= end:
                yield d

    return {
        "student1_id": match["student1_id"],
        "student2_id": match["student2_id"],
        "total_pages1": s1_total,
        "total_pages2": s2_total,
        "jadeed1": sum(d.get("jadeed", 0) for d in _records(match["student1_id"])),
        "tikrar1": sum(d.get("tikrar", 0) for d in _records(match["student1_id"])),
        "jadeed2": sum(d.get("jadeed", 0) for d in _records(match["student2_id"])),
        "tikrar2": sum(d.get("tikrar", 0) for d in _records(match["student2_id"])),
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
