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

LOCATIONS = {
    "Iraq": (33.3152, 44.3661, "Baghdad centroid proxy"),
    "Syria": (35.0, 38.5, "Syria centroid proxy"),
    "Arabian Gulf": (26.5, 52.0, "Arabian Gulf regional proxy"),
    "Arabian Sea": (15.0, 65.0, "Arabian Sea regional proxy"),
    "Gulf of Aden": (12.5, 48.0, "Gulf of Aden regional proxy"),
    "Strait of Hormuz": (26.5667, 56.25, "Strait of Hormuz regional proxy"),
    "Gulf of Oman": (24.7, 58.7, "Gulf of Oman regional proxy"),
    "Aegean Sea": (38.5, 25.0, "Aegean Sea regional proxy"),
    "Mediterranean Sea": (35.0, 18.0, "Mediterranean Sea regional proxy"),
    "Iran": (32.0, 53.0, "Iran centroid proxy"),
    "Germany": (51.1657, 10.4515, "Germany centroid proxy"),
    "Netherlands": (52.1326, 5.2913, "Netherlands centroid proxy"),
    "Azerbaijan": (40.4093, 49.8671, "Baku proxy"),
    "Detroit, MI": (42.3314, -83.0458, "Detroit city coordinate"),
    "Papua New Guinea": (-6.3150, 143.9555, "Papua New Guinea centroid proxy"),
    "Kazakhstan": (48.0196, 66.9237, "Kazakhstan centroid proxy"),
    "Georgia": (41.7151, 44.8271, "Tbilisi proxy"),
    "Turkmenistan": (37.9601, 58.3261, "Ashgabat proxy"),
    "Mexico": (23.6345, -102.5528, "Mexico centroid proxy"),
}


def get_json(url, cache_key, sleep=0.15):
    path = CACHE / f"{cache_key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    req = urllib.request.Request(url, headers={"User-Agent": "war-ufo-science-pipeline/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", errors="replace")
        data = json.loads(body)
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
    if "Late" in s or "Early" in s or "Mid" in s:
        return None, "vague_date"
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}-\d{1,2}/\d{1,2}/\d{2,4}", s):
        s = s.split("-", 1)[0]
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if not m:
        return None, "unparsed_date"
    month, day, year = map(int, m.groups())
    if year < 100:
        year += 1900 if year >= 40 else 2000
    try:
        return date(year, month, day), "ok"
    except Exception:
        return None, "invalid_date"


def location_info(loc):
    if loc in LOCATIONS:
        lat, lon, note = LOCATIONS[loc]
        return lat, lon, note
    if loc in {"Moon", "Low Earth Orbit"}:
        return None, None, "not_earth_surface_location"
    return None, None, "location_too_broad_or_unmapped"


def weather_fetch(d, lat, lon):
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "start_date": d.isoformat(),
        "end_date": d.isoformat(),
        "daily": ",".join([
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "rain_sum",
            "snowfall_sum",
            "wind_speed_10m_max",
            "wind_gusts_10m_max",
            "weather_code",
        ]),
        "timezone": "UTC",
    }
    url = "https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(params)
    return get_json(url, f"weather_{d}_{lat:.3f}_{lon:.3f}")


def moon_phase_fetch(d):
    url = f"https://aa.usno.navy.mil/api/moon/phases/date?date={d.year}-{d.month}-{d.day}&nump=4"
    return get_json(url, f"moonphase_{d}")


def launch_fetch(d):
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - timedelta(days=1)
    end = start + timedelta(days=3)
    params = {
        "window_start__gte": start.isoformat().replace("+00:00", "Z"),
        "window_start__lte": end.isoformat().replace("+00:00", "Z"),
        "limit": "20",
    }
    url = "https://ll.thespacedevs.com/2.3.0/launches/?" + urllib.parse.urlencode(params)
    return get_json(url, f"launches_{d}")


def weather_summary(data):
    if data.get("fetch_error") or data.get("error"):
        return "fetch_error: " + str(data.get("fetch_error") or data.get("reason") or data.get("error"))
    daily = data.get("daily") or {}
    if not daily:
        return "no_daily_weather_returned"
    def first(k):
        v = daily.get(k)
        return None if not v else v[0]
    return (
        f"Open-Meteo daily archive: weather_code={first('weather_code')}, "
        f"temp_min={first('temperature_2m_min')}, temp_max={first('temperature_2m_max')}, "
        f"precip={first('precipitation_sum')}, rain={first('rain_sum')}, "
        f"snow={first('snowfall_sum')}, wind_max={first('wind_speed_10m_max')}, "
        f"gust_max={first('wind_gusts_10m_max')}."
    )


