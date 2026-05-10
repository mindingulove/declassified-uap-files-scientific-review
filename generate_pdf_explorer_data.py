import sqlite3
import json
import os

def main():
    base_dir = os.path.dirname(__file__)
    db_path = os.path.join(base_dir, 'cases.sqlite')
    js_path = os.path.join(base_dir, 'frontend', 'pdf_data.js')
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # 1. Fetch PDF Cases
    cases = conn.execute("""
        SELECT * FROM cases 
        WHERE asset_type = 'PDF'
        ORDER BY case_id
    """).fetchall()
    
    pdf_cases = []
    for c in cases:
        cid = c["case_id"]
        
        # 2. Fetch Witness/Observation Highlights
        observations = conn.execute("""
            SELECT 
                source_page, source_quote, claim_type, witness_label, 
                directness, shape, color_brightness, motion, sound, 
                duration, sensor, page_avg_confidence
            FROM witness_matrix 
            WHERE case_id = ?
            ORDER BY source_page, page_avg_confidence DESC
        """, (cid,)).fetchall()
        
        # 3. Fetch External Correlations
        correlations = conn.execute("""
            SELECT correlation_type, status, source, result_summary
            FROM external_correlations
            WHERE case_id = ?
        """, (cid,)).fetchall()
        
        # 4. Try to locate the PDF file
        pdf_path = None
        title_slug = c["title"].lower().replace(' ', '_').replace('-', '_')
        pdf_dir = os.path.join(base_dir, 'war_ufo_downloads', 'pdf')
        if os.path.exists(pdf_dir):
            for f in os.listdir(pdf_dir):
                f_lower = f.lower().replace(' ', '_').replace('-', '_')
                if title_slug in f_lower or f_lower in title_slug:
                    pdf_path = f"./war_ufo_downloads/pdf/{f}"
                    break
        
        pdf_cases.append({
            "case_id": cid,
            "title": c["title"],
            "agency": c["agency"],
            "incident_date": c["incident_date"],
            "incident_location": c["incident_location"],
            "classification": c["classification"],
            "description": c["description"],
            "object_description": c["object_description"],
            "sensor_type": c["sensor_type"],
            "platform": c["platform"],
            "radar_iff_es_correlation": c["radar_iff_es_correlation"],
            "pdf_path": pdf_path,
            "observations": [dict(o) for o in observations],
            "correlations": [dict(corr) for corr in correlations]
        })
    
    conn.close()
    
    with open(js_path, 'w') as f:
        f.write("window.PDF_DATA = ")
        json.dump(pdf_cases, f, indent=2)
        f.write(";")
        
    print(f"Generated enriched data for {len(pdf_cases)} PDF cases.")

if __name__ == "__main__":
    main()
