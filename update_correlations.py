import sqlite3
import os
from datetime import datetime

def update_correlations():
    db_path = os.path.join(os.path.dirname(__file__), 'cases.sqlite')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    correlations = [
        (79, 'space_activity', 'identified', 'Chinese Long March 2D launch (May 5, 2022). Sighting matches twilight phenomenon from Taiyuan launch at 02:38 UTC.'),
        (81, 'space_activity', 'plausible', 'Likely Russian Zircon hypersonic missile test (May 28/29, 2022) or other high-altitude event. Widespread sightings across Middle East.'),
        (82, 'space_activity', 'identified', 'Chinese Long March 2D launch (July 29, 2022). Sighting matches fuel venting of second stage following Yaogan 35-03 deployment at 13:28 UTC.'),
        (83, 'space_activity', 'identified', 'Russian Soyuz 2.1b launch of Kosmos 2565 (Nov 30, 2022). Perfect match for timing (21:10 UTC) and appearance in Iraq/Syria.'),
        (84, 'space_activity', 'identified', 'Chinese Long March 2D launch (Oct 23, 2023). Sighting in UAE matches second stage trajectory/venting from Xichang launch at 20:03 UTC.'),
        (85, 'space_activity', 'identified', 'Chinese Long March 2D launch (Oct 23, 2023). Sighting in UAE matches second stage trajectory/venting from Xichang launch at 20:03 UTC.'),
        (86, 'space_activity', 'identified', 'Starlink Group 7-11 launch (Jan 24, 2024). Sighting in Greece matches Starlink train following 00:35 UTC launch.'),
        (92, 'space_activity', 'plausible', 'Russian Soyuz 2.1b launch of Kosmos 2570 (Oct 27, 2023). Timing matches (06:04 UTC), though military sensor reports unresolved low-altitude maneuvers.')
    ]
    
    for case_id, c_type, status, summary in correlations:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO external_correlations (case_id, correlation_type, status, source, result_summary, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (case_id, c_type, status, 'Satellite/Launch Trajectory Analysis', summary, datetime.now().isoformat()))
            print(f"Updated Case {case_id}: {status}")
        except Exception as e:
            print(f"Error updating Case {case_id}: {e}")
            
    conn.commit()
    conn.close()

if __name__ == "__main__":
    update_correlations()
