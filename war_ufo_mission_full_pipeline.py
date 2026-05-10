#!/usr/bin/env python3
"""
Full pipeline for video-linked mission PDFs:
  1. Parse every text file for: DTG → ISO date, MGRS → lat/lon, altitude,
     platform speed, UAP velocity, thermal, observer assessment, sensor pod.
  2. Write dates + coordinates back to cases.sqlite.
  3. For video cases with a date+location, fetch:
       - Weather       (Open-Meteo historical)
       - Moon phase    (USNO API)
       - Fireballs     (NASA/JPL Fireball API)
       - Launches      (The Space Devs)
  4. Update environmental_checks table.
  5. Re-run mission_data_extracts for all video-linked cases.
  6. Regenerate data.js patch (mission_data + env_checks keys).
"""

import re, sqlite3, json, os, math, time, urllib.request, urllib.parse
from datetime import datetime, timedelta, date
from pathlib import Path

DB   = "./cases.sqlite"
TEXT = "./text_layer"
CACHE = "./external_cache"
DATA_JS = "./frontend/data.js"

# ── DTG parsing ───────────────────────────────────────────────────────────────
MONTHS = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,
           "JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}

def parse_dtg(dtg):
    """'240015:00ZOCT23' → date(2023,10,24)"""
    m = re.match(r'(\d{2})(\d{2})(\d{2}):(\d{2})Z([A-Z]{3})(\d{2})', dtg)
    if not m:
        return None
    day = int(m.group(1))
    mon = MONTHS.get(m.group(5).upper())
    yr  = 2000 + int(m.group(6))
    if not mon:
        return None
    try:
        return date(yr, mon, day)
    except ValueError:
        return None

# ── UTM zone+band → approximate lat/lon center ───────────────────────────────
def zone_band_approx(zone, band):
    """Return (lat, lon) centre of UTM zone×band cell (~100–200 km accuracy)."""
    band_ranges = {
        'C':(-80,-72),'D':(-72,-64),'E':(-64,-56),'F':(-56,-48),'G':(-48,-40),
        'H':(-40,-32),'J':(-32,-24),'K':(-24,-16),'L':(-16,-8), 'M':(-8,0),
        'N':(0,8),    'P':(8,16),   'Q':(16,24),  'R':(24,32),  'S':(32,40),
        'T':(40,48),  'U':(48,56),  'V':(56,64),  'W':(64,72),  'X':(72,84),
    }
    rng = band_ranges.get(band.upper())
    if not rng:
        return None, None
    lat = (rng[0] + rng[1]) / 2
    lon = (zone - 1) * 6 - 180 + 3
    return round(lat, 2), round(lon, 2)

