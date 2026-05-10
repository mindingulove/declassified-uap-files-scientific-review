import os
#!/usr/bin/env python3
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/tmp/war_ufo_science")
DB = BASE / "cases.sqlite"


def jloads(v, default=None):
    if not v:
        return default
    try:
        return json.loads(v)
    except Exception:
        return default


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def split_claims(text):
    text = clean(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    claims = []
    keywords = re.compile(
        r"\b(witness|saw|observed|reported|object|orb|sphere|disc|disk|light|uap|ufo|radar|flir|infrared|nvg|helicopter|launch|motion|hover|moving|corroborat|fbi 302|senior|government)\b",
        re.I,
    )
    for p in parts:
        p = clean(p)
        if 40 <= len(p) <= 700 and keywords.search(p):
            claims.append(p)
    return claims[:8]


def classify_case(row, score, limitations, video_flags):
    title = (row["title"] or "").lower()
    desc = (row["description"] or "").lower()
    flags = video_flags or {}
    if flags.get("resolved_as_aircraft") or "resolved as an aircraft" in f"{title} {desc}":
        return "identified: aircraft"
    if row["asset_type"] == "IMG":
        return "insufficient data: still image only"
    if "launch summary" in desc or "launch history" in desc:
        return "identified/context: space launch reference"
    if limitations and any("context is thin" in x.lower() for x in limitations):
        return "insufficient data"
    if score is not None and score >= 12:
        return "high-value unresolved pending controls"
    if score is not None and score >= 8:
        return "plausibly interesting but incomplete"
    if score is not None and score <= 1:
        return "low evidentiary value"
    return "unreviewed"


def hypothesis_scores(row, score, limitations, video_flags):
    blob = f"{row['title']} {row['description']} {row['sensor_type'] or ''} {row['platform'] or ''}".lower()
    limitations_text = " ".join(limitations or []).lower()
    flags = video_flags or {}
    base = {
        "aircraft": [0.35, "", ""],
        "balloon": [0.20, "", ""],
        "bird/insect": [0.15, "", ""],
        "satellite/space object": [0.15, "", ""],
        "weather/astronomy": [0.15, "", ""],
        "camera/sensor artifact": [0.20, "", ""],
        "insufficient data": [0.50, "", ""],
        "unresolved after controls": [0.10, "", ""],
    }
    if flags.get("resolved_as_aircraft"):
        base["aircraft"] = [0.90, "DVIDS/metadata marks video as resolved as aircraft.", ""]
        base["unresolved after controls"] = [0.05, "", "Marked resolved as aircraft."]
    if row["asset_type"] == "VID":
        base["camera/sensor artifact"][0] += 0.10
        base["insufficient data"][0] += 0.15
        base["unresolved after controls"][2] = "Video-only evidence requires sensor geometry and environmental controls."
    if row["asset_type"] == "IMG":
        base["camera/sensor artifact"] = [0.65, "Still/annotated image requires artifact and archival comparison.", ""]
        base["insufficient data"][0] += 0.20
    if any(k in blob for k in ["apollo", "gemini", "skylab", "nasa"]):
        base["satellite/space object"][0] += 0.20
        base["camera/sensor artifact"][0] += 0.15
    if any(k in blob for k in ["radar", "iff", "flir", "infrared", "nvg", "electro-optical", "swir"]):
        base["unresolved after controls"][0] += 0.15
        base["insufficient data"][2] = "Sensor mention improves value, but raw geometry/track solution is still missing."
    if any(k in blob for k in ["multiple witnesses", "corroborating", "federal law enforcement", "senior us intelligence official", "fbi 302"]):
        base["unresolved after controls"][0] += 0.20
        base["insufficient data"][0] -= 0.10
    if "context is thin" in limitations_text or "weak or absent incident date" in limitations_text:
        base["insufficient data"][1] = "Case card flags weak context/date/location."
    if score is not None and score >= 12:
        base["unresolved after controls"][0] = max(base["unresolved after controls"][0] + 0.20, 0.60)
        base["insufficient data"][0] = min(base["insufficient data"][0], 0.35)
    out = {}
    for h, vals in base.items():
        vals[0] = max(0.0, min(1.0, vals[0]))
        out[h] = vals
    return out


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()

    rows = conn.execute(
        """
        SELECT c.*, cs.scientific_priority_score, cs.limitations_json,
               cs.priority_reasons_json, v.description_flags_json
        FROM cases c
        LEFT JOIN case_scores cs USING(case_id)
        LEFT JOIN videos v USING(case_id)
        """
    ).fetchall()

    conn.execute("DELETE FROM witness_claims")
    for r in rows:
        limitations = jloads(r["limitations_json"], [])
        reasons = jloads(r["priority_reasons_json"], [])
        flags = jloads(r["description_flags_json"], {})
        score = r["scientific_priority_score"]
        classification = classify_case(r, score, limitations, flags)
        conn.execute(
            "UPDATE cases SET classification=?, updated_at=? WHERE case_id=?",
            (classification, now, r["case_id"]),
        )

        # Populate witness/direct-claim table from descriptions and priority reasons.
        claims = split_claims(r["description"])
        for reason in reasons or []:
            if any(k in reason.lower() for k in ["witness", "fbi 302", "government", "corroboration"]):
                claims.insert(0, f"Priority evidence: {reason}")
        seen = set()
        for claim in claims:
            if claim in seen:
                continue
            seen.add(claim)
            low = claim.lower()
            directness = "direct_observation" if any(k in low for k in ["first-hand", "saw", "observed", "fbi 302", "witness"]) else "not_assessed"
            independence = "possible_independent" if any(k in low for k in ["multiple", "corroborat", "separately", "federal"]) else "not_assessed"
            corroboration = 0.7 if independence == "possible_independent" else (0.5 if directness == "direct_observation" else None)
            conn.execute(
                """
                INSERT INTO witness_claims (
                  case_id, source_type, witness_label, claim_text, independence_status,
                  directness, corroboration_score, notes
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    r["case_id"],
                    "metadata_description",
                    r["witnesses"],
                    claim,
                    independence,
                    directness,
                    corroboration,
                    "heuristic extraction from existing local metadata; requires human validation",
                ),
            )

        # Populate environmental checks with known blocking status or pending actionable status.
        has_date = bool(r["incident_date"])
        has_loc = bool(r["incident_location"])
        for check_type in ["weather", "astronomy", "aviation", "space_activity", "military_context"]:
            if not (has_date and has_loc):
                missing = []
                if not has_date:
                    missing.append("incident date")
                if not has_loc:
                    missing.append("incident location")
                status = "insufficient_" + "_and_".join(m.replace(" ", "_") for m in missing)
                verb = "are" if len(missing) > 1 else "is"
                summary = "Cannot query reliably from local data because " + " and ".join(missing) + f" {verb} missing."
                if has_date:
                    summary += f" Date present: {r['incident_date']}."
                if has_loc:
                    summary += f" Location present: {r['incident_location']}."
            else:
                status = "ready_for_external_lookup"
                summary = f"Has date/location: {r['incident_date']} / {r['incident_location']}. External lookup not yet run."
            if check_type == "military_context" and r["agency"]:
                summary += f" Agency context available: {r['agency']}."
            conn.execute(
                """
                UPDATE environmental_checks
                SET status=?, result_summary=?, checked_at=?
                WHERE case_id=? AND check_type=?
                """,
                (status, summary, now, r["case_id"], check_type),
            )

        # Score placeholder hypotheses using available metadata.
        for hyp, vals in hypothesis_scores(r, score, limitations, flags).items():
            posterior, evidence_for, evidence_against = vals
            status = "metadata_scored"
            conn.execute(
                """
                UPDATE hypotheses
                SET prior_score=?, evidence_for=?, evidence_against=?, posterior_score=?, status=?
                WHERE case_id=? AND hypothesis=?
                """,
                (posterior, evidence_for, evidence_against, posterior, status, r["case_id"], hyp),
            )

    # Add OCR page quality proxy from text length. This is not true Tesseract confidence.
    conn.execute(
        """
        UPDATE ocr_pages
        SET ocr_confidence = CASE
          WHEN page_text_chars >= 1200 THEN 0.80
          WHEN page_text_chars >= 400 THEN 0.60
          WHEN page_text_chars >= 80 THEN 0.35
          WHEN page_text_chars > 0 THEN 0.15
          ELSE 0.0
        END,
        ocr_confidence_method = 'text_length_proxy_not_tesseract_confidence'
        """
    )
    conn.execute(
        """
        UPDATE ocr_documents
        SET ocr_confidence_method='page_text_length_proxy; rerun TSV/HOCR for real confidence'
        """
    )

    # Enrich video rows from existing descriptions.
    conn.execute(
        """
        UPDATE videos
        SET tracking_status='frame_samples_extracted_not_tracked',
            angular_velocity_status='not_computable_without_sensor_geometry'
        """
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
        (
            now,
            str(BASE),
            "Enriched cases.sqlite from existing local metadata/OCR/video/image artifacts: classifications, witness_claims, hypothesis scores, environmental readiness, OCR confidence proxy.",
        ),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
