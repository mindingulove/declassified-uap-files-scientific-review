import sqlite3
import json
import os
from datetime import datetime, timedelta

def get_cases():
    db_path = os.path.join(os.path.dirname(__file__), 'cases.sqlite')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.case_id, c.title, c.incident_date, m.incident_lat, m.incident_lon 
        FROM cases c 
        JOIN mission_data_extracts m ON c.case_id = m.case_id
        WHERE c.incident_date IS NOT NULL AND m.incident_lat IS NOT NULL
    """)
    cases = cursor.fetchall()
    conn.close()
    return cases

def load_launches(date_str):
    filename = os.path.join(os.path.dirname(__file__), 'external_cache', f'launches_{date_str}.json')
    if not os.path.exists(filename):
        return []
    with open(filename, 'r') as f:
        data = json.load(f)
        return data.get('results', [])

def main():
    cases = get_cases()
    print(f"Found {len(cases)} cases with date and location.")
    
    for case_id, title, date_str, lat, lon in cases:
        print(f"\nCase {case_id}: {title} ({date_str}) @ {lat}, {lon}")
        launches = load_launches(date_str)
        if not launches:
            print("  No launch data found in cache for this date.")
            continue
            
        for launch in launches:
            net = launch.get('net')
            name = launch.get('name')
            pad = launch.get('pad', {})
            pad_name = pad.get('name')
            pad_lat = pad.get('latitude')
            pad_lon = pad.get('longitude')
            
            try:
                launch_time = datetime.strptime(net, "%Y-%m-%dT%H:%M:%SZ")
                print(f"  Candidate Launch: {name}")
                print(f"    Time: {net}")
                print(f"    Pad: {pad_name} ({pad_lat}, {pad_lon})")
                
                if pad_lat and pad_lon:
                    dist = ((float(lat) - float(pad_lat))**2 + (float(lon) - float(pad_lon))**2)**0.5
                    print(f"    Distance from pad to incident (deg): {dist:.2f}")
            except Exception as e:
                print(f"    Error parsing launch time: {e}")

if __name__ == "__main__":
    main()
