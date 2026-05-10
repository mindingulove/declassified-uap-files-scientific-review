import os
#!/usr/bin/env python3
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

BASE = Path("/tmp/war_ufo_science")
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


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_sensor_mode(title, desc, video_title=""):
    blob = f"{title} {desc} {video_title}".lower()
    modes = []
    for needle, label in [
        ("infrared", "IR"),
        ("flir", "FLIR"),
        ("short-wave infrared", "SWIR"),
        ("swir", "SWIR"),
        ("electro-optical", "EO"),
        ("nvg", "NVG"),
        ("radar", "RADAR"),
        ("iff", "IFF"),
    ]:
        if needle in blob and label not in modes:
            modes.append(label)
    return modes


def video_track(path, max_samples=90):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return {"status": "failed_open"}
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if fps else 0
    if frame_count <= 0:
        return {"status": "no_frames", "fps": fps, "frame_count": frame_count}
    sample_count = min(max_samples, max(3, int(duration))) if duration else min(max_samples, frame_count)
    idxs = np.linspace(0, frame_count - 1, sample_count).astype(int)
    positions = []
    brightness = []
    prev_gray = None
    flow_mags = []
    feature_counts = []
    for idx in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (320, 180), interpolation=cv2.INTER_AREA)
        brightness.append(float(np.mean(small)))
        # Track the strongest compact bright or dark contrast candidate, not a claimed object.
        blur = cv2.GaussianBlur(small, (5, 5), 0)
        _, bright = cv2.threshold(blur, 235, 255, cv2.THRESH_BINARY)
        _, dark = cv2.threshold(blur, 25, 255, cv2.THRESH_BINARY_INV)
        mask = cv2.bitwise_or(bright, dark)
        nlabels, labels, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
        candidates = []
        for i in range(1, nlabels):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if 3 <= area <= 1200:
                x, y = cents[i]
                candidates.append((area, float(x), float(y)))
        if candidates:
            area, x, y = max(candidates, key=lambda t: t[0])
            positions.append({"frame": int(idx), "time_s": float(idx / fps), "x_320": x, "y_180": y, "area": area})
        if prev_gray is not None:
            pts = cv2.goodFeaturesToTrack(prev_gray, maxCorners=80, qualityLevel=0.02, minDistance=8)
            if pts is not None:
                nxt, st, err = cv2.calcOpticalFlowPyrLK(prev_gray, small, pts, None)
                if nxt is not None and st is not None:
                    good_old = pts[st.flatten() == 1]
                    good_new = nxt[st.flatten() == 1]
                    if len(good_old):
                        mag = np.linalg.norm(good_new.reshape(-1, 2) - good_old.reshape(-1, 2), axis=1)
                        flow_mags.append(float(np.median(mag)))
                        feature_counts.append(int(len(good_old)))
        prev_gray = small
    cap.release()
    speeds = []
    for a, b in zip(positions, positions[1:]):
        dt = b["time_s"] - a["time_s"]
        if dt > 0:
            speeds.append(math.hypot(b["x_320"] - a["x_320"], b["y_180"] - a["y_180"]) / dt)
    return {
        "status": "sampled_tracking_complete",
        "fps": fps,
        "frame_count": frame_count,
        "duration_s": duration,
        "sampled_frames": len(idxs),
        "candidate_detections": len(positions),
        "median_candidate_speed_px_s_320w": float(np.median(speeds)) if speeds else None,
        "max_candidate_speed_px_s_320w": float(np.max(speeds)) if speeds else None,
        "median_optical_flow_px": float(np.median(flow_mags)) if flow_mags else None,
        "median_tracked_features": float(np.median(feature_counts)) if feature_counts else None,
        "mean_frame_brightness": float(np.mean(brightness)) if brightness else None,
        "positions_sample_json": positions[:20],
        "limitations": [
            "candidate tracker follows strongest compact contrast, not verified target",
            "pixel velocities are not angular velocities without FOV/sensor geometry",
            "sampled-frame pass only; manual validation required",
        ],
    }


