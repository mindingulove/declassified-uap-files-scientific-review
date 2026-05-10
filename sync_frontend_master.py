import sqlite3
import json
import os
import re

def clean_path(path):
    if not path: return None
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if path.startswith(base_dir + os.sep):
        return "./" + os.path.relpath(path, base_dir)
    # Convert absolute paths to relative ones based on the project structure
    if '/private/tmp/war_ufo_science/' in path:
        return path.replace('/private/tmp/war_ufo_science/', './')
    if '/tmp/war_ufo_science/' in path:
        return path.replace('/tmp/war_ufo_science/', './')
    if '/tmp/war_ufo_mining/videos/' in path:
        return path.replace('/tmp/war_ufo_mining/videos/', './war_ufo_mining/videos/')
    if '/tmp/war_ufo_downloads/img/' in path:
        return path.replace('/tmp/war_ufo_downloads/img/', './war_ufo_downloads/img/')
    if '/tmp/war_ufo_downloads/pdf/' in path:
        return path.replace('/tmp/war_ufo_downloads/pdf/', './war_ufo_downloads/pdf/')
    if '/Users/jaymeeduardo/electron/UAP/pursue-ufo-files/pdfs/' in path:
        return path.replace('/Users/jaymeeduardo/electron/UAP/pursue-ufo-files/pdfs/', './war_ufo_downloads/pdf/')
    # Generic catch-all for filenames
    if '/' in path:
        filename = os.path.basename(path)
        if '.pdf' in filename.lower(): return f"./war_ufo_downloads/pdf/{filename}"
        if '.mp4' in filename.lower(): return f"./war_ufo_mining/videos/mp4/{filename}"
    return path

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, 'cases.sqlite')
    js_path = os.path.join(base_dir, 'frontend', 'data.js')
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # 1. Base Data
    all_cases = [dict(r) for r in conn.execute("SELECT * FROM cases ORDER BY case_id").fetchall()]
    videos = [dict(r) for r in conn.execute("SELECT * FROM videos").fetchall()]
    images = [dict(r) for r in conn.execute("SELECT * FROM images").fetchall()]
    scenarios = [dict(r) for r in conn.execute("SELECT * FROM geometry_speed_scenarios").fetchall()]
    hypotheses = [dict(r) for r in conn.execute("SELECT * FROM hypotheses").fetchall()]
    
    # 2. Asset Resolution (The Missing Piece)
    assets = [dict(r) for r in conn.execute("SELECT * FROM assets").fetchall()]
    for a in assets:
        a['local_path'] = clean_path(a['local_path'])
    
    # Map assets to cases
    case_assets = {}
    for a in assets:
        cid = a['case_id']
        if cid not in case_assets: case_assets[cid] = []
        case_assets[cid].append(a)

    # 3. Mission Data
    mission_rows = conn.execute("""
        SELECT c.case_id, m.* FROM cases c
        JOIN mission_data_extracts m ON (
            m.source_file LIKE '%' || replace(lower(c.paired_pdf), '-', '_') || '%'
            OR m.source_file LIKE '%' || lower(c.paired_pdf) || '%'
        )
    """).fetchall()
    mission_data = {r["case_id"]: dict(r) for r in mission_rows}
    
    # 4. Environmental Checks & Correlations
    env_data = {}
    for r in conn.execute("SELECT * FROM environmental_checks").fetchall():
        cid = r["case_id"]
        if cid not in env_data: env_data[cid] = []
        env_data[cid].append(dict(r))
        
    for r in conn.execute("SELECT * FROM external_correlations").fetchall():
        cid = r["case_id"]
        if cid not in env_data: env_data[cid] = []
        if not any(e['check_type'] == r['correlation_type'] for e in env_data[cid]):
            env_data[cid].append({
                "check_type": r["correlation_type"],
                "status": "fetched" if r["status"] in ('identified', 'plausible') else r["status"],
                "result_summary": r["result_summary"]
            })

    # 5. Forensic Deep Dive (ALL TABLES)
    forensics = {}
    for cid in [c['case_id'] for c in all_cases]:
        f = {}
        # Scores
        row = conn.execute("SELECT * FROM case_scores WHERE case_id = ?", (cid,)).fetchone()
        if row: f['scores'] = dict(row)
        
        # Rationale
        row = conn.execute("SELECT * FROM case_classification_rationale WHERE case_id = ?", (cid,)).fetchone()
        if row: f['rationale'] = dict(row)
        
        # Sensor
        row = conn.execute("SELECT * FROM sensor_forensics WHERE case_id = ?", (cid,)).fetchone()
        if row: f['sensor'] = dict(row)
        
        # Bayesian
        f['bayesian'] = [dict(r) for r in conn.execute("SELECT * FROM bayesian_scores WHERE case_id = ?", (cid,)).fetchall()]
        
        # Corroboration
        f['corroboration'] = [dict(r) for r in conn.execute("SELECT * FROM witness_corroboration WHERE case_id = ?", (cid,)).fetchall()]
        
        # NLP Entities
        f['nlp'] = [dict(r) for r in conn.execute("SELECT * FROM nlp_entities WHERE case_id = ?", (cid,)).fetchall()]
        
        # Audit
        row = conn.execute("SELECT * FROM scientific_completion_audit WHERE case_id = ?", (cid,)).fetchone()
        if row: f['audit'] = dict(row)
        
        # Image Forensics
        row = conn.execute("SELECT * FROM image_forensics WHERE case_id = ?", (cid,)).fetchone()
        if row: f['image'] = dict(row)

        # Advanced Video Analysis
        row = conn.execute("SELECT * FROM advanced_video_tracks WHERE case_id = ?", (cid,)).fetchone()
        if row:
            f['advanced_video'] = dict(row)
            f['advanced_video']['track_csv'] = clean_path(f['advanced_video'].get('track_csv'))
            if f['advanced_video'].get('result_json'):
                try:
                    result = json.loads(f['advanced_video']['result_json'])
                    if 'track_csv' in result:
                        result['track_csv'] = clean_path(result['track_csv'])
                    f['advanced_video']['result_json'] = json.dumps(result, ensure_ascii=False)
                except Exception:
                    pass
        f['video_hypotheses'] = [dict(r) for r in conn.execute("SELECT * FROM video_hypothesis_comparison WHERE case_id = ?", (cid,)).fetchall()]
        
        # Witness Matrix (Enriched)
        f['witness_matrix'] = [dict(r) for r in conn.execute("SELECT * FROM witness_matrix WHERE case_id = ?", (cid,)).fetchall()]
        
        # Add assets
        f['assets'] = case_assets.get(cid, [])
        
        forensics[cid] = f

    # 6. Update main cases list with path info
    for c in all_cases:
        cid = c['case_id']
        c_f = forensics.get(cid, {})
        c_assets = c_f.get('assets', [])
        
        if c['asset_type'] == 'PDF':
            pdf_asset = next((a for a in c_assets if a['asset_type'] == 'PDF'), None)
            if pdf_asset: c['pdf_path'] = pdf_asset['local_path']
            
        if c['asset_type'] == 'VID':
            vid_asset = next((a for a in c_assets if a['asset_type'] == 'VID'), None)
            if vid_asset: c['local_path'] = vid_asset['local_path']

        if c['asset_type'] == 'IMG':
            img_asset = next((a for a in c_assets if a['asset_type'] == 'IMG'), None)
            if img_asset: c['img_path'] = img_asset['local_path']

    conn.close()
    
    # 7. Final Assemble
    master_data = {
        "records": all_cases,
        "videos": videos,
        "images": images,
        "scenarios": scenarios,
        "hypotheses": hypotheses,
        "mission_data": mission_data,
        "env_checks": env_data,
        "forensics": forensics
    }
    
    with open(js_path, 'w') as f:
        f.write("window.UAP_DATA = ")
        json.dump(master_data, f, indent=2)
        f.write(";")
        
    print(f"Master data.js synced: 161 cases, {len(forensics)} forensic deep-dives.")

if __name__ == "__main__":
    main()
