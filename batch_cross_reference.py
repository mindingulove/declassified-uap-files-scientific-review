import sqlite3
import json
import os
from datetime import datetime, timedelta
import math

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

def load_all_launches():
    all_launches = []
    cache_dir = os.path.join(os.path.dirname(__file__), 'external_cache')
    if not os.path.exists(cache_dir): return []
    for filename in os.listdir(cache_dir):
        if filename.startswith('launches_') and filename.endswith('.json'):
            with open(os.path.join(cache_dir, filename), 'r') as f:
                try:
                    data = json.load(f)
                    all_launches.extend(data.get('results', []))
                except:
                    pass
    return all_launches

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def main():
    cases = get_cases()
    launches = load_all_launches()
    
    unique_launches = {l['id']: l for l in launches if 'id' in l}.values()
    print(f"Loaded {len(cases)} cases and {len(unique_launches)} unique launches.")
    
    results = []
    for case in cases:
        case_id, title, date_str, lat, lon = case
        try:
            case_date = datetime.strptime(date_str, "%Y-%m-%d")
        except:
            continue
            
        for launch in unique_launches:
            net = launch.get('net')
            if not net: continue
            
            launch_time = datetime.strptime(net, "%Y-%m-%dT%H:%M:%SZ")
            diff = abs((launch_time - case_date).total_seconds())
            if diff < 2 * 24 * 3600:
                pad = launch.get('pad', {})
                pad_lat = pad.get('latitude')
                pad_lon = pad.get('longitude')
                dist = -1
                if pad_lat is not None and pad_lon is not None:
                    dist = haversine(float(lat), float(lon), float(pad_lat), float(pad_lon))
                
                results.append({
                    'case_id': case_id,
                    'case_title': title,
                    'case_date': date_str,
                    'launch_name': launch['name'],
                    'launch_time': net,
                    'time_diff_hours': (launch_time - case_date).total_seconds() / 3600,
                    'pad_dist_km': dist
                })
                
    results.sort(key=lambda x: abs(x['time_diff_hours']))
    print("\nTop Potential Correlations (Time & Location Proximity):")
    print(f"{'Case':<4} {'Launch Name':<40} {'Diff(h)':<8} {'Dist(km)':<8}")
    for res in results[:20]:
        print(f"{res['case_id']:<4} {res['launch_name'][:40]:<40} {res['time_diff_hours']:<8.1f} {res['pad_dist_km']:<8.0f}")

if __name__ == "__main__":
    main()
