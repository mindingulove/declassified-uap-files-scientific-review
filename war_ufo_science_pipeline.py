#!/usr/bin/env python3
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE = Path("/tmp/war_ufo_science")
CSV_PATH = Path("/tmp/war_ufo_downloads/uap-csv-live.csv")
REPO_PDF = Path("./pdfs")
TMP_PDF = Path("/tmp/war_ufo_downloads/pdf")
TMP_IMG = Path("/tmp/war_ufo_downloads/img")
TMP_VIDEO = Path("./war_ufo_mining/videos/mp4")
TEXT_LAYER = BASE / "text_layer"
OCR_TEXT = BASE / "ocr_text"
PAGE_OCR_TEXT = BASE / "page_ocr_text"
PDF_PAGES = BASE / "pdf_pages"
VIDEO_FRAMES = BASE / "video_frames"
IMAGE_META = BASE / "image_meta"
CASE_CARDS = BASE / "case_cards"


def mkdirs():
    for p in [BASE, TEXT_LAYER, OCR_TEXT, PAGE_OCR_TEXT, PDF_PAGES, VIDEO_FRAMES, IMAGE_META, CASE_CARDS]:
        p.mkdir(parents=True, exist_ok=True)


def slug(s, n=120):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-").lower()
    return s[:n] or "file"


def file_name_for(url, typ, title):
    if url and url.startswith("http"):
        name = unquote(os.path.basename(urlparse(url).path))
    else:
        name = ""
    if not name or "." not in name:
        name = slug(title)
        if typ == "PDF":
            name += ".pdf"
        elif typ == "IMG":
            name += ".jpg"
    return name


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd, timeout=None):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)


def run_cwd(cmd, cwd, timeout=None):
    return subprocess.run(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)


def load_records():
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    records = []
    for i, r in enumerate(rows, start=1):
        records.append({
            "record_index": i,
            "redaction": r.get("Redaction", ""),
            "release_date": r.get("Release Date", ""),
            "title": r.get("Title", "").strip(),
            "type": r.get("Type", "").strip(),
            "video_pairing": r.get("Video Pairing", "").strip(),
            "pdf_pairing": r.get("PDF Pairing", "").strip(),
            "description": r.get("Description Blurb", "").strip(),
            "dvids_video_id": r.get("DVIDS Video ID", "").strip(),
            "video_title": r.get("Video Title", "").strip(),
            "agency": r.get("Agency", "").strip(),
            "incident_date": r.get("Incident Date", "").strip(),
            "incident_location": r.get("Incident Location", "").strip(),
            "asset_url": r.get("PDF | Image Link", "").strip(),
            "modal_image": r.get("Modal Image", "").strip(),
        })
    return [r for r in records if r["title"]]


def find_local_asset(r):
    if r["type"] in {"PDF", "IMG"} and r["asset_url"].startswith("http"):
        name = file_name_for(r["asset_url"], r["type"], r["title"])
        dirs = [REPO_PDF, TMP_PDF] if r["type"] == "PDF" else [TMP_IMG, TMP_PDF, REPO_PDF]
        for d in dirs:
            p = d / name
            if p.exists() and p.stat().st_size > 1000:
                return str(p)
    if r["type"] == "VID" and r["dvids_video_id"]:
        matches = sorted(TMP_VIDEO.glob(f"{r['dvids_video_id']}-*.mp4"))
        if matches:
            return str(matches[0])
    return ""


