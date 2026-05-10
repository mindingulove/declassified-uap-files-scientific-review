import os
#!/usr/bin/env python3
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/tmp/war_ufo_science")
DB = BASE / "cases.sqlite"
TMP_DB = BASE / "cases.sqlite.tmp"
SCHEMA_SQL = BASE / "cases_schema.sql"


def load_json(name, default):
    path = BASE / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def slug(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s or "").strip("-").lower()


def norm_blank(v):
    if v in (None, "", "N/A", "n/a", "NA"):
        return None
    return v


def detect_sensor(record, video=None):
    blob = " ".join(
        str(x or "")
        for x in [
            record.get("title"),
            record.get("description"),
            record.get("video_title"),
            video.get("claimed_sensor") if video else None,
        ]
    ).lower()
    sensors = []
    checks = [
        ("infrared", "infrared"),
        ("flir", "FLIR"),
        ("nvg", "NVG"),
        ("short-wave infrared", "SWIR"),
        ("swir", "SWIR"),
        ("electro-optical", "EO"),
        ("radar", "radar"),
        ("iff", "IFF"),
        ("es ", "ES"),
    ]
    for needle, label in checks:
        if needle in blob and label not in sensors:
            sensors.append(label)
    return ", ".join(sensors) or None


def detect_witnesses(record):
    blob = f"{record.get('title','')} {record.get('description','')}".lower()
    labels = []
    if "federal law enforcement" in blob or "federal government" in blob or "federal employees" in blob:
        labels.append("government employees")
    if "senior us intelligence official" in blob:
        labels.append("senior intelligence official")
    if "fbi 302" in blob:
        labels.append("formal FBI 302 interview")
    if "multiple witnesses" in blob or "corroborating eyewitness" in blob or "separately reported" in blob:
        labels.append("multiple/corroborating witnesses")
    if "eyewitness" in blob and not labels:
        labels.append("eyewitness claim")
    return ", ".join(labels) or None


def detect_object_description(record):
    blob = f"{record.get('title','')} {record.get('description','')}".lower()
    found = []
    for term in ["orb", "sphere", "disc", "disk", "flying disc", "triangle", "cylinder", "light", "object", "uap", "ufo"]:
        if term in blob and term not in found:
            found.append(term)
    return ", ".join(found) or None


def detect_platform(record):
    blob = f"{record.get('title','')} {record.get('description','')} {record.get('video_title','')}".lower()
    found = []
    for term in ["mq-9", "aircraft", "helicopter", "ship", "navy", "army", "sensor", "apollo", "gemini", "skylab"]:
        if term in blob:
            found.append(term)
    return ", ".join(found) or None


def detect_motion(record):
    blob = f"{record.get('title','')} {record.get('description','')}".lower()
    found = []
    for term in ["stationary", "hover", "moving", "launched", "accelerat", "turn", "track", "orbit", "flew", "formation"]:
        if term in blob:
            found.append(term)
    return ", ".join(found) or None


def json_dump(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True) if v is not None else None


