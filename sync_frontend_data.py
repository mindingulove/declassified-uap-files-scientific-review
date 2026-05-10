import sqlite3
import json
import os
import re

def main():
    base_dir = os.path.dirname(__file__)
    db_path = os.path.join(base_dir, 'cases.sqlite')
    js_path = os.path.join(base_dir, 'frontend', 'data.js')
    
    if not os.path.exists(db_path):
        print(f"Error: {db_path} not found")
        return
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # 1. Fetch Mission Data
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
    
    mission_data = {r["case_id"]: dict(r) for r in rows}
    
    # 2. Fetch Environmental Checks & External Correlations
    env_data = {}
    
    # Standard checks
    env_rows = conn.execute("""
        SELECT case_id, check_type, status, result_summary
        FROM environmental_checks
        WHERE case_id IN (SELECT case_id FROM videos)
    """).fetchall()
    for r in env_rows:
        cid = r["case_id"]
        if cid not in env_data: env_data[cid] = []
        env_data[cid].append({
            "check_type": r["check_type"],
            "status": r["status"],
            "result_summary": r["result_summary"]
        })
        
    # Space Activity / External Correlations (Merge into env_checks for display)
    corr_rows = conn.execute("""
        SELECT case_id, correlation_type, status, result_summary
        FROM external_correlations
        WHERE case_id IN (SELECT case_id FROM videos)
    """).fetchall()
    for r in corr_rows:
        cid = r["case_id"]
        if cid not in env_data: env_data[cid] = []
        # Avoid duplication if check_type already exists
        if not any(e['check_type'] == r['correlation_type'] for e in env_data[cid]):
            env_data[cid].append({
                "check_type": r["correlation_type"],
                "status": "fetched" if r["status"] in ('identified', 'plausible') else r["status"],
                "result_summary": r["result_summary"]
            })
        else:
            # Update existing if the new one is better
            for e in env_data[cid]:
                if e['check_type'] == r['correlation_type'] and r['status'] in ('identified', 'plausible'):
                    e['status'] = 'fetched'
                    e['result_summary'] = r['result_summary']

    conn.close()
    
    # 3. Read and Update data.js
    with open(js_path, 'r') as f:
        content = f.read()
    
    # Find the JSON part
    match = re.search(r'window\.UAP_DATA\s*=\s*({.*});', content, re.DOTALL)
    if not match:
        print("Error: Could not find UAP_DATA object in data.js")
        return
        
    data = json.loads(match.group(1))
    data['mission_data'] = mission_data
    data['env_checks'] = env_data
    
    # Convert paths back to relative if the script messed them up (though it shouldn't)
    # Ensure they stay relative.
    
    new_js = f"window.UAP_DATA = {json.dumps(data, indent=2, ensure_ascii=False)};"
    with open(js_path, 'w') as f:
        f.write(new_js)
        
    print(f"Successfully synced data.js with {len(mission_data)} mission entries and {len(env_data)} env check entries.")

if __name__ == "__main__":
    main()
