import sqlite3
import json
import os
from datetime import datetime, timezone

def main():
    base_dir = os.path.dirname(__file__)
    db_path = os.path.join(base_dir, 'cases.sqlite')
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # 1. Reset hypotheses to baseline prior_score if unscored
    conn.execute("UPDATE hypotheses SET posterior_score = prior_score WHERE posterior_score IS NULL")
    # Actually, build_cases_db set posterior_score to the same as prior_score or 0.15 etc.
    
    # 2. Identify cases with high-confidence space activity
    corrs = conn.execute(\"\"\"
        SELECT case_id, correlation_type, status, result_summary 
        FROM external_correlations 
        WHERE status IN ('identified', 'plausible') 
        AND (correlation_type LIKE '%space%' OR correlation_type LIKE '%launch%')
    \"\"\").fetchall()
    
    print(f"Applying space activity weights to {len(corrs)} correlation matches...")
    
    for c in corrs:
        cid = c['case_id']
        # Boost "satellite/space object" hypothesis
        # identified = 0.9, plausible = 0.6
        weight = 0.95 if c['status'] == 'identified' else 0.75
        
        conn.execute(\"\"\"
            UPDATE hypotheses 
            SET posterior_score = ?, 
                evidence_for = ?,
                status = 'correlated_scored'
            WHERE case_id = ? AND hypothesis = 'satellite/space object'
        \"\"\", (weight, c['result_summary'], cid))
        
        # Penalize others
        conn.execute(\"\"\"
            UPDATE hypotheses 
            SET posterior_score = 0.05
            WHERE case_id = ? AND hypothesis != 'satellite/space object'
        \"\"\", (cid,))

    # 3. Recalculate normalized Bayesian probabilities
    cases = conn.execute("SELECT DISTINCT case_id FROM hypotheses").fetchall()
    now = datetime.now(timezone.utc).isoformat()
    
    conn.execute("DELETE FROM bayesian_scores")
    
    for row in cases:
        cid = row['case_id']
        hrows = conn.execute("SELECT hypothesis, posterior_score FROM hypotheses WHERE case_id = ?", (cid,)).fetchall()
        
        total = sum(max(0, h['posterior_score'] or 0.1) for h in hrows)
        if total > 0:
            for h in hrows:
                prob = max(0, h['posterior_score'] or 0.1) / total
                conn.execute(\"\"\"
                    INSERT INTO bayesian_scores (case_id, hypothesis, normalized_probability, source, note, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                \"\"\", (cid, h['hypothesis'], prob, 'correlation-weighted Bayesian engine', 'Probability updated based on external geospatial/temporal match.', now))

    # 4. Update main case classification if probability is high
    top_matches = conn.execute(\"\"\"
        SELECT case_id, hypothesis, normalized_probability 
        FROM bayesian_scores 
        WHERE normalized_probability > 0.6
    \"\"\").fetchall()
    
    for tm in top_matches:
        status = f"identified: {tm['hypothesis']}" if tm['normalized_probability'] > 0.85 else f"plausible: {tm['hypothesis']}"
        conn.execute("UPDATE cases SET classification = ? WHERE case_id = ?", (status, tm['case_id']))

    conn.commit()
    conn.close()
    print("Bayesian update complete.")

if __name__ == "__main__":
    main()
