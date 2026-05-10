# PURSUE Release 01 Content Mining Report

Generated from the live `war.gov/UFO/` CSV, direct downloads, extracted PDF text layers, DVIDS video metadata, and sampled video frames.

## Corpus Status

- Live CSV records: 161
- Agencies: Department of War 82, FBI 57, NASA 15, Department of State 7
- File types: 119 PDF, 28 VID, 14 IMG
- Direct PDF/IMG assets: 133/133 found or downloaded
- Video assets: 28/28 DVIDS video records resolved and downloaded as MP4
- Extracted text files from PDFs: 115
- Limitation: older FBI/Air Force/DoW historical PDFs are mostly scanned-image files. Their text layers are weak or absent and require a dedicated OCR pass for complete mining.

## Artifacts

- Live CSV: `/tmp/war_ufo_downloads/uap-csv-live.csv`
- Parsed live records: `/tmp/war_ufo_downloads/records-live.json`
- New direct downloads: `/tmp/war_ufo_downloads/pdf`, `/tmp/war_ufo_downloads/img`
- Existing reused PDFs: `/Users/jaymeeduardo/electron/UAP/pursue-ufo-files/pdfs`
- Extracted PDF text: `/tmp/war_ufo_text`
- DVIDS video metadata: `/tmp/war_ufo_mining/videos/video_meta.json`
- Downloaded MP4s: `/tmp/war_ufo_mining/videos/mp4`
- Video technical probe: `/tmp/war_ufo_mining/videos/video_probe_summary.json`
- Video contact sheets: `/tmp/war_ufo_mining/videos/contact_sheets`
- All-video visual sheet: `/tmp/war_ufo_mining/videos/all_video_contact_sheets.jpg`

## High-Value Findings

### 1. Western US Event: strongest multi-witness narrative package

File: `western_us_event_slides_5.08.2026.pdf`

This is the most striking non-sensor narrative in the release. It summarizes statements from seven federal law-enforcement personnel over two days in the Western US. The event classes are internally distinct:

- Orange orbs launching smaller red orbs in groups of two to four.
- A large fiery orange orb, later estimated by AARO at roughly 12-18 meters diameter and about 1050 meters from observers.
- A dark/triangular or kite-like low object with red/white lights, moving laterally off-road without changing orientation.
- A transparent kite-like object seen partly with NVGs, with witness claim that stars were faintly visible through it.

Mining note: this file has an extractable text layer and should be prioritized for witness-comparison work.

### 2. FBI USPER Statement: senior intelligence witness plus multi-sensor pursuit

File: `usper-statement-redacted.pdf`

The document is marked `SECRET//NOFORN` in the text layer and describes a 2025 search operation involving a senior US intelligence official, partner personnel, helicopters, FLIR/NVG use, and observation-post reports.

Key extracted content:

- Prior reports involved orbs/lights and thuds as if something had fallen.
- LP/OP reported a `super-hot` orb under FLIR at ground level.
- The orb reportedly moved at high speed, broke into two objects, and could not be matched by the helicopter.
- Witnesses later saw a swarm of lights and multiple orange/white/yellow oval orbs flaring up and down in sequence.

Mining note: this is a core cross-sensor/cross-witness file. It has enough text for direct searching despite redactions.

### 3. FBI September 2023 sighting: composite is important, interviews are thin in text extraction

Files:

- `2024-04-30-composite-sketch.pdf`
- `serial-3_redacted.pdf`
- `serial-4-redacted_redacted.pdf`
- `serial 5 redacted_redacted.pdf`

The CSV/record description says the FBI Lab rendering depicts an ellipsoid bronze metallic object, 130-195 feet long, materializing from a bright light and disappearing instantaneously. The interview PDFs have weak text extraction, but one extracted segment mentions witness stress afterward, weird dreams, and TV outage checks after a storm. Another extracted segment says a witness thought it might have been a meteor coming straight toward them.

Mining note: the composite PDF is image-only in text extraction. Visual/OCR review is needed.

### 4. State Department cables are mixed: some serious aviation content, some context/noise

Most important:

- Kazakhstan 1994 cable: a Tajik Air chief pilot and three American pilots in a Boeing 747SP reported a UFO at 41,000 feet over Kazakhstan. Extracted text says the object appeared as an intensely bright light approaching from the eastern horizon at high speed and at a higher altitude.
- Mexico 2003 cable: documents the Mexican congressional UAP hearing, but the cable itself also contains unrelated political reporting. It records that Ryan Graves later criticized the alien-body display as an unsubstantiated stunt.
- Georgia 2001 and Turkmenistan 2004 cables are diplomatically interesting but lower evidentiary value for phenomena. Georgia is a geopolitical denial/deflection cable; Turkmenistan is mainly about a UFOlogist NGO becoming a civil-society partner.

### 5. 1963 "Space Alien Race Question" memo exists and is historically important, but needs manual/OCR work

File: `59_214434_sp_16_[7.18.1963].pdf`

The first page is readable visually and is from the Executive Office of the President, National Aeronautics and Space Council, dated July 18, 1963, subject `Thoughts on the Space Alien Race Question`. The visible text frames the question as policy planning if alien intelligence is discovered in space, while also presenting skepticism toward flying saucer advocates.

