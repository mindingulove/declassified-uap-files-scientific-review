# UAP Scientific Record Explorer (USRE)

USRE is a local forensic-analysis workspace for 161 PURSUE/UAP records: 119 PDFs, 28 videos, and 14 images. It normalizes source records into SQLite, extracts text/OCR/media features, caches environmental context, and exports a frontend dashboard for review.

The project is an evidence-management and triage pipeline. It does not treat witness reports, annotations, video contrast points, or heuristic scores as proof of object identity. Many cases remain unreviewed or blocked by missing time, location, range, field-of-view, platform-pose, and original-archive data.

---

## Current Corpus Snapshot

- Records: 161
- PDFs: 119
- Videos: 28
- Images: 14
- Local assets represented in `cases.sqlite`: 161
- HQ OCR subset: 10 high-value documents, 195 pages, 29,372 word rows
- Witness matrix rows: 536 page-cited extracted claims
- External correlation rows: 372
- Advanced video tracks: 28 candidate-track rows
- Bayesian/heuristic hypothesis rows: 1,288
- Open `review_tasks` rows: 50

Current top-level classifications in `cases.sqlite`:

- `unreviewed`: 72
- `low evidentiary value`: 46
- `plausibly interesting but incomplete`: 15
- `insufficient data: still image only`: 14
- `insufficient data`: 11
- `high-value unresolved pending controls`: 2
- `identified: aircraft`: 1

---

## Evidence Rules

- Videos are sensor-display evidence, not self-interpreting proof. Kinematic claims require sensor FOV, range, platform motion, exact time, and scene context.
- Annotated or cropped images are leads until compared with unannotated archival originals.
- Scanned historical PDFs remain incomplete until OCR/manual transcription reaches reviewable quality.
- Witness, agency-summary, and later analytical-commentary claims are stored separately where possible.
- “Unresolved” means controls are incomplete or no identification has yet been made. It does not mean exotic origin.

---

## Pipeline Methods

1. **Normalization**
   - Source records are mapped into `cases.sqlite` with title, asset type, date, location, agency, sensor/platform hints, description, local asset path, and paired PDF/video/image links.

2. **Provenance and Assets**
   - `assets` stores original URLs, local paths, filenames, DVIDS IDs, file size, and SHA256 where available.
   - The local corpus combines `war_ufo_downloads/`, `war_ufo_mining/`, prior extracted PDF text, OCR outputs, and frontend exports.

3. **PDF Text and OCR**
   - Embedded text is extracted where available.
   - Low/absent text-layer PDFs are routed to OCR.
   - HQ OCR uses rendered pages plus Tesseract TSV/HOCR/TXT output, with word-level confidence stored in `hq_ocr_words`.

4. **Witness Matrix**
   - Regex-assisted extraction creates page-cited claim rows for witness/source review.
   - These rows are machine extracted and require human adjudication before they are treated as validated claims.

5. **Video Analysis**
   - OpenCV extracts candidate contrast features from sampled or frame-by-frame video.
   - Kalman smoothing is applied to the candidate pixel track.
   - Global optical-flow, reticle/centerline, zoom-proxy, parallax-proxy, and FFT frequency-domain metrics are recorded.
   - The tracked point is an algorithm-selected contrast candidate, not a human-verified target.
   - Pixel speed is not angular speed unless FOV and sensor geometry are known.

6. **Image Forensics**
   - The image layer records dimensions, pixel metrics, Laplacian edge/focus metrics, artifact-risk flags, and original-archive comparison requirements.
   - Laplacian variance and response measures describe sharpness/high-frequency edge content; they do not identify the observed object by themselves.
   - Dust, film grain, reseau marks, scan artifacts, redaction artifacts, and annotation/crop effects are review hypotheses, not automatically excluded conditions.

7. **Environmental Controls**
   - Cached checks include weather, moon phase, launches, CNEOS fireballs, satellite/decay lookups, and broad military/aviation queryability notes.
   - Many records only have broad/vague locations or dates, so controls may be proxy-level rather than event-precise.

8. **Hypothesis Scoring**
   - `bayesian_scores` is a normalized heuristic hypothesis ranking layer.
   - It is not a calibrated Bayesian statistical model.
   - Scores are useful for triage and dashboard ordering, not for final identification without source review and missing controls.

---

## Implemented Advanced Methods

