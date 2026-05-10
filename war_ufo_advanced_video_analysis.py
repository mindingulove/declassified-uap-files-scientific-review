import os
#!/usr/bin/env python3
import csv
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent
DB = BASE / "cases.sqlite"
TRACK_DIR = BASE / "video_tracks"
TRACK_DIR.mkdir(exist_ok=True)


def dumps(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def detect_candidate(gray):
    # Contrast-based candidate: small bright/dark connected components away from very large overlays.
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, bright = cv2.threshold(blur, 235, 255, cv2.THRESH_BINARY)
    _, dark = cv2.threshold(blur, 25, 255, cv2.THRESH_BINARY_INV)
    mask = cv2.bitwise_or(bright, dark)
    nlabels, labels, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    h, w = gray.shape
    candidates = []
    for i in range(1, nlabels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if not (3 <= area <= 2500):
            continue
        x, y = cents[i]
        # Prefer off-center, compact regions; avoid full reticle/text overlays.
        density = area / max(1, stats[i, cv2.CC_STAT_WIDTH] * stats[i, cv2.CC_STAT_HEIGHT])
        if density < 0.08:
            continue
        candidates.append((area, float(x), float(y), int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])))
    if not candidates:
        return None
    # Largest compact contrast region is a candidate, not verified target truth.
    area, x, y, bw, bh = max(candidates, key=lambda t: t[0])
    return {"x": x, "y": y, "area": area, "bbox_w": bw, "bbox_h": bh}


def kalman_smooth(points):
    if not points:
        return []
    kf = cv2.KalmanFilter(4, 2)
    kf.transitionMatrix = np.array([[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]], np.float32)
    kf.measurementMatrix = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], np.float32)
    kf.processNoiseCov = np.eye(4, dtype=np.float32) * 0.03
    kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 2.0
    first = points[0]
    kf.statePre = np.array([[first["x"]], [first["y"]], [0], [0]], np.float32)
    kf.statePost = kf.statePre.copy()
    smoothed = []
    for p in points:
        pred = kf.predict()
        meas = np.array([[np.float32(p["x"])], [np.float32(p["y"])]])
        est = kf.correct(meas)
        q = dict(p)
        q["kalman_x"] = float(est[0, 0])
        q["kalman_y"] = float(est[1, 0])
        q["kalman_vx_px_s"] = float(est[2, 0])
        q["kalman_vy_px_s"] = float(est[3, 0])
        smoothed.append(q)
    return smoothed


def frequency_analysis(points):
    """Estimate periodic motion from sampled candidate tracks using FFT."""
    if len(points) < 8:
        return {
            "status": "insufficient_track_points",
            "dominant_frequency_hz": None,
            "dominant_period_s": None,
            "spectral_peak_ratio": None,
            "periodic_motion_flag": "not_assessable",
        }

    times = np.array([p["time_s"] for p in points], dtype=float)
    xs = np.array([p["kalman_x"] for p in points], dtype=float)
    ys = np.array([p["kalman_y"] for p in points], dtype=float)
    duration = float(times[-1] - times[0])
    if duration <= 0:
        return {
            "status": "invalid_timebase",
            "dominant_frequency_hz": None,
            "dominant_period_s": None,
            "spectral_peak_ratio": None,
            "periodic_motion_flag": "not_assessable",
        }

    sample_count = min(256, max(16, len(points)))
    uniform_t = np.linspace(times[0], times[-1], sample_count)
    x_uniform = np.interp(uniform_t, times, xs)
    y_uniform = np.interp(uniform_t, times, ys)
    signal = np.hypot(x_uniform - np.mean(x_uniform), y_uniform - np.mean(y_uniform))
    signal = signal - np.mean(signal)
    if np.allclose(signal, 0):
        return {
            "status": "flat_track_signal",
            "dominant_frequency_hz": None,
            "dominant_period_s": None,
            "spectral_peak_ratio": None,
            "periodic_motion_flag": "not_detected",
        }

    dt = duration / max(1, sample_count - 1)
    spectrum = np.abs(np.fft.rfft(signal))
    freqs = np.fft.rfftfreq(sample_count, d=dt)
    if len(freqs) <= 1:
        return {
            "status": "insufficient_frequency_bins",
            "dominant_frequency_hz": None,
            "dominant_period_s": None,
            "spectral_peak_ratio": None,
            "periodic_motion_flag": "not_assessable",
        }

    spectrum[0] = 0.0
    peak_idx = int(np.argmax(spectrum))
    peak = float(spectrum[peak_idx])
    total = float(np.sum(spectrum) + 1e-9)
    peak_ratio = peak / total
    dominant_frequency = float(freqs[peak_idx]) if peak > 0 else None
    return {
        "status": "fft_frequency_analysis_complete",
        "dominant_frequency_hz": dominant_frequency,
        "dominant_period_s": (1.0 / dominant_frequency) if dominant_frequency else None,
        "spectral_peak_ratio": peak_ratio,
        "periodic_motion_flag": "possible_periodic_component" if peak_ratio >= 0.35 else "not_detected",
    }