def build_inventory():
    records = load_records()
    for r in records:
        p = find_local_asset(r)
        r["local_path"] = p
        if p:
            pp = Path(p)
            r["local_filename"] = pp.name
            r["local_size"] = pp.stat().st_size
            r["sha256"] = sha256(pp)
        else:
            r["local_filename"] = ""
            r["local_size"] = 0
            r["sha256"] = ""
    (BASE / "inventory.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    with open(BASE / "inventory.csv", "w", newline="", encoding="utf-8") as f:
        fields = list(records[0].keys())
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(records)
    return records


def pdf_page_count(path):
    r = run(["pdfinfo", path])
    m = re.search(r"^Pages:\s+(\d+)", r.stdout, re.M)
    return int(m.group(1)) if m else None


def extract_text_layer(records):
    results = []
    pdfs = [r for r in records if r["type"] == "PDF" and r["local_path"]]
    seen = {}
    for r in pdfs:
        path = r["local_path"]
        if path in seen:
            r["text_layer_path"] = seen[path]["text_layer_path"]
            r["text_layer_chars"] = seen[path]["text_layer_chars"]
            r["pages"] = seen[path]["pages"]
            continue
        out = TEXT_LAYER / f"{r['record_index']:03d}-{slug(r['title'])}.txt"
        if not out.exists():
            run(["pdftotext", "-layout", path, str(out)], timeout=180)
        chars = out.stat().st_size if out.exists() else 0
        pages = pdf_page_count(path)
        item = {
            "record_index": r["record_index"],
            "title": r["title"],
            "path": path,
            "pages": pages,
            "text_layer_path": str(out),
            "text_layer_chars": chars,
            "chars_per_page": (chars / pages) if pages else None,
            "needs_ocr": bool(pages and chars / max(pages, 1) < 80),
        }
        seen[path] = item
        results.append(item)
        r["text_layer_path"] = str(out)
        r["text_layer_chars"] = chars
        r["pages"] = pages
    (BASE / "pdf_text_layer_summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def ocr_pdf(path, out_txt, max_pages=None):
    pages = pdf_page_count(path) or 0
    if max_pages:
        pages = min(pages, max_pages)
    page_items = []
    for page in range(1, pages + 1):
        page_base = PDF_PAGES / f"{slug(Path(path).stem, 80)}-p{page:04d}"
        existing = sorted(PDF_PAGES.glob(f"{page_base.name}-*.png"))
        if not existing:
            run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", "170", "-png", path, str(page_base)], timeout=180)
            existing = sorted(PDF_PAGES.glob(f"{page_base.name}-*.png"))
        if existing:
            png = existing[0]
            txt = PAGE_OCR_TEXT / f"{slug(Path(path).stem, 80)}-p{page:04d}.txt"
            page_items.append((page, png, txt))

    def ocr_one(item):
        page, png, txt = item
        if not txt.exists() or txt.stat().st_size == 0:
            # This local Tesseract/Leptonica build fails on absolute image paths.
            # Run from the page-image directory and pass only the image basename.
            run_cwd(["tesseract", png.name, str(txt.with_suffix("")), "-l", "eng", "--psm", "6"], png.parent, timeout=240)
        return page, txt

    workers = max(1, int(os.environ.get("WAR_UFO_OCR_WORKERS", "4")))
    completed = []
    if workers == 1:
        for item in page_items:
            completed.append(ocr_one(item))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(ocr_one, item) for item in page_items]
            for fut in as_completed(futures):
                completed.append(fut.result())

    chunks = []
    for _, txt in sorted(completed):
        if txt.exists():
            chunks.append(txt.read_text(errors="ignore"))
    out_txt.write_text("\n\n".join(chunks), encoding="utf-8", errors="ignore")
    return out_txt.stat().st_size if out_txt.exists() else 0


def evidence_priority(r):
    blob = f"{r['title']} {r['description']} {r['agency']} {r['incident_location']} {r.get('video_title','')}".lower()
    score = 0
    reasons = []

    def add(points, reason):
        nonlocal score
        score += points
        reasons.append(reason)

    # Strong scientific value: direct, attributable, or independently corroborated observations.
    if "fbi 302" in blob:
        add(5, "formal FBI 302 witness interview")
    if "senior us intelligence official" in blob:
        add(5, "senior intelligence witness")
    if "federal law enforcement" in blob or "federal government" in blob or "federal employees" in blob:
        add(4, "government employee witnesses")
    if "corroborating eyewitness" in blob or "multiple witnesses" in blob or "separately reported" in blob or "independently" in blob:
        add(4, "multi-witness/corroboration language")
    if "first-hand account" in blob:
        add(3, "direct witness testimony")
    if "eyewitness reports" in blob or "eyewitness testimonies" in blob:
        add(1, "generic eyewitness-history language")

    # Cross-sensor or paired media value.
    if r.get("dvids_video_id"):
        add(4, "paired DVIDS video record")
    if any(k in blob for k in ["infrared", "flir", "nvg", "short-wave infrared", "swir", "electro-optical", "radar", "iff"]):
        add(3, "sensor or sensor-correlation language")
    if "mission report" in blob or "range fouler" in blob:
        add(2, "standardized operational reporting form")

    # High-value named cases/documents.
    if "western us event" in blob or "orbs launching orbs" in blob:
        add(5, "high-value Western US multi-category case")
    if "composite sketch" in blob or "fbi lab rendered" in blob:
        add(4, "forensic/rendered witness-composite material")
    if "space alien race question" in blob:
        add(4, "unique presidential-council policy memo")
    if "foofighter" in blob or "foo fighter" in blob or "1944" in blob and "german" in blob:
        add(4, "WWII-era UAP/foofighter historical record")
    if "maury" in blob:
        add(3, "named early UFO-history case")

    # Generic historical bulk files have value, but should not dominate triage without specifics.
    if "62-hq-83894" in blob:
        add(1, "large FBI historical UFO case file")
    if "flying discs 1949" in blob or "incident reports on unidentified flying objects" in blob:
        add(4, "structured historical incident-report collection")
    if re.search(r"\bgeneral[_ ]?194[678]\b", blob):
        add(0, "generic early archive volume; not priority by itself")

    # Penalize items that are mainly contextual or already resolved.
    if "resolved as an aircraft" in blob:
        add(-5, "marked resolved as aircraft")
    if "launch summary" in blob or "launch history" in blob:
        add(-2, "background launch-history reference")
    if "ufoiogists" in blob or "civil society" in blob:
        add(-3, "diplomatic/civil-society context, weak anomaly evidence")

    return score, reasons


def ocr_needed_pdfs(records, mode="priority"):
    summaries = json.loads((BASE / "pdf_text_layer_summary.json").read_text())
    by_index = {x["record_index"]: x for x in summaries}
    scored = []
    for r in records:
        if r["type"] != "PDF" or not r["local_path"]:
            continue
        s = by_index.get(r["record_index"])
        if not s or not s["needs_ocr"]:
            continue
        score, reasons = evidence_priority(r)
        scored.append({"record_index": r["record_index"], "title": r["title"], "score": score, "reasons": reasons, "description_key": r["description"][:140]})

    (BASE / "ocr_priority_scores.json").write_text(json.dumps(sorted(scored, key=lambda x: x["score"], reverse=True), indent=2), encoding="utf-8")

    targets = []
    group_counts = {}
    for item in sorted(scored, key=lambda x: x["score"], reverse=True):
        r = next(x for x in records if x["record_index"] == item["record_index"])
        if mode == "all":
            targets.append((r, item))
            continue
        if item["score"] < 4:
            continue
        key = item["description_key"]
        group_counts[key] = group_counts.get(key, 0) + 1
        # Avoid letting broad duplicated FBI/archive descriptions consume the whole interactive OCR pass.
        if group_counts[key] > int(os.environ.get("WAR_UFO_PRIORITY_GROUP_CAP", "3")):
            continue
        targets.append((r, item))
    results = []
    for i, (r, priority_item) in enumerate(targets, start=1):
        out = OCR_TEXT / f"{r['record_index']:03d}-{slug(r['title'])}.ocr.txt"
        priority_cap = int(os.environ.get("WAR_UFO_PRIORITY_OCR_PAGES", "5"))
        max_pages = None if mode == "all" else min(int(r.get("pages") or 9999), priority_cap)
        force_ocr = os.environ.get("WAR_UFO_FORCE_OCR", "0") == "1"
        if force_ocr or not out.exists() or out.stat().st_size == 0:
            print(f"OCR {i}/{len(targets)} pages={'all' if max_pages is None else max_pages}: {r['title']}", flush=True)
            try:
                chars = ocr_pdf(r["local_path"], out, max_pages=max_pages)
            except Exception as e:
                chars = 0
                results.append({"record_index": r["record_index"], "title": r["title"], "error": str(e)})
                continue
        else:
            chars = out.stat().st_size
        results.append({
            "record_index": r["record_index"],
            "title": r["title"],
            "ocr_path": str(out),
            "ocr_chars": chars,
            "priority_score": priority_item["score"],
            "priority_reasons": priority_item["reasons"],
            "mode": mode,
        })
    (BASE / f"ocr_summary_{mode}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def analyze_videos(records):
    rows = []
    for r in records:
        if r["type"] != "VID" or not r["local_path"]:
            continue
        path = r["local_path"]
        probe_path = BASE / "video_probe_json"
        probe_path.mkdir(exist_ok=True)
        out_json = probe_path / f"{r['dvids_video_id']}.json"
        if not out_json.exists():
            pr = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path], timeout=120)
            out_json.write_text(pr.stdout, encoding="utf-8")
        data = json.loads(out_json.read_text() or "{}")
        vstream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
        astream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
        duration = float(data.get("format", {}).get("duration") or 0)
        frame_dir = VIDEO_FRAMES / r["dvids_video_id"]
        frame_dir.mkdir(exist_ok=True)
        frame_paths = []
        for pct in [0.1, 0.3, 0.5, 0.7, 0.9]:
            jpg = frame_dir / f"{int(pct * 100):02d}.jpg"
            if not jpg.exists() and duration:
                run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{duration*pct:.3f}", "-i", path, "-frames:v", "1", "-vf", "scale=640:-1", str(jpg)], timeout=120)
            if jpg.exists():
                frame_paths.append(str(jpg))
        desc = r["description"].lower()
        rows.append({
            "record_index": r["record_index"],
            "dvids_video_id": r["dvids_video_id"],
            "title": r["title"],
            "video_title": r["video_title"],
            "duration_seconds": duration,
            "width": vstream.get("width"),
            "height": vstream.get("height"),
            "has_audio": bool(astream),
            "local_path": path,
            "sample_frames": frame_paths,
            "claimed_sensor": "infrared" if "infrared" in desc else ("swir/eo" if "short-wave infrared" in desc or "electro-optical" in desc else ""),
            "description_flags": {
                "resolved_as_aircraft": "resolved as an aircraft" in (r["video_title"] + " " + r["description"]).lower(),
                "reflection_possible": "reflection" in desc,
                "no_written_description": "did not provide any oral or written description" in desc,
                "looped": "looped" in desc,
            }
        })
    (BASE / "video_analysis.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows


def analyze_images(records):
    rows = []
    for r in records:
        if r["type"] != "IMG" or not r["local_path"]:
            continue
        pr = run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", r["local_path"]], timeout=60)
        width = height = None
        for line in pr.stdout.splitlines():
            if "pixelWidth:" in line:
                width = int(line.split(":")[-1].strip())
            if "pixelHeight:" in line:
                height = int(line.split(":")[-1].strip())
        rows.append({
            "record_index": r["record_index"],
            "title": r["title"],
            "agency": r["agency"],
            "incident_date": r["incident_date"],
            "incident_location": r["incident_location"],
            "local_path": r["local_path"],
            "width": width,
            "height": height,
            "description": r["description"],
            "initial_risk_flags": {
                "annotated_or_highlighted": any(k in r["description"].lower() for k in ["highlight", "annotat", "rendered", "overlay"]),
                "archival_photo": "archival" in r["description"].lower(),
                "submitted_to_aaro": "submitted" in r["description"].lower() and "aaro" in r["description"].lower(),
            }
        })
    (BASE / "image_analysis.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows


def summarize_cases(records):
    text_summary = json.loads((BASE / "pdf_text_layer_summary.json").read_text()) if (BASE / "pdf_text_layer_summary.json").exists() else []
    text_by_index = {x["record_index"]: x for x in text_summary}
    video_by_index = {x["record_index"]: x for x in json.loads((BASE / "video_analysis.json").read_text())} if (BASE / "video_analysis.json").exists() else {}
    image_by_index = {x["record_index"]: x for x in json.loads((BASE / "image_analysis.json").read_text())} if (BASE / "image_analysis.json").exists() else {}
    cards = []
    for r in records:
        evidence = []
        limitations = []
        if r["type"] == "PDF":
            s = text_by_index.get(r["record_index"], {})
            evidence.append(f"PDF pages: {s.get('pages')}; embedded text chars: {s.get('text_layer_chars')}")
            if s.get("needs_ocr"):
                limitations.append("Low or absent embedded text; OCR/manual transcription required for reliable content mining.")
        elif r["type"] == "VID":
            v = video_by_index.get(r["record_index"], {})
            evidence.append(f"Video duration: {v.get('duration_seconds')}s; resolution: {v.get('width')}x{v.get('height')}; DVIDS ID: {r['dvids_video_id']}")
            if v.get("description_flags", {}).get("resolved_as_aircraft"):
                limitations.append("DVIDS/CSV title marks this as resolved as aircraft despite UAP title wording.")
            if v.get("description_flags", {}).get("no_written_description"):
                limitations.append("Original reporter did not provide oral/written description; video context is thin.")
        elif r["type"] == "IMG":
            im = image_by_index.get(r["record_index"], {})
            evidence.append(f"Image dimensions: {im.get('width')}x{im.get('height')}")
            if im.get("initial_risk_flags", {}).get("annotated_or_highlighted"):
                limitations.append("Annotated/highlighted image; original unannotated source should be compared.")
        score, score_reasons = evidence_priority(r)
        blob = f"{r['title']} {r['description']}".lower()
        if r["type"] == "VID":
            score += 2
            score_reasons.append("downloaded inspectable video asset")
        if r["type"] == "IMG":
            score_reasons.append("still image requires provenance/artifact checks")
        if r["incident_date"] in {"N/A", ""}:
            score -= 1
            score_reasons.append("weak or absent incident date")
        score -= 1 if r["incident_date"] in {"N/A", ""} else 0
        cards.append({
            "record_index": r["record_index"],
            "title": r["title"],
            "type": r["type"],
            "agency": r["agency"],
            "incident_date": r["incident_date"],
            "incident_location": r["incident_location"],
            "local_path": r["local_path"],
            "scientific_priority_score": score,
            "priority_reasons": score_reasons,
            "evidence_available": evidence,
            "limitations": limitations,
            "description": r["description"],
        })
    cards.sort(key=lambda x: x["scientific_priority_score"], reverse=True)
    (BASE / "case_cards.json").write_text(json.dumps(cards, indent=2), encoding="utf-8")
    with open(BASE / "case_cards.csv", "w", newline="", encoding="utf-8") as f:
        fields = ["record_index", "scientific_priority_score", "type", "agency", "incident_date", "incident_location", "title", "local_path", "limitations", "description"]
        w = csv.DictWriter(f, fields)
        w.writeheader()
        for c in cards:
            row = {k: c.get(k, "") for k in fields}
            row["limitations"] = " | ".join(c["limitations"])
            w.writerow(row)
    return cards


def report(records):
    cards = json.loads((BASE / "case_cards.json").read_text())
    pdfs = [r for r in records if r["type"] == "PDF"]
    vids = [r for r in records if r["type"] == "VID"]
    imgs = [r for r in records if r["type"] == "IMG"]
    text_summary = json.loads((BASE / "pdf_text_layer_summary.json").read_text())
    low_text = [x for x in text_summary if x["needs_ocr"]]
    md = []
    md.append("# PURSUE Scientific Analysis - Pipeline Report\n")
    md.append("## Corpus\n")
    md.append(f"- Records: {len(records)}\n- PDFs: {len(pdfs)}\n- Videos: {len(vids)}\n- Images: {len(imgs)}\n")
    md.append(f"- Local assets found: {sum(1 for r in records if r['local_path'])}/{len(records)}\n")
    md.append(f"- PDFs with low/absent embedded text: {len(low_text)}/{len(text_summary)}\n")
    md.append("\n## Reproducible Outputs\n")
    for p in ["inventory.csv", "pdf_text_layer_summary.json", "ocr_summary_priority.json", "video_analysis.json", "image_analysis.json", "case_cards.csv", "case_cards.json"]:
        if (BASE / p).exists():
            md.append(f"- `{BASE / p}`\n")
    md.append("\n## Highest Priority Cases\n")
    for c in cards[:25]:
        md.append(f"### {c['record_index']}. {c['title']}\n")
        md.append(f"- Score: {c['scientific_priority_score']}; Type: {c['type']}; Agency: {c['agency']}; Date: {c['incident_date']}; Location: {c['incident_location']}\n")
        md.append(f"- Asset: `{c['local_path']}`\n")
        if c["limitations"]:
            md.append(f"- Limitations: {'; '.join(c['limitations'])}\n")
        if c.get("priority_reasons"):
            md.append(f"- Priority reasons: {'; '.join(c['priority_reasons'])}\n")
        md.append(f"- Description: {c['description'][:800].replace(chr(10), ' ')}\n\n")
    md.append("\n## Scientific Interpretation Rules Used\n")
    md.append("- Treat videos as sensor evidence, not self-interpreting proof. Context, sensor geometry, range, platform motion, and environmental correlation are required before kinematic claims.\n")
    md.append("- Treat annotated images as leads only until unannotated originals are compared.\n")
    md.append("- Treat scanned historical PDFs as unmined until OCR/manual transcription reaches acceptable quality.\n")
    md.append("- Separate direct witness testimony, agency summary, and later analytical comment.\n")
    (BASE / "scientific_pipeline_report.md").write_text("".join(md), encoding="utf-8")


def main():
    mkdirs()
    command = sys.argv[1] if len(sys.argv) > 1 else "all"
    records = build_inventory()
    if command in {"all", "inventory"}:
        print(f"inventory written: {BASE / 'inventory.csv'}")
    if command in {"all", "text"}:
        extract_text_layer(records)
        print(f"text-layer summary written: {BASE / 'pdf_text_layer_summary.json'}")
    if command in {"all", "ocr-priority"}:
        if not (BASE / "pdf_text_layer_summary.json").exists():
            extract_text_layer(records)
        ocr_needed_pdfs(records, mode="priority")
        print(f"priority OCR summary written: {BASE / 'ocr_summary_priority.json'}")
    if command == "ocr-all":
        if not (BASE / "pdf_text_layer_summary.json").exists():
            extract_text_layer(records)
        ocr_needed_pdfs(records, mode="all")
        print(f"all OCR summary written: {BASE / 'ocr_summary_all.json'}")
    if command in {"all", "video"}:
        analyze_videos(records)
        print(f"video analysis written: {BASE / 'video_analysis.json'}")
    if command in {"all", "image"}:
        analyze_images(records)
        print(f"image analysis written: {BASE / 'image_analysis.json'}")
    if command in {"all", "cards"}:
        summarize_cases(records)
        report(records)
        print(f"report written: {BASE / 'scientific_pipeline_report.md'}")


if __name__ == "__main__":
    main()