def moon_summary(data, d):
    if data.get("fetch_error") or data.get("error"):
        return "fetch_error: " + str(data.get("fetch_error") or data.get("error"))
    phases = data.get("phasedata") or []
    if not phases:
        return "USNO moon phase API returned no phases."
    target = datetime(d.year, d.month, d.day)
    best = None
    best_delta = None
    for p in phases:
        try:
            pd = datetime(int(p["year"]), int(p["month"]), int(p["day"]))
        except Exception:
            continue
        delta = abs((pd - target).days)
        if best is None or delta < best_delta:
            best = p
            best_delta = delta
    if not best:
        return "USNO moon phase data unparseable."
    return f"USNO nearest primary moon phase: {best.get('phase')} on {best.get('year')}-{best.get('month')}-{best.get('day')} {best.get('time')} UTC, {best_delta} days from event date."


def launch_summary(data):
    if data.get("fetch_error") or data.get("detail"):
        return "fetch_error: " + str(data.get("fetch_error") or data.get("detail"))
    results = data.get("results") or []
    if not results:
        return "The Space Devs: no launches in +/-1 day window."
    names = []
    for r in results[:5]:
        names.append(f"{r.get('name')} at {r.get('window_start')} status={((r.get('status') or {}).get('name'))}")
    return "The Space Devs launches in +/-1 day window: " + " | ".join(names)


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS external_correlations (
          correlation_id INTEGER PRIMARY KEY AUTOINCREMENT,
          case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
          correlation_type TEXT NOT NULL,
          status TEXT NOT NULL,
          source TEXT,
          query_json TEXT,
          result_json TEXT,
          result_summary TEXT,
          fetched_at TEXT,
          UNIQUE(case_id, correlation_type, source)
        );
        """
    )
    rows = conn.execute(
        "SELECT case_id,title,asset_type,incident_date,incident_location,agency FROM cases WHERE incident_date IS NOT NULL AND incident_location IS NOT NULL"
    ).fetchall()
    for r in rows:
        d, date_status = parse_date(r["incident_date"])
        lat, lon, loc_status = location_info(r["incident_location"])
        base_query = {
            "incident_date": r["incident_date"],
            "parsed_date": d.isoformat() if d else None,
            "incident_location": r["incident_location"],
            "lat": lat,
            "lon": lon,
            "location_note": loc_status,
        }
        if d and lat is not None:
            w = weather_fetch(d, lat, lon)
            status = "fetched" if not (w.get("fetch_error") or w.get("error")) else "fetch_error"
            summary = weather_summary(w)
            conn.execute(
                """
                INSERT OR REPLACE INTO external_correlations
                (case_id,correlation_type,status,source,query_json,result_json,result_summary,fetched_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (r["case_id"], "weather", status, "Open-Meteo Archive API", json.dumps(base_query), json.dumps(w), summary, now),
            )
            conn.execute(
                "UPDATE environmental_checks SET status=?, source=?, result_summary=?, checked_at=? WHERE case_id=? AND check_type='weather'",
                (status, "Open-Meteo Archive API", summary, now, r["case_id"]),
            )
        else:
            reason = date_status if not d else loc_status
            summary = f"Weather not fetched: {reason}."
            conn.execute(
                """
                INSERT OR REPLACE INTO external_correlations
                (case_id,correlation_type,status,source,query_json,result_json,result_summary,fetched_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (r["case_id"], "weather", "not_queryable", "Open-Meteo Archive API", json.dumps(base_query), None, summary, now),
            )
            conn.execute(
                "UPDATE environmental_checks SET status=?, source=?, result_summary=?, checked_at=? WHERE case_id=? AND check_type='weather'",
                ("not_queryable", "Open-Meteo Archive API", summary, now, r["case_id"]),
            )

        if d:
            moon = moon_phase_fetch(d)
            status = "fetched" if not (moon.get("fetch_error") or moon.get("error")) else "fetch_error"
            summary = moon_summary(moon, d)
            conn.execute(
                """
                INSERT OR REPLACE INTO external_correlations
                (case_id,correlation_type,status,source,query_json,result_json,result_summary,fetched_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (r["case_id"], "astronomy_moon_phase", status, "USNO Moon Phases API", json.dumps(base_query), json.dumps(moon), summary, now),
            )
            astro_summary = summary + " Venus/meteor/satellite checks need event time and narrower sky position; not fetched from current metadata."
            conn.execute(
                "UPDATE environmental_checks SET status=?, source=?, result_summary=?, checked_at=? WHERE case_id=? AND check_type='astronomy'",
                (status, "USNO Moon Phases API", astro_summary, now, r["case_id"]),
            )
        else:
            summary = f"Astronomy not fetched: {date_status}; Venus/Moon/satellite checks require date and ideally event time."
            conn.execute(
                """
                INSERT OR REPLACE INTO external_correlations
                (case_id,correlation_type,status,source,query_json,result_json,result_summary,fetched_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (r["case_id"], "astronomy_moon_phase", "not_queryable", "USNO Moon Phases API", json.dumps(base_query), None, summary, now),
            )
            conn.execute(
                "UPDATE environmental_checks SET status=?, source=?, result_summary=?, checked_at=? WHERE case_id=? AND check_type='astronomy'",
                ("not_queryable", "USNO Moon Phases API", summary, now, r["case_id"]),
            )

        if d:
            launches = launch_fetch(d)
            status = "fetched" if not (launches.get("fetch_error") or launches.get("detail")) else "fetch_error"
            summary = launch_summary(launches)
            conn.execute(
                """
                INSERT OR REPLACE INTO external_correlations
                (case_id,correlation_type,status,source,query_json,result_json,result_summary,fetched_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (r["case_id"], "space_activity_launches", status, "The Space Devs Launch Library 2", json.dumps(base_query), json.dumps(launches), summary, now),
            )
            conn.execute(
                "UPDATE environmental_checks SET status=?, source=?, result_summary=?, checked_at=? WHERE case_id=? AND check_type='space_activity'",
                (status, "The Space Devs Launch Library 2", summary, now, r["case_id"]),
            )
        else:
            summary = f"Space activity not fetched: {date_status}."
            conn.execute(
                """
                INSERT OR REPLACE INTO external_correlations
                (case_id,correlation_type,status,source,query_json,result_json,result_summary,fetched_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (r["case_id"], "space_activity_launches", "not_queryable", "The Space Devs Launch Library 2", json.dumps(base_query), None, summary, now),
            )
            conn.execute(
                "UPDATE environmental_checks SET status=?, source=?, result_summary=?, checked_at=? WHERE case_id=? AND check_type='space_activity'",
                ("not_queryable", "The Space Devs Launch Library 2", summary, now, r["case_id"]),
            )

        # ADS-B historical data is not fetched without event time and tight bounding box.
        if d and lat is not None:
            status = "not_queryable_missing_event_time"
            summary = "ADS-B not fetched: current metadata has date and approximate region, but no event time; historical ADS-B requires timestamp and tight bounding box to avoid meaningless results."
        else:
            status = "not_queryable"
            summary = f"ADS-B not fetched: {date_status if not d else loc_status}."
        conn.execute(
            """
            INSERT OR REPLACE INTO external_correlations
            (case_id,correlation_type,status,source,query_json,result_json,result_summary,fetched_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (r["case_id"], "aviation_adsb", status, "OpenSky Network API candidate", json.dumps(base_query), None, summary, now),
        )
        conn.execute(
            "UPDATE environmental_checks SET status=?, source=?, result_summary=?, checked_at=? WHERE case_id=? AND check_type='aviation'",
            (status, "OpenSky Network API candidate", summary, now, r["case_id"]),
        )

        # Military context cannot be externally verified from public API here; populate from agency/region.
        summary = f"Military context local-only: agency={r['agency']}; region={r['incident_location']}. External NOTAM/training/flares/drones lookup not yet available."
        conn.execute(
            """
            INSERT OR REPLACE INTO external_correlations
            (case_id,correlation_type,status,source,query_json,result_json,result_summary,fetched_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (r["case_id"], "military_context", "local_context_only", "local corpus metadata", json.dumps(base_query), None, summary, now),
        )
        conn.execute(
            "UPDATE environmental_checks SET status=?, source=?, result_summary=?, checked_at=? WHERE case_id=? AND check_type='military_context'",
            ("local_context_only", "local corpus metadata", summary, now, r["case_id"]),
        )

    conn.execute(
        """
        INSERT INTO pipeline_runs (
          run_time, source_base, inventory_count, ocr_document_count, video_count, image_count, notes
        )
        SELECT ?, ?, (SELECT count(*) FROM cases), (SELECT count(*) FROM ocr_documents),
               (SELECT count(*) FROM videos), (SELECT count(*) FROM images),
               ?
        """,
        (now, str(BASE), "Fetched external weather, USNO moon phase, and launch-library correlations where date/location allowed; ADS-B marked not queryable without event time."),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