def resolve_asset_path(path):
    p = Path(path)
    if p.exists():
        return str(p)
    marker = "war_ufo_mining/videos/mp4/"
    s = str(path)
    if marker in s:
        candidate = BASE / marker / s.split(marker, 1)[1]
        if candidate.exists():
            return str(candidate)
    return str(p)


def analyze_video(path, case_id):
    path = resolve_asset_path(path)
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return {"status": "failed_open"}, []
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if frame_count <= 0:
        cap.release()
        return {"status": "no_frames", "fps": fps, "frame_count": frame_count}, []
    # Frame-by-frame for short clips; sampled at ~2 fps for long clips.
    duration = frame_count / fps
    step = 1 if duration <= 20 else max(1, int(round(fps / 2)))
    max_points = 900
    idxs = list(range(0, frame_count, step))
    if len(idxs) > max_points:
        step = max(1, int(frame_count / max_points))
        idxs = list(range(0, frame_count, step))
    points = []
    prev_gray = None
    global_flow = []
    brightness = []
    center_line_scores = []
    zoom_proxy = []
    for idx in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        gray_full = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray_full, (640, 360), interpolation=cv2.INTER_AREA)
        t = idx / fps
        cand = detect_candidate(gray)
        edges = cv2.Canny(gray, 60, 140)
        center_vertical = float(np.mean(edges[:, 316:324] > 0))
        center_horizontal = float(np.mean(edges[176:184, :] > 0))
        center_line_scores.append(center_vertical + center_horizontal)
        brightness.append(float(np.mean(gray)))
        zoom_proxy.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
        flow = None
        if prev_gray is not None:
            pts = cv2.goodFeaturesToTrack(prev_gray, maxCorners=120, qualityLevel=0.02, minDistance=8)
            if pts is not None:
                nxt, st, err = cv2.calcOpticalFlowPyrLK(prev_gray, gray, pts, None)
                if nxt is not None and st is not None:
                    old = pts[st.flatten() == 1].reshape(-1, 2)
                    new = nxt[st.flatten() == 1].reshape(-1, 2)
                    if len(old):
                        mag = np.linalg.norm(new - old, axis=1)
                        flow = float(np.median(mag))
                        global_flow.append(flow)
        if cand:
            cand.update({"frame": idx, "time_s": t, "flow_px": flow})
            points.append(cand)
        prev_gray = gray
    cap.release()
    smooth = kalman_smooth(points)
    frequency = frequency_analysis(smooth)
    speeds = []
    for a, b in zip(smooth, smooth[1:]):
        dt = b["time_s"] - a["time_s"]
        if dt > 0:
            speeds.append(math.hypot(b["kalman_x"] - a["kalman_x"], b["kalman_y"] - a["kalman_y"]) / dt)
    track_csv = TRACK_DIR / f"{case_id:03d}_track.csv"
    with open(track_csv, "w", newline="", encoding="utf-8") as f:
        fields = ["frame", "time_s", "x", "y", "kalman_x", "kalman_y", "kalman_vx_px_s", "kalman_vy_px_s", "area", "bbox_w", "bbox_h", "flow_px"]
        w = csv.DictWriter(f, fields)
        w.writeheader()
        for p in smooth:
            w.writerow({k: p.get(k) for k in fields})
    reticle_score = float(np.median(center_line_scores)) if center_line_scores else None
    zoom_variability = float(np.std(zoom_proxy) / (np.mean(zoom_proxy) + 1e-6)) if zoom_proxy else None
    flow_med = float(np.median(global_flow)) if global_flow else None
    track_med = float(np.median(speeds)) if speeds else None
    parallax_status = "not_assessable"
    if flow_med is not None and track_med is not None:
        ratio = track_med / (flow_med + 1e-6)
        if ratio < 1.5:
            parallax_status = "candidate_motion_similar_to_global_scene_motion"
        elif ratio >= 1.5:
            parallax_status = "candidate_motion_exceeds_global_scene_motion"
    comparison = {
        "aircraft": "plausible_if_linear_motion_or_source_metadata_resolved_aircraft",
        "bird_insect": "not_excludable_without_range/focus/scene_context; IR clips reduce but do not eliminate this",
        "balloon": "not_excludable_without wind/range/altitude; slow smooth motion compatible in some clips",
        "drone": "not_excludable_without range/signature/local activity data",
        "artifact": "not_excludable; compression/reticle/global motion checks required",
    }
    summary = {
        "status": "advanced_local_track_complete",
        "fps": fps,
        "frame_count": frame_count,
        "duration_s": duration,
        "processed_frames": len(idxs),
        "detections": len(points),
        "detection_fraction": len(points) / max(1, len(idxs)),
        "track_csv": str(track_csv),
        "median_kalman_speed_px_s_640w": track_med,
        "max_kalman_speed_px_s_640w": float(np.max(speeds)) if speeds else None,
        "median_global_optical_flow_px": flow_med,
        "reticle_centerline_score": reticle_score,
        "zoom_change_proxy_cv": zoom_variability,
        "frequency_analysis_status": frequency["status"],
        "dominant_frequency_hz": frequency["dominant_frequency_hz"],
        "dominant_period_s": frequency["dominant_period_s"],
        "spectral_peak_ratio": frequency["spectral_peak_ratio"],
        "periodic_motion_flag": frequency["periodic_motion_flag"],
        "parallax_status": parallax_status,
        "comparison_flags": comparison,
        "angular_velocity_status": "not_computable_without_fov",
        "photogrammetry_status": "not_computable_without_fov_range_platform_pose",
        "limitations": [
            "candidate is algorithm-selected contrast feature, not human-verified target",
            "pixel track is not angular or physical motion without sensor FOV and platform geometry",
            "parallax is only a global-flow proxy",
            "frequency-domain output is an FFT over the candidate pixel track, not biological identification",
            "aircraft/bird/balloon/drone comparison remains qualitative without range/time/location controls",
        ],
    }
    return summary, smooth