Mining note: the PDF is encrypted with copying disabled and `pdftotext` yields no useful text. Tesseract did not extract usable text in the current pass, so this needs a better OCR pipeline or manual transcription.

### 6. NASA material is less sensational than the repo markdown implies

NASA material includes Apollo/Gemini/Skylab transcripts, audio, and annotated images. The Apollo 17 image is explicitly annotated around three colored dots in a triangular formation. Visual inspection confirms the annotated points are small and low-information; the image by itself does not establish object identity, distance, scale, or motion.

The Apollo transcript excerpts contain astronaut observations of bright particles/fragments and unknowns, but in at least one Apollo 17 excerpt the crew explicitly discusses possible mundane sources such as pieces from the S-IVB. This should be framed as historical anomaly/context evidence, not as strong proof.

### 7. Modern DoW mission reports are mostly sensor-track records, not narrative close encounters

Extracted mission-report text repeatedly uses AARO release markings and standardized language. Common patterns:

- `observed an unidentified aerial phenomenon`
- `possible UAP/UAV`
- `Range Fouler Debrief/Reporting Form`
- `negative ES, radar track, and IFF track`
- significant redaction around platform, coordinates, and operational context

Notable extracted details:

- East China Sea 2024: object created IR lens flare on MX-20/MX-25 sensors, suggesting significant heat source; moved through field of view at high speed.
- Arabian Sea 2020 range fouler: three possible unidentified small air contacts; negative ES, radar, and IFF.
- Iraq 2022: possible UAP/UAV flying west to east; no further events observed.
- August 2024 email: possible UAP described as oval/orb.

Mining note: these files are good for structured extraction: date, theater, sensor modality, reported shape, kinematics, correlation/no-correlation with radar/IFF/ES.

## Video Review

All 28 DVIDS video records were resolved via the hidden `DVIDS Video ID` CSV field and DVIDS API. One 720p MP4 rendition per video was downloaded. Every downloaded MP4 probes cleanly as 1280x720 with audio track present.

Durations range from 5.0 seconds to 371.6 seconds. The longest are:

- 1006119 Gemini 7 audio excerpt: 371.6s
- 1006104 Arabian Gulf 2020: 312.0s
- 1006067 UAE October 2023: 297.3s
- 1006097 Arabian Gulf 2020: 293.2s
- 1006080 Greece October 2023: 177.2s
- 1006083 Middle East May 2020: 137.4s
- 1006107 Japan 2023: 119.7s

Visual sampling shows the DoW videos are almost entirely sensor-display footage: infrared/electro-optical imagery, reticles, blacked-out overlays, target boxes, and small contrast regions. They are useful as evidence of what was submitted to AARO, but most are too compressed/redacted/context-poor for independent identification from the video alone.

Important correction: `DOW-UAP-PR38` has CSV video title `Resolved as an Aircraft, Middle East 2013`, even though its record title begins `Unresolved UAP Report`. This should be treated as resolved/likely aircraft unless deeper metadata contradicts it.

Video classes seen in sampled frames:

- Small single contrast point/spot tracked by IR.
- Split EO/SWIR views where the object is detectable in one modality and weak/absent in another.
- Reticle/box tracking over sea or terrain with heavy overlays.
- At least one video includes an apparent ship/sea context, likely important for reflection/sea-source hypotheses.
- Several videos show very short clips of small fast-moving points with minimal environmental context.
- Gemini 7 record is audio presented as a NASA-logo video wrapper, not visual UAP footage.

## What Is Strongest vs Weakest

Strongest for follow-up:

- Western US Event: multi-witness, multiple phenomenon categories, concise text.
- USPER Statement: senior intelligence witness, FLIR/NVG/LP-OP/helicopter chain, clear sequence.
- September 2023 FBI case: composite plus multiple 302s, but needs better OCR/manual review.
- Modern DoW mission reports with negative radar/IFF/ES and sensor descriptions.
- DVIDS videos paired to specific mission reports, especially longer clips with sensor modality changes.

Weakest or most easily overclaimed:

- Apollo 17 image: visually intriguing but low-information without original NASA frame provenance, artifact analysis, and context.
- Broad statements about `NASA astronauts consistently reported UAP`: the transcripts include mundane fragment discussions and should be handled carefully.
- State Department Turkmenistan/Georgia cables: they mention UFOs but are not strong anomaly evidence.
- Historical FBI scans: potentially important, but not yet mined until OCR is done.

## Recommended Next Pass

1. Build a real OCR pipeline for the scanned historical PDFs, especially FBI 62-HQ-83894, 1944-1945 foofighter documents, and the 1963 memo.
2. For modern mission reports, extract a structured table with fields: date, location, platform redaction marker, sensor type, object description, motion, radar/IFF/ES correlation, and paired DVIDS video ID.
3. For videos, compare each DVIDS clip against the associated mission-report language and produce case cards with still frames.
4. For NASA images, locate original NASA catalog IDs and compare the PURSUE annotated images against unannotated originals.
5. For witness files, manually OCR/transcribe the FBI 302s and compare phrase-level consistency across witnesses.