# ── MGRS → lat/lon (simplified, accurate enough for env-fetching) ────────────
def mgrs_to_latlon(mgrs_str):
    """Very rough: extract GZD+square letters and central 100km-sq coords."""
    m = re.match(r'(\d{1,2})([C-X])([A-HJ-NP-Z]{2})(\d+)', mgrs_str.strip())
    if not m:
        return None, None
    zone   = int(m.group(1))
    band   = m.group(2)
    sq     = m.group(3)
    nums   = m.group(4)
    n_dig  = len(nums) // 2
    if n_dig == 0:
        return None, None
    easting_m  = int(nums[:n_dig]) * (10 ** (5 - n_dig))
    northing_m = int(nums[n_dig:]) * (10 ** (5 - n_dig))

    # Easting col letters A-Z (skip I,O) in 8-col sets per zone
    col_letters = [c for c in "ABCDEFGHJKLMNPQRSTUVWXYZ"]
    row_letters = [c for c in "ABCDEFGHJKLMNPQRSTUV"]

    col_idx = col_letters.index(sq[0]) if sq[0] in col_letters else 0
    row_idx = row_letters.index(sq[1]) if sq[1] in row_letters else 0

    # Zone easting origin (100km square columns cycle by set of 8)
    set_num = ((zone - 1) % 3) + 1
    col_origin = {1: 1, 2: 4, 3: 7}.get(set_num, 1)
    e_100km = ((col_letters.index(sq[0]) - col_letters.index("ABCDEFGHJKLMNPQRSTUVWXYZ"[(col_origin-1)])) % 8) + 1
    e_m = (e_100km - 1) * 100000 + easting_m + 100000

    # Northing: latitude band determines false northing
    band_origins = {c: i*8 for i, c in enumerate("CDEFGHJKLMNPQRSTUVWX")}
    lat_band_deg = band_origins.get(band.upper(), 0)
    row_cycle = 20 if zone % 2 == 1 else 20  # always 20
    n_100km = (row_idx + 1) * 100000 + northing_m

    # Convert UTM-like to lat/lon
    a  = 6378137.0; f = 1/298.257223563; b = a*(1-f)
    e2 = (a**2 - b**2)/a**2; ep2 = (a**2 - b**2)/b**2
    k0 = 0.9996
    E  = e_m; N = n_100km
    lon0 = math.radians((zone - 1)*6 - 180 + 3)

    M = N / k0
    mu = M / (a*(1 - e2/4 - 3*e2**2/64))
    e1 = (1 - math.sqrt(1-e2))/(1 + math.sqrt(1-e2))
    ph1 = mu + (3*e1/2 - 27*e1**3/32)*math.sin(2*mu) + \
               (21*e1**2/16 - 55*e1**4/32)*math.sin(4*mu) + \
               (151*e1**3/96)*math.sin(6*mu)
    N1 = a/math.sqrt(1-e2*math.sin(ph1)**2)
    T1 = math.tan(ph1)**2
    C1 = ep2*math.cos(ph1)**2
    R1 = a*(1-e2)/(1-e2*math.sin(ph1)**2)**1.5
    D  = (E - 500000)/(N1*k0)
    lat = ph1 - (N1*math.tan(ph1)/R1)*(D**2/2 - (5+3*T1+10*C1-4*C1**2-9*ep2)*D**4/24)
    lon = lon0 + (D - (1+2*T1+C1)*D**3/6)/math.cos(ph1)
    return round(math.degrees(lat), 4), round(math.degrees(lon), 4)

# ── HTTP helper with caching ──────────────────────────────────────────────────
def fetch_json(url, cache_key, params=None):
    cache_path = os.path.join(CACHE, cache_key + ".json")
    if os.path.exists(cache_path):
        return json.load(open(cache_path))
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "UAP-Science-Pipeline/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        with open(cache_path, "w") as f:
            json.dump(data, f)
        time.sleep(0.3)
        return data
    except Exception as e:
        print(f"  FETCH FAILED {cache_key}: {e}")
        return None

# ── Environmental fetches ─────────────────────────────────────────────────────
def fetch_weather(dt: date, lat: float, lon: float):
    key = f"weather_{dt}_{lat}_{lon}"
    return fetch_json("https://archive-api.open-meteo.com/v1/archive", key, {
        "latitude": lat, "longitude": lon,
        "start_date": str(dt), "end_date": str(dt),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                 "windspeed_10m_max,weathercode",
        "timezone": "UTC",
    })

def fetch_moonphase(dt: date):
    key = f"moonphase_{dt}"
    return fetch_json(
        f"https://api.usno.navy.mil/moon/phase?date={dt.month}/{dt.day}/{dt.year}&nump=4",
        key
    )

def fetch_fireballs(dt: date):
    key = f"fireball_{dt}"
    d1 = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
    d2 = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
    return fetch_json("https://ssd-api.jpl.nasa.gov/fireball.api", key, {
        "date-min": d1, "date-max": d2
    })

def fetch_launches(dt: date):
    key = f"launches_{dt}"
    d1 = (dt - timedelta(days=1)).isoformat()
    d2 = (dt + timedelta(days=1)).isoformat()
    return fetch_json("https://ll.thespacedevs.com/2.3.0/launches/", key, {
        "window_start__gte": d1 + "T00:00:00Z",
        "window_start__lte": d2 + "T23:59:59Z",
        "limit": 10,
    })

