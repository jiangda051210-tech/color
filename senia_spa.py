"""
SENIA SPA — 全功能 React 单页应用
=================================
暴露所有 24+ SENIA 端点的完整前端.
"""

from __future__ import annotations


def render_senia_spa(app_version: str = "2.4.0") -> str:
    return _SPA_HTML.replace("{{VERSION}}", app_version)


_SPA_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SENIA Elite — Full Dashboard</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#06080f;--card:rgba(12,20,35,.72);--glass:rgba(255,255,255,.04);
  --bdr:rgba(255,255,255,.07);--bdr2:rgba(99,179,255,.3);
  --t1:#e8edf5;--t2:rgba(200,210,230,.6);--t3:rgba(160,175,200,.4);
  --acc:#4ea8ff;--glow:rgba(78,168,255,.2);
  --pass:#00e68a;--warn:#ffc14d;--fail:#ff5c72;
  --r:14px;--f:'Inter',-apple-system,system-ui,sans-serif;--mono:'JetBrains Mono',monospace;
}
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400&display=swap');
body{font-family:var(--f);background:var(--bg);color:var(--t1);min-height:100vh}
body::before{content:'';position:fixed;top:-40%;left:-20%;width:80%;height:80%;
  background:radial-gradient(ellipse,rgba(78,168,255,.06) 0%,transparent 70%);pointer-events:none}

.app{max-width:1280px;margin:0 auto;padding:20px}