def exec_schema(conn):
    schema = """
PRAGMA foreign_keys = ON;

CREATE TABLE cases (
  case_id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  incident_date TEXT,
  incident_location TEXT,
  agency TEXT,
  release_date TEXT,
  sensor_type TEXT,
  witnesses TEXT,
  platform TEXT,
  duration_seconds REAL,
  object_description TEXT,
  claimed_motion TEXT,
  weather_context_status TEXT DEFAULT 'not_checked',
  astronomy_context_status TEXT DEFAULT 'not_checked',
  aviation_context_status TEXT DEFAULT 'not_checked',
  space_activity_status TEXT DEFAULT 'not_checked',
  military_context_status TEXT DEFAULT 'not_checked',
  radar_iff_es_correlation TEXT,
  paired_video_id TEXT,
  paired_pdf TEXT,
  paired_image TEXT,
  confidence REAL,
  classification TEXT DEFAULT 'unreviewed',
  description TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE assets (
  asset_id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  asset_type TEXT NOT NULL,
  asset_key TEXT NOT NULL,
  original_url TEXT,
  modal_image_url TEXT,
  local_path TEXT,
  filename TEXT,
  sha256 TEXT,
  file_size INTEGER,
  download_time TEXT,
  dvids_video_id TEXT,
  metadata_json TEXT,
  UNIQUE(case_id, asset_type, asset_key)
);

CREATE TABLE pdf_text_layers (
  case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
  pages INTEGER,
  embedded_text_path TEXT,
  embedded_text_chars INTEGER,
  chars_per_page REAL,
  needs_ocr INTEGER,
  text_source TEXT
);

CREATE TABLE ocr_documents (
  case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
  ocr_path TEXT,
  ocr_chars INTEGER,
  ocr_mode TEXT,
  priority_score REAL,
  priority_reasons_json TEXT,
  ocr_engine TEXT,
  ocr_confidence_method TEXT,
  manual_review_status TEXT DEFAULT 'not_reviewed'
);

CREATE TABLE ocr_pages (
  case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  page_number INTEGER NOT NULL,
  page_text_path TEXT NOT NULL,
  page_text_chars INTEGER,
  ocr_confidence REAL,
  ocr_confidence_method TEXT,
  PRIMARY KEY(case_id, page_number)
);

CREATE TABLE videos (
  case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
  dvids_video_id TEXT,
  video_title TEXT,
  duration_seconds REAL,
  width INTEGER,
  height INTEGER,
  has_audio INTEGER,
  claimed_sensor TEXT,
  description_flags_json TEXT,
  ffprobe_status TEXT,
  tracking_status TEXT DEFAULT 'not_tracked',
  angular_velocity_status TEXT DEFAULT 'not_available'
);

CREATE TABLE video_frames (
  frame_id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  frame_path TEXT NOT NULL,
  sample_index INTEGER,
  frame_note TEXT,
  UNIQUE(case_id, frame_path)
);

CREATE TABLE images (
  case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
  width INTEGER,
  height INTEGER,
  initial_risk_flags_json TEXT,
  exif_status TEXT DEFAULT 'basic_dimensions_only',
  archival_comparison_status TEXT DEFAULT 'not_checked',
  artifact_review_status TEXT DEFAULT 'not_reviewed'
);

CREATE TABLE witness_claims (
  claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  source_type TEXT,
  witness_label TEXT,
  claim_text TEXT,
  independence_status TEXT DEFAULT 'not_assessed',
  directness TEXT DEFAULT 'not_assessed',
  corroboration_score REAL,
  notes TEXT
);

CREATE TABLE environmental_checks (
  check_id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  check_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'not_checked',
  source TEXT,
  result_summary TEXT,
  checked_at TEXT,
  UNIQUE(case_id, check_type)
);

CREATE TABLE hypotheses (
  hypothesis_id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  hypothesis TEXT NOT NULL,
  category TEXT,
  prior_score REAL,
  evidence_for TEXT,
  evidence_against TEXT,
  posterior_score REAL,
  status TEXT DEFAULT 'unscored',
  UNIQUE(case_id, hypothesis)
);

CREATE TABLE case_scores (
  case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
  scientific_priority_score REAL,
  priority_reasons_json TEXT,
  limitations_json TEXT,
  evidence_available_json TEXT,
  scoring_method TEXT
);

CREATE TABLE review_tasks (
  task_id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  task_type TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'open',
  rationale TEXT,
  UNIQUE(case_id, task_type)
);

CREATE TABLE pipeline_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_time TEXT NOT NULL,
  source_base TEXT NOT NULL,
  inventory_count INTEGER,
  ocr_document_count INTEGER,
  video_count INTEGER,
  image_count INTEGER,
  notes TEXT
);
"""
    conn.executescript(schema)
    SCHEMA_SQL.write_text(schema, encoding="utf-8")


