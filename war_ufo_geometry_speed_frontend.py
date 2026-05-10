import os
#!/usr/bin/env python3
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/tmp/war_ufo_science")
DB = BASE / "cases.sqlite"
FRONTEND = BASE / "frontend"
FRONTEND.mkdir(exist_ok=True)

FOV_SCENARIOS = [
    ("very_narrow_sensor", 0.5),
    ("narrow_sensor", 1.5),
    ("medium_sensor", 5.0),
    ("wide_sensor", 15.0),
    ("very_wide_context", 30.0),
]

RANGE_SCENARIOS = [
    ("near_insect_or_debris", 5, 50, 0, 15, "near small object"),
    ("bird", 50, 1000, 2, 30, "bird speed envelope"),
    ("small_drone", 100, 5000, 0, 45, "small drone speed envelope"),
    ("balloon", 500, 30000, 0, 25, "windborne object envelope"),
    ("aircraft", 1000, 80000, 50, 350, "conventional aircraft envelope"),
    ("missile_fast_aircraft", 5000, 150000, 300, 2000, "fast military/missile envelope"),
    ("satellite_or_reentry", 150000, 2000000, 3000, 12000, "orbital/reentry apparent-motion envelope"),
]


def dumps(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def speed_from(pixel_speed_px_s, fov_deg, width_px, range_m):
    if pixel_speed_px_s is None or width_px <= 0:
        return None
    ang_deg_s = pixel_speed_px_s * (fov_deg / width_px)
    ang_rad_s = math.radians(ang_deg_s)
    return range_m * ang_rad_s


def plausibility(speed_min, speed_max, typ_min, typ_max):
    if speed_min is None:
        return "not_computable"
    if speed_max < typ_min * 0.5:
        return "too_slow_for_class"
    if speed_min > typ_max * 2:
        return "too_fast_for_class"
    if speed_max < typ_min or speed_min > typ_max:
        return "marginal"
    return "plausible"


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS geometry_speed_scenarios (
          scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
          case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
          fov_label TEXT NOT NULL,
          fov_deg REAL NOT NULL,
          range_class TEXT NOT NULL,
          range_min_m REAL NOT NULL,
          range_max_m REAL NOT NULL,
          median_pixel_speed_px_s REAL,
          max_pixel_speed_px_s REAL,
          angular_speed_deg_s REAL,
          speed_min_m_s REAL,
          speed_max_m_s REAL,
          max_observed_speed_min_m_s REAL,
          max_observed_speed_max_m_s REAL,
          speed_min_kmh REAL,
          speed_max_kmh REAL,
          max_observed_speed_min_kmh REAL,
          max_observed_speed_max_kmh REAL,
          typical_speed_min_m_s REAL,
          typical_speed_max_m_s REAL,
          plausibility TEXT,
          assumption_note TEXT,
          updated_at TEXT NOT NULL,
          UNIQUE(case_id, fov_label, range_class)
        );

        CREATE TABLE IF NOT EXISTS platform_geometry_assumptions (
          case_id INTEGER PRIMARY KEY REFERENCES cases(case_id) ON DELETE CASCADE,
          observed_width_px INTEGER,
          observed_height_px INTEGER,
          fov_status TEXT,
          range_status TEXT,
          platform_pose_status TEXT,
          speed_status TEXT,
          usable_for_photogrammetry INTEGER,
          note TEXT,
          updated_at TEXT NOT NULL
        );
        """
    )
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(geometry_speed_scenarios)").fetchall()}
    for col, typ in [
        ("max_observed_speed_min_m_s", "REAL"),
        ("max_observed_speed_max_m_s", "REAL"),
        ("max_observed_speed_min_kmh", "REAL"),
        ("max_observed_speed_max_kmh", "REAL"),
    ]:
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE geometry_speed_scenarios ADD COLUMN {col} {typ}")
    conn.execute("DELETE FROM geometry_speed_scenarios")
    rows = conn.execute(
        """
        SELECT c.case_id,c.title,v.width,v.height,a.median_kalman_speed_px_s,a.max_kalman_speed_px_s,
               a.parallax_status,a.track_csv
        FROM advanced_video_tracks a
        JOIN videos v USING(case_id)
        JOIN cases c USING(case_id)
        ORDER BY c.case_id
        """
    ).fetchall()
    for r in rows:
        width = int(r["width"] or 1280)
        median_px = r["median_kalman_speed_px_s"]
        max_px = r["max_kalman_speed_px_s"]
        conn.execute(
            """
            INSERT OR REPLACE INTO platform_geometry_assumptions
            (case_id,observed_width_px,observed_height_px,fov_status,range_status,platform_pose_status,
             speed_status,usable_for_photogrammetry,note,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                r["case_id"], width, int(r["height"] or 720), "assumed_scenario_only", "assumed_scenario_only",
                "missing", "scenario_speed_only_not_true_speed", 0,
                "FOV/range/platform pose are not known. Speeds are scenario bands from pixel speed, not measurements.",
                now,
            ),
        )
        for fov_label, fov_deg in FOV_SCENARIOS:
            angular = None if median_px is None else median_px * (fov_deg / width)
            for range_class, rmin, rmax, typ_min, typ_max, note in RANGE_SCENARIOS:
                smin = speed_from(median_px, fov_deg, width, rmin)
                smax = speed_from(median_px, fov_deg, width, rmax)
                max_smin = speed_from(max_px, fov_deg, width, rmin)
                max_smax = speed_from(max_px, fov_deg, width, rmax)
                pl = plausibility(smin, smax, typ_min, typ_max)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO geometry_speed_scenarios
                    (case_id,fov_label,fov_deg,range_class,range_min_m,range_max_m,median_pixel_speed_px_s,
                     max_pixel_speed_px_s,angular_speed_deg_s,speed_min_m_s,speed_max_m_s,
                     max_observed_speed_min_m_s,max_observed_speed_max_m_s,speed_min_kmh,speed_max_kmh,
                     max_observed_speed_min_kmh,max_observed_speed_max_kmh,typical_speed_min_m_s,
                     typical_speed_max_m_s,plausibility,assumption_note,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        r["case_id"], fov_label, fov_deg, range_class, rmin, rmax, median_px, max_px, angular,
                        smin, smax, max_smin, max_smax,
                        None if smin is None else smin * 3.6, None if smax is None else smax * 3.6,
                        None if max_smin is None else max_smin * 3.6, None if max_smax is None else max_smax * 3.6,
                        typ_min, typ_max, pl, note + f"; parallax_proxy={r['parallax_status']}", now,
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
        (now, str(BASE), "Generated scenario-based FOV/range/speed bands and Bootstrap frontend exports."),
    )
    conn.commit()

    data = {}
    data["videos"] = [dict(x) for x in conn.execute(
        """
        SELECT c.case_id,c.title,c.classification,c.incident_date,c.incident_location,c.agency,
               asset.original_url,asset.local_path,
               v.duration_seconds,v.width,v.height,v.claimed_sensor,
               a.status,a.processed_frames,a.detections,a.detection_fraction,a.track_csv,
               a.median_kalman_speed_px_s,a.max_kalman_speed_px_s,a.median_global_optical_flow_px,
               a.reticle_centerline_score,a.zoom_change_proxy_cv,a.parallax_status,
               a.angular_velocity_status,a.photogrammetry_status
        FROM cases c
        JOIN videos v USING(case_id)
        JOIN advanced_video_tracks a USING(case_id)
        JOIN assets asset USING(case_id)
        ORDER BY c.case_id
        """
    ).fetchall()]
    data["scenarios"] = [dict(x) for x in conn.execute("SELECT * FROM geometry_speed_scenarios ORDER BY case_id,fov_deg,range_min_m").fetchall()]
    data["hypotheses"] = [dict(x) for x in conn.execute("SELECT * FROM video_hypothesis_comparison ORDER BY case_id,hypothesis").fetchall()]
    data["platform"] = [dict(x) for x in conn.execute("SELECT * FROM platform_geometry_assumptions ORDER BY case_id").fetchall()]
    data["frames"] = [dict(x) for x in conn.execute("SELECT * FROM video_track_frames ORDER BY case_id,frame_label").fetchall()]
    data_path = FRONTEND / "data.js"
    data_path.write_text("window.UAP_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    html = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>UAP Video Geometry Explorer</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background:#f6f7f9; }
    .metric { font-variant-numeric: tabular-nums; }
    .table-wrap { max-height: 62vh; overflow:auto; }
    .badge-plausible { background:#198754; }
    .badge-marginal { background:#fd7e14; }
    .badge-too_fast_for_class, .badge-too_slow_for_class { background:#6c757d; }
    .small-note { font-size:.86rem; color:#5c6670; }
    .speed-unreliable { opacity:0.45; text-decoration:line-through; }
    .badge-plausibility { cursor:pointer; }
    th[title] { cursor:help; border-bottom:1px dashed #aaa; }
  </style>
</head>
<body>
<nav class="navbar navbar-dark bg-dark">
  <div class="container-fluid"><span class="navbar-brand">UAP Video Geometry Explorer</span></div>
</nav>
<main class="container-fluid py-3">
  <div class="row g-3">
    <div class="col-lg-3">
      <label class="form-label">Video case</label>
      <select id="caseSelect" class="form-select"></select>
      <div id="caseInfo" class="mt-3"></div>
      <div class="alert alert-warning mt-3 small">
        Speeds are scenario bands from pixel motion. They are not true speeds unless FOV, range, and platform geometry are known.
      </div>
    </div>
    <div class="col-lg-9">
      <ul class="nav nav-tabs" role="tablist">
        <li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#scenarios" type="button">Speed Scenarios</button></li>
        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#track" type="button">Track Metrics</button></li>
        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#hypotheses" type="button">Hypotheses</button></li>
      </ul>
      <div class="tab-content bg-white border border-top-0 p-3">
        <section id="scenarios" class="tab-pane fade show active">
          <div class="row g-2 mb-2">
            <div class="col-md-4"><select id="fovFilter" class="form-select"></select></div>
            <div class="col-md-4"><select id="plausFilter" class="form-select"></select></div>
          </div>
          <div class="table-wrap"><table class="table table-sm table-hover align-middle">
            <thead><tr>
              <th>FOV</th>
              <th>Range Class</th>
              <th>Range m</th>
              <th title="Median angular rate of the tracked object across all frames, derived from Kalman-filtered pixel speed × (FOV / frame width). Zero or near-zero when the camera is tracking the object.">Angular deg/s</th>
              <th title="Speed band from MEDIAN pixel motion × angular scale × range. Valid only when the camera is NOT tracking the object. If the camera follows the object, median pixel speed collapses to near-zero tracking error and this column is meaningless — see the tracking-camera warning.">Speed (med. px) km/h</th>
              <th title="Speed band from the MAXIMUM instantaneous pixel speed observed anywhere in the track. Less sensitive to tracking-camera bias than the median column, but still underestimates true speed when tracking is active.">Max-observed Speed km/h</th>
              <th>Plausibility</th>
            </tr></thead>
            <tbody id="scenarioRows"></tbody>
          </table></div>
        </section>
        <section id="track" class="tab-pane fade">
          <div id="trackMetrics"></div>
        </section>
        <section id="hypotheses" class="tab-pane fade">
          <div class="table-wrap"><table class="table table-sm">
            <thead><tr><th>Hypothesis</th><th>Status</th><th>Evidence / Missing Data</th></tr></thead>
            <tbody id="hypRows"></tbody>
          </table></div>
        </section>
      </div>
    </div>
  </div>
</main>
<div class="modal fade" id="frameModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-xl modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title" id="frameModalTitle">Frame</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <div class="modal-body">
        <video id="frameModalVideo" class="w-100 border" controls preload="metadata" style="max-height:65vh;background:#000;display:block">
          Your browser does not support video.
        </video>
        <div id="frameModalMeta" class="small-note mt-2"></div>
      </div>
    </div>
  </div>
</div>
<script src="data.js"></script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
const D = window.UAP_DATA;
const fmt = (v, d=2) => v === null || v === undefined ? "n/a" : Number(v).toFixed(d);
let _currentRows = [];
function trackingCameraInfo(v) {
  const score = v.reticle_centerline_score;
  const flow = v.median_global_optical_flow_px;
  const objPx = v.median_kalman_speed_px_s;
  const isHigh = score !== null && score !== undefined && score > 0.7;
  const isFlow = flow !== null && flow !== undefined && objPx !== null && objPx !== undefined && objPx > 0 && flow > objPx * 3;
  if (!isHigh && !isFlow) return null;
  let reason = '';
  if (isHigh) reason += `Reticle centerline score ${fmt(score,3)} (>0.7) — the object stays near the frame center across frames. `;
  if (isFlow) reason += `Background camera motion ${fmt(flow,3)} px/frame is ${(flow/objPx).toFixed(1)}× the object's median pixel speed ${fmt(objPx,4)} px/s. `;
  return reason.trim();
}
function showScenarioFrame(event, idx) {
  event.stopPropagation();
  const s = _currentRows[idx];
  const id = Number(caseSelect.value);
  const context = `<b>Scenario:</b> ${s.fov_label} (${fmt(s.fov_deg,1)}°) / ${s.range_class} (${fmt(s.range_min_m,0)}–${fmt(s.range_max_m,0)} m)<br>
    Speed (med. px): <code>${fmtSmall(s.speed_min_kmh,4)}–${fmtSmall(s.speed_max_kmh,4)} km/h</code> &nbsp;
    Max-observed: <code>${fmtSmall(s.max_observed_speed_min_kmh,4)}–${fmtSmall(s.max_observed_speed_max_kmh,4)} km/h</code><br>
    Plausibility: <b>${s.plausibility}</b>`;
  showFrame(id, context);
}
const fmtSmall = (v, d=3) => {
  if (v === null || v === undefined) return "n/a";
  const n = Number(v);
  if (Math.abs(n) < 0.000001) return "0.000000";
  if (Math.abs(n) < 0.01) return n.toFixed(6);
  return n.toFixed(d);
};
const caseSelect = document.getElementById('caseSelect');
D.videos.forEach(v => {
  const opt = document.createElement('option');
  opt.value = v.case_id;
  opt.textContent = `${v.case_id} — ${v.title}`;
  caseSelect.appendChild(opt);
});
function badge(v) {
  return `<span class="badge badge-${v}">${v}</span>`;
}
function relLink(path, label) {
  if (!path) return "n/a";
  if (path.startsWith("./")) {
    return `<a href="${path.replace('./frontend/', '').replace('./', '../')}" target="_blank">${label}</a>`;
  }
  if (path.startsWith("http")) return `<a href="${path}" target="_blank">${label}</a>`;
  return `<code>${path}</code>`;
}
function frameRel(path) {
  if (!path) return "";
  if (path.startsWith("./frontend/")) return path.replace("./frontend/", "");
  if (path.startsWith("./")) return "../" + path.replace("./", "");
  return path;
}
function representativeFrame(caseId) {
  const frames = (D.frames || []).filter(f => f.case_id === caseId && f.image_path);
  if (!frames.length) return undefined;
  const bySpeed = frames.filter(f => f.speed_px_s > 0).sort((a, b) => b.speed_px_s - a.speed_px_s);
  if (bySpeed.length) return bySpeed[0];
  return frames.find(f => f.frame_label === 'middle') ||
         frames.find(f => f.frame_label === 'last') ||
         frames.find(f => f.frame_label === 'first') || frames[0];
}
function localVideoUrl(path) {
  if (!path) return null;
  const canonical = path.startsWith('/tmp/') ? '/private/tmp/' + path.slice(5) : path;
  return 'file://' + canonical;
}
function showFrame(caseId, context) {
  const v = D.videos.find(x => x.case_id === caseId);
  const f = representativeFrame(caseId);
  const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('frameModal'));
  document.getElementById('frameModalTitle').textContent = `Case ${caseId} — ${v ? v.title : ''}`;
  const vid = document.getElementById('frameModalVideo');
  const maxPx = v ? v.max_kalman_speed_px_s : null;
  const noMotion = maxPx !== null && maxPx < 0.5;
  const targetTime = f ? f.time_s : 0;
  const url = v ? localVideoUrl(v.local_path) : null;
  if (!url) {
    vid.removeAttribute('src');
    document.getElementById('frameModalMeta').innerHTML = '<em>No local video file for this case.</em>';
  } else {
    if (vid.dataset.loadedUrl !== url) {
      vid.src = url;
      vid.dataset.loadedUrl = url;
    }
    function seekTo() { vid.currentTime = targetTime; }
    if (vid.readyState >= 1) { seekTo(); } else { vid.addEventListener('loadedmetadata', seekTo, {once: true}); }
    const noMotionNote = noMotion
      ? `<div class="alert alert-secondary p-2 mb-1 small"><strong>No object motion detected</strong> — max ${fmt(maxPx,4)} px/s. Likely audio-only or static visual. No moving UAP in the track.</div>`
      : '';
    const posNote = f
      ? `Seeked to <code>${fmt(targetTime,3)}s</code> · ${f.frame_label} frame · object at x=<code>${fmt(f.track_x,1)}</code> y=<code>${fmt(f.track_y,1)}</code> px · <code>${fmt(f.speed_px_s,4)} px/s</code>`
      : `Seeked to <code>${fmt(targetTime,3)}s</code>`;
    document.getElementById('frameModalMeta').innerHTML =
      noMotionNote + posNote + (context ? `<div class="mt-1">${context}</div>` : '');
  }
  modal.show();
}
function render() {
  const id = Number(caseSelect.value);
  const v = D.videos.find(x => x.case_id === id);
  const trackWarn = trackingCameraInfo(v);
  document.getElementById('caseInfo').innerHTML = `
    <h5><span class="badge text-bg-secondary me-1">Case ${v.case_id}</span>${v.title}</h5>
    <div class="small-note">${v.classification || ''}</div>
    <dl class="row mt-2">
      <dt class="col-6">Date</dt><dd class="col-6">${v.incident_date || 'n/a'}</dd>
      <dt class="col-6">Location</dt><dd class="col-6">${v.incident_location || 'n/a'}</dd>
      <dt class="col-6">Agency</dt><dd class="col-6">${v.agency || 'n/a'}</dd>
      <dt class="col-6">Duration</dt><dd class="col-6 metric">${fmt(v.duration_seconds,1)} s</dd>
      <dt class="col-6">Resolution</dt><dd class="col-6 metric">${v.width}x${v.height}</dd>
      <dt class="col-6">Sensor</dt><dd class="col-6">${v.claimed_sensor || 'unknown'}</dd>
      <dt class="col-6">Source</dt><dd class="col-6">${relLink(v.original_url, 'war.gov source')}</dd>
      <dt class="col-6">Local file</dt><dd class="col-6">${relLink(v.local_path, 'video file')}</dd>
      <dt class="col-6">Track CSV</dt><dd class="col-6">${relLink(v.track_csv, (v.track_csv || '').split('/').pop())}</dd>
    </dl>
    ${trackWarn ? `<div class="alert alert-warning p-2 small mb-0">
      <strong>Tracking camera — speed (med. px) unreliable.</strong><br>
      ${trackWarn}<br>
      The camera autopilot is following the object, keeping it near the frame center.
      Median pixel motion reflects only tracking residual, not true object velocity.
      <em>Use max-observed speed as a lower bound instead.</em>
    </div>` : ''}`;
  const fovs = [...new Set(D.scenarios.filter(s => s.case_id === id).map(s => s.fov_label))];
  const fsel = document.getElementById('fovFilter');
  const old = fsel.value;
  fsel.innerHTML = '<option value="">All FOVs</option>' + fovs.map(f => `<option>${f}</option>`).join('');
  fsel.value = fovs.includes(old) ? old : '';
  const psel = document.getElementById('plausFilter');
  if (!psel.innerHTML) psel.innerHTML = '<option value="">All plausibility</option><option>plausible</option><option>marginal</option><option>too_fast_for_class</option><option>too_slow_for_class</option>';
  const rows = D.scenarios.filter(s => s.case_id === id && (!fsel.value || s.fov_label === fsel.value) && (!psel.value || s.plausibility === psel.value));
  _currentRows = rows;
  document.getElementById('scenarioRows').innerHTML = rows.map((s, i) => `
    <tr>
      <td>${s.fov_label}<div class="small-note">${fmt(s.fov_deg,1)}°</div></td>
      <td>${s.range_class}</td>
      <td class="metric">${fmt(s.range_min_m,0)}-${fmt(s.range_max_m,0)}</td>
      <td class="metric">${fmtSmall(s.angular_speed_deg_s,6)}</td>
      <td class="metric${trackWarn ? ' speed-unreliable' : ''}" title="${trackWarn ? 'Unreliable: camera is tracking the object — see warning' : ''}">${fmtSmall(s.speed_min_kmh,4)}-${fmtSmall(s.speed_max_kmh,4)}</td>
      <td class="metric">${fmtSmall(s.max_observed_speed_min_kmh,4)}-${fmtSmall(s.max_observed_speed_max_kmh,4)}</td>
      <td><span class="badge badge-${s.plausibility} badge-plausibility" title="Click to view representative frame for this scenario" onclick="showScenarioFrame(event,${i})">${s.plausibility}</span></td>
    </tr>`).join('');
  document.getElementById('trackMetrics').innerHTML = `
    <div class="row g-3">
      ${[
        ['Processed frames', v.processed_frames],
        ['Detections', v.detections],
        ['Detection fraction', fmt(v.detection_fraction,2)],
        ['Median pixel speed', fmt(v.median_kalman_speed_px_s,3) + ' px/s'],
        ['Max pixel speed', fmt(v.max_kalman_speed_px_s,3) + ' px/s'],
        ['Global optical flow', fmt(v.median_global_optical_flow_px,3)],
        ['Reticle centerline score', fmt(v.reticle_centerline_score,4)],
        ['Zoom proxy CV', fmt(v.zoom_change_proxy_cv,3)],
        ['Parallax proxy', v.parallax_status],
        ['Angular velocity', v.angular_velocity_status],
        ['Photogrammetry', v.photogrammetry_status]
      ].map(x => `<div class="col-md-4"><div class="border rounded p-2"><div class="small-note">${x[0]}</div><div class="metric">${x[1] ?? 'n/a'}</div></div></div>`).join('')}
    </div>`;
  document.getElementById('hypRows').innerHTML = D.hypotheses.filter(h => h.case_id === id).map(h => `
    <tr><td>${h.hypothesis}</td><td>${h.status}</td><td>${h.evidence_for || ''}<div class="small-note">${h.required_missing_data || ''}</div></td></tr>
  `).join('');
}
caseSelect.addEventListener('change', render);
document.getElementById('fovFilter').addEventListener('change', render);
document.getElementById('plausFilter').addEventListener('change', render);
render();
</script>
</body>
</html>
'''
    (FRONTEND / "index.html").write_text(html, encoding="utf-8")
    conn.close()
    print(FRONTEND / "index.html")


if __name__ == "__main__":
    main()