# ── Summarise fetched data into result_summary strings ───────────────────────
def summarise_weather(data):
    if not data or "daily" not in data:
        return "Weather API returned no data."
    d = data["daily"]
    codes = d.get("weathercode", [None])
    wc = codes[0] if codes else None
    tmax = d.get("temperature_2m_max", [None])[0]
    tmin = d.get("temperature_2m_min", [None])[0]
    rain = d.get("precipitation_sum", [None])[0]
    wind = d.get("windspeed_10m_max", [None])[0]
    return (f"WMO code {wc}; temp {tmin}–{tmax}°C; "
            f"precip {rain}mm; max wind {wind}km/h")

def summarise_moon(data):
    if not data or "phasedata" not in data:
        return "Moon phase API returned no data."
    phases = data["phasedata"]
    if not phases:
        return "No moon phase data."
    p = phases[0]
    return f"Nearest moon phase: {p['phase']} on {p['year']}-{p['month']:02d}-{p['day']:02d} at {p['time']} UTC"

def summarise_fireballs(data):
    if not data:
        return "Fireball API returned no data."
    count = int(data.get("count", 0))
    if count == 0:
        return "No fireballs logged ±1 day."
    fields = data.get("fields", [])
    rows = data.get("data", [])[:3]
    parts = []
    for row in rows:
        rd = dict(zip(fields, row))
        parts.append(f"{rd.get('date','')} energy={rd.get('energy','')}GJ")
    return f"{count} fireball(s) ±1 day: {'; '.join(parts)}"

def summarise_launches(data):
    if not data:
        return "Launch API returned no data."
    results = data.get("results", [])
    if not results:
        return "No launches ±1 day."
    parts = [f"{r['name']} at {r.get('window_start','?')[:16]}Z status={r['status']['name']}"
             for r in results[:3]]
    return f"{data.get('count',0)} launch(es) ±1 day: {'; '.join(parts)}"

