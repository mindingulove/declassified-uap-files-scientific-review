#!/usr/bin/env python3
"""
Extract geometry and mission parameters from OCR'd mission report text files
and write them into cases.sqlite as mission_data_extracts rows.

Fields targeted:
  platform_altitude_ft / _m   — aircraft altitude from mission report
  platform_speed_ktas          — aircraft true airspeed
  platform_speed_kmh
  uap_velocity_mph / _kmh     — observer-estimated UAP speed
  uap_altitude_ft / _m
  sensor_pod                   — TGT pod designator
  sensor_fov_deg               — if explicitly stated
  slant_range_nm / _m          — if explicitly stated
  thermal_signature            — HOT / COLD / UNK
  observer_assessment          — e.g. Benign
  source_file
"""

import re, sqlite3, os, glob, json
from pathlib import Path

DB = "./cases.sqlite"
TEXT_DIRS = [
    "./text_layer",
    "/private/tmp/war_ufo_text",
    "./ocr_text",
]

# ── helpers ──────────────────────────────────────────────────────────────────
def first(pattern, text, group=1, flags=re.IGNORECASE):
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else None

def fl_to_m(fl_str):
    """'FL243' → metres"""
    if not fl_str:
        return None
    m = re.match(r"FL\s*(\d+)", fl_str, re.IGNORECASE)
    if m:
        return round(int(m.group(1)) * 100 * 0.3048, 1)
    m = re.match(r"(\d+)\s*ft", fl_str, re.IGNORECASE)
    if m:
        return round(int(m.group(1)) * 0.3048, 1)
    return None

def ktas_to_kmh(v):
    return round(float(v) * 1.852, 1) if v else None

def mph_to_kmh(v):
    return round(float(v) * 1.60934, 1) if v else None

def nm_to_m(v):
    return round(float(v) * 1852, 0) if v else None

# ── per-file extraction ───────────────────────────────────────────────────────
def extract(text, path):
    r = {"source_file": str(path)}

    # Platform altitude  e.g. "FL243", "24300 ft", "altitude: FL230"
    alt_raw = first(r"friendly aircraft altitude[^:]*:\s*(FL\d+|\d+\s*ft)", text) or \
              first(r"aircraft altitude[^:]*:\s*(FL\d+|\d+\s*ft)", text) or \
              first(r"\bFL(\d{2,3})\b", text, group=0)
    r["platform_altitude_raw"] = alt_raw
    r["platform_altitude_m"] = fl_to_m(alt_raw)
    if r["platform_altitude_m"]:
        r["platform_altitude_ft"] = round(r["platform_altitude_m"] / 0.3048)

    # Platform speed  e.g. "162 KTAS", "158KIAS"
    spd_raw = first(r"aircraft airspeed[^:]*:\s*(\d+(?:\.\d+)?)\s*KTAS", text) or \
              first(r"aircraft speed[^:]*:\s*(\d+(?:\.\d+)?)\s*KTAS", text) or \
              first(r"\b(\d+(?:\.\d+)?)\s*KTAS\b", text) or \
              first(r"\b(\d+(?:\.\d+)?)\s*KIAS\b", text)
    try:
        r["platform_speed_ktas"] = float(spd_raw) if spd_raw else None
    except (ValueError, TypeError):
        r["platform_speed_ktas"] = None
    r["platform_speed_kmh"] = ktas_to_kmh(r["platform_speed_ktas"])

    # UAP kinetic velocity  e.g. "320 MPH", "440 MPH"
    uap_speeds = re.findall(r"kinetic velocity[^:]*:\s*([\d.]+)\s*MPH", text, re.IGNORECASE)
    if not uap_speeds:
        uap_speeds = re.findall(r"UAP.*?([\d.]+)\s*MPH", text, re.IGNORECASE)
    if uap_speeds:
        vals = [float(v) for v in uap_speeds]
        r["uap_velocity_mph_low"] = min(vals)
        r["uap_velocity_mph_high"] = max(vals)
        r["uap_velocity_kmh_low"] = mph_to_kmh(min(vals))
        r["uap_velocity_kmh_high"] = mph_to_kmh(max(vals))

    # UAP altitude
    uap_alt = first(r"kinetic altitude[^:]*:\s*(FL\d+|\d+\s*ft|UNK)", text)
    r["uap_altitude_raw"] = uap_alt if uap_alt and uap_alt.upper() != "UNK" else None
    r["uap_altitude_m"] = fl_to_m(uap_alt)

    # Slant range  e.g. "3 NM", "3.5 NM"
    rng = first(r"\b(\d+(?:\.\d+)?)\s*NM\b", text)
    try:
        r["slant_range_nm"] = float(rng) if rng else None
    except (ValueError, TypeError):
        r["slant_range_nm"] = None
    r["slant_range_m"] = nm_to_m(r["slant_range_nm"])

    # Sensor pod
    r["sensor_pod"] = first(r"TGT Pod[^:]*:\s*([A-Z0-9/\-]+)", text)

    # Sensor FOV — rarely explicit but try
    r["sensor_fov_deg"] = first(r"FOV[^:]*:\s*([\d.]+)\s*deg", text, group=1)

    # Thermal signature
    thermal = first(r"thermal[^:]*:\s*(HOT|COLD|UNK|WARM)", text)
    r["thermal_signature"] = thermal.upper() if thermal else None

    # Observer assessment
    assessment = first(r"observer assessment[^:]*:\s*(\w+)", text)
    r["observer_assessment"] = assessment

    # Mission type / operation
    r["operation"] = first(r"operation:\s*(\S+)", text)
    r["mission_type"] = first(r"mission type:\s*(\w+)", text)

    return r

