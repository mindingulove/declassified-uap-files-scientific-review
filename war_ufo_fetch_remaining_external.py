import os
#!/usr/bin/env python3
import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path("/tmp/war_ufo_science")
DB = BASE / "cases.sqlite"
CACHE = BASE / "external_cache"
CACHE.mkdir(exist_ok=True)


def get_json(url, cache_key, use_cache=True, sleep=0.2):
    path = CACHE / f"{cache_key}.json"
    if use_cache and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    req = urllib.request.Request(url, headers={"User-Agent": "war-ufo-science-pipeline/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=35) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        data = {"fetch_error": str(e), "url": url}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    time.sleep(sleep)
    return data


def parse_date(s):
    if not s:
        return None, "missing_date"
    s = s.strip()
    if re.fullmatch(r"\d{4}", s):
        return None, "year_only"
    if s.lower().startswith(("late", "early", "mid")):
        return None, "vague_date"
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}-\d{1,2}/\d{1,2}/\d{2,4}", s):
        s = s.split("-", 1)[0]
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if not m:
        return None, "unparsed_date"
    mo, da, yr = map(int, m.groups())
    if yr < 100:
        yr += 1900 if yr >= 40 else 2000
    try:
        return date(yr, mo, da), "ok"
    except Exception:
        return None, "invalid_date"


def insert_corr(conn, case_id, ctype, status, source, query, result, summary, now):
    conn.execute(
        """
        INSERT OR REPLACE INTO external_correlations
        (case_id,correlation_type,status,source,query_json,result_json,result_summary,fetched_at)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (case_id, ctype, status, source, json.dumps(query), json.dumps(result) if result is not None else None, summary, now),
    )


def fetch_fireballs(d):
    start = d - timedelta(days=1)
    end = d + timedelta(days=1)
    params = {
        "date-min": start.isoformat(),
        "date-max": end.isoformat(),
        "req-loc": "true",
    }
    url = "https://ssd-api.jpl.nasa.gov/fireball.api?" + urllib.parse.urlencode(params)
    return get_json(url, f"fireball_{d}")


def fireball_summary(data):
    if data.get("fetch_error") or data.get("code"):
        return "fetch_error: " + str(data.get("fetch_error") or data.get("message") or data.get("code"))
    count = int(data.get("count") or 0)
    if count == 0:
        return "NASA/JPL CNEOS Fireball API: no located fireballs in +/-1 day global window."
    fields = data.get("fields") or []
    rows = data.get("data") or []
    date_idx = fields.index("date") if "date" in fields else 0
    lat_idx = fields.index("lat") if "lat" in fields else None
    lon_idx = fields.index("lon") if "lon" in fields else None
    examples = []
    for r in rows[:5]:
        loc = ""
        if lat_idx is not None and lon_idx is not None:
            loc = f" lat={r[lat_idx]} lon={r[lon_idx]}"
        examples.append(f"{r[date_idx]}{loc}")
    return f"NASA/JPL CNEOS Fireball API: {count} located fireball(s) in +/-1 day global window. Examples: " + " | ".join(examples)


def fetch_celestrak_decays():
    url = "https://celestrak.org/satcat/decayed-with-last.php?FORMAT=json"
    return get_json(url, "celestrak_recent_decays", use_cache=False)


def decay_summary(data, d):
    if isinstance(data, dict) and data.get("fetch_error"):
        return "fetch_error: " + data["fetch_error"], "fetch_error", []
    if not isinstance(data, list):
        return "CelesTrak recent decays returned unexpected format.", "fetch_error", []
    matches = []
    for item in data:
        ds = item.get("DECAY_DATE") or item.get("DECAY") or item.get("decayDate")
        if not ds:
            continue
        try:
            dd = datetime.fromisoformat(ds[:10]).date()
        except Exception:
            continue
        if abs((dd - d).days) <= 1:
            matches.append(item)
    if matches:
        names = []
        for m in matches[:8]:
            names.append(f"{m.get('SATNAME') or m.get('OBJECT_NAME')} decay={m.get('DECAY_DATE') or m.get('DECAY')}")
        return "CelesTrak recent decays +/-1 day: " + " | ".join(names), "fetched_recent_match", matches
    return "CelesTrak recent-decay feed has no matching decay within +/-1 day. Note: feed only covers recent decays, not historical archive.", "fetched_no_recent_match", []


def retry_launch(d):
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - timedelta(days=1)
    end = start + timedelta(days=3)
    params = {
        "window_start__gte": start.isoformat().replace("+00:00", "Z"),
        "window_start__lte": end.isoformat().replace("+00:00", "Z"),
        "limit": "20",
    }
    url = "https://ll.thespacedevs.com/2.3.0/launches/?" + urllib.parse.urlencode(params)
    return get_json(url, f"launches_retry_{d}", use_cache=False, sleep=1.0)


def launch_summary(data):
    if data.get("fetch_error") or data.get("detail"):
        return "fetch_error: " + str(data.get("fetch_error") or data.get("detail")), "fetch_error"
    results = data.get("results") or []
    if not results:
        return "The Space Devs: no launches in +/-1 day window.", "fetched"
    names = [f"{r.get('name')} at {r.get('window_start')} status={((r.get('status') or {}).get('name'))}" for r in results[:5]]
    return "The Space Devs launches in +/-1 day window: " + " | ".join(names), "fetched"


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT case_id,title,incident_date,incident_location FROM cases WHERE incident_date IS NOT NULL"
    ).fetchall()
    celestrak = fetch_celestrak_decays()
    for r in rows:
        d, dstatus = parse_date(r["incident_date"])
        query = {"incident_date": r["incident_date"], "parsed_date": d.isoformat() if d else None, "incident_location": r["incident_location"]}
        if d:
            fb = fetch_fireballs(d)
            fbsum = fireball_summary(fb)
            fbstatus = "fetched" if not fbsum.startswith("fetch_error") else "fetch_error"
            insert_corr(conn, r["case_id"], "meteor_fireball", fbstatus, "NASA/JPL CNEOS Fireball API", query, fb, fbsum, now)

            decsum, decstatus, decmatches = decay_summary(celestrak, d)
            insert_corr(conn, r["case_id"], "reentry_debris_recent_decay", decstatus, "CelesTrak recent decays feed", query, decmatches, decsum, now)
        else:
            insert_corr(conn, r["case_id"], "meteor_fireball", "not_queryable", "NASA/JPL CNEOS Fireball API", query, None, f"Fireball lookup not fetched: {dstatus}.", now)
            insert_corr(conn, r["case_id"], "reentry_debris_recent_decay", "not_queryable", "CelesTrak recent decays feed", query, None, f"Reentry/debris lookup not fetched: {dstatus}.", now)

        # Satellite/Starlink pass lookup requires exact time and tight Earth coordinates; current DB does not have both.
        event = conn.execute("SELECT recovered_times_json, location_precision FROM case_event_details WHERE case_id=?", (r["case_id"],)).fetchone()
        times = json.loads(event["recovered_times_json"] or "[]") if event else []
        loc_precision = event["location_precision"] if event else "unknown"
        if d and times and loc_precision not in {"broad_region", "missing", "non_earth_or_space", "known_lunar_landing_site"}:
            status = "not_fetched_missing_tle_pipeline"
            summary = "Date/time/location are partly sufficient, but historical TLE propagation pipeline is not installed/populated yet."
        else:
            status = "not_queryable_missing_time_or_coordinates"
            summary = "Starlink/satellite pass lookup not fetched: requires exact event time plus narrow Earth coordinates and historical TLEs."
        insert_corr(conn, r["case_id"], "starlink_satellite_pass", status, "CelesTrak historical TLE candidate", query, None, summary, now)

        # Historical NOTAM/training/flares/drone feeds are not available from broad public unauthenticated APIs for these events.
        insert_corr(
            conn,
            r["case_id"],
            "military_notam_training_flares_drones",
            "not_queryable_public_historical_source_missing",
            "public NOTAM/training-source candidate",
            query,
            None,
            "Not fetched: requires historical NOTAM/training/flares/drone range data, exact time/location, and often restricted military sources.",
            now,
        )

    # Retry only rows that previously hit launch fetch_error.
    errors = conn.execute(
        "SELECT c.case_id,c.incident_date FROM external_correlations e JOIN cases c USING(case_id) WHERE e.correlation_type='space_activity_launches' AND e.status='fetch_error'"
    ).fetchall()
    for r in errors:
        d, dstatus = parse_date(r["incident_date"])
        if not d:
            continue
        data = retry_launch(d)
        summary, status = launch_summary(data)
        query = {"incident_date": r["incident_date"], "parsed_date": d.isoformat(), "retry": True}
        insert_corr(conn, r["case_id"], "space_activity_launches", status, "The Space Devs Launch Library 2", query, data, summary, now)
        conn.execute(
            "UPDATE environmental_checks SET status=?, source=?, result_summary=?, checked_at=? WHERE case_id=? AND check_type='space_activity'",
            (status, "The Space Devs Launch Library 2", summary, now, r["case_id"]),
        )
        # Stop early if API says throttled; avoid hammering.
        if status == "fetch_error" and "throttled" in summary.lower():
            break

    conn.execute(
        """
        INSERT INTO pipeline_runs (
          run_time, source_base, inventory_count, ocr_document_count, video_count, image_count, notes
        )
        SELECT ?, ?, (SELECT count(*) FROM cases), (SELECT count(*) FROM hq_ocr_documents),
               (SELECT count(*) FROM videos), (SELECT count(*) FROM images),
               ?
        """,
        (now, str(BASE), "Fetched remaining external checks where possible: CNEOS fireballs, CelesTrak recent decays, Space Devs retry; marked Starlink/satellite and military NOTAM checks by queryability."),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