/* ── NAV ── */
.nav{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--bdr);margin-bottom:24px;flex-wrap:wrap}
.nav-brand{font-size:18px;font-weight:700;background:linear-gradient(135deg,#fff,var(--acc));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-right:auto}
.nav-tabs{display:flex;gap:4px;flex-wrap:wrap}
.nav-tab{padding:7px 16px;border-radius:8px;font-size:13px;cursor:pointer;
  color:var(--t2);border:1px solid transparent;transition:all .2s;background:none}
.nav-tab:hover{color:var(--t1);background:var(--glass);border-color:var(--bdr)}
.nav-tab.active{color:var(--acc);background:rgba(78,168,255,.08);border-color:var(--bdr2)}

/* ── PANELS ── */
.panel{display:none;animation:fadeIn .3s ease}
.panel.active{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}

.card{background:var(--card);backdrop-filter:blur(16px);border:1px solid var(--bdr);
  border-radius:var(--r);padding:24px;margin-bottom:16px}
.card-title{font-size:13px;color:var(--t3);text-transform:uppercase;letter-spacing:.8px;
  font-weight:600;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.card-title::before{content:'';width:3px;height:14px;background:var(--acc);border-radius:2px}

.form-row{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.form-field{flex:1;min-width:150px}
.form-field label{display:block;font-size:11px;color:var(--t3);text-transform:uppercase;
  letter-spacing:.6px;margin-bottom:5px}
.form-field input,.form-field select,.form-field textarea{
  width:100%;padding:9px 12px;background:var(--glass);border:1px solid var(--bdr);
  border-radius:8px;color:var(--t1);font-size:13px;font-family:var(--f);outline:none}
.form-field input:focus,.form-field select:focus,.form-field textarea:focus{border-color:var(--acc)}
.form-field textarea{min-height:60px;resize:vertical;font-family:var(--mono);font-size:12px}

.btn{padding:9px 24px;border:none;border-radius:8px;font-size:13px;font-weight:600;
  cursor:pointer;transition:all .2s;font-family:var(--f)}
.btn-primary{background:linear-gradient(135deg,var(--acc),#00c8ff);color:#06080f;
  box-shadow:0 3px 15px var(--glow)}
.btn-primary:hover{transform:translateY(-1px);box-shadow:0 5px 25px var(--glow)}
.btn-secondary{background:var(--glass);color:var(--t1);border:1px solid var(--bdr)}
.btn-secondary:hover{border-color:var(--bdr2)}

.result-box{background:rgba(0,0,0,.3);border:1px solid var(--bdr);border-radius:8px;
  padding:14px;margin-top:12px;font-family:var(--mono);font-size:12px;
  white-space:pre-wrap;max-height:300px;overflow-y:auto;color:var(--t2)}

.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:16px}
.kpi{background:var(--glass);border:1px solid var(--bdr);border-radius:10px;padding:14px;text-align:center}
.kpi-val{font-size:22px;font-weight:600;font-family:var(--mono)}
.kpi-label{font-size:10px;color:var(--t3);text-transform:uppercase;margin-top:4px}

.badge{display:inline-block;padding:4px 12px;border-radius:6px;font-size:12px;font-weight:600}
.badge-pass{background:rgba(0,230,138,.1);color:var(--pass)}
.badge-warn{background:rgba(255,193,77,.1);color:var(--warn)}
.badge-fail{background:rgba(255,92,114,.1);color:var(--fail)}

@media(max-width:640px){
  .app{padding:10px 8px}
  .form-row{flex-direction:column}
  .form-field{min-width:100%}
  .form-field input,.form-field select,.form-field textarea{padding:12px;font-size:16px;min-height:44px}
  .nav{flex-direction:column;gap:8px}
  .nav-tabs{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}
  .nav-tab{padding:10px 14px;min-height:40px}
  .kpi-row{grid-template-columns:repeat(2,1fr)}
  .btn{min-height:44px;padding:12px 20px;font-size:14px}
  .card{padding:14px}
  .result-box{font-size:11px;max-height:200px}
}
</style>
</head>
<body>
<div class="app">
<nav class="nav">
  <div class="nav-brand">SENIA Elite</div>
  <div class="nav-tabs" id="tabs"></div>
</nav>
<div id="panels"></div>
</div>

<script>
const TABS = [
  {id:'analyze',label:'📸 Analyze',icon:'📸'},
  {id:'predict',label:'🔮 Predict',icon:'🔮'},
  {id:'history',label:'📈 History',icon:'📈'},
  {id:'passport',label:'🎫 Passport',icon:'🎫'},
  {id:'learning',label:'🧠 Learning',icon:'🧠'},
  {id:'knowledge',label:'📚 Knowledge',icon:'📚'},
  {id:'admin',label:'⚙️ Admin',icon:'⚙️'},
];

// Build tabs
const tabsEl = document.getElementById('tabs');
const panelsEl = document.getElementById('panels');
TABS.forEach((t,i) => {
  const btn = document.createElement('div');
  btn.className = 'nav-tab' + (i===0?' active':'');
  btn.textContent = t.label;
  btn.onclick = () => switchTab(t.id);
  btn.dataset.tab = t.id;
  tabsEl.appendChild(btn);
});

function switchTab(id) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.toggle('active', t.dataset.tab===id));
  document.querySelectorAll('.panel').forEach(p => p.classList.toggle('active', p.id==='p-'+id));
}

function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function jsonBox(id,data){document.getElementById(id).textContent=typeof data==='string'?data:JSON.stringify(data,null,2)}

async function postForm(url, formId, resultId) {
  const form = new FormData(document.getElementById(formId));
  try {
    document.getElementById(resultId).textContent = 'Loading...';
    const r = await fetch(url, {method:'POST', body:form});
    const j = await r.json();
    jsonBox(resultId, j);
  } catch(e) { jsonBox(resultId, 'Error: '+e.message); }
}

async function getJson(url, resultId) {
  try {
    document.getElementById(resultId).textContent = 'Loading...';
    const r = await fetch(url);
    const j = await r.json();
    jsonBox(resultId, j);
  } catch(e) { jsonBox(resultId, 'Error: '+e.message); }
}

// ── Panel: Analyze ──
panelsEl.innerHTML += `
<div class="panel active" id="p-analyze">
  <div class="card">
    <div class="card-title">Upload & Analyze</div>
    <form id="f-analyze">
      <div class="form-row">
        <div class="form-field" style="flex:2"><label>Image</label><input type="file" name="image" accept="image/*" required></div>
        <div class="form-field"><label>Profile</label>
          <select name="profile"><option value="auto">Auto</option><option value="wood">Wood</option>
          <option value="solid">Solid</option><option value="stone">Stone</option>
          <option value="metallic">Metallic</option><option value="high_gloss">High Gloss</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-field"><label>Lot ID</label><input name="lot_id" placeholder="L001"></div>
        <div class="form-field"><label>Product</label><input name="product_code" placeholder="FILM-A"></div>
        <div class="form-field"><label>Grid</label><input name="grid" value="6x8"></div>
      </div>
      <button type="button" class="btn btn-primary" onclick="postForm('/v1/senia/analyze','f-analyze','r-analyze')">Analyze</button>
    </form>
    <div class="result-box" id="r-analyze">Upload a photo to begin</div>
  </div>
  <div class="card">
    <div class="card-title">Operator Feedback (Self-Learning)</div>
    <form id="f-feedback">
      <div class="form-row">
        <div class="form-field"><label>Run ID</label><input name="run_id" value="manual"></div>
        <div class="form-field"><label>System Tier</label>
          <select name="system_tier"><option>PASS</option><option>MARGINAL</option><option>FAIL</option></select></div>
        <div class="form-field"><label>Your Judgment</label>
          <select name="operator_tier"><option>PASS</option><option>MARGINAL</option><option>FAIL</option></select></div>
        <div class="form-field"><label>ΔE00</label><input name="dE00" type="number" step="0.01" value="1.5"></div>
        <div class="form-field"><label>Profile</label><input name="profile" value="wood"></div>
      </div>
      <button type="button" class="btn btn-secondary" onclick="postForm('/v1/senia/feedback','f-feedback','r-feedback')">Submit Feedback</button>
    </form>
    <div class="result-box" id="r-feedback"></div>
  </div>
</div>`;

// ── Panel: Predict ──
panelsEl.innerHTML += `
<div class="panel" id="p-predict">
  <div class="card">
    <div class="card-title">Recipe → Color Prediction</div>
    <form id="f-predict">
      <div class="form-row">
        <div class="form-field"><label>Product Code</label><input name="product_code" value="FILM-A"></div>
        <div class="form-field" style="flex:2"><label>Recipe JSON</label>
          <input name="recipe_json" value='{"C":42,"M":28,"Y":26,"K":5}'></div>
      </div>
      <div style="display:flex;gap:8px">
        <button type="button" class="btn btn-primary" onclick="postForm('/v1/senia/predict/color','f-predict','r-predict')">Predict Color</button>
      </div>
    </form>
    <div class="result-box" id="r-predict"></div>
  </div>
  <div class="card">
    <div class="card-title">Reverse Optimize: Target Color → Best Recipe</div>
    <form id="f-optimize">
      <div class="form-row">
        <div class="form-field"><label>Product</label><input name="product_code" value="FILM-A"></div>
        <div class="form-field"><label>Target L</label><input name="target_L" type="number" step="0.1" value="55"></div>
        <div class="form-field"><label>Target a</label><input name="target_a" type="number" step="0.1" value="0"></div>
        <div class="form-field"><label>Target b</label><input name="target_b" type="number" step="0.1" value="8"></div>
      </div>
      <div class="form-row">
        <div class="form-field" style="flex:2"><label>Current Recipe JSON</label>
          <input name="current_recipe_json" value='{"C":42,"M":28,"Y":26,"K":5}'></div>
      </div>
      <button type="button" class="btn btn-primary" onclick="postForm('/v1/senia/predict/optimize-recipe','f-optimize','r-optimize')">Optimize</button>
    </form>
    <div class="result-box" id="r-optimize"></div>
  </div>
  <div class="card">
    <div class="card-title">Record Training Data</div>
    <form id="f-record">
      <div class="form-row">
        <div class="form-field"><label>Product</label><input name="product_code" value="FILM-A"></div>
        <div class="form-field" style="flex:2"><label>Recipe JSON</label>
          <input name="recipe_json" value='{"C":42,"M":28,"Y":26,"K":5}'></div>
      </div>
      <div class="form-row">
        <div class="form-field"><label>Measured L</label><input name="measured_L" type="number" step="0.1"></div>
        <div class="form-field"><label>Measured a</label><input name="measured_a" type="number" step="0.1"></div>
        <div class="form-field"><label>Measured b</label><input name="measured_b" type="number" step="0.1"></div>
      </div>
      <button type="button" class="btn btn-secondary" onclick="postForm('/v1/senia/predict/record','f-record','r-record')">Record Sample</button>
    </form>
    <div class="result-box" id="r-record"></div>
  </div>
</div>`;

// ── Panel: History ──
panelsEl.innerHTML += `
<div class="panel" id="p-history">
  <div class="card">
    <div class="card-title">Lot Trend & Drift Detection</div>
    <div class="form-row">
      <div class="form-field"><label>Lot ID</label><input id="h-lot" placeholder="L001"></div>
      <div class="form-field"><label>Product</label><input id="h-prod"></div>
      <div class="form-field" style="flex:0">
        <label>&nbsp;</label>
        <button class="btn btn-primary" onclick="getJson('/v1/senia/lot-trend?lot_id='+encodeURIComponent(document.getElementById('h-lot').value)+'&product_code='+encodeURIComponent(document.getElementById('h-prod').value),'r-history')">Query</button>
      </div>
    </div>
    <div class="result-box" id="r-history"></div>
  </div>
  <div class="card">
    <div class="card-title">Cross-Batch Memory (Reorder Matching)</div>
    <div class="form-row">
      <div class="form-field"><label>Product</label><input id="bm-prod" value="FILM-A"></div>
      <div class="form-field"><label>Target L</label><input id="bm-L" type="number" step="0.1" value="55"></div>
      <div class="form-field"><label>Target a</label><input id="bm-a" type="number" step="0.1" value="0"></div>
      <div class="form-field"><label>Target b</label><input id="bm-b" type="number" step="0.1" value="8"></div>
      <div class="form-field" style="flex:0"><label>&nbsp;</label>
        <button class="btn btn-secondary" onclick="getJson('/v1/senia/batch-memory/find?product_code='+document.getElementById('bm-prod').value+'&L='+document.getElementById('bm-L').value+'&a='+document.getElementById('bm-a').value+'&b='+document.getElementById('bm-b').value,'r-batch')">Find Match</button>
      </div>
    </div>
    <div class="result-box" id="r-batch"></div>
  </div>
  <div class="card">
    <div class="card-title">Aging Prediction</div>
    <div class="form-row">
      <div class="form-field"><label>Current ΔE</label><input id="ag-de" type="number" step="0.1" value="1.5"></div>
      <div class="form-field"><label>ΔL</label><input id="ag-dL" type="number" step="0.1" value="0.5"></div>
      <div class="form-field"><label>Δb</label><input id="ag-db" type="number" step="0.1" value="0.3"></div>
      <div class="form-field"><label>Profile</label><input id="ag-prof" value="wood"></div>
      <div class="form-field" style="flex:0"><label>&nbsp;</label>
        <button class="btn btn-secondary" onclick="getJson('/v1/senia/aging-predict?current_dE='+document.getElementById('ag-de').value+'&current_dL='+document.getElementById('ag-dL').value+'&current_db='+document.getElementById('ag-db').value+'&profile='+document.getElementById('ag-prof').value,'r-aging')">Predict</button>
      </div>
    </div>
    <div class="result-box" id="r-aging"></div>
  </div>
</div>`;

// ── Panel: Passport ──
panelsEl.innerHTML += `
<div class="panel" id="p-passport">
  <div class="card">
    <div class="card-title">Generate QR Color Passport</div>
    <form id="f-passport">
      <div class="form-row">
        <div class="form-field"><label>Lot ID</label><input name="lot_id" value="L001"></div>
        <div class="form-field"><label>Product</label><input name="product_code" value="FILM-A"></div>
        <div class="form-field"><label>Tier</label>
          <select name="tier"><option>PASS</option><option>MARGINAL</option><option>FAIL</option></select></div>
        <div class="form-field"><label>ΔE00</label><input name="dE00" type="number" step="0.01" value="0.85"></div>
      </div>
      <div class="form-row">
        <div class="form-field"><label>L</label><input name="L" type="number" step="0.1" value="55"></div>
        <div class="form-field"><label>a</label><input name="a" type="number" step="0.1" value="-1.3"></div>
        <div class="form-field"><label>b</label><input name="b" type="number" step="0.1" value="7.8"></div>
        <div class="form-field"><label>Profile</label><input name="profile" value="wood"></div>
        <div class="form-field"><label>Directions</label><input name="directions" placeholder="偏红,偏黄"></div>
      </div>
      <button type="button" class="btn btn-primary" onclick="postForm('/v1/senia/passport/generate','f-passport','r-passport')">Generate Passport</button>
    </form>
    <div class="result-box" id="r-passport"></div>
  </div>
</div>`;

// ── Panel: Learning ──
panelsEl.innerHTML += `
<div class="panel" id="p-learning">
  <div class="card">
    <div class="card-title">Self-Learning Statistics</div>
    <button class="btn btn-primary" onclick="getJson('/v1/senia/learning/stats','r-stats')">Refresh Stats</button>
    <div class="result-box" id="r-stats"></div>
  </div>
  <div class="card">
    <div class="card-title">Threshold Management</div>
    <div class="form-row">
      <div class="form-field"><label>Profile</label><input id="th-prof" value="wood"></div>
      <div class="form-field"><label>Product (optional)</label><input id="th-prod"></div>
      <div class="form-field"><label>Customer (optional)</label><input id="th-cust"></div>
      <div class="form-field" style="flex:0"><label>&nbsp;</label>
        <button class="btn btn-secondary" onclick="getJson('/v1/senia/thresholds?profile='+document.getElementById('th-prof').value+'&product_code='+document.getElementById('th-prod').value+'&customer_id='+document.getElementById('th-cust').value,'r-thresh')">Get Thresholds</button>
      </div>
    </div>
    <div class="result-box" id="r-thresh"></div>
    <div style="margin-top:12px">
      <button class="btn btn-secondary" onclick="getJson('/v1/senia/thresholds/all','r-thresh-all')">View All Overrides</button>
    </div>
    <div class="result-box" id="r-thresh-all"></div>
  </div>
</div>`;

// ── Panel: Knowledge ──
panelsEl.innerHTML += `
<div class="panel" id="p-knowledge">
  <div class="card">
    <div class="card-title">Knowledge Engine — Auto Optimize</div>
    <p style="color:var(--t2);font-size:13px;margin-bottom:12px">从行业标准、材质数据库、老化研究中自动优化系统参数</p>
    <button class="btn btn-primary" onclick="postJson('/v1/senia/knowledge/optimize','r-knowledge')">Run Auto-Optimize</button>
    <div class="result-box" id="r-knowledge"></div>
  </div>
  <div class="card">
    <div class="card-title">Material Reference Database</div>
    <div class="form-row">
      <div class="form-field"><label>Material Type</label>
        <select id="km-type">
          <option>wood_oak_gray</option><option>wood_walnut</option><option>wood_maple_light</option>
          <option>stone_marble_white</option><option>stone_slate_dark</option>
          <option>solid_white</option><option>solid_black</option><option>metallic_silver</option>
        </select></div>
      <div class="form-field" style="flex:0"><label>&nbsp;</label>
        <button class="btn btn-secondary" onclick="getJson('/v1/senia/knowledge/material?material='+document.getElementById('km-type').value,'r-material')">Query</button>
      </div>
    </div>
    <div class="result-box" id="r-material"></div>
  </div>
  <div class="card">
    <div class="card-title">Industry Standards</div>
    <button class="btn btn-secondary" onclick="getJson('/v1/senia/knowledge/standard?name=decorative_film_industry','r-standard')">Decorative Film</button>
    <button class="btn btn-secondary" onclick="getJson('/v1/senia/knowledge/standard?name=GB_T_11186_coating','r-standard')">GB/T 11186</button>
    <button class="btn btn-secondary" onclick="getJson('/v1/senia/knowledge/standard?name=ISO_12647_printing','r-standard')">ISO 12647</button>
    <div class="result-box" id="r-standard"></div>
  </div>
</div>`;

// ── Panel: Admin ──
panelsEl.innerHTML += `
<div class="panel" id="p-admin">
  <div class="card">
    <div class="card-title">System Status</div>
    <button class="btn btn-primary" onclick="getJson('/v1/senia/admin/status','r-admin-status')">Refresh</button>
    <div class="result-box" id="r-admin-status"></div>
  </div>
  <div class="card">
    <div class="card-title">Disk Usage</div>
    <button class="btn btn-secondary" onclick="getJson('/v1/senia/admin/disk-check','r-disk')">Check Disk</button>
    <div class="result-box" id="r-disk"></div>
  </div>
  <div class="card">
    <div class="card-title">Backup</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn btn-secondary" onclick="postJson('/v1/backup/create','r-backup')">Create Backup</button>
      <button class="btn btn-secondary" onclick="getJson('/v1/backup/list','r-backup')">List Backups</button>
      <button class="btn btn-secondary" onclick="postJson('/v1/backup/rotate','r-backup')">Rotate (keep 7)</button>
    </div>
    <div class="result-box" id="r-backup"></div>
  </div>
  <div class="card">
    <div class="card-title">Edge SDK (Offline Analysis)</div>
    <form id="f-edge">
      <div class="form-row">
        <div class="form-field" style="flex:2"><label>Ref Pixels JSON</label>
          <textarea name="ref_pixels_json">[[128,128,128],[130,127,125],[129,129,128]]</textarea></div>
        <div class="form-field" style="flex:2"><label>Sample Pixels JSON</label>
          <textarea name="sample_pixels_json">[[140,125,115],[142,123,112],[138,126,118]]</textarea></div>
        <div class="form-field"><label>Profile</label><input name="profile" value="wood"></div>
      </div>
      <button type="button" class="btn btn-secondary" onclick="postForm('/v1/senia/edge/analyze','f-edge','r-edge')">Analyze (Edge)</button>
    </form>
    <div class="result-box" id="r-edge"></div>
  </div>
  <div class="card">
    <div class="card-title">Capture Station Guide</div>
    <button class="btn btn-secondary" onclick="getJson('/v1/senia/capture-station/guide','r-guide')">View BOM & Setup Guide</button>
    <div class="result-box" id="r-guide"></div>
  </div>
  <div class="card">
    <div class="card-title">Danger Zone</div>
    <button class="btn" style="background:var(--fail);color:white" onclick="if(confirm('Reset all learning data?'))postJson('/v1/senia/admin/reset-learning','r-reset')">Reset Learning</button>
    <div class="result-box" id="r-reset"></div>
  </div>
</div>`;

async function postJson(url, resultId) {
  try {
    document.getElementById(resultId).textContent = 'Loading...';
    const r = await fetch(url, {method:'POST'});
    jsonBox(resultId, await r.json());
  } catch(e) { jsonBox(resultId, 'Error: '+e.message); }
}
</script>
</body></html>"""