# ── map text files to case_ids via assets table ──────────────────────────────
def build_file_case_map(conn):
    mapping = {}  # filename_stem → case_id
    cur = conn.execute("SELECT case_id, filename FROM assets WHERE filename IS NOT NULL")
    for case_id, fname in cur.fetchall():
        stem = Path(fname).stem.lower()
        mapping[stem] = case_id
    # Also map by numeric prefix (e.g. "042-dow-uap-d23..." → case related to file 042)
    cur2 = conn.execute("SELECT case_id, local_path FROM assets WHERE local_path IS NOT NULL")
    for case_id, lp in cur2.fetchall():
        if lp:
            stem = Path(lp).stem.lower()
            mapping[stem] = case_id
    return mapping

def match_case_id(path, mapping, conn):
    stem = Path(path).stem.lower()
    if stem in mapping:
        return mapping[stem]
    # Try stripping numeric prefix "042-..."
    clean = re.sub(r"^\d+-", "", stem)
    if clean in mapping:
        return mapping[clean]
    # Try partial match against asset filenames
    for key, cid in mapping.items():
        if len(key) > 10 and key in stem:
            return cid
    # Last resort: look up paired_pdf in cases table
    cur = conn.execute("SELECT case_id FROM cases WHERE paired_pdf LIKE ?", (f"%{stem[:30]}%",))
    row = cur.fetchone()
    if row:
        return row[0]
    return None

