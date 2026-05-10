import os
#!/usr/bin/env python3
"""
Append mission_data and environmental_checks to the existing data.js,
so the frontend can display them without a full regeneration.

Also back-fills incident_date in cases table where the mission PDF gives us one,
then re-runs cached weather/moon/satellite lookups for those cases.
"""

import sqlite3, json, re, os
from pathlib import Path

DB = "./cases.sqlite"
DATA_JS = "./frontend/data.js"

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # ── 1. Build mission_data keyed by video case_id ─────────────────────────
    # Join via paired_pdf → source_file match
    rows = conn.execute("""
        SELECT
            c.case_id,
            m.platform_altitude_ft,
            m.platform_altitude_m,
            m.platform_speed_ktas,
            m.platform_speed_kmh,
            m.uap_velocity_mph_low,
            m.uap_velocity_mph_high,
            m.uap_velocity_kmh_low,
            m.uap_velocity_kmh_high,
            m.uap_altitude_m,
            m.slant_range_nm,
            m.slant_range_m,
            m.sensor_pod,
            m.sensor_fov_deg,
            m.thermal_signature,
            m.observer_assessment,
            m.operation,
            m.mission_type,
            c.paired_pdf
        FROM cases c
        JOIN videos v ON v.case_id = c.case_id
        JOIN mission_data_extracts m ON (
            m.source_file LIKE '%' || replace(lower(c.paired_pdf), '-', '_') || '%'
            OR m.source_file LIKE '%' || lower(c.paired_pdf) || '%'
        )
        WHERE c.paired_pdf IS NOT NULL
        ORDER BY c.case_id
    """).fetchall()

    mission_data = {}
    for r in rows:
        mission_data[r["case_id"]] = dict(r)

    print(f"Mission data mapped for {len(mission_data)} video cases: {sorted(mission_data.keys())}")

    # ── 2. Build environmental_checks keyed by video case_id ─────────────────
    env_rows = conn.execute("""
        SELECT e.case_id, e.check_type, e.status, e.result_summary, e.checked_at
        FROM environmental_checks e
        WHERE e.case_id IN (SELECT case_id FROM videos)
        ORDER BY e.case_id, e.check_type
    """).fetchall()

    env_data = {}
    for r in env_rows:
        cid = r["case_id"]
        if cid not in env_data:
            env_data[cid] = []
        env_data[cid].append({
            "check_type": r["check_type"],
            "status": r["status"],
            "result_summary": r["result_summary"],
        })

    # ── 3. Patch data.js ─────────────────────────────────────────────────────
    content = Path(DATA_JS).read_text()
    # Strip trailing semicolon and closing brace
    content = content.rstrip()
    if content.endswith(';'):
        content = content[:-1]
    # The data.js ends with ...}  (closing brace of the UAP_DATA object)
    # We inject two new keys before that closing brace.
    assert content.endswith('}'), f"Unexpected end: {content[-20:]!r}"
    content = content[:-1]  # strip the closing }

    patch = (
        f', "mission_data": {json.dumps(mission_data, ensure_ascii=False)}'
        f', "env_checks": {json.dumps(env_data, ensure_ascii=False)}'
        f'}};'
    )
    Path(DATA_JS).write_text(content + patch)
    print(f"data.js patched — {len(content) + len(patch)} bytes total")

    conn.close()

if __name__ == "__main__":
    main()
