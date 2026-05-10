import os
#!/usr/bin/env python3
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/tmp/war_ufo_science")
DB = BASE / "cases.sqlite"


def dumps(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def norm(v):
    return (v or "").strip().lower()


def extract_times(text):
    vals = []
    # Finds 2149 hours, 22:49, 1700, 5-10 seconds, etc. Keeps likely clock times.
    for m in re.finditer(r"\b(?:at\s+|approximately\s+|about\s+)?((?:[01]?\d|2[0-3]):[0-5]\d|[01]\d[0-5]\d|2[0-3][0-5]\d)\s*(?:hours|hrs|z|utc)?\b", text or "", re.I):
        val = m.group(1)
        if re.fullmatch(r"(19|20)\d{2}", val):
            continue
        vals.append(val)
    return vals


def extract_durations(text):
    vals = []
    for m in re.finditer(r"\b(\d+\s*(?:to|-|—)\s*\d+\s*(?:seconds?|minutes?|hours?)|\d+\s*(?:seconds?|minutes?|hours?))\b", text or "", re.I):
        vals.append(m.group(1))
    return vals


def directness_rank(v):
    if v == "direct_or_interviewed_observation":
        return 2
    if v and v != "not_assessed":
        return 1
    return 0


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS case_event_details (
          case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
          recovered_times_json TEXT,
          recovered_durations_json TEXT,
          recovered_locations_json TEXT,
          recovered_sensors_json TEXT,
          date_precision TEXT,
          location_precision TEXT,
          event_time_precision TEXT,
          environmental_query_readiness TEXT,
          note TEXT,
          updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS witness_corroboration (
          corroboration_id INTEGER PRIMARY KEY AUTOINCREMENT,
          case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
          feature_key TEXT NOT NULL,
          claim_count INTEGER NOT NULL,
          page_count INTEGER NOT NULL,
          direct_claim_count INTEGER NOT NULL,
          possible_independent_count INTEGER NOT NULL,
          source_pages_json TEXT,
          representative_quotes_json TEXT,
          machine_corroboration_score REAL,
          status TEXT,
          UNIQUE(case_id, feature_key)
        );

        CREATE TABLE IF NOT EXISTS scientific_completion_audit (
          case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
          database_complete INTEGER,
          provenance_complete INTEGER,
          ocr_complete INTEGER,
          hq_ocr_complete INTEGER,
          video_analysis_complete INTEGER,
          image_analysis_complete INTEGER,
          witness_matrix_complete INTEGER,
          witness_human_review_complete INTEGER,
          environmental_complete INTEGER,
          classification_final INTEGER,
          missing_items_json TEXT,
          updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS missing_data_requests (
          request_id INTEGER PRIMARY KEY AUTOINCREMENT,
          case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
          field_needed TEXT NOT NULL,
          reason TEXT NOT NULL,
          priority INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          UNIQUE(case_id, field_needed)
        );
        """
    )

    conn.execute("DELETE FROM witness_corroboration")
    conn.execute("DELETE FROM scientific_completion_audit")
    conn.execute("DELETE FROM missing_data_requests")

    cases = conn.execute("SELECT * FROM cases").fetchall()
    for c in cases:
        cid = c["case_id"]
        claims = conn.execute("SELECT * FROM witness_matrix WHERE case_id=?", (cid,)).fetchall()
        times = set()
        durations = set()
        locations = set()
        sensors = set()
        for w in claims:
            quote = w["source_quote"] or ""
            times.update(extract_times(quote))
            durations.update(extract_durations(quote))
            if w["time_stated"]:
                times.add(w["time_stated"])
            if w["duration"]:
                durations.add(w["duration"])
            if w["location_stated"]:
                locations.add(w["location_stated"])
            if w["sensor"]:
                sensors.add(w["sensor"])

        date = c["incident_date"] or ""
        loc = c["incident_location"] or ""
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", date):
            date_precision = "day"
        elif re.fullmatch(r"\d{4}", date):
            date_precision = "year"
        elif date.lower().startswith(("late", "early", "mid")):
            date_precision = "vague_period"
        elif date:
            date_precision = "partial_or_range"
        else:
            date_precision = "missing"
        if loc in {"Iraq", "Syria", "United States", "Western United States", "Arabian Gulf", "Arabian Sea", "Aegean Sea", "Middle East"}:
            loc_precision = "broad_region"
        elif loc in {"Moon", "Low Earth Orbit"}:
            loc_precision = "non_earth_or_space"
        elif loc:
            loc_precision = "country_or_city_or_proxy"
        else:
            loc_precision = "missing"
        time_precision = "clock_time_recovered" if times else "missing"
        readiness = "ready" if date_precision == "day" and loc_precision not in {"missing", "broad_region", "non_earth_or_space"} and times else "not_ready"
        note = "Exact environmental lookup needs day-level date, narrow Earth location, and event time. Current readiness is computed from structured and HQ OCR-derived fields."
        conn.execute(
            """
            INSERT OR REPLACE INTO case_event_details
            (case_id,recovered_times_json,recovered_durations_json,recovered_locations_json,recovered_sensors_json,
             date_precision,location_precision,event_time_precision,environmental_query_readiness,note,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cid, dumps(sorted(times)), dumps(sorted(durations)), dumps(sorted(locations)), dumps(sorted(sensors)),
                date_precision, loc_precision, time_precision, readiness, note, now,
            ),
        )

        # Feature-level witness corroboration. This is machine grouping, not final human adjudication.
        groups = defaultdict(list)
        for w in claims:
            features = []
            for key in ["shape", "color_brightness", "motion", "sensor"]:
                if w[key]:
                    features.append(f"{key}:{norm(w[key])}")
            if not features:
                continue
            for f in features:
                groups[f].append(w)
        for f, rows in groups.items():
            pages = sorted({r["source_page"] for r in rows if r["source_page"] is not None})
            direct = sum(1 for r in rows if directness_rank(r["directness"]) > 0)
            indep = sum(1 for r in rows if r["independence_status"] == "possible_independent")
            score = min(1.0, 0.1 * len(rows) + 0.15 * len(pages) + 0.2 * direct + 0.25 * indep)
            status = "machine_correlated_needs_human_review" if score >= 0.5 else "weak_machine_group"
            quotes = [r["source_quote"][:250] for r in rows[:5]]
            conn.execute(
                """
                INSERT OR REPLACE INTO witness_corroboration
                (case_id,feature_key,claim_count,page_count,direct_claim_count,possible_independent_count,
                 source_pages_json,representative_quotes_json,machine_corroboration_score,status)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (cid, f, len(rows), len(pages), direct, indep, dumps(pages), dumps(quotes), score, status),
            )

        # Completion audit.
        has_asset = conn.execute("SELECT 1 FROM assets WHERE case_id=?", (cid,)).fetchone() is not None
        chain_ok = conn.execute("SELECT 1 FROM chain_of_custody WHERE case_id=? AND hash_match=1", (cid,)).fetchone() is not None
        hq_ok = conn.execute("SELECT 1 FROM hq_ocr_documents WHERE case_id=?", (cid,)).fetchone() is not None
        ocr_ok = conn.execute("SELECT 1 FROM ocr_documents WHERE case_id=?", (cid,)).fetchone() is not None
        video_ok = c["asset_type"] != "VID" or conn.execute("SELECT 1 FROM video_tracking WHERE case_id=?", (cid,)).fetchone() is not None
        image_ok = c["asset_type"] != "IMG" or conn.execute("SELECT 1 FROM image_forensics WHERE case_id=?", (cid,)).fetchone() is not None
        witness_ok = len(claims) > 0
        human_done = conn.execute("SELECT 1 FROM witness_matrix WHERE case_id=? AND review_status!='needs_human_review'", (cid,)).fetchone() is not None
        env_statuses = [r["status"] for r in conn.execute("SELECT status FROM environmental_checks WHERE case_id=?", (cid,)).fetchall()]
        env_complete = bool(env_statuses) and all(s == "fetched" for s in env_statuses)
        final_class = c["classification"] in {
            "identified: aircraft",
            "identified: artifact/reflection",
            "identified: satellite/space/weather",
            "truly unresolved after reasonable checks",
        }
        missing = []
        if c["asset_type"] == "PDF" and not (ocr_ok or hq_ok):
            missing.append("OCR/transcription")
        if hq_ok and not human_done:
            missing.append("human validation of witness matrix")
        if not env_complete:
            missing.append("complete environmental controls")
        if c["asset_type"] == "VID":
            missing.append("verified target track and sensor geometry")
        if c["asset_type"] == "IMG":
            missing.append("original archival image comparison")
        if not final_class:
            missing.append("final classification after controls")
        conn.execute(
            """
            INSERT OR REPLACE INTO scientific_completion_audit
            (case_id,database_complete,provenance_complete,ocr_complete,hq_ocr_complete,video_analysis_complete,
             image_analysis_complete,witness_matrix_complete,witness_human_review_complete,environmental_complete,
             classification_final,missing_items_json,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cid, 1 if has_asset else 0, 1 if chain_ok else 0, 1 if ocr_ok else 0, 1 if hq_ok else 0,
                1 if video_ok else 0, 1 if image_ok else 0, 1 if witness_ok else 0, 1 if human_done else 0,
                1 if env_complete else 0, 1 if final_class else 0, dumps(missing), now,
            ),
        )

        priority = 10 if c["classification"] == "high-value unresolved pending controls" else 5
        if date_precision != "day":
            conn.execute("INSERT OR IGNORE INTO missing_data_requests (case_id,field_needed,reason,priority) VALUES (?,?,?,?)",
                         (cid, "exact_event_date", f"Current date precision is {date_precision}; needed for astronomy/ADS-B/weather.", priority))
        if loc_precision in {"missing", "broad_region", "non_earth_or_space"}:
            conn.execute("INSERT OR IGNORE INTO missing_data_requests (case_id,field_needed,reason,priority) VALUES (?,?,?,?)",
                         (cid, "narrow_event_location_or_coordinates", f"Current location precision is {loc_precision}; needed for ADS-B/satellite/weather.", priority))
        if not times and c["asset_type"] in {"PDF", "VID"}:
            conn.execute("INSERT OR IGNORE INTO missing_data_requests (case_id,field_needed,reason,priority) VALUES (?,?,?,?)",
                         (cid, "event_time_or_time_window", "Needed for ADS-B, satellite passes, Venus/Moon altitude, and military activity checks.", priority))
        if c["asset_type"] == "VID":
            conn.execute("INSERT OR IGNORE INTO missing_data_requests (case_id,field_needed,reason,priority) VALUES (?,?,?,?)",
                         (cid, "sensor_geometry_fov_platform_pose", "Needed for photogrammetry and angular velocity.", priority))
        if c["asset_type"] == "IMG":
            conn.execute("INSERT OR IGNORE INTO missing_data_requests (case_id,field_needed,reason,priority) VALUES (?,?,?,?)",
                         (cid, "original_unannotated_archival_image", "Needed to test dust, film grain, reseau marks, scan artifacts, and annotation effects.", priority))

    conn.execute(
        """
        INSERT INTO pipeline_runs (
          run_time, source_base, inventory_count, ocr_document_count, video_count, image_count, notes
        )
        SELECT ?, ?, (SELECT count(*) FROM cases), (SELECT count(*) FROM hq_ocr_documents),
               (SELECT count(*) FROM videos), (SELECT count(*) FROM images),
               ?
        """,
        (now, str(BASE), "Added event-detail recovery, witness-corroboration groups, completion audit, and missing-data requests."),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