# ── main ─────────────────────────────────────────────────────────────────────
def main():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mission_data_extracts (
            case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
            platform_altitude_ft REAL,
            platform_altitude_m REAL,
            platform_altitude_raw TEXT,
            platform_speed_ktas REAL,
            platform_speed_kmh REAL,
            uap_velocity_mph_low REAL,
            uap_velocity_mph_high REAL,
            uap_velocity_kmh_low REAL,
            uap_velocity_kmh_high REAL,
            uap_altitude_m REAL,
            uap_altitude_raw TEXT,
            slant_range_nm REAL,
            slant_range_m REAL,
            sensor_pod TEXT,
            sensor_fov_deg REAL,
            thermal_signature TEXT,
            observer_assessment TEXT,
            operation TEXT,
            mission_type TEXT,
            source_file TEXT,
            extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    file_map = build_file_case_map(conn)

    inserted = 0
    skipped = 0
    for text_dir in TEXT_DIRS:
        for path in sorted(glob.glob(os.path.join(text_dir, "*.txt"))):
            text = open(path, errors="replace").read()
            r = extract(text, path)

            # Only keep files with at least some useful data
            useful = any(r.get(k) for k in (
                "platform_altitude_m", "platform_speed_kmh",
                "uap_velocity_kmh_low", "slant_range_m", "sensor_pod",
                "thermal_signature"
            ))
            if not useful:
                skipped += 1
                continue

            case_id = match_case_id(path, file_map, conn)
            if not case_id:
                print(f"  [no case match] {os.path.basename(path)}")
                skipped += 1
                continue

            params = {
                "case_id": case_id,
                "platform_altitude_ft": r.get("platform_altitude_ft"),
                "platform_altitude_m": r.get("platform_altitude_m"),
                "platform_altitude_raw": r.get("platform_altitude_raw"),
                "platform_speed_ktas": r.get("platform_speed_ktas"),
                "platform_speed_kmh": r.get("platform_speed_kmh"),
                "uap_velocity_mph_low": r.get("uap_velocity_mph_low"),
                "uap_velocity_mph_high": r.get("uap_velocity_mph_high"),
                "uap_velocity_kmh_low": r.get("uap_velocity_kmh_low"),
                "uap_velocity_kmh_high": r.get("uap_velocity_kmh_high"),
                "uap_altitude_m": r.get("uap_altitude_m"),
                "uap_altitude_raw": r.get("uap_altitude_raw"),
                "slant_range_nm": r.get("slant_range_nm"),
                "slant_range_m": r.get("slant_range_m"),
                "sensor_pod": r.get("sensor_pod"),
                "sensor_fov_deg": r.get("sensor_fov_deg"),
                "thermal_signature": r.get("thermal_signature"),
                "observer_assessment": r.get("observer_assessment"),
                "operation": r.get("operation"),
                "mission_type": r.get("mission_type"),
                "source_file": r.get("source_file"),
            }
            conn.execute("""
                INSERT OR REPLACE INTO mission_data_extracts (
                    case_id, platform_altitude_ft, platform_altitude_m, platform_altitude_raw,
                    platform_speed_ktas, platform_speed_kmh,
                    uap_velocity_mph_low, uap_velocity_mph_high,
                    uap_velocity_kmh_low, uap_velocity_kmh_high,
                    uap_altitude_m, uap_altitude_raw,
                    slant_range_nm, slant_range_m,
                    sensor_pod, sensor_fov_deg,
                    thermal_signature, observer_assessment,
                    operation, mission_type, source_file
                ) VALUES (
                    :case_id, :platform_altitude_ft, :platform_altitude_m, :platform_altitude_raw,
                    :platform_speed_ktas, :platform_speed_kmh,
                    :uap_velocity_mph_low, :uap_velocity_mph_high,
                    :uap_velocity_kmh_low, :uap_velocity_kmh_high,
                    :uap_altitude_m, :uap_altitude_raw,
                    :slant_range_nm, :slant_range_m,
                    :sensor_pod, :sensor_fov_deg,
                    :thermal_signature, :observer_assessment,
                    :operation, :mission_type, :source_file
                )
            """, params)
            print(f"  case {case_id:3d}  alt={r.get('platform_altitude_m')}m  "
                  f"spd={r.get('platform_speed_kmh')}km/h  "
                  f"uap={r.get('uap_velocity_kmh_low')}-{r.get('uap_velocity_kmh_high')}km/h  "
                  f"thermal={r.get('thermal_signature')}  "
                  f"{os.path.basename(path)}")
            inserted += 1

    conn.commit()
    conn.close()
    print(f"\nDone — {inserted} records inserted/updated, {skipped} skipped.")

if __name__ == "__main__":
    main()
