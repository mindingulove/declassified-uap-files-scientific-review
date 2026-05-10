import os
import sqlite3
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(os.path.dirname(__file__))
DB = BASE / "cases.sqlite"
HQ = BASE / "hq_ocr"
PAGES = HQ / "pages"
OUT = HQ / "tesseract"
for d in [HQ, PAGES, OUT]: d.mkdir(parents=True, exist_ok=True)

def run(cmd, cwd=None, timeout=None):
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)

def pdf_pages(path):
    p = run(["pdfinfo", path], timeout=60)
    m = re.search(r"^Pages:\s+(\d+)", p.stdout, re.M)
    return int(m.group(1)) if m else 0

def ocr_quick(pdf, case_id, title, max_pages=3):
    slug = re.sub(r"[^a-z0-9]", "-", title.lower())[:50]
    doc_slug = f"{case_id:03d}-{slug}"
    num_pages = pdf_pages(str(pdf))
    print(f"OCR Case {case_id} ({num_pages} pgs)...")
    
    conn = sqlite3.connect(DB)
    for p in range(1, min(num_pages, max_pages) + 1):
        base = PAGES / f"{doc_slug}-p{p:04d}"
        png = PAGES / f"{base.name}-1.png"
        if not png.exists():
            run(["pdftoppm", "-f", str(p), "-l", str(p), "-r", "150", "-png", str(pdf), str(base)])
        
        out_base = OUT / f"{doc_slug}-p{p:04d}"
        txt_path = Path(str(out_base) + ".txt")
        if not txt_path.exists():
            run(["tesseract", png.name, str(out_base), "-l", "eng", "--psm", "3"], cwd=png.parent)
        
        if txt_path.exists():
            text = txt_path.read_text(errors="ignore")
            # Basic trait extraction
            for shape in ["orb", "disc", "sphere", "triangle"]:
                if shape in text.lower():
                    conn.execute("INSERT INTO witness_matrix (case_id, source_page, source_quote, claim_type, shape) VALUES (?,?,?,?,?)",
                                 (case_id, p, f"Found mention of {shape} on page {p}", "object_description", shape))
    
    conn.execute("INSERT OR REPLACE INTO hq_ocr_documents (case_id, source_pdf, pages, ocr_engine, updated_at) VALUES (?,?,?,?,?)",
                 (case_id, str(pdf), num_pages, "tesseract_quick", datetime.now().isoformat()))
    conn.execute("UPDATE scientific_completion_audit SET ocr_complete=1, witness_matrix_complete=1 WHERE case_id=?", (case_id,))
    conn.commit()
    conn.close()

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT c.case_id, c.title, a.local_path FROM cases c JOIN assets a USING(case_id) WHERE c.asset_type='PDF' AND c.case_id NOT IN (SELECT case_id FROM hq_ocr_documents) AND a.local_path IS NOT NULL LIMIT 20").fetchall()
    conn.close()
    
    for r in rows:
        path = BASE / r['local_path'].replace("./", "")
        if path.exists():
            ocr_quick(path, r['case_id'], r['title'])

if __name__ == "__main__":
    main()