def ensure_column(conn, table, column, definition):
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS advanced_video_tracks (
          case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
          status TEXT,
          processed_frames INTEGER,
          detections INTEGER,
          detection_fraction REAL,
          track_csv TEXT,
          median_kalman_speed_px_s REAL,
          max_kalman_speed_px_s REAL,
          median_global_optical_flow_px REAL,
          reticle_centerline_score REAL,
          zoom_change_proxy_cv REAL,
          parallax_status TEXT,
          angular_velocity_status TEXT,
          photogrammetry_status TEXT,
          result_json TEXT,
          updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS video_hypothesis_comparison (
          case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
          hypothesis TEXT NOT NULL,
          status TEXT NOT NULL,
          evidence_for TEXT,
          evidence_against TEXT,
          required_missing_data TEXT,
          updated_at TEXT,
          PRIMARY KEY(case_id, hypothesis)
        );
        """
    )
    for column, definition in [
        ("frequency_analysis_status", "TEXT"),
        ("dominant_frequency_hz", "REAL"),
        ("dominant_period_s", "REAL"),
        ("spectral_peak_ratio", "REAL"),
        ("periodic_motion_flag", "TEXT"),
    ]:
        ensure_column(conn, "advanced_video_tracks", column, definition)
    rows = conn.execute(
        "SELECT c.case_id,c.title,a.local_path FROM videos v JOIN cases c USING(case_id) JOIN assets a USING(case_id) ORDER BY c.case_id"
    ).fetchall()
    for r in rows:
        print(f"Advanced video {r['case_id']}: {r['title']}", flush=True)
        summary, points = analyze_video(r["local_path"], r["case_id"])
        conn.execute(
            """
            INSERT OR REPLACE INTO advanced_video_tracks
            (case_id,status,processed_frames,detections,detection_fraction,track_csv,
             median_kalman_speed_px_s,max_kalman_speed_px_s,median_global_optical_flow_px,
             reticle_centerline_score,zoom_change_proxy_cv,frequency_analysis_status,
             dominant_frequency_hz,dominant_period_s,spectral_peak_ratio,periodic_motion_flag,
             parallax_status,angular_velocity_status,
             photogrammetry_status,result_json,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                r["case_id"], summary.get("status"), summary.get("processed_frames"), summary.get("detections"),
                summary.get("detection_fraction"), summary.get("track_csv"), summary.get("median_kalman_speed_px_s_640w"),
                summary.get("max_kalman_speed_px_s_640w"), summary.get("median_global_optical_flow_px"),
                summary.get("reticle_centerline_score"), summary.get("zoom_change_proxy_cv"),
                summary.get("frequency_analysis_status"), summary.get("dominant_frequency_hz"),
                summary.get("dominant_period_s"), summary.get("spectral_peak_ratio"),
                summary.get("periodic_motion_flag"), summary.get("parallax_status"),
                summary.get("angular_velocity_status"), summary.get("photogrammetry_status"), dumps(summary), now,
            ),
        )
        for hyp, status in summary.get("comparison_flags", {}).items():
            conn.execute(
                """
                INSERT OR REPLACE INTO video_hypothesis_comparison
                (case_id,hypothesis,status,evidence_for,evidence_against,required_missing_data,updated_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    r["case_id"], hyp, "not_excluded_local_review", status, None,
                    "exact time/location, range, FOV, platform motion, environmental controls, and human target validation",
                    now,
                ),
            )
        conn.execute(
            """
            UPDATE videos
            SET tracking_status='advanced_candidate_track_generated',
                angular_velocity_status='not_computable_without_sensor_fov'
            WHERE case_id=?
            """,
            (r["case_id"],),
        )
        conn.execute(
            """
            UPDATE photogrammetry_status
            SET status='blocked_missing_geometry',
                available_geometry='video pixels, duration, candidate pixel track',
                scale_distance_claim_allowed=0,
                note='Advanced pixel track exists, but photogrammetry still needs FOV/range/platform pose.',
                updated_at=?
            WHERE case_id=?
            """,
            (now, r["case_id"]),
        )
        conn.commit()
    conn.execute(
        """
        INSERT INTO pipeline_runs (
          run_time, source_base, inventory_count, ocr_document_count, video_count, image_count, notes
        )
        SELECT ?, ?, (SELECT count(*) FROM cases), (SELECT count(*) FROM hq_ocr_documents),
               (SELECT count(*) FROM videos), (SELECT count(*) FROM images),
               ?
        """,
        (now, str(BASE), "Advanced video analysis: candidate track CSVs, Kalman smoothing, FFT frequency metrics, reticle/zoom proxies, parallax proxy, hypothesis comparison flags."),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