def extract_entities(text):
    out = []
    patterns = [
        ("date", r"\b(?:\d{1,2}/\d{1,2}/\d{2,4}|19\d{2}|20\d{2}|January|February|March|April|May|June|July|August|September|October|November|December)\b"),
        ("sensor", r"\b(?:FLIR|infrared|IR|NVG|SWIR|electro-optical|EO|radar|IFF|sensor)\b"),
        ("object", r"\b(?:orb|sphere|disc|disk|object|light|UAP|UFO|balloon|aircraft|drone|satellite|meteor)\b"),
        ("motion", r"\b(?:hover(?:ing)?|accelerat\w+|moving|turn(?:ing)?|stationary|launched|tracked|pursuit|formation)\b"),
        ("location", r"\b(?:Iraq|Syria|Arabian Gulf|Gulf of Oman|Aegean Sea|Germany|Detroit|Moon|United States|Western United States|Middle East)\b"),
    ]
    for etype, pat in patterns:
        seen = set()
        for m in re.finditer(pat, text or "", flags=re.I):
            val = m.group(0)
            key = val.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((etype, val, "regex_local", 0.55))
            if len(seen) >= 20:
                break
    return out


def bayes_from_hypotheses(rows):
    vals = []
    total = 0.0
    for h in rows:
        score = h["posterior_score"] if h["posterior_score"] is not None else 0.1
        score = max(0.001, float(score))
        vals.append((h["hypothesis"], score))
        total += score
    if not total:
        return []
    return [(hyp, score / total) for hyp, score in vals]


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS video_tracking (
          case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
          method TEXT,
          status TEXT,
          sampled_frames INTEGER,
          candidate_detections INTEGER,
          median_candidate_speed_px_s REAL,
          max_candidate_speed_px_s REAL,
          median_optical_flow_px REAL,
          median_tracked_features REAL,
          result_json TEXT,
          limitation TEXT,
          updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS sensor_forensics (
          case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
          sensor_modes_json TEXT,
          blooming_risk TEXT,
          lens_flare_risk TEXT,
          gimbal_behavior_status TEXT,
          compression_artifact_risk TEXT,
          reticle_track_status TEXT,
          forensic_note TEXT,
          updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS photogrammetry_status (
          case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
          status TEXT NOT NULL,
          required_geometry TEXT,
          available_geometry TEXT,
          scale_distance_claim_allowed INTEGER NOT NULL,
          note TEXT,
          updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS nlp_entities (
          entity_id INTEGER PRIMARY KEY AUTOINCREMENT,
          case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
          source TEXT NOT NULL,
          entity_type TEXT NOT NULL,
          entity_text TEXT NOT NULL,
          extraction_method TEXT,
          confidence REAL,
          UNIQUE(case_id, source, entity_type, entity_text)
        );

        CREATE TABLE IF NOT EXISTS cross_source_validation (
          validation_id INTEGER PRIMARY KEY AUTOINCREMENT,
          case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
          related_case_id INTEGER REFERENCES cases(case_id),
          relation_type TEXT NOT NULL,
          validation_status TEXT NOT NULL,
          evidence_summary TEXT,
          missing_controls_json TEXT,
          updated_at TEXT,
          UNIQUE(case_id, related_case_id, relation_type)
        );

        CREATE TABLE IF NOT EXISTS chain_of_custody (
          asset_id INTEGER PRIMARY KEY REFERENCES assets(asset_id) ON DELETE CASCADE,
          case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
          local_path TEXT,
          recorded_sha256 TEXT,
          verified_sha256 TEXT,
          hash_match INTEGER,
          verified_at TEXT,
          note TEXT
        );

        CREATE TABLE IF NOT EXISTS bayesian_scores (
          case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
          hypothesis TEXT NOT NULL,
          normalized_probability REAL,
          source TEXT,
          note TEXT,
          updated_at TEXT,
          PRIMARY KEY(case_id, hypothesis)
        );

        CREATE TABLE IF NOT EXISTS human_review_protocol (
          review_id INTEGER PRIMARY KEY AUTOINCREMENT,
          case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
          pass_number INTEGER NOT NULL,
          reviewer_role TEXT NOT NULL,
          task TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          disagreement_status TEXT DEFAULT 'not_started',
          annotation_schema_json TEXT,
          UNIQUE(case_id, pass_number, reviewer_role, task)
        );
        """
    )

    # Chain of custody: verify every local file hash.
    for a in conn.execute("SELECT * FROM assets WHERE local_path IS NOT NULL AND local_path != ''").fetchall():
        path = Path(a["local_path"])
        verified = sha256(path) if path.exists() else None
        match = 1 if verified and verified == a["sha256"] else 0
        conn.execute(
            """
            INSERT OR REPLACE INTO chain_of_custody
            (asset_id,case_id,local_path,recorded_sha256,verified_sha256,hash_match,verified_at,note)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (a["asset_id"], a["case_id"], a["local_path"], a["sha256"], verified, match, now, "SHA256 verified from local file" if match else "missing file or hash mismatch"),
        )

    # Video tracking and sensor forensics.
    videos = conn.execute(
        """
        SELECT c.case_id,c.title,c.description,v.video_title,v.duration_seconds,v.width,v.height,v.description_flags_json,a.local_path
        FROM videos v JOIN cases c USING(case_id) JOIN assets a USING(case_id)
        ORDER BY c.case_id
        """
    ).fetchall()
    for v in videos:
        metrics = video_track(v["local_path"])
        conn.execute(
            """
            INSERT OR REPLACE INTO video_tracking
            (case_id,method,status,sampled_frames,candidate_detections,median_candidate_speed_px_s,
             max_candidate_speed_px_s,median_optical_flow_px,median_tracked_features,result_json,limitation,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                v["case_id"],
                "OpenCV sampled compact-contrast tracker + Lucas-Kanade optical flow",
                metrics.get("status"),
                metrics.get("sampled_frames"),
                metrics.get("candidate_detections"),
                metrics.get("median_candidate_speed_px_s_320w"),
                metrics.get("max_candidate_speed_px_s_320w"),
                metrics.get("median_optical_flow_px"),
                metrics.get("median_tracked_features"),
                dumps(metrics),
                "; ".join(metrics.get("limitations", [])),
                now,
            ),
        )
        modes = detect_sensor_mode(v["title"], v["description"], v["video_title"])
        flags = j(v["description_flags_json"], {}) or {}
        compression = "high" if (v["width"] or 0) <= 1280 else "unknown"
        note = "Sensor mode inferred from metadata text only; no raw sensor telemetry/FOV available."
        if flags.get("resolved_as_aircraft"):
            note += " Source metadata marks case resolved as aircraft."
        conn.execute(
            """
            INSERT OR REPLACE INTO sensor_forensics
            (case_id,sensor_modes_json,blooming_risk,lens_flare_risk,gimbal_behavior_status,
             compression_artifact_risk,reticle_track_status,forensic_note,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                v["case_id"],
                dumps(modes),
                "possible_for_bright_IR_sources" if any(m in modes for m in ["IR", "FLIR", "SWIR"]) else "not_assessed",
                "possible_requires_frame_review",
                "not_assessable_without_platform_sensor_metadata",
                compression,
                "not_assessable_from_sampled_metadata_only",
                note,
                now,
            ),
        )

    # Photogrammetry status for all cases.
    for c in conn.execute("SELECT case_id,asset_type,title FROM cases").fetchall():
        available = "none"
        status = "not_available"
        note = "No FOV, range, camera model, platform pose, or target distance in current structured metadata."
        if c["asset_type"] == "VID":
            available = "video pixels and duration only"
        elif c["asset_type"] == "IMG":
            available = "image dimensions only"
        conn.execute(
            """
            INSERT OR REPLACE INTO photogrammetry_status
            (case_id,status,required_geometry,available_geometry,scale_distance_claim_allowed,note,updated_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                c["case_id"],
                status,
                "camera/sensor FOV, focal length, platform pose, range or known object size, timestamp",
                available,
                0,
                note,
                now,
            ),
        )

    # NLP extraction from metadata plus OCR text snippets where present.
    conn.execute("DELETE FROM nlp_entities")
    for c in conn.execute("SELECT case_id,title,description,incident_date,incident_location,sensor_type FROM cases").fetchall():
        meta_text = " ".join(str(x or "") for x in [c["title"], c["description"], c["incident_date"], c["incident_location"], c["sensor_type"]])
        for etype, text, method, conf in extract_entities(meta_text):
            conn.execute(
                "INSERT OR IGNORE INTO nlp_entities (case_id,source,entity_type,entity_text,extraction_method,confidence) VALUES (?,?,?,?,?,?)",
                (c["case_id"], "metadata", etype, text, method, conf),
            )
        od = conn.execute("SELECT ocr_path FROM ocr_documents WHERE case_id=?", (c["case_id"],)).fetchone()
        if od and od["ocr_path"] and Path(od["ocr_path"]).exists():
            snippet = Path(od["ocr_path"]).read_text(errors="ignore")[:20000]
            for etype, text, method, conf in extract_entities(snippet):
                conn.execute(
                    "INSERT OR IGNORE INTO nlp_entities (case_id,source,entity_type,entity_text,extraction_method,confidence) VALUES (?,?,?,?,?,?)",
                    (c["case_id"], "ocr_text", etype, text, method, conf),
                )

    # Cross-source validation from explicit video_pairing/pdf_pairing metadata and external correlations.
    conn.execute("DELETE FROM cross_source_validation")
    video_by_pr = {}
    for c in conn.execute("SELECT case_id,title FROM cases WHERE asset_type='VID'").fetchall():
        m = re.search(r"PR[- ]?(\d+)", c["title"], re.I)
        if m:
            video_by_pr[m.group(1)] = c["case_id"]
    for row in conn.execute("SELECT a.case_id,c.title,a.metadata_json FROM assets a JOIN cases c USING(case_id)").fetchall():
        meta = j(row["metadata_json"], {}) or {}
        vp = meta.get("video_pairing") or ""
        m = re.search(r"PR[- ]?(\d+)", vp, re.I)
        if m and m.group(1) in video_by_pr:
            related = video_by_pr[m.group(1)]
            conn.execute(
                """
                INSERT OR IGNORE INTO cross_source_validation
                (case_id,related_case_id,relation_type,validation_status,evidence_summary,missing_controls_json,updated_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    row["case_id"],
                    related,
                    "mission_report_to_video",
                    "paired_by_csv_metadata",
                    f"PDF metadata video_pairing={vp} matches video case {related}.",
                    dumps(["compare exact timestamps", "compare sensor mode", "compare object description", "compare event location"]),
                    now,
                ),
            )
    for c in conn.execute("SELECT case_id FROM cases").fetchall():
        corr = conn.execute("SELECT correlation_type,status,result_summary FROM external_correlations WHERE case_id=?", (c["case_id"],)).fetchall()
        if corr:
            fetched = [f"{x['correlation_type']}={x['status']}" for x in corr]
            conn.execute(
                """
                INSERT OR IGNORE INTO cross_source_validation
                (case_id,related_case_id,relation_type,validation_status,evidence_summary,missing_controls_json,updated_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    c["case_id"],
                    None,
                    "environmental_correlation",
                    "partially_populated",
                    "; ".join(fetched),
                    dumps(["event time", "tight location", "ADS-B historical query", "satellite/Starlink pass query"]),
                    now,
                ),
            )

    # Bayesian normalized scores from current hypothesis posteriors.
    conn.execute("DELETE FROM bayesian_scores")
    for c in conn.execute("SELECT case_id FROM cases").fetchall():
        hrows = conn.execute("SELECT hypothesis,posterior_score FROM hypotheses WHERE case_id=?", (c["case_id"],)).fetchall()
        for hyp, prob in bayes_from_hypotheses(hrows):
            conn.execute(
                "INSERT INTO bayesian_scores (case_id,hypothesis,normalized_probability,source,note,updated_at) VALUES (?,?,?,?,?,?)",
                (c["case_id"], hyp, prob, "normalized local heuristic hypothesis scores", "Not a calibrated statistical model; ranks hypotheses from available evidence.", now),
            )

    # Human review two-pass protocol.
    conn.execute("DELETE FROM human_review_protocol")
    schema = {
        "fields": ["claim", "source_quote", "directness", "independence", "artifact_risk", "environmental_match", "hypothesis_rank", "reviewer_confidence"],
        "disagreement_resolution": "second reviewer plus adjudication if classifications differ",
    }
    for c in conn.execute("SELECT case_id,asset_type,classification FROM cases").fetchall():
        tasks = ["case_card_fact_check", "classification_review"]
        if c["asset_type"] == "VID":
            tasks += ["video_target_validation", "sensor_artifact_review"]
        if c["asset_type"] == "IMG":
            tasks += ["archival_original_comparison", "image_artifact_review"]
        if "unresolved" in (c["classification"] or ""):
            tasks += ["witness_claim_matrix", "environmental_controls_review"]
        for pass_no, role in [(1, "primary_reviewer"), (2, "blind_second_reviewer")]:
            for task in tasks:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO human_review_protocol
                    (case_id,pass_number,reviewer_role,task,status,disagreement_status,annotation_schema_json)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (c["case_id"], pass_no, role, task, "open", "not_started", dumps(schema)),
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
        (now, str(BASE), "Populated method tables: OpenCV tracking, sensor forensics, photogrammetry status, NLP entities, cross-source validation, chain of custody, Bayesian normalized scores, human review protocol."),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