# ── Field extractor for mission text ─────────────────────────────────────────
def extract_fields(text):
    """Return dict of extracted fields from a mission report text."""
    r = {}

    # First takeoff DTG → incident date
    dtgs = re.findall(r'\d{6}:\d{2}Z[A-Z]{3}\d{2}', text)
    for dtg in dtgs:
        d = parse_dtg(dtg)
        if d:
            r["incident_date"] = d.isoformat()
            r["_parsed_dtg"] = dtg
            break

    # All kinetic velocities
    vel_mph = [float(v) for v in re.findall(r'Kinetic Velocity:\s*([\d.]+)\s*MPH', text, re.IGNORECASE)]
    if vel_mph:
        r["uap_velocity_mph_low"]  = min(vel_mph)
        r["uap_velocity_mph_high"] = max(vel_mph)
        r["uap_velocity_kmh_low"]  = round(min(vel_mph)*1.60934, 1)
        r["uap_velocity_kmh_high"] = round(max(vel_mph)*1.60934, 1)

    # Platform altitude
    fl = re.search(r'\bFL(\d{2,3})\b', text)
    if fl:
        ft = int(fl.group(1)) * 100
        r["platform_altitude_ft"] = ft
        r["platform_altitude_m"]  = round(ft * 0.3048, 1)
        r["platform_altitude_raw"] = fl.group(0)

    # Platform speed
    ktas = re.search(r'(?:Friendly Aircraft Speed|Aircraft Airspeed)[^\n]*?(\d{3,4})\s*KTAS', text, re.IGNORECASE)
    if not ktas:
        ktas = re.search(r'\b(\d{3,4})\s*KTAS\b', text)
    if ktas:
        r["platform_speed_ktas"] = float(ktas.group(1))
        r["platform_speed_kmh"]  = round(float(ktas.group(1))*1.852, 1)

    # Thermal
    th = re.search(r'UAP Signatures[^:]*:\s*(HOT|COLD|UNK|WARM)', text, re.IGNORECASE)
    if th:
        r["thermal_signature"] = th.group(1).upper()

    # Observer assessment
    oa = re.search(r'Observer Assessment[^:]*:\s*(\w+)', text, re.IGNORECASE)
    if oa:
        r["observer_assessment"] = oa.group(1)

    # Sensor pod
    pod = re.search(r'TGT Pod[^:]*:\s*([A-Z0-9/\-]+)', text, re.IGNORECASE)
    if pod:
        r["sensor_pod"] = pod.group(1)

    # Operation
    op = re.search(r'Operation:\s*(OP\s+\w+|\w+)', text, re.IGNORECASE)
    if op:
        r["operation"] = op.group(1).strip()

    # Mission type
    mt = re.search(r'Mission Type:\s*(\w+)', text, re.IGNORECASE)
    if mt:
        r["mission_type"] = mt.group(1)

    # MGRS coordinates → lat/lon (take first good-looking one)
    mgrs_hits = re.findall(r'\b(\d{2}[A-Z]{2,3}\d{6,10})\b', text)
    for mg in mgrs_hits:
        lat, lon = mgrs_to_latlon(mg)
        if lat and -90 < lat < 90 and -180 < lon < 180:
            r["lat"] = lat
            r["lon"] = lon
            r["mgrs"] = mg
            break

    # Fallback: extract zone+band from any partial MGRS reference
    # (OCR often garbles the easting/northing digits but preserves zone+band+square prefix)
    if "lat" not in r:
        # Require word boundary + exactly 2 zone digits to avoid greedily matching mid-word
        partial = re.search(
            r'(?:Aircraft Location|Friendly Aircraft Location|Start Point|First Coord|'
            r'Friendly Aircraft Altitude)[^:]*:[ \t]*\b(\d{2})([C-X])',
            text, re.IGNORECASE
        )
        if not partial:
            # Any clear 2-digit zone+band in the text
            partial = re.search(r'\b(\d{2})([C-X])[A-HJ-NP-Z]{2}', text)
        if partial:
            approx_lat, approx_lon = zone_band_approx(int(partial.group(1)), partial.group(2))
            if approx_lat:
                r["lat"] = approx_lat
                r["lon"] = approx_lon
                r["mgrs"] = f"approx_{partial.group(1)}{partial.group(2)}"

    return r

