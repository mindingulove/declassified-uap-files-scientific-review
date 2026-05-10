import os
#!/usr/bin/env python3
import csv
import json
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/tmp/war_ufo_science")
DB = BASE / "cases.sqlite"
HQ = BASE / "hq_ocr"
PAGES = HQ / "pages"
OUT = HQ / "tesseract"
DOCS = HQ / "documents"
for d in [HQ, PAGES, OUT, DOCS]:
    d.mkdir(parents=True, exist_ok=True)

HIGH_VALUE_IDS = [156, 161, 157, 158, 159, 160, 29, 22, 25, 32]


def slug(s, n=100):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s or "").strip("-").lower()[:n] or "file"


def run(cmd, cwd=None, timeout=None):
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)


def pdf_pages(path):
    p = run(["pdfinfo", path], timeout=60)
    m = re.search(r"^Pages:\s+(\d+)", p.stdout, re.M)
    return int(m.group(1)) if m else 0


def render_page(pdf, doc_slug, page):
    base = PAGES / f"{doc_slug}-p{page:04d}"
    existing = sorted(PAGES.glob(f"{base.name}-*.png"))
    if existing:
        return existing[0]
    # 300 DPI preserves layout and small type better for scans.
    r = run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", "300", "-png", pdf, str(base)], timeout=180)
    existing = sorted(PAGES.glob(f"{base.name}-*.png"))
    if not existing:
        raise RuntimeError(f"pdftoppm failed page {page}: {r.stderr[:500]}")
    return existing[0]


def ocr_page(png, doc_slug, page):
    out_base = OUT / f"{doc_slug}-p{page:04d}"
    txt = Path(str(out_base) + ".txt")
    tsv = Path(str(out_base) + ".tsv")
    hocr = OUT / f"{doc_slug}-p{page:04d}.hocr"
    if txt.exists() and tsv.exists() and hocr.exists():
        return txt, tsv, hocr
    # Local Tesseract build previously failed on absolute image paths; use cwd.
    r = run(
        ["tesseract", png.name, str(out_base), "-l", "eng", "--psm", "6", "txt", "tsv", "hocr"],
        cwd=png.parent,
        timeout=240,
    )
    if not tsv.exists():
        raise RuntimeError(f"tesseract failed {png}: {r.stderr[:500]}")
    return txt, tsv, hocr


def parse_tsv(tsv_path):
    words = []
    confs = []
    with open(tsv_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            text = (row.get("text") or "").strip()
            try:
                conf = float(row.get("conf", "-1"))
            except ValueError:
                conf = -1
            if text and conf >= 0:
                item = {
                    "word": text,
                    "conf": conf,
                    "left": int(float(row.get("left") or 0)),
                    "top": int(float(row.get("top") or 0)),
                    "width": int(float(row.get("width") or 0)),
                    "height": int(float(row.get("height") or 0)),
                    "block_num": int(float(row.get("block_num") or 0)),
                    "par_num": int(float(row.get("par_num") or 0)),
                    "line_num": int(float(row.get("line_num") or 0)),
                    "word_num": int(float(row.get("word_num") or 0)),
                }
                words.append(item)
                confs.append(conf)
    avg = sum(confs) / len(confs) if confs else None
    return words, avg


def split_sentences(text):
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 30]


def claim_type(sentence):
    s = sentence.lower()
    if any(k in s for k in ["i saw", "observed", "witness", "first-hand", "stated that", "reported that"]):
        return "witness_observation"
    if any(k in s for k in ["radar", "flir", "infrared", "nvg", "sensor", "video", "helicopter"]):
        return "sensor_or_platform"
    if any(k in s for k in ["orb", "sphere", "disc", "disk", "object", "light", "uap", "ufo"]):
        return "object_description"
    if any(k in s for k in ["moving", "hover", "accelerat", "launched", "turn", "track", "pursuit"]):
        return "motion"
    return None


