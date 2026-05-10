import sqlite3
import json
import os
import math
from datetime import datetime, timedelta

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km
    try:
        dlat = math.radians(float(lat2) - float(lat1))
        dlon = math.radians(float(lon2) - float(lon1))
        a = math.sin(dlat / 2)**2 + math.cos(math.radians(float(lat1))) * math.cos(math.radians(float(lat2))) * math.sin(dlon / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c
    except:
        return 999999

def main():
    base_dir = os.path.dirname(__file__)
    db_path = os.path.join(base_dir, 'cases.sqlite')
    cache_dir = os.path.join(base_dir, 'external_cache')
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # 1. Load all unique launches from cache
    launches = {}
    if os.path.exists(cache_dir):
        for f in os.listdir(cache_dir):
            if f.startswith('launches_') and f.endswith('.json'):
                try:
                    with open(os.path.join(cache_dir, f), 'r') as j:
                        data = json.load(j)
                        for l in data.get('results', []):
                            launches[l['id']] = l
                except: continue
    
    print(f"Loaded {len(launches)} unique launches from cache.")

    # 2. Get cases with location
    cases = conn.execute("SELECT c.case_id, c.title, c.incident_date, m.incident_lat, m.incident_lon FROM cases c JOIN mission_data_extracts m ON c.case_id = m.case_id WHERE m.incident_lat IS NOT NULL").fetchall()
    
    # Also get cases without mission_data_extracts but with location proxies
    # (Using the LOCATIONS map from the earlier fetch script for broad region proxies)
    PROXIES = {
        "Iraq": (33.3, 44.3), "Syria": (35.0, 38.5), "Middle East": (25.0, 45.0),
        "Arabian Gulf": (26.5, 52.0), "Greece": (38.0, 23.0), "Western United States": (38.0, -110.0)
    }
    
    other_cases = conn.execute("SELECT case_id, title, incident_date, incident_location FROM cases WHERE incident_date IS NOT NULL").fetchall()
    
    matches = 0
    for c in list(cases) + list(other_cases):
        cid = c['case_id']
        c_date_str = c['incident_date']
        if not c_date_str: continue
        
        # Parse case date
        try:
            # Handle MM/DD/YY or YYYY-MM-DD
            if '-' in c_date_str:
                c_date = datetime.strptime(c_date_str, "%Y-%m-%d")
            else:
                parts = c_date_str.split('/')
                m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
                if y < 100: y += 1900 if y >= 40 else 2000
                c_date = datetime(y, m, d)
        except: continue
        
        c_lat, c_lon = None, None
        if 'incident_lat' in c.keys() and c['incident_lat'] is not None:
            c_lat, c_lon = c['incident_lat'], c['incident_lon']
        elif c['incident_location'] in PROXIES:
            c_lat, c_lon = PROXIES[c['incident_location']]
            
        if c_lat is None: continue

        for lid, l in launches.items():
            l_net = l.get('net')
            if not l_net: continue
            
            try:
                l_date = datetime.strptime(l_net, "%Y-%m-%dT%H:%M:%SZ")
            except: continue
            
            # 1. Temporal Check (+/- 24 hours)
            diff_hours = (l_date - c_date).total_seconds() / 3600
            if abs(diff_hours) <= 36: # Allow 36 hours for international date line / timezone issues
                
                # 2. Geospatial Proximity
                pad = l.get('pad', {})
                p_lat, p_lon = pad.get('latitude'), pad.get('longitude')
                
                dist = haversine(c_lat, c_lon, p_lat, p_lon)
                
                # Proximity Threshold: 5000km (Rocket plumes are visible from huge distances)
                if dist < 5000:
                    status = "identified" if dist < 1000 and abs(diff_hours) < 6 else "plausible"
                    summary = f"Launch Vicinity Match: {l['name']} launched from {pad.get('name')} ({dist:.0f}km away). "
                    summary += f"Time Diff: {diff_hours:.1f}h. Likely visible as twilight phenomenon or orbital maneuver."
                    
                    conn.execute(\"\"\"
                        INSERT OR REPLACE INTO external_correlations 
                        (case_id, correlation_type, status, source, result_summary, fetched_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    \"\"\", (cid, 'space_activity_vicinity', status, 'Automated Proximity Engine', summary, datetime.now().isoformat()))
                    matches += 1

    conn.commit()
    conn.close()
    print(f"Space Proximity Engine Complete: {matches} correlations established.")

if __name__ == "__main__":
    main()
