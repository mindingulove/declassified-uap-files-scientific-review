import os
#!/usr/bin/env python3
import json
import sqlite3
from datetime import datetime, timezone

DB = "./cases.sqlite"


def dumps(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


APOLLO_WINDOWS = {
    "apollo12_surface": {
        "mission": "Apollo 12",
        "window_start_utc": "1969-11-19T06:54:35Z",
        "window_end_utc": "1969-11-20T14:25:47Z",
        "landing_site": "Oceanus Procellarum / Ocean of Storms",
        "coordinates": {"lat": -3.04, "lon": -23.42},
        "basis": "NASA/NSSDC landing time plus NASA surface-stay statement; PURSUE image description says lunar surface viewed from Apollo 12 landing site.",
    },
    "apollo17_surface": {
        "mission": "Apollo 17",
        "window_start_utc": "1972-12-11T19:54:57Z",
        "window_end_utc": "1972-12-14T22:54:37Z",
        "landing_site": "Taurus-Littrow",
        "coordinates": {"lat": 20.16, "lon": 30.77},
        "basis": "NASA Apollo 17 mission page landing and LM liftoff times; PURSUE image description says NASA photograph from Apollo 17 mission.",
    },
}


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS date_probability_windows (
          window_id INTEGER PRIMARY KEY AUTOINCREMENT,
          case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
          window_label TEXT NOT NULL,
          start_utc TEXT NOT NULL,
          end_utc TEXT NOT NULL,
          probability REAL NOT NULL,
          probability_model TEXT NOT NULL,
          evidence_basis TEXT NOT NULL,
          source_citations_json TEXT,
          caveats_json TEXT,
          created_at TEXT NOT NULL,
          UNIQUE(case_id, window_label)
        );
        """
    )
    cases = conn.execute(
        "SELECT case_id,title,asset_type,description FROM cases WHERE title LIKE '%Apollo 12%' OR title LIKE '%Apollo 17%' ORDER BY case_id"
    ).fetchall()
    for c in cases:
        title = c["title"] or ""
        desc = c["description"] or ""
        if "Apollo 12" in title:
            w = APOLLO_WINDOWS["apollo12_surface"]
            if c["asset_type"] == "IMG":
                prob = 0.90
                label = "apollo12_lunar_surface_stay_primary"
                model = "surface-site image prior: uniform over LM surface stay, high confidence because description says viewed from Apollo 12 landing site"
                caveats = ["exact frame time not recovered", "must compare original NASA frame ID for precise timestamp", "probability is temporal-window confidence, not object-identification confidence"]
            elif "Day 05" in desc or "Day 06" in desc:
                prob = 0.95
                label = "apollo12_transcript_elapsed_time_window"
                model = "mission elapsed time transcript prior anchored to Apollo 12 launch epoch"
                caveats = ["elapsed-time conversion should be computed precisely if exact event UTC is required"]
            else:
                prob = 0.70
                label = "apollo12_mission_context_window"
                model = "mission-context prior"
                caveats = ["record lacks enough detail for precise event timestamp"]
            source_citations = [
                "NASA Apollo 12 mission page",
                "NASA/NSSDC Apollo 12 landing time",
                "PURSUE local CSV/image description",
            ]
        elif "Apollo 17" in title:
            w = APOLLO_WINDOWS["apollo17_surface"]
            if c["asset_type"] == "IMG":
                prob = 0.85
                label = "apollo17_lunar_surface_stay_primary"
                model = "mission image prior: uniform over Apollo 17 surface stay; less than Apollo 12 because description says Apollo 17 mission image but not explicit landing-site surface view"
                caveats = ["exact NASA frame ID not recovered", "could be surface or mission-context photograph until original archival frame is matched", "probability is temporal-window confidence, not object-identification confidence"]
            elif "Day 00" in desc or "Day 02" in desc or "Day 03" in desc:
                # These observations happened before lunar landing; give the mission/transcript elapsed-time window, not surface stay.
                launch = "1972-12-07T05:33:00Z"
                label = "apollo17_transcript_elapsed_time_window"
                prob = 0.95
                model = "mission elapsed time transcript prior anchored to Apollo 17 launch epoch"
                caveats = ["not a lunar surface-stay event; transcript day/hour should be converted to exact UTC for final environmental controls"]
                conn.execute(
                    """
                    INSERT OR REPLACE INTO date_probability_windows
                    (case_id,window_label,start_utc,end_utc,probability,probability_model,evidence_basis,source_citations_json,caveats_json,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        c["case_id"], label, launch, "1972-12-10T21:12:46Z", prob, model,
                        "Apollo 17 transcript describes Day 00/02/03 mission elapsed-time observations before lunar surface operations.",
                        dumps(["NASA Apollo 17 mission page", "PURSUE local CSV description"]),
                        dumps(caveats), now,
                    ),
                )
                continue
            else:
                prob = 0.65
                label = "apollo17_mission_context_window"
                model = "mission-context prior"
                caveats = ["record lacks exact event timestamp"]
            source_citations = [
                "NASA Apollo 17 mission page",
                "PURSUE local CSV/image description",
            ]
        else:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO date_probability_windows
            (case_id,window_label,start_utc,end_utc,probability,probability_model,evidence_basis,source_citations_json,caveats_json,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                c["case_id"], label, w["window_start_utc"], w["window_end_utc"], prob, model,
                w["basis"], dumps(source_citations), dumps(caveats), now,
            ),
        )
        # Improve event detail status for Apollo image records: date is now a bounded window, location is known lunar site.
        if c["asset_type"] == "IMG":
            conn.execute(
                """
                UPDATE case_event_details
                SET date_precision='bounded_probability_window',
                    location_precision='known_lunar_landing_site',
                    environmental_query_readiness='non_earth_specialized_lookup_required',
                    note=?
                WHERE case_id=?
                """,
                (
                    "Apollo mission dates allow a bounded lunar-surface probability window. Earth weather/ADS-B do not apply; lunar lighting, mission timeline, and original frame matching are required.",
                    c["case_id"],
                ),
            )
            conn.execute(
                """
                UPDATE environmental_checks
                SET status='not_applicable_lunar_surface_window',
                    source='NASA mission timeline probability window',
                    result_summary=?
                WHERE case_id=? AND check_type IN ('weather','aviation','military_context')
                """,
                ("Earth weather, ADS-B, and terrestrial military context do not apply to lunar surface imagery.", c["case_id"]),
            )
            conn.execute(
                """
                UPDATE environmental_checks
                SET status='specialized_lunar_lookup_required',
                    source='NASA mission timeline probability window',
                    result_summary=?
                WHERE case_id=? AND check_type IN ('astronomy','space_activity')
                """,
                ("Use Apollo surface timeline, Sun angle, mission frame ID, and lunar sky geometry rather than Earth-based weather/ADS-B.", c["case_id"]),
            )

    conn.execute(
        """
        INSERT INTO pipeline_runs (
          run_time, source_base, inventory_count, ocr_document_count, video_count, image_count, notes
        )
        SELECT ?, ?, (SELECT count(*) FROM cases), (SELECT count(*) FROM hq_ocr_documents),
               (SELECT count(*) FROM videos), (SELECT count(*) FROM images),
               ?
        """,
        (now, "/tmp/war_ufo_science", "Added Apollo mission date probability windows for Apollo 12/17 records."),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
