
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
