"""
Medical Creator Verifier - Web Server
Upload an xlsx/csv, kick off verification, download results.
"""

import asyncio
import csv
import io
import os
import threading
from flask import Flask, request, jsonify, send_file, Response

from verifier import load_handles_from_file, run_verification, progress, reset_progress

app = Flask(__name__)

UPLOAD_DIR = "/tmp/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def run_in_background(handles):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_verification(handles))
    loop.close()


@app.route("/")
def index():
    return """<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Medical Creator Verifier</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, system-ui, sans-serif; background: #0a0a0a; color: #e0e0e0; padding: 24px; }
  .container { max-width: 720px; margin: 0 auto; }
  h1 { font-size: 22px; margin-bottom: 8px; color: #fff; }
  .sub { color: #888; margin-bottom: 32px; font-size: 14px; }
  .card { background: #161616; border: 1px solid #2a2a2a; border-radius: 12px; padding: 24px; margin-bottom: 16px; }
  label { font-size: 13px; color: #999; display: block; margin-bottom: 8px; }
  input[type="file"] { margin-bottom: 16px; }
  button { background: #2563eb; color: #fff; border: none; padding: 10px 24px; border-radius: 8px; cursor: pointer; font-size: 14px; }
  button:hover { background: #1d4ed8; }
  button:disabled { background: #333; cursor: not-allowed; }
  .progress-bar { background: #222; border-radius: 6px; height: 8px; margin: 12px 0; overflow: hidden; }
  .progress-fill { background: #2563eb; height: 100%; transition: width 0.3s; border-radius: 6px; }
  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 16px 0; }
  .stat { text-align: center; }
  .stat-num { font-size: 24px; font-weight: 700; color: #fff; }
  .stat-label { font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }
  .status-text { font-size: 13px; color: #888; margin-top: 8px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 16px; }
  th { text-align: left; padding: 8px; border-bottom: 1px solid #2a2a2a; color: #888; font-weight: 500; }
  td { padding: 8px; border-bottom: 1px solid #1a1a1a; }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .tag-yes { background: #064e3b; color: #34d399; }
  .tag-no { background: #1c1917; color: #a8a29e; }
  .tag-err { background: #451a03; color: #fb923c; }
  .dl-btn { margin-top: 16px; }
  #results-card { display: none; }
</style>
</head><body>
<div class="container">
  <h1>Medical Creator Verifier</h1>
  <p class="sub">Upload Kalodata xlsx - screenshots each TikTok profile - OpenAI Vision checks for scrubs/lab coats</p>

  <div class="card">
    <label>Upload creator file (.xlsx or .csv)</label>
    <input type="file" id="file" accept=".xlsx,.csv,.xls">
    <br>
    <button id="start-btn" onclick="startRun()">Start verification</button>
  </div>

  <div class="card" id="progress-card" style="display:none;">
    <div class="stats">
      <div class="stat"><div class="stat-num" id="s-total">0</div><div class="stat-label">Total</div></div>
      <div class="stat"><div class="stat-num" id="s-done">0</div><div class="stat-label">Done</div></div>
      <div class="stat"><div class="stat-num" id="s-med" style="color:#34d399">0</div><div class="stat-label">Medical</div></div>
      <div class="stat"><div class="stat-num" id="s-err" style="color:#fb923c">0</div><div class="stat-label">Errors</div></div>
    </div>
    <div class="progress-bar"><div class="progress-fill" id="pbar" style="width:0%"></div></div>
    <div class="status-text" id="status-text">Starting...</div>
  </div>

  <div class="card" id="results-card">
    <h3 style="margin-bottom:8px; color:#fff;">Results</h3>
    <button class="dl-btn" onclick="window.location='/download'">Download CSV</button>
    <div id="results-table"></div>
  </div>
</div>

<script>
let polling = null;

async function startRun() {
  const file = document.getElementById('file').files[0];
  if (!file) { alert('Pick a file first'); return; }

  const form = new FormData();
  form.append('file', file);

  document.getElementById('start-btn').disabled = true;
  document.getElementById('progress-card').style.display = 'block';
  document.getElementById('results-card').style.display = 'none';

  const res = await fetch('/start', { method: 'POST', body: form });
  const data = await res.json();
  if (data.error) { alert(data.error); return; }

  polling = setInterval(pollStatus, 2000);
}

async function pollStatus() {
  const res = await fetch('/status');
  const d = await res.json();

  document.getElementById('s-total').textContent = d.total;
  document.getElementById('s-done').textContent = d.processed;
  document.getElementById('s-med').textContent = d.medical_count;
  document.getElementById('s-err').textContent = d.error_count;

  const pct = d.total > 0 ? Math.round((d.processed / d.total) * 100) : 0;
  document.getElementById('pbar').style.width = pct + '%';
  document.getElementById('status-text').textContent = d.status === 'running'
    ? 'Processing ' + d.current_handle + '...'
    : d.status === 'done' ? 'Complete!' : d.status;

  if (d.status === 'done' || d.status === 'error') {
    clearInterval(polling);
    document.getElementById('start-btn').disabled = false;
    document.getElementById('results-card').style.display = 'block';
    renderTable(d.results || []);
  }
}

function renderTable(results) {
  // Show only medical ones at top, then errors, then not-medical
  const sorted = [...results].sort((a, b) => {
    if (a.is_medical === true && b.is_medical !== true) return -1;
    if (a.is_medical !== true && b.is_medical === true) return 1;
    return 0;
  });

  let html = '<table><tr><th>Handle</th><th>Verdict</th><th>Role</th><th>Confidence</th><th>Reasoning</th></tr>';
  for (const r of sorted) {
    const tag = r.is_medical === true ? '<span class="tag tag-yes">MEDICAL</span>'
      : r.is_medical === false ? '<span class="tag tag-no">NOT MEDICAL</span>'
      : '<span class="tag tag-err">ERROR</span>';
    html += '<tr><td>' + r.handle + '</td><td>' + tag + '</td><td>' + (r.likely_role||'-') + '</td><td>' + (r.confidence||'-') + '</td><td>' + (r.reasoning||'-') + '</td></tr>';
  }
  html += '</table>';
  document.getElementById('results-table').innerHTML = html;
}
</script>
</body></html>"""


@app.route("/start", methods=["POST"])
def start():
    if progress["status"] == "running":
        return jsonify({"error": "Already running. Wait for it to finish."})

    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file uploaded"})

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        return jsonify({"error": "Upload .xlsx or .csv"})

    path = os.path.join(UPLOAD_DIR, "input" + ext)
    f.save(path)

    handles = load_handles_from_file(path)
    if not handles:
        return jsonify({"error": "No handles found in file. Need a 'handle' or 'username' column."})

    thread = threading.Thread(target=run_in_background, args=(handles,), daemon=True)
    thread.start()

    return jsonify({"ok": True, "count": len(handles)})


@app.route("/status")
def status():
    return jsonify(progress)


@app.route("/download")
def download():
    if not progress["results"]:
        return "No results yet", 404

    output = io.StringIO()
    fieldnames = ["handle", "is_medical", "confidence", "likely_role", "signals_found", "reasoning"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(progress["results"])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=med_verify_results.csv"},
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
