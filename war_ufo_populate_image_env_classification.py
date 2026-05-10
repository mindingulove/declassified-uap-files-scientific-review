import os
#!/usr/bin/env python3
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent
DB = BASE / "cases.sqlite"


def j(v, default=None):
    if not v:
        return default
    try:
        return json.loads(v)
    except Exception:
        return default


def dumps(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def sips_metadata(path):
    try:
        p = subprocess.run(["sips", "-g", "all", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
    except Exception as e:
        return {"error": str(e)}
    meta = {"sips_returncode": p.returncode}
    for line in p.stdout.splitlines():
        if ":" in line and not line.strip().startswith("/"):
            k, v = line.strip().split(":", 1)
            meta[k.strip()] = v.strip()
    return meta


def resolve_asset_path(path):
    p = Path(path)
    if p.exists():
        return str(p)
    marker = "war_ufo_downloads/img/"
    s = str(path)
    if marker in s:
        candidate = BASE / marker / s.split(marker, 1)[1]
        if candidate.exists():
            return str(candidate)
    return str(p)


def analyze_image(path):
    path = resolve_asset_path(path)
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        return {"read_error": "cv2_imread_failed"}
    if img.ndim == 2:
        gray = img
        channels = 1
    else:
        channels = img.shape[2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    mean = float(np.mean(gray))
    std = float(np.std(gray))
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    abs_lap = np.abs(lap)
    lap_var = float(lap.var())
    lap_mean_abs = float(np.mean(abs_lap))
    lap_p95_abs = float(np.percentile(abs_lap, 95))
    lap_high_ratio = float(np.mean(abs_lap >= max(15.0, lap_p95_abs)))
    if lap_var < 30:
        lap_focus_class = "low_edge_detail_or_blurry"
    elif lap_var < 120:
        lap_focus_class = "moderate_edge_detail"
    else:
        lap_focus_class = "high_edge_detail"
    bright_ratio = float(np.mean(gray >= 245))
    dark_ratio = float(np.mean(gray <= 10))
    edges = cv2.Canny(gray, 80, 160)
    edge_density = float(np.mean(edges > 0))
    # Tiny saturated connected components are useful artifact candidates in lunar/scan imagery.
    _, thresh = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY)
    nlabels, labels, stats, _ = cv2.connectedComponentsWithStats(thresh, connectivity=8)
    small_bright = 0
    large_bright = 0
    for i in range(1, nlabels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if 1 <= area <= 25:
            small_bright += 1
        elif area > 25:
            large_bright += 1
    return {
        "width": w,
        "height": h,
        "channels": channels,
        "gray_mean": mean,
        "gray_std": std,
        "laplacian_variance": lap_var,
        "laplacian_mean_abs": lap_mean_abs,
        "laplacian_p95_abs": lap_p95_abs,
        "laplacian_high_response_ratio": lap_high_ratio,
        "laplacian_focus_class": lap_focus_class,
        "bright_pixel_ratio": bright_ratio,
        "dark_pixel_ratio": dark_ratio,
        "edge_density": edge_density,
        "small_bright_components": small_bright,
        "large_bright_components": large_bright,
    }


def artifact_flags(case, metrics, risk_flags):
    title = (case["title"] or "").lower()
    desc = (case["description"] or "").lower()
    flags = []
    if "nasa" in title or "apollo" in title or case["incident_location"] == "Moon":
        flags += ["reseau_marks_possible", "film_grain_possible", "dust_or_scan_artifact_possible", "archival_original_required"]
    if "fbi photo" in title:
        flags += ["annotation_or_crop_possible", "scan_artifact_possible", "archival_original_required"]
    if risk_flags.get("annotated_or_highlighted"):
        flags.append("annotation_effect_possible")
    if metrics.get("small_bright_components", 0) > 50:
        flags.append("many_tiny_bright_components_possible_stars_grain_or_dust")
    if metrics.get("laplacian_variance", 0) < 30:
        flags.append("low_sharpness_limits_object_boundary_claims")
    if metrics.get("laplacian_high_response_ratio", 0) > 0.08:
        flags.append("dense_high_frequency_edges_possible_annotation_scan_or_grain")
    if metrics.get("bright_pixel_ratio", 0) > 0.02:
        flags.append("saturation_or_highlight_regions_present")
    if "highlight" in desc or "annotat" in desc:
        flags.append("description_mentions_annotation")
    return sorted(set(flags))


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS image_forensics (
          case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
          local_path TEXT,
          metadata_json TEXT,
          pixel_metrics_json TEXT,
          artifact_flags_json TEXT,
          archival_comparison_status TEXT,
          exif_status TEXT,
          scale_distance_claim_status TEXT,
          review_note TEXT,
          updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS classification_framework (
          category TEXT PRIMARY KEY,
          definition TEXT NOT NULL,
          minimum_evidence TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS case_classification_rationale (
          case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
          classification TEXT NOT NULL,
          rationale TEXT NOT NULL,
          unresolved_controls_remaining_json TEXT,
          updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute("DELETE FROM classification_framework")
    framework = [
        ("identified: aircraft", "Evidence or metadata supports aircraft explanation.", "Explicit resolution, flight correlation, sensor/visual match, or analyst determination."),
        ("identified: artifact/reflection", "Evidence supports camera, scan, lens, reflection, annotation, or processing artifact.", "Original comparison or strong image/sensor artifact indicators."),
        ("identified: satellite/space/weather", "Evidence supports astronomical, satellite, reentry, meteorological, or space activity explanation.", "Date/location correlation with external source."),
        ("plausibly identified but incomplete", "A mundane hypothesis is plausible but controls are incomplete.", "Some matching features but missing decisive environmental/sensor data."),
        ("insufficient data", "The record lacks enough geometry, timing, location, witness independence, or source context.", "Missing key fields or thin context."),
        ("truly unresolved after reasonable checks", "Reasonable checks did not identify the object.", "Weather, astronomy, aviation, space, military, artifact, and witness controls completed."),
        ("high-value unresolved pending controls", "Strong enough to prioritize, but not yet through all controls.", "Multi-witness or sensor-rich record with date/location/context still needing external checks."),
        ("low evidentiary value", "Contextual, generic, duplicate, or weakly evidentiary record.", "Low score or mostly background material."),
    ]
    conn.executemany("INSERT INTO classification_framework VALUES (?,?,?)", framework)

    img_rows = conn.execute(
        """
        SELECT c.*, a.local_path, i.initial_risk_flags_json
        FROM cases c
        JOIN assets a USING(case_id)
        LEFT JOIN images i USING(case_id)
        WHERE c.asset_type='IMG'
        """
    ).fetchall()
    for row in img_rows:
        path = resolve_asset_path(row["local_path"])
        risk = j(row["initial_risk_flags_json"], {}) or {}
        meta = sips_metadata(path) if path and Path(path).exists() else {"error": "missing_local_path"}
        metrics = analyze_image(path) if path and Path(path).exists() else {"read_error": "missing_local_path"}
        flags = artifact_flags(row, metrics, risk)
        is_nasa = "nasa" in (row["title"] or "").lower() or row["incident_location"] == "Moon"
        note = (
            "Local pixel/metadata checks only. Laplacian metrics measure edge detail/sharpness, not object identity. Original unannotated archival comparison has not been performed."
        )
        if is_nasa:
            note += " NASA lunar images require original mission frame comparison and reseau/film artifact review."
        else:
            note += " FBI photos require source/original comparison to distinguish object from annotation or scan artifact."
        conn.execute(
            """
            INSERT OR REPLACE INTO image_forensics (
              case_id,local_path,metadata_json,pixel_metrics_json,artifact_flags_json,
              archival_comparison_status,exif_status,scale_distance_claim_status,review_note,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["case_id"],
                path,
                dumps(meta),
                dumps(metrics),
                dumps(flags),
                "not_completed_requires_original_unannotated_source",
                "basic_sips_metadata_extracted" if not meta.get("error") else "metadata_failed",
                "not_allowed_without_camera_geometry_and_original_source",
                note,
                now,
            ),
        )
        # Image-only records should not imply distance/scale or unresolved status yet.
        conn.execute(
            """
            UPDATE cases
            SET classification='insufficient data: still image only', updated_at=?
            WHERE case_id=?
            """,
            (now, row["case_id"]),
        )

    # Case-level rationale and remaining controls.
    rows = conn.execute(
        """
        SELECT c.*, cs.scientific_priority_score, cs.limitations_json, cs.priority_reasons_json
        FROM cases c LEFT JOIN case_scores cs USING(case_id)
        """
    ).fetchall()
    conn.execute("DELETE FROM case_classification_rationale")
    for r in rows:
        limitations = j(r["limitations_json"], []) or []
        reasons = j(r["priority_reasons_json"], []) or []
        controls = []
        if r["incident_date"] and r["incident_location"]:
            controls += ["weather", "astronomy", "aviation/ADS-B where available", "space activity", "military context"]
        else:
            controls.append("date/location recovery")
        if r["asset_type"] == "VID":
            controls += ["frame-by-frame tracking", "sensor geometry", "artifact/parallax review", "mission-report timestamp pairing"]
        if r["asset_type"] == "IMG":
            controls += ["original unannotated archival comparison", "EXIF/source metadata", "dust/grain/reseau/reflection review"]
        if "witness" in (r["witnesses"] or "").lower() or r["case_id"] in (156, 161):
            controls += ["independent witness claim separation", "timing/location consistency matrix"]
        rationale_parts = []
        if r["scientific_priority_score"] is not None:
            rationale_parts.append(f"priority_score={r['scientific_priority_score']}")
        if reasons:
            rationale_parts.append("reasons=" + "; ".join(reasons[:4]))
        if limitations:
            rationale_parts.append("limitations=" + "; ".join(limitations[:3]))
        if not rationale_parts:
            rationale_parts.append("classification based on sparse local metadata only")
        conn.execute(
            """
            INSERT INTO case_classification_rationale (
              case_id,classification,rationale,unresolved_controls_remaining_json,updated_at
            ) VALUES (?,?,?,?,?)
            """,
            (r["case_id"], r["classification"], " | ".join(rationale_parts), dumps(sorted(set(controls))), now),
        )

    conn.execute(
        """
        INSERT INTO pipeline_runs (
          run_time, source_base, inventory_count, ocr_document_count, video_count, image_count, notes
        )
        SELECT ?, ?, (SELECT count(*) FROM cases), (SELECT count(*) FROM ocr_documents),
               (SELECT count(*) FROM videos), (SELECT count(*) FROM images),
               ?
        """,
        (now, str(BASE), "Populated image_forensics with Laplacian edge/sharpness metrics, classification_framework, and case_classification_rationale from local assets."),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
