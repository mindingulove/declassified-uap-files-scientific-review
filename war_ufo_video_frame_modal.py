import os
#!/usr/bin/env python3
import csv
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/tmp/war_ufo_science")
DB = BASE / "cases.sqlite"
FRAME_DIR = BASE / "frontend" / "frames"
FRAME_DIR.mkdir(parents=True, exist_ok=True)


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)


def read_track(path):
    rows = []
    if not path or not Path(path).exists():
        return rows
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                row["_time"] = float(row.get("time_s") or 0)
                row["_frame"] = int(float(row.get("frame") or 0))
                row["_vx"] = float(row.get("kalman_vx_px_s") or 0)
                row["_vy"] = float(row.get("kalman_vy_px_s") or 0)
                row["_speed"] = (row["_vx"] ** 2 + row["_vy"] ** 2) ** 0.5
            except Exception:
                row["_time"] = 0
                row["_frame"] = 0
                row["_speed"] = 0
            rows.append(row)
    return rows


def pick_rows(rows):
    if not rows:
        return []
    picks = [
        ("first", rows[0]),
        ("middle", rows[len(rows) // 2]),
        ("last", rows[-1]),
        ("max_speed", max(rows, key=lambda r: r.get("_speed", 0))),
    ]
    out = []
    seen = set()
    for label, r in picks:
        key = r["_frame"]
        if key in seen:
            continue
        seen.add(key)
        out.append((label, r))
    return out


def extract_frame(video_path, case_id, label, row):
    out = FRAME_DIR / f"{case_id:03d}_{label}_f{row['_frame']:06d}.jpg"
    if out.exists() and out.stat().st_size > 1000:
        return out
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", f"{row['_time']:.3f}", "-i", video_path,
        "-frames:v", "1", "-vf", "scale=960:-1", str(out)
    ]
    run(cmd)
    return out if out.exists() else None


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS video_track_frames (
          frame_image_id INTEGER PRIMARY KEY AUTOINCREMENT,
          case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
          frame_label TEXT NOT NULL,
          source_frame INTEGER,
          time_s REAL,
          image_path TEXT,
          track_x REAL,
          track_y REAL,
          kalman_x REAL,
          kalman_y REAL,
          speed_px_s REAL,
          updated_at TEXT,
          UNIQUE(case_id, frame_label)
        );
        """
    )
    rows = conn.execute(
        """
        SELECT c.case_id,c.title,a.local_path,t.track_csv
        FROM cases c JOIN assets a USING(case_id) JOIN advanced_video_tracks t USING(case_id)
        ORDER BY c.case_id
        """
    ).fetchall()
    for r in rows:
        track_rows = read_track(r["track_csv"])
        for label, tr in pick_rows(track_rows):
            img = extract_frame(r["local_path"], r["case_id"], label, tr)
            conn.execute(
                """
                INSERT OR REPLACE INTO video_track_frames
                (case_id,frame_label,source_frame,time_s,image_path,track_x,track_y,kalman_x,kalman_y,speed_px_s,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    r["case_id"], label, tr.get("_frame"), tr.get("_time"), str(img) if img else None,
                    float(tr.get("x") or 0), float(tr.get("y") or 0),
                    float(tr.get("kalman_x") or 0), float(tr.get("kalman_y") or 0),
                    tr.get("_speed"), now,
                ),
            )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