def main():
    inventory = load_json("inventory.json", [])
    pdf_layers = {x["record_index"]: x for x in load_json("pdf_text_layer_summary.json", [])}
    ocr_docs = {x["record_index"]: x for x in load_json("ocr_summary_all.json", [])}
    videos = {x["record_index"]: x for x in load_json("video_analysis.json", [])}
    images = {x["record_index"]: x for x in load_json("image_analysis.json", [])}
    cards = {x["record_index"]: x for x in load_json("case_cards.json", [])}
    now = datetime.now(timezone.utc).isoformat()

    if TMP_DB.exists():
        TMP_DB.unlink()
    conn = sqlite3.connect(TMP_DB)
    conn.row_factory = sqlite3.Row
    exec_schema(conn)

    for r in inventory:
        rid = int(r["record_index"])
        v = videos.get(rid)
        c = cards.get(rid, {})
        duration = v.get("duration_seconds") if v else None
        confidence = c.get("scientific_priority_score")
        confidence_norm = None if confidence is None else max(0.0, min(1.0, float(confidence) / 15.0))
        conn.execute(
            """
            INSERT INTO cases (
              case_id,title,asset_type,incident_date,incident_location,agency,release_date,
              sensor_type,witnesses,platform,duration_seconds,object_description,claimed_motion,
              radar_iff_es_correlation,paired_video_id,paired_pdf,paired_image,confidence,
              classification,description,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                rid,
                r.get("title"),
                r.get("type"),
                norm_blank(r.get("incident_date")),
                norm_blank(r.get("incident_location")),
                norm_blank(r.get("agency")),
                norm_blank(r.get("release_date")),
                detect_sensor(r, v),
                detect_witnesses(r),
                detect_platform(r),
                duration,
                detect_object_description(r),
                detect_motion(r),
                detect_sensor(r, v) if detect_sensor(r, v) and any(x in detect_sensor(r, v) for x in ["radar", "IFF", "ES"]) else None,
                norm_blank(r.get("dvids_video_id")),
                norm_blank(r.get("pdf_pairing")),
                norm_blank(r.get("modal_image")) if r.get("type") == "IMG" else None,
                confidence_norm,
                "unreviewed",
                r.get("description"),
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO assets (
              case_id,asset_type,asset_key,original_url,modal_image_url,local_path,filename,sha256,file_size,
              download_time,dvids_video_id,metadata_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                rid,
                r.get("type"),
                r.get("local_path") or r.get("asset_url") or r.get("local_filename") or f"record-{rid}",
                norm_blank(r.get("asset_url")),
                norm_blank(r.get("modal_image")),
                norm_blank(r.get("local_path")),
                norm_blank(r.get("local_filename")),
                norm_blank(r.get("sha256")),
                r.get("local_size") or None,
                None,
                norm_blank(r.get("dvids_video_id")),
                json_dump({k: r.get(k) for k in ["redaction", "video_pairing", "pdf_pairing", "video_title"]}),
            ),
        )

        pl = pdf_layers.get(rid)
        if pl:
            conn.execute(
                """
                INSERT INTO pdf_text_layers (
                  case_id,pages,embedded_text_path,embedded_text_chars,chars_per_page,needs_ocr,text_source
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    rid,
                    pl.get("pages"),
                    pl.get("text_layer_path"),
                    pl.get("text_layer_chars"),
                    pl.get("chars_per_page"),
                    1 if pl.get("needs_ocr") else 0,
                    "embedded_text" if not pl.get("needs_ocr") else "embedded_text_low_or_absent",
                ),
            )

        od = ocr_docs.get(rid)
        if od:
            conn.execute(
                """
                INSERT INTO ocr_documents (
                  case_id,ocr_path,ocr_chars,ocr_mode,priority_score,priority_reasons_json,
                  ocr_engine,ocr_confidence_method,manual_review_status
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    rid,
                    od.get("ocr_path"),
                    od.get("ocr_chars"),
                    od.get("mode"),
                    od.get("priority_score"),
                    json_dump(od.get("priority_reasons")),
                    "tesseract eng --psm 6 via rendered PDF pages",
                    "not_captured_plain_text_run; rerun TSV/HOCR for numeric confidence",
                    "required" if rid in {156, 157, 159, 161, 22, 25, 29, 32} else "not_reviewed",
                ),
            )
            stem = slug(Path(r.get("local_path") or "").stem, )[:80]
            page_files = sorted((BASE / "page_ocr_text").glob(f"{stem}-p*.txt"))
            for pf in page_files:
                m = re.search(r"-p(\d{4})\.txt$", pf.name)
                if not m:
                    continue
                conn.execute(
                    """
                    INSERT INTO ocr_pages (
                      case_id,page_number,page_text_path,page_text_chars,ocr_confidence,ocr_confidence_method
                    ) VALUES (?,?,?,?,?,?)
                    """,
                    (
                        rid,
                        int(m.group(1)),
                        str(pf),
                        pf.stat().st_size,
                        None,
                        "not_captured_plain_text_run",
                    ),
                )

        if v:
            conn.execute(
                """
                INSERT INTO videos (
                  case_id,dvids_video_id,video_title,duration_seconds,width,height,has_audio,
                  claimed_sensor,description_flags_json,ffprobe_status
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    rid,
                    v.get("dvids_video_id"),
                    v.get("video_title"),
                    v.get("duration_seconds"),
                    v.get("width"),
                    v.get("height"),
                    1 if v.get("has_audio") else 0,
                    v.get("claimed_sensor"),
                    json_dump(v.get("description_flags")),
                    "complete",
                ),
            )
            for i, fp in enumerate(v.get("sample_frames") or [], 1):
                conn.execute(
                    "INSERT INTO video_frames (case_id,frame_path,sample_index,frame_note) VALUES (?,?,?,?)",
                    (rid, fp, i, "sampled frame"),
                )

        im = images.get(rid)
        if im:
            conn.execute(
                """
                INSERT INTO images (
                  case_id,width,height,initial_risk_flags_json
                ) VALUES (?,?,?,?)
                """,
                (rid, im.get("width"), im.get("height"), json_dump(im.get("initial_risk_flags"))),
            )

        if c:
            conn.execute(
                """
                INSERT INTO case_scores (
                  case_id,scientific_priority_score,priority_reasons_json,limitations_json,
                  evidence_available_json,scoring_method
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    rid,
                    c.get("scientific_priority_score"),
                    json_dump(c.get("priority_reasons")),
                    json_dump(c.get("limitations")),
                    json_dump(c.get("evidence_available")),
                    "rule_based_triage_v2_from_metadata_text_video_image",
                ),
            )

        for check in ["weather", "astronomy", "aviation", "space_activity", "military_context"]:
            conn.execute(
                "INSERT INTO environmental_checks (case_id,check_type,status) VALUES (?,?,?)",
                (rid, check, "not_checked" if norm_blank(r.get("incident_date")) and norm_blank(r.get("incident_location")) else "insufficient_date_or_location"),
            )

        for hyp, cat in [
            ("aircraft", "identified_candidate"),
            ("balloon", "identified_candidate"),
            ("bird/insect", "identified_candidate"),
            ("satellite/space object", "identified_candidate"),
            ("weather/astronomy", "identified_candidate"),
            ("camera/sensor artifact", "identified_candidate"),
            ("insufficient data", "data_quality"),
            ("unresolved after controls", "residual"),
        ]:
            conn.execute(
                "INSERT INTO hypotheses (case_id,hypothesis,category,status) VALUES (?,?,?,?)",
                (rid, hyp, cat, "unscored"),
            )

        priority = int(c.get("scientific_priority_score") or 0)
        if r.get("type") == "VID":
            conn.execute(
                "INSERT INTO review_tasks (case_id,task_type,priority,rationale) VALUES (?,?,?,?)",
                (rid, "video_tracking_and_artifact_review", priority, "Run OpenCV tracking, artifact checks, and pair timestamps with mission report."),
            )
        if r.get("type") == "IMG":
            conn.execute(
                "INSERT INTO review_tasks (case_id,task_type,priority,rationale) VALUES (?,?,?,?)",
                (rid, "archival_image_comparison", priority, "Compare with original unannotated archival image and inspect artifacts/metadata."),
            )
        if rid in {156, 161, 157, 159, 29, 22, 25, 32}:
            conn.execute(
                "INSERT OR IGNORE INTO review_tasks (case_id,task_type,priority,rationale) VALUES (?,?,?,?)",
                (rid, "manual_transcription_and_witness_analysis", max(priority, 10), "High-value witness/historical document requires human review and claim extraction."),
            )

    conn.execute(
        """
        INSERT INTO pipeline_runs (
          run_time,source_base,inventory_count,ocr_document_count,video_count,image_count,notes
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (
            now,
            str(BASE),
            len(inventory),
            len(ocr_docs),
            len(videos),
            len(images),
            "SQLite built from generated JSON/CSV/OCR artifacts. OCR page confidence not captured in original plain-text run.",
        ),
    )
    conn.commit()
    conn.close()
    if DB.exists():
        DB.unlink()
    TMP_DB.rename(DB)
    print(DB)


if __name__ == "__main__":
    main()