def extract_fields(sentence):
    s = sentence
    field = {
        "time_stated": None,
        "location_stated": None,
        "shape": None,
        "color_brightness": None,
        "motion": None,
        "sound": None,
        "duration": None,
        "sensor": None,
        "directness": "not_assessed",
        "independence_status": "not_assessed",
    }
    tm = re.search(r"\b(\d{1,2}:\d{2}\s*(?:Z|UTC|AM|PM)?)\b", s, re.I)
    if tm:
        field["time_stated"] = tm.group(1)
    dur = re.search(r"\b(\d+\s*(?:seconds?|minutes?|hours?|hrs?|mins?))\b", s, re.I)
    if dur:
        field["duration"] = dur.group(1)
    for shape in ["orb", "sphere", "disc", "disk", "light", "object", "triangle", "cylinder"]:
        if re.search(rf"\b{shape}s?\b", s, re.I):
            field["shape"] = shape
            break
    for motion in ["hovering", "hover", "moving", "accelerating", "launched", "turning", "tracked", "pursuit", "stationary"]:
        if motion in s.lower():
            field["motion"] = motion
            break
    for sensor in ["FLIR", "infrared", "IR", "NVG", "SWIR", "EO", "radar", "IFF", "helicopter", "video"]:
        if re.search(rf"\b{re.escape(sensor)}\b", s, re.I):
            field["sensor"] = sensor
            break
    if re.search(r"\b(red|green|white|blue|orange|bright|dark|super-hot|hot)\b", s, re.I):
        field["color_brightness"] = re.search(r"\b(red|green|white|blue|orange|bright|dark|super-hot|hot)\b", s, re.I).group(1)
    if re.search(r"\b(no sound|silent|sound|noise|heard)\b", s, re.I):
        field["sound"] = re.search(r"\b(no sound|silent|sound|noise|heard)\b", s, re.I).group(1)
    if re.search(r"\b(first-hand|i saw|observed|witnessed|fbi 302|interview)\b", s, re.I):
        field["directness"] = "direct_or_interviewed_observation"
    if re.search(r"\b(multiple|corroborat|separately|independent|seven|two witnesses)\b", s, re.I):
        field["independence_status"] = "possible_independent"
    loc = re.search(r"\b(United States|Western United States|Germany|Detroit|Iraq|Syria|Moon|Middle East|Arabian Gulf|military installation)\b", s, re.I)
    if loc:
        field["location_stated"] = loc.group(1)
    return field


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS hq_ocr_documents (
          case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
          source_pdf TEXT NOT NULL,
          pages INTEGER,
          combined_text_path TEXT,
          avg_word_confidence REAL,
          word_count INTEGER,
          hocr_dir TEXT,
          tsv_dir TEXT,
          ocr_engine TEXT,
          created_at TEXT,
          updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS hq_ocr_pages (
          case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
          page_number INTEGER NOT NULL,
          image_path TEXT,
          text_path TEXT,
          tsv_path TEXT,
          hocr_path TEXT,
          avg_word_confidence REAL,
          word_count INTEGER,
          char_count INTEGER,
          PRIMARY KEY(case_id, page_number)
        );

        CREATE TABLE IF NOT EXISTS hq_ocr_words (
          case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
          page_number INTEGER NOT NULL,
          word_index INTEGER NOT NULL,
          word TEXT NOT NULL,
          confidence REAL,
          left INTEGER,
          top INTEGER,
          width INTEGER,
          height INTEGER,
          block_num INTEGER,
          par_num INTEGER,
          line_num INTEGER,
          word_num INTEGER,
          PRIMARY KEY(case_id, page_number, word_index)
        );

        CREATE TABLE IF NOT EXISTS witness_matrix (
          claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
          case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
          source_page INTEGER,
          source_text_path TEXT,
          source_quote TEXT,
          claim_type TEXT,
          witness_label TEXT,
          directness TEXT,
          independence_status TEXT,
          time_stated TEXT,
          location_stated TEXT,
          shape TEXT,
          color_brightness TEXT,
          motion TEXT,
          sound TEXT,
          duration TEXT,
          sensor TEXT,
          page_avg_confidence REAL,
          extraction_method TEXT,
          review_status TEXT DEFAULT 'needs_human_review'
        );
        """
    )

    rows = conn.execute(
        """
        SELECT c.case_id,c.title,a.local_path
        FROM cases c JOIN assets a USING(case_id)
        WHERE c.case_id IN (%s) AND a.local_path IS NOT NULL
        ORDER BY c.case_id
        """ % ",".join(str(x) for x in HIGH_VALUE_IDS)
    ).fetchall()

    for row in rows:
        case_id = row["case_id"]
        pdf = row["local_path"]
        title_slug = f"{case_id:03d}-{slug(row['title'])}"
        pages = pdf_pages(pdf)
        all_confs = []
        all_text = []
        conn.execute("DELETE FROM hq_ocr_pages WHERE case_id=?", (case_id,))
        conn.execute("DELETE FROM hq_ocr_words WHERE case_id=?", (case_id,))
        for page in range(1, pages + 1):
            print(f"HQ OCR case {case_id} page {page}/{pages}: {row['title']}", flush=True)
            png = render_page(pdf, title_slug, page)
            txt, tsv, hocr = ocr_page(png, title_slug, page)
            page_text = txt.read_text(errors="ignore") if txt.exists() else ""
            words, avg = parse_tsv(tsv)
            if avg is not None:
                all_confs += [w["conf"] for w in words]
            all_text.append(f"\n\n--- PAGE {page} ---\n{page_text}")
            conn.execute(
                """
                INSERT OR REPLACE INTO hq_ocr_pages
                (case_id,page_number,image_path,text_path,tsv_path,hocr_path,avg_word_confidence,word_count,char_count)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (case_id, page, str(png), str(txt), str(tsv), str(hocr), avg, len(words), len(page_text)),
            )
            for i, w in enumerate(words, 1):
                conn.execute(
                    """
                    INSERT INTO hq_ocr_words
                    (case_id,page_number,word_index,word,confidence,left,top,width,height,block_num,par_num,line_num,word_num)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        case_id, page, i, w["word"], w["conf"], w["left"], w["top"], w["width"], w["height"],
                        w["block_num"], w["par_num"], w["line_num"], w["word_num"],
                    ),
                )
        combined = DOCS / f"{title_slug}.hq.txt"
        combined.write_text("".join(all_text), encoding="utf-8", errors="ignore")
        avg_doc = sum(all_confs) / len(all_confs) if all_confs else None
        conn.execute(
            """
            INSERT OR REPLACE INTO hq_ocr_documents
            (case_id,source_pdf,pages,combined_text_path,avg_word_confidence,word_count,hocr_dir,tsv_dir,ocr_engine,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (case_id, pdf, pages, str(combined), avg_doc, len(all_confs), str(OUT), str(OUT), "tesseract 5.5.2 eng --psm 6 TSV+HOCR+TXT at 300 DPI", now, now),
        )
        conn.commit()

    # Build a page-cited witness matrix from HQ OCR pages.
    conn.execute("DELETE FROM witness_matrix")
    hv_pages = conn.execute(
        """
        SELECT p.case_id,p.page_number,p.text_path,p.avg_word_confidence,c.witnesses,c.title
        FROM hq_ocr_pages p JOIN cases c USING(case_id)
        ORDER BY p.case_id,p.page_number
        """
    ).fetchall()
    for p in hv_pages:
        text = Path(p["text_path"]).read_text(errors="ignore") if p["text_path"] else ""
        for sent in split_sentences(text):
            ctype = claim_type(sent)
            if not ctype:
                continue
            fields = extract_fields(sent)
            conn.execute(
                """
                INSERT INTO witness_matrix
                (case_id,source_page,source_text_path,source_quote,claim_type,witness_label,directness,
                 independence_status,time_stated,location_stated,shape,color_brightness,motion,sound,duration,
                 sensor,page_avg_confidence,extraction_method,review_status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    p["case_id"], p["page_number"], p["text_path"], sent[:1000], ctype, p["witnesses"],
                    fields["directness"], fields["independence_status"], fields["time_stated"], fields["location_stated"],
                    fields["shape"], fields["color_brightness"], fields["motion"], fields["sound"], fields["duration"],
                    fields["sensor"], p["avg_word_confidence"], "regex over HQ OCR page text", "needs_human_review",
                ),
            )
    conn.execute(
        """
        INSERT INTO pipeline_runs (
          run_time, source_base, inventory_count, ocr_document_count, video_count, image_count, notes
        )
        SELECT ?, ?, (SELECT count(*) FROM cases), (SELECT count(*) FROM hq_ocr_documents),
               (SELECT count(*) FROM videos), (SELECT count(*) FROM images),
               ?
        """,
        (now, str(BASE), "High-quality OCR subset with TSV/HOCR confidence and page-cited witness_matrix generated."),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