# ── Tesseract OCR for scanned PDFs ───────────────────────────────────────────
def ocr_pdf(pdf_path):
    """Convert PDF to images and run Tesseract, return combined text."""
    import subprocess, tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        img_base = os.path.join(tmpdir, "page")
        subprocess.run(["pdftoppm", "-r", "200", "-png", pdf_path, img_base],
                       check=True, capture_output=True)
        pages = sorted(f for f in os.listdir(tmpdir) if f.endswith(".png"))
        texts = []
        for pg in pages:
            result = subprocess.run(
                ["tesseract", os.path.join(tmpdir, pg), "stdout", "-l", "eng", "--psm", "6"],
                capture_output=True, text=True)
            texts.append(result.stdout)
        return "\n".join(texts)

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # Ensure mission_data_extracts table exists (from previous script)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mission_data_extracts (
            case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
            platform_altitude_ft REAL, platform_altitude_m REAL, platform_altitude_raw TEXT,
            platform_speed_ktas REAL, platform_speed_kmh REAL,
            uap_velocity_mph_low REAL, uap_velocity_mph_high REAL,
            uap_velocity_kmh_low REAL, uap_velocity_kmh_high REAL,
            uap_altitude_m REAL, uap_altitude_raw TEXT,
            slant_range_nm REAL, slant_range_m REAL,
            sensor_pod TEXT, sensor_fov_deg REAL,
            thermal_signature TEXT, observer_assessment TEXT,
            operation TEXT, mission_type TEXT,
            incident_lat REAL, incident_lon REAL, incident_mgrs TEXT,
            source_file TEXT,
            extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Add lat/lon columns if missing
    for col, typ in [("incident_lat","REAL"),("incident_lon","REAL"),("incident_mgrs","TEXT")]:
        try:
            conn.execute(f"ALTER TABLE mission_data_extracts ADD COLUMN {col} {typ}")
        except Exception:
            pass
    conn.commit()

    # Build doc_num → [(case_id, paired_pdf)] map for video cases
    rows = conn.execute("""
        SELECT c.case_id, c.paired_pdf
        FROM cases c
        WHERE c.case_id IN (SELECT case_id FROM videos)
          AND c.paired_pdf IS NOT NULL
        ORDER BY c.case_id
    """).fetchall()

    # doc_num → list of case_ids
    doc_cases = {}
    for r in rows:
        m = re.search(r'd(\d+)', r["paired_pdf"], re.IGNORECASE)
        if m:
            dn = m.group(1)
            doc_cases.setdefault(dn, []).append(r["case_id"])

    pdf_dir = "/private/tmp/war_ufo_downloads/pdf"

    for doc_num, case_ids in sorted(doc_cases.items()):
        # Find text file
        txt_files = [f for f in os.listdir(TEXT) if re.search(rf'-d{doc_num}-', f, re.IGNORECASE)]
        if not txt_files:
            print(f"D{doc_num}: no text file, skipping"); continue

        txt_path = os.path.join(TEXT, txt_files[0])
        text = open(txt_path, errors="replace").read()

        # If text is very sparse, try OCR
        if len(text.strip()) < 200:
            pdf_matches = [f for f in os.listdir(pdf_dir)
                           if re.search(rf'-d{doc_num}-', f, re.IGNORECASE)]
            if pdf_matches:
                pdf_path = os.path.join(pdf_dir, pdf_matches[0])
                print(f"D{doc_num}: sparse text ({len(text)}c), running Tesseract on {pdf_path}")
                text = ocr_pdf(pdf_path)
                # Save OCR result
                ocr_path = txt_path.replace(".txt", ".ocr.txt")
                open(ocr_path, "w").write(text)
                print(f"  OCR produced {len(text)} chars → {ocr_path}")
            else:
                print(f"D{doc_num}: no PDF found for OCR"); continue

        fields = extract_fields(text)
        print(f"D{doc_num} cases={case_ids}  date={fields.get('incident_date','NO')}  "
              f"lat={fields.get('lat','?')} lon={fields.get('lon','?')}  "
              f"FL={fields.get('platform_altitude_raw','NO')}  "
              f"UAP_kph={fields.get('uap_velocity_kmh_low','?')}-{fields.get('uap_velocity_kmh_high','?')}")

        for case_id in case_ids:
            # Update incident_date if missing
            cur_date = conn.execute("SELECT incident_date FROM cases WHERE case_id=?", (case_id,)).fetchone()
            if cur_date and not cur_date["incident_date"] and fields.get("incident_date"):
                conn.execute("UPDATE cases SET incident_date=?, updated_at=datetime('now') WHERE case_id=?",
                             (fields["incident_date"], case_id))
                print(f"  → case {case_id}: set incident_date={fields['incident_date']}")

            # Upsert mission_data_extracts
            conn.execute("""
                INSERT OR REPLACE INTO mission_data_extracts (
                    case_id, platform_altitude_ft, platform_altitude_m, platform_altitude_raw,
                    platform_speed_ktas, platform_speed_kmh,
                    uap_velocity_mph_low, uap_velocity_mph_high,
                    uap_velocity_kmh_low, uap_velocity_kmh_high,
                    thermal_signature, observer_assessment,
                    sensor_pod, operation, mission_type,
                    incident_lat, incident_lon, incident_mgrs,
                    source_file
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                case_id,
                fields.get("platform_altitude_ft"), fields.get("platform_altitude_m"), fields.get("platform_altitude_raw"),
                fields.get("platform_speed_ktas"), fields.get("platform_speed_kmh"),
                fields.get("uap_velocity_mph_low"), fields.get("uap_velocity_mph_high"),
                fields.get("uap_velocity_kmh_low"), fields.get("uap_velocity_kmh_high"),
                fields.get("thermal_signature"), fields.get("observer_assessment"),
                fields.get("sensor_pod"), fields.get("operation"), fields.get("mission_type"),
                fields.get("lat"), fields.get("lon"), fields.get("mgrs"),
                txt_path,
            ))

        conn.commit()

    # ── Environmental fetches for all video cases ─────────────────────────────
    print("\n── Environmental fetches ─────────────────────────────────────────")
    video_cases = conn.execute("SELECT case_id FROM videos ORDER BY case_id").fetchall()

    for row in video_cases:
        cid = row["case_id"]
        info = conn.execute("SELECT incident_date, incident_location FROM cases WHERE case_id=?", (cid,)).fetchone()
        mission = conn.execute("SELECT incident_lat, incident_lon FROM mission_data_extracts WHERE case_id=?", (cid,)).fetchone()

        inc_date_str = info["incident_date"] if info else None
        lat = mission["incident_lat"] if mission else None
        lon = mission["incident_lon"] if mission else None

        if not inc_date_str:
            print(f"  case {cid}: no date, skipping env fetch")
            continue

        try:
            inc_date = date.fromisoformat(inc_date_str)
        except Exception:
            continue

        print(f"  case {cid}: {inc_date}  lat={lat} lon={lon}")

        # Weather (needs lat/lon)
        if lat and lon:
            wd = fetch_weather(inc_date, lat, lon)
            summary = summarise_weather(wd)
            conn.execute("""
                INSERT OR REPLACE INTO environmental_checks
                    (case_id, check_type, status, result_summary, checked_at)
                VALUES (?, 'weather', 'fetched', ?, datetime('now'))
            """, (cid, summary))
            print(f"    weather: {summary[:80]}")
        else:
            # Try to parse location from incident_location text
            loc = info["incident_location"] if info else ""
            conn.execute("""
                INSERT OR REPLACE INTO environmental_checks
                    (case_id, check_type, status, result_summary, checked_at)
                VALUES (?, 'weather', 'no_coordinates', 'MGRS not extracted from PDF — no lat/lon available for weather API.', datetime('now'))
            """, (cid,))

        # Moon phase (date only)
        md = fetch_moonphase(inc_date)
        moon_sum = summarise_moon(md)
        conn.execute("""
            INSERT OR REPLACE INTO environmental_checks
                (case_id, check_type, status, result_summary, checked_at)
            VALUES (?, 'astronomy', 'fetched', ?, datetime('now'))
        """, (cid, moon_sum))
        print(f"    moon: {moon_sum[:80]}")

        # Fireballs
        fb = fetch_fireballs(inc_date)
        fb_sum = summarise_fireballs(fb)
        conn.execute("""
            INSERT OR REPLACE INTO environmental_checks
                (case_id, check_type, status, result_summary, checked_at)
            VALUES (?, 'space_activity', 'fetched', ?, datetime('now'))
        """, (cid, "Fireballs: " + fb_sum))
        print(f"    fireballs: {fb_sum[:80]}")

        # Launches
        lv = fetch_launches(inc_date)
        lv_sum = summarise_launches(lv)
        conn.execute("""
            INSERT OR REPLACE INTO environmental_checks
                (case_id, check_type, status, result_summary, checked_at)
            VALUES (?, 'space_activity', 'fetched', ?, datetime('now'))
        """, (cid, f"Launches: {lv_sum}; Fireballs: {fb_sum}"))

        conn.commit()

    conn.close()

    # ── Regenerate data.js patch ───────────────────────────────────────────────
    print("\n── Patching data.js ──────────────────────────────────────────────")
    import subprocess
    result = subprocess.run(["python3", "/private/tmp/war_ufo_add_mission_data_to_js.py"],
                            capture_output=True, text=True)
    print(result.stdout.strip())
    if result.returncode != 0:
        print("PATCH ERROR:", result.stderr[:300])

    print("\nDone.")

if __name__ == "__main__":
    main()