- **Heuristic hypothesis ranking:** Normalizes current hypothesis weights and external-correlation boosts into `bayesian_scores`; explicitly non-calibrated.
- **Kalman smoothing:** Smooths algorithm-selected candidate pixel tracks in `video_tracks/*.csv` and `advanced_video_tracks`.
- **FFT frequency-domain analysis:** Computes dominant frequency, period, spectral peak ratio, and a periodic-motion flag from the candidate track. This is the implemented discrete-signal method for sampled video tracks.
- **Laplacian image metrics:** Computes edge/focus response statistics for still images and stores them in `image_env_classification` for dashboard review.
- **SGP4 support:** `satellite_trajectory_check.py` can propagate TLEs for satellite-position checks when suitable time/location data exist.
- **Haversine distance:** Used for launch/site vicinity checks and geospatial proxy matching.

---

## Reproducible Outputs

- `inventory.csv`
- `pdf_text_layer_summary.json`
- `ocr_summary_priority.json`
- `video_analysis.json`
- `image_analysis.json`
- `case_cards.csv`
- `case_cards.json`
- `cases.sqlite`
- `frontend/data.js`
- `video_tracks/*.csv`

---

## Main Database Tables

- `cases`: normalized case records and current classification
- `assets`: local/remote asset provenance and file metadata
- `pdf_text_layers`, `ocr_pages`, `hq_ocr_pages`, `hq_ocr_words`: text and OCR layers
- `videos`, `video_tracking`, `advanced_video_tracks`, `video_hypothesis_comparison`: video metadata, candidate tracks, and review flags
- `images`, `image_forensics`: still-image metadata and artifact flags
- `external_correlations`, `environmental_checks`: weather, moon, launch, fireball, satellite, and queryability controls
- `witness_claims`, `witness_matrix`, `witness_corroboration`: extracted witness/source claims
- `hypotheses`, `bayesian_scores`: heuristic hypothesis ranking
- `review_tasks`, `human_review_protocol`, `missing_data_requests`: work still requiring human review or missing data
- `pipeline_runs`: audit log of generated pipeline layers

---

## Script Reference

### Ingestion

- `war_ufo_downloader.js`: crawls/downloads PDF and image assets from the source site.
- `war_ufo_video_probe.js`: probes visible media/video links.
- `war_ufo_video_download.js`: downloads resolved DVIDS video assets.

### Database and Enrichment

- `war_ufo_build_cases_db.py`: initializes the SQLite schema from generated artifacts.
- `war_ufo_enrich_cases_db.py`: adds classifications, witness claims, hypotheses, and OCR quality notes.
- `war_ufo_populate_methods.py`: populates method/review layers and heuristic scores.
- `war_ufo_complete_review_layers.py`: adds completion audit, missing-data requests, and corroboration groups.

### Media and OCR

- `war_ufo_science_pipeline.py`: inventory, PDF text extraction, OCR routing, video/image summaries, and case-card generation.
- `pdf_forensic_pipeline.py`: quick OCR path for selected PDFs.
- `war_ufo_hq_ocr_witness_matrix.py`: 300 DPI Tesseract TSV/HOCR/TXT OCR and witness-matrix extraction.
- `war_ufo_advanced_video_analysis.py`: candidate tracking, Kalman smoothing, FFT frequency metrics, reticle/zoom/parallax proxies, and video hypothesis flags.

### External Controls

- `war_ufo_fetch_external_correlations.py`: weather, moon, and launch checks.
- `war_ufo_fetch_remaining_external.py`: CNEOS fireballs, CelesTrak decay data, and retry checks.
- `automate_space_correlations.py`: geospatial/temporal vicinity matching.
- `cross_reference_launches.py`, `batch_cross_reference.py`: launch/site cross-reference helpers.
- `satellite_trajectory_check.py`: SGP4 satellite propagation helper.

### Frontend

- `sync_frontend_master.py`: exports `frontend/data.js` from the database.
- `generate_pdf_explorer_data.py`: builds searchable PDF/OCR data for the dashboard.
- `war_ufo_geometry_speed_frontend.py`: generates scenario-based FOV/range/speed bands and frontend views.
- `sync_frontend_data.py`: sync helper for frontend data assets.

---

## Known Gaps

- Manual adjudication is still required for witness-matrix claims and review tasks.
- ADS-B/aviation controls are not complete, especially where timestamps are vague or redacted.
- Many environmental controls use broad location proxies rather than precise coordinates.
- Video target validation is incomplete; current tracks follow candidate contrast features.
- Photogrammetry and angular velocity remain blocked without FOV, range, and platform-pose metadata.
- Still-image artifact review remains pending until original unannotated archival masters are compared.
- No dependency lockfile currently exists; the pipeline expects local Python, Node, SQLite, OpenCV, NumPy, Tesseract, ffmpeg/ffprobe, and Poppler-style PDF tools.

---

## Operational Notes

- `cases.sqlite` is the local forensic core. Do not expose it as a public web asset.
- `external_cache/` and generated JSON/CSV files support offline review after data has been fetched.
- The frontend is generated from local artifacts; update the database first, then regenerate `frontend/data.js`.
