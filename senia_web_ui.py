"""
SENIA 高级前端界面
=================
现代化设计: 毛玻璃 + 渐变 + 微动画 + AI智能感
"""

from __future__ import annotations

def render_senia_home(app_version: str = "2.4.0") -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#06080f">
<meta name="description" content="SENIA 智能对色系统 — 拍照即出结果">
<link rel="manifest" href="data:application/json,{{}}" >
<title>SENIA 智能对色</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

:root {{
  --bg-primary: #06080f;
  --bg-card: rgba(12, 20, 35, 0.72);
  --bg-glass: rgba(255,255,255,0.04);
  --border: rgba(255,255,255,0.07);
  --border-active: rgba(99,179,255,0.35);
  --text-primary: #e8edf5;
  --text-secondary: rgba(200,210,230,0.6);
  --text-dim: rgba(160,175,200,0.4);
  --accent: #4ea8ff;
  --accent-glow: rgba(78,168,255,0.25);
  --pass: #00e68a;
  --pass-bg: rgba(0,230,138,0.1);
  --marginal: #ffc14d;
  --marginal-bg: rgba(255,193,77,0.1);
  --fail: #ff5c72;
  --fail-bg: rgba(255,92,114,0.1);
  --radius: 16px;
  --radius-sm: 10px;
  --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  --mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace;
}}

@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

body {{
  font-family: var(--font);
  background: var(--bg-primary);
  color: var(--text-primary);
  min-height: 100vh;
  overflow-x: hidden;
}}

/* ── 背景光效 ── */
body::before {{
  content: '';
  position: fixed; top: -40%; left: -20%; width: 80%; height: 80%;
  background: radial-gradient(ellipse, rgba(78,168,255,0.07) 0%, transparent 70%);
  pointer-events: none; z-index: 0;
}}
body::after {{
  content: '';
  position: fixed; bottom: -30%; right: -10%; width: 60%; height: 60%;
  background: radial-gradient(ellipse, rgba(0,230,138,0.04) 0%, transparent 70%);
  pointer-events: none; z-index: 0;
}}

.app {{ position: relative; z-index: 1; max-width: 1200px; margin: 0 auto; padding: 24px 20px; }}

/* ── 顶栏 ── */
.topbar {{
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 0; margin-bottom: 32px; border-bottom: 1px solid var(--border);
}}
.brand {{ display: flex; align-items: center; gap: 12px; }}
.brand-icon {{
  width: 38px; height: 38px; border-radius: 10px;
  background: linear-gradient(135deg, var(--accent), #00e68a);
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 16px; color: #06080f;
}}
.brand-text {{ font-size: 18px; font-weight: 600; letter-spacing: -0.3px; }}
.brand-tag {{
  font-size: 11px; color: var(--text-dim); font-weight: 400;
  background: var(--bg-glass); padding: 3px 8px; border-radius: 6px;
  border: 1px solid var(--border); font-family: var(--mono);
}}
.topbar-links {{ display: flex; gap: 6px; }}
.topbar-links a {{
  color: var(--text-secondary); text-decoration: none; font-size: 13px;
  padding: 6px 14px; border-radius: 8px; transition: all .2s;
  border: 1px solid transparent;
}}
.topbar-links a:hover {{
  color: var(--text-primary); background: var(--bg-glass);
  border-color: var(--border);
}}

/* ── Hero ── */
.hero {{ text-align: center; margin-bottom: 48px; }}
.hero h1 {{
  font-size: 40px; font-weight: 700; letter-spacing: -1.5px;
  background: linear-gradient(135deg, #fff 20%, var(--accent) 50%, #00e68a 80%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text; margin-bottom: 12px;
}}
.hero p {{ color: var(--text-secondary); font-size: 16px; max-width: 560px; margin: 0 auto; line-height: 1.6; }}

/* ── 上传区 ── */
.upload-zone {{
  background: var(--bg-card);
  backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
  border: 1.5px dashed var(--border-active);
  border-radius: var(--radius); padding: 48px 32px; text-align: center;
  cursor: pointer; transition: all .3s; position: relative; overflow: hidden;
  margin-bottom: 32px;
}}
.upload-zone:hover {{ border-color: var(--accent); background: rgba(12,20,35,0.85); }}
.upload-zone.dragging {{ border-color: var(--accent); box-shadow: 0 0 40px var(--accent-glow); }}
.upload-zone.has-file {{ border-style: solid; border-color: var(--pass); }}
.upload-icon {{ font-size: 48px; margin-bottom: 12px; opacity: 0.7; }}
.upload-title {{ font-size: 18px; font-weight: 600; margin-bottom: 8px; }}
.upload-hint {{ color: var(--text-secondary); font-size: 13px; }}
.upload-preview {{
  display: none; max-height: 280px; border-radius: var(--radius-sm);
  margin-top: 16px; object-fit: contain;
}}
.upload-zone.has-file .upload-preview {{ display: block; }}
.upload-zone.has-file .upload-placeholder {{ display: none; }}

/* ── 设置行 ── */
.settings-row {{
  display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 32px;
  align-items: end;
}}
.field {{ flex: 1; min-width: 140px; }}
.field label {{
  display: block; font-size: 11px; color: var(--text-dim);
  text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 6px; font-weight: 500;
}}
.field select, .field input {{
  width: 100%; padding: 10px 14px; background: var(--bg-glass);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  color: var(--text-primary); font-size: 14px; font-family: var(--font);
  transition: border-color .2s; outline: none;
}}
.field select:focus, .field input:focus {{ border-color: var(--accent); }}

.btn-analyze {{
  padding: 10px 36px; border: none; border-radius: var(--radius-sm);
  background: linear-gradient(135deg, var(--accent), #00c8ff);
  color: #06080f; font-size: 15px; font-weight: 600; cursor: pointer;
  transition: all .2s; font-family: var(--font); min-width: 140px;
  box-shadow: 0 4px 20px var(--accent-glow);
}}
.btn-analyze:hover {{ transform: translateY(-1px); box-shadow: 0 6px 30px var(--accent-glow); }}
.btn-analyze:disabled {{ opacity: 0.5; cursor: not-allowed; transform: none; }}

/* ── 分析进度 ── */
.progress-bar {{
  display: none; margin-bottom: 32px; background: var(--bg-card);
  border-radius: var(--radius); padding: 24px; backdrop-filter: blur(20px);
  border: 1px solid var(--border);
}}
.progress-bar.active {{ display: block; }}
.progress-steps {{ display: flex; gap: 4px; margin-bottom: 16px; }}
.progress-step {{
  flex: 1; height: 3px; background: var(--bg-glass); border-radius: 2px;
  transition: background .5s;
}}
.progress-step.done {{ background: var(--accent); }}
.progress-step.active {{ background: var(--accent); animation: pulse-step 1s infinite; }}
@keyframes pulse-step {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
.progress-label {{
  font-size: 13px; color: var(--text-secondary); text-align: center;
  font-family: var(--mono);
}}

/* ── 结果区 ── */
.result-area {{ display: none; }}
.result-area.active {{ display: block; }}

/* 判定大卡片 */
.verdict-card {{
  background: var(--bg-card); backdrop-filter: blur(20px);
  border-radius: var(--radius); padding: 32px; margin-bottom: 24px;
  border: 1px solid var(--border); position: relative; overflow: hidden;
}}
.verdict-card::before {{
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
}}
.verdict-card.pass::before {{ background: linear-gradient(90deg, var(--pass), #00c8ff); }}
.verdict-card.marginal::before {{ background: linear-gradient(90deg, var(--marginal), #ffaa00); }}
.verdict-card.fail::before {{ background: linear-gradient(90deg, var(--fail), #ff3366); }}

.verdict-header {{ display: flex; align-items: center; gap: 20px; margin-bottom: 20px; }}
.verdict-badge {{
  font-size: 32px; font-weight: 700; letter-spacing: -1px; font-family: var(--mono);
  padding: 8px 24px; border-radius: var(--radius-sm);
}}
.verdict-badge.pass {{ color: var(--pass); background: var(--pass-bg); }}
.verdict-badge.marginal {{ color: var(--marginal); background: var(--marginal-bg); }}
.verdict-badge.fail {{ color: var(--fail); background: var(--fail-bg); }}
.verdict-de {{ font-size: 14px; color: var(--text-secondary); }}
.verdict-de strong {{ font-size: 28px; font-weight: 600; color: var(--text-primary); font-family: var(--mono); }}
.verdict-dirs {{
  display: flex; gap: 8px; flex-wrap: wrap;
}}
.dir-tag {{
  padding: 5px 14px; border-radius: 20px; font-size: 13px; font-weight: 500;
  background: var(--bg-glass); border: 1px solid var(--border);
}}

/* 指标网格 */
.metrics-grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px; margin-bottom: 24px;
}}
.metric-card {{
  background: var(--bg-glass); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 16px; text-align: center;
}}
.metric-label {{ font-size: 11px; color: var(--text-dim); text-transform: uppercase;
  letter-spacing: 0.6px; margin-bottom: 6px; }}
.metric-value {{ font-size: 24px; font-weight: 600; font-family: var(--mono); }}

/* 调色建议 / 根因 双列 */
.insights-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }}
@media (max-width: 768px) {{ .insights-row {{ grid-template-columns: 1fr; }} }}

.insight-card {{
  background: var(--bg-card); backdrop-filter: blur(20px);
  border: 1px solid var(--border); border-radius: var(--radius); padding: 24px;
}}
.insight-title {{
  font-size: 13px; color: var(--text-dim); text-transform: uppercase;
  letter-spacing: 0.8px; margin-bottom: 14px; font-weight: 600;
  display: flex; align-items: center; gap: 8px;
}}
.advice-item {{
  padding: 10px 14px; margin-bottom: 8px; border-radius: var(--radius-sm);
  background: var(--bg-glass); border-left: 3px solid var(--accent);
  font-size: 14px; line-height: 1.5;
}}
.advice-item.process {{ border-left-color: var(--marginal); }}
.root-cause-badge {{
  display: inline-block; padding: 6px 16px; border-radius: 8px;
  font-size: 14px; font-weight: 600; margin-bottom: 12px;
}}
.root-cause-badge.recipe {{ background: var(--marginal-bg); color: var(--marginal); }}
.root-cause-badge.process {{ background: var(--fail-bg); color: var(--fail); }}
.root-cause-badge.ok {{ background: var(--pass-bg); color: var(--pass); }}

/* 热图 */
.heatmap-section {{
  background: var(--bg-card); backdrop-filter: blur(20px);
  border: 1px solid var(--border); border-radius: var(--radius);
  padding: 24px; margin-bottom: 24px; text-align: center;
}}
.heatmap-section img {{
  max-width: 100%; border-radius: var(--radius-sm);
  border: 1px solid var(--border);
}}

/* 底部 */
.footer {{
  text-align: center; padding: 32px 0; color: var(--text-dim); font-size: 12px;
  border-top: 1px solid var(--border); margin-top: 48px;
}}

/* ── 动画 ── */
/* ── 移动端适配 ── */
/* ── 平板适配 ── */
@media (max-width: 900px) {{
  .metrics-grid {{ grid-template-columns: repeat(3, 1fr); }}
  .insights-row {{ grid-template-columns: 1fr; }}
}}

/* ── 手机适配 (关键: 44px 最小触摸目标) ── */
@media (max-width: 640px) {{
  .app {{ padding: 12px 10px; }}
  .hero {{ margin-bottom: 20px; }}
  .hero h1 {{ font-size: 24px; }}
  .hero p {{ font-size: 13px; }}
  .verdict-header {{ flex-direction: column; gap: 8px; }}
  .verdict-badge {{ font-size: 22px; padding: 6px 16px; }}
  .verdict-de strong {{ font-size: 20px; }}
  .verdict-card {{ padding: 14px 12px; }}
  .metrics-grid {{ grid-template-columns: repeat(2, 1fr); gap: 8px; }}
  .metric-card {{ padding: 10px; }}
  .metric-value {{ font-size: 18px; }}
  .insights-row {{ grid-template-columns: 1fr; gap: 10px; }}
  .insight-card {{ padding: 14px; }}
  .settings-row {{ flex-direction: column; gap: 8px; }}
  .field {{ min-width: 100%; }}
  .field select, .field input {{ padding: 12px 14px; font-size: 16px; min-height: 44px; }}
  .btn-analyze {{ width: 100%; min-height: 48px; font-size: 16px; }}
  .topbar {{ flex-direction: column; gap: 6px; align-items: flex-start; }}
  .topbar-links {{ width: 100%; overflow-x: auto; white-space: nowrap; }}
  .topbar-links a {{ padding: 8px 12px; min-height: 36px; }}
  .upload-zone {{ padding: 24px 16px; }}
  .dir-tag {{ padding: 6px 12px; font-size: 12px; min-height: 32px; display: inline-flex; align-items: center; }}
  .advice-item {{ padding: 10px 12px; font-size: 13px; }}
  /* 双拍上传在手机上竖排 */
  #dualUpload {{ grid-template-columns: 1fr !important; }}
  /* 模式按钮更大 */
  #modeBtn1, #modeBtn2 {{ padding: 12px 16px; font-size: 13px; flex: 1; min-height: 44px; }}
  /* 反馈按钮更大 */
  .insight-card button {{ min-height: 44px; }}
}}

@keyframes fadeInUp {{
  from {{ opacity: 0; transform: translateY(20px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}
.result-area.active > * {{ animation: fadeInUp .5s ease-out both; }}
.result-area.active > *:nth-child(2) {{ animation-delay: .1s; }}
.result-area.active > *:nth-child(3) {{ animation-delay: .2s; }}
.result-area.active > *:nth-child(4) {{ animation-delay: .3s; }}
.result-area.active > *:nth-child(5) {{ animation-delay: .4s; }}
</style>
</head>
<body>
<div class="app">

  <!-- 顶栏 -->
  <header class="topbar">
    <div class="brand">
      <div class="brand-icon">S</div>
      <span class="brand-text">SENIA Elite</span>
      <span class="brand-tag">v{app_version}</span>
    </div>
    <nav class="topbar-links">
      <a href="/v1/web/dashboard">Full Dashboard</a>
      <a href="/v1/web/executive-dashboard">Executive</a>
      <a href="/v1/web/precision-observatory">Observatory</a>
      <a href="/docs">API</a>
    </nav>
  </header>

  <!-- Hero -->
  <section class="hero">
    <h1>智能对色系统</h1>
    <p>拍一张照片，自动判定颜色是否合格，告诉你偏差方向和调色建议</p>
  </section>

  <!-- 拍摄指引 (首次提示) -->
  <div id="cameraGuide" style="background:var(--bg-card);backdrop-filter:blur(20px);border:1px solid var(--border-active);
    border-radius:var(--radius);padding:24px;margin-bottom:24px;display:none">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <span style="font-size:15px;font-weight:600">📸 拍摄指引</span>
      <button onclick="this.parentElement.parentElement.style.display='none';localStorage.setItem('senia_guide_seen','1')"
        style="background:none;border:1px solid var(--border);color:var(--t2,var(--text-secondary));padding:4px 12px;border-radius:6px;cursor:pointer;font-size:12px">知道了</button>
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;font-size:13px;color:var(--text-secondary)">
      <div>🔲 <strong>大货（整版膜）</strong>平铺在桌上</div>
      <div>📋 <strong>标样（小色板）</strong>放在大货旁边或上方</div>
      <div>💡 <strong>灯光</strong>：尽量用固定光源，避免阴影</div>
      <div>📱 <strong>手机</strong>：距离约 30~40cm，正对拍摄</div>
    </div>
  </div>

  <!-- 模式选择 -->
  <div style="display:flex;gap:8px;margin-bottom:16px;justify-content:center">
    <button id="modeBtn1" onclick="setMode('single')" style="padding:8px 20px;border-radius:8px;border:1px solid var(--accent);background:rgba(78,168,255,.1);color:var(--accent);cursor:pointer;font-size:14px;font-weight:600">
      📷 一张照片 (快速)</button>
    <button id="modeBtn2" onclick="setMode('dual')" style="padding:8px 20px;border-radius:8px;border:1px solid var(--border);background:var(--bg-glass);color:var(--text-secondary);cursor:pointer;font-size:14px;font-weight:600">
      📷📷 两张照片 (精准)</button>
  </div>

  <!-- 单拍上传 -->
  <div id="singleUpload" class="upload-zone" onclick="document.getElementById('fileInput').click()">
    <div class="upload-placeholder">
      <div class="upload-icon">📷</div>
      <div class="upload-title">点击选择照片，或拖拽到此处</div>
      <div class="upload-hint">请确保照片中同时包含大货和标样 &nbsp;|&nbsp; 支持 JPG / PNG / DNG</div>
    </div>
    <img class="upload-preview" id="uploadPreview">
    <input type="file" id="fileInput" accept="image/*" style="display:none">
  </div>

  <!-- 双拍上传 -->
  <div id="dualUpload" style="display:none;display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px">
    <div class="upload-zone" onclick="document.getElementById('refInput').click()" style="padding:24px 16px">
      <div class="upload-placeholder">
        <div style="font-size:32px;margin-bottom:8px">📋</div>
        <div style="font-size:15px;font-weight:600">标样照片</div>
        <div style="font-size:12px;color:var(--text-secondary)">只拍标样，占满画面</div>
      </div>
      <img class="upload-preview" id="refPreview" style="max-height:180px">
      <input type="file" id="refInput" accept="image/*" style="display:none">
    </div>
    <div class="upload-zone" onclick="document.getElementById('smpInput').click()" style="padding:24px 16px">
      <div class="upload-placeholder">
        <div style="font-size:32px;margin-bottom:8px">🔲</div>
        <div style="font-size:15px;font-weight:600">大货照片</div>
        <div style="font-size:12px;color:var(--text-secondary)">只拍大货，占满画面</div>
      </div>
      <img class="upload-preview" id="smpPreview" style="max-height:180px">
      <input type="file" id="smpInput" accept="image/*" style="display:none">
    </div>
  </div>

  <!-- 设置行 (简化: 只显示必填, 其余折叠) -->
  <div class="settings-row">
    <div class="field">
      <label>材质类型</label>
      <select id="profile">
        <option value="auto" selected>自动识别</option>
        <option value="wood">木纹</option>
        <option value="solid">纯色</option>
        <option value="stone">石纹</option>
        <option value="metallic">金属</option>
        <option value="high_gloss">高光</option>
      </select>
    </div>
    <div class="field">
      <label>批次号</label>
      <input id="lotId" placeholder="选填，如 L20240728-01">
    </div>
    <div class="field">
      <label>产品编号</label>
      <input id="productCode" placeholder="选填，如 AW-125470">
    </div>
    <input type="hidden" id="grid" value="6x8">
    <button class="btn-analyze" id="btnAnalyze" disabled>开始对色</button>
  </div>

  <!-- 进度条 -->
  <div class="progress-bar" id="progressBar">
    <div class="progress-steps" id="progressSteps"></div>
    <div class="progress-label" id="progressLabel"></div>
  </div>

  <!-- 结果区 -->
  <div class="result-area" id="resultArea">
    <!-- JS 动态填充 -->
  </div>

  <footer class="footer">
    SENIA Elite v{app_version} &mdash; 智能对色系统 &nbsp;|&nbsp; 有网即可访问 &nbsp;|&nbsp; PC · 手机 · 平板
  </footer>
</div>

<script>
const $ = id => document.getElementById(id);
const btnAnalyze = $('btnAnalyze');
const progressBar = $('progressBar');
const resultArea = $('resultArea');
let selectedFile = null;
let refFile = null, smpFile = null;
let currentMode = 'single';

function setMode(mode) {{
  currentMode = mode;
  $('singleUpload').style.display = mode === 'single' ? 'block' : 'none';
  $('dualUpload').style.display = mode === 'dual' ? 'grid' : 'none';
  $('modeBtn1').style.borderColor = mode === 'single' ? 'var(--accent)' : 'var(--border)';
  $('modeBtn1').style.background = mode === 'single' ? 'rgba(78,168,255,.1)' : 'var(--bg-glass)';
  $('modeBtn1').style.color = mode === 'single' ? 'var(--accent)' : 'var(--text-secondary)';
  $('modeBtn2').style.borderColor = mode === 'dual' ? 'var(--accent)' : 'var(--border)';
  $('modeBtn2').style.background = mode === 'dual' ? 'rgba(78,168,255,.1)' : 'var(--bg-glass)';
  $('modeBtn2').style.color = mode === 'dual' ? 'var(--accent)' : 'var(--text-secondary)';
  checkReady();
}}

function checkReady() {{
  if (currentMode === 'single') btnAnalyze.disabled = !selectedFile;
  else btnAnalyze.disabled = !(refFile && smpFile);
}}

// ── 单拍上传 ──
$('fileInput').addEventListener('change', () => {{
  if ($('fileInput').files.length) {{
    selectedFile = $('fileInput').files[0];
    const reader = new FileReader();
    reader.onload = e => {{ $('uploadPreview').src = e.target.result; }};
    reader.readAsDataURL(selectedFile);
    $('singleUpload').classList.add('has-file');
    checkReady();
  }}
}});

// ── 双拍上传 ──
$('refInput').addEventListener('change', () => {{
  if ($('refInput').files.length) {{
    refFile = $('refInput').files[0];
    const r = new FileReader();
    r.onload = e => {{ $('refPreview').src = e.target.result; $('refPreview').style.display='block'; }};
    r.readAsDataURL(refFile);
    checkReady();
  }}
}});
$('smpInput').addEventListener('change', () => {{
  if ($('smpInput').files.length) {{
    smpFile = $('smpInput').files[0];
    const r = new FileReader();
    r.onload = e => {{ $('smpPreview').src = e.target.result; $('smpPreview').style.display='block'; }};
    r.readAsDataURL(smpFile);
    checkReady();
  }}
}});

// ── 分析进度动画 ──
// 首次访问显示拍摄指引
if (!localStorage.getItem('senia_guide_seen')) {{
  document.getElementById('cameraGuide').style.display = 'block';
}}

const STEPS = [
  '正在识别大货和标样...',
  '透视校正中...',
  '过滤手写和贴纸...',
  '提取底色中...',
  '计算色差 (CIEDE2000)...',
  '三级判定中...',
  '生成调色建议...',
];

function showProgress(stepIdx) {{
  progressBar.classList.add('active');
  let html = '';
  for (let i = 0; i < STEPS.length; i++) {{
    const cls = i < stepIdx ? 'done' : i === stepIdx ? 'active' : '';
    html += `<div class="progress-step ${{cls}}"></div>`;
  }}
  $('progressSteps').innerHTML = html;
  $('progressLabel').textContent = STEPS[Math.min(stepIdx, STEPS.length - 1)];
}}

// ── 分析请求 ──
btnAnalyze.addEventListener('click', async () => {{
  if (!selectedFile) return;
  btnAnalyze.disabled = true;
  resultArea.classList.remove('active');
  resultArea.innerHTML = '';

  // 模拟进度
  let step = 0;
  const timer = setInterval(() => {{ if (step < STEPS.length - 1) showProgress(++step); }}, 600);

  try {{
    showProgress(0);
    const form = new FormData();
    let url;
    if (currentMode === 'dual') {{
      form.append('reference', refFile);
      form.append('sample', smpFile);
      url = '/v1/senia/dual-shot';
    }} else {{
      form.append('image', selectedFile);
      url = '/v1/senia/analyze';
    }}
    form.append('profile', $('profile').value);
    form.append('lot_id', $('lotId').value);
    form.append('product_code', $('productCode').value);
    if (currentMode === 'single') form.append('grid', $('grid').value);

    const resp = await fetch(url, {{ method: 'POST', body: form }});
    clearInterval(timer);
    showProgress(STEPS.length);

    if (!resp.ok) {{
      const err = await resp.json().catch(() => ({{ detail: resp.statusText }}));
      throw new Error(err.detail || 'Analysis failed');
    }}

    const data = await resp.json();
    setTimeout(() => {{ renderResult(data); progressBar.classList.remove('active'); }}, 500);
  }} catch (err) {{
    clearInterval(timer);
    progressBar.classList.remove('active');
    resultArea.innerHTML = `<div class="verdict-card fail"><div class="verdict-header">
      <div class="verdict-badge fail">分析失败</div>
      <div style="font-size:14px;line-height:1.6">${{esc(err.message)}}</div></div>
      <div style="margin-top:16px;text-align:center">
        <button onclick="document.getElementById('uploadZone').click()" class="btn-analyze" style="font-size:14px;padding:8px 24px">📷 重新拍摄</button>
      </div></div>`;
    resultArea.classList.add('active');
  }} finally {{
    btnAnalyze.disabled = false;
  }}
}});

function esc(s) {{ const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }}

// ── 渲染结果 ──
function renderResult(d) {{
  const tier = d.tier || 'UNKNOWN';
  const tierCls = tier === 'PASS' ? 'pass' : tier === 'MARGINAL' ? 'marginal' : 'fail';
  const tierLabel = tier === 'PASS' ? '合格' : tier === 'MARGINAL' ? '临界' : '不合格';
  const summary = d.result?.summary || {{}};
  const dev = d.deviation || {{}};
  const dirs = dev.directions || [];
  const recipe = d.recipe_advice || {{}};
  const uni = d.uniformity || {{}};
  const reasons = d.tier_reasons || [];
  const heatmapUrl = d.artifacts?.heatmap;

  let html = '';

  // 播放提示音
  try {{ new Audio('data:audio/wav;base64,UklGRl9vT19teleVBFTQAAAAEAAQAAgA8AAQBIAAAGAAAQB'+
    'kYXRhW28vT19'+('A'.repeat(200))).play().catch(()=>{{}}); }} catch(e) {{}}

  const now = new Date();
  const timeStr = now.getHours().toString().padStart(2,'0')+':'+now.getMinutes().toString().padStart(2,'0')+':'+now.getSeconds().toString().padStart(2,'0');

  // 判定卡片
  html += `<div class="verdict-card ${{tierCls}}">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;font-size:12px;color:var(--text-dim)">
      <span>${{d.lot_id ? '批次 '+esc(d.lot_id) : ''}} ${{d.product_code ? '· 产品 '+esc(d.product_code) : ''}}</span>
      <span>${{timeStr}} · ${{(d.elapsed_sec||0).toFixed(1)}}s</span>
    </div>
    <div class="verdict-header">
      <div class="verdict-badge ${{tierCls}}">${{tierLabel}}</div>
      <div class="verdict-de"><strong>${{(summary.avg_delta_e00||0).toFixed(2)}}</strong> 色差
        &nbsp;&middot;&nbsp; p95: ${{(summary.p95_delta_e00||0).toFixed(2)}}
        &nbsp;&middot;&nbsp; 最大: ${{(summary.max_delta_e00||0).toFixed(2)}}</div>
    </div>
    <div class="verdict-dirs">
      ${{dirs.map(d => `<span class="dir-tag">${{esc(d)}}</span>`).join('')}}
      ${{dirs.length === 0 ? '<span class="dir-tag" style="border-color:var(--pass)">色差极小</span>' : ''}}
    </div>
    <div style="margin-top:16px;display:flex;gap:10px;justify-content:center">
      <button onclick="document.getElementById('uploadZone').click()" class="btn-analyze"
        style="font-size:13px;padding:8px 20px">📷 重新拍摄</button>
      <button onclick="window.print()" style="padding:8px 20px;border-radius:var(--radius-sm);border:1px solid var(--border);
        background:var(--bg-glass);color:var(--text-secondary);cursor:pointer;font-size:13px">🖨 打印结果</button>
    </div>
  </div>`;

  // 指标网格
  html += `<div class="metrics-grid">
    <div class="metric-card">
      <div class="metric-label">ΔL (明暗)</div>
      <div class="metric-value" style="color:${{Math.abs(dev.dL||0)>1?'var(--marginal)':'var(--text-primary)'}}">${{(dev.dL||0).toFixed(2)}}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Δa (红绿)</div>
      <div class="metric-value" style="color:${{Math.abs(dev.da||0)>0.8?'var(--fail)':'var(--text-primary)'}}">${{(dev.da||0).toFixed(2)}}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Δb (黄蓝)</div>
      <div class="metric-value" style="color:${{Math.abs(dev.db||0)>0.8?'var(--fail)':'var(--text-primary)'}}">${{(dev.db||0).toFixed(2)}}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">ΔC (饱和度)</div>
      <div class="metric-value">${{(dev.dC||0).toFixed(2)}}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">材质</div>
      <div class="metric-value" style="font-size:16px">${{
        {{'wood':'木纹','solid':'纯色','stone':'石纹','metallic':'金属','high_gloss':'高光'}}[d.profile?.used] || d.profile?.used || '自动'}}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">拍摄质量</div>
      <div class="metric-value">${{((d.result?.confidence?.overall||0)*100).toFixed(0)}}%</div>
    </div>
  </div>`;

  // 调色建议 + 根因
  const advices = recipe.advices || [];
  html += `<div class="insights-row">
    <div class="insight-card">
      <div class="insight-title">🎯 调色建议</div>
      ${{advices.length === 0 ? '<div class="advice-item" style="border-left-color:var(--pass)">色差合格, 无需调整</div>' :
        advices.slice(0, 6).map(a => `<div class="advice-item ${{a.category === 'process' ? 'process' : ''}}">${{esc(a.action)}}</div>`).join('')}}
    </div>
    <div class="insight-card">
      <div class="insight-title">🔍 根因分析</div>
      <div class="root-cause-badge ${{uni.root_cause || 'ok'}}">${{
        uni.root_cause === 'recipe' ? '配方问题' :
        uni.root_cause === 'process' ? '工艺问题' :
        uni.root_cause === 'mixed' ? '混合问题' : '正常'}}</div>
      <p style="color:var(--text-secondary);font-size:14px;line-height:1.6">${{esc(uni.explanation || '')}}</p>
      ${{reasons.map(r => `<p style="color:var(--text-dim);font-size:12px;margin-top:6px">&bull; ${{esc(r)}}</p>`).join('')}}
    </div>
  </div>`;

  // ── 高级分析 (多光源 + 成本 + 指纹) ──
  const prec = d.precision || {{}};
  const mi = prec.multi_illuminant_dE || {{}};
  const costR = d.cost_risk || {{}};
  const met = d.metamerism || {{}};
  if (Object.keys(mi).length > 0 || costR.total_risk) {{
    html += `<div class="insights-row">`;
    if (Object.keys(mi).length > 0) {{
      html += `<div class="insight-card">
        <div class="insight-title">💡 多光源色差预测</div>
        ${{Object.entries(mi).map(([k,v]) =>
          `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);font-size:13px">
            <span>${{k==='A'?'暖色灯(A)':k==='F11'?'商场灯(TL84)':k==='F2'?'荧光灯(F2)':k==='LED'?'LED灯':k}}</span>
            <span style="font-family:var(--mono);color:${{v>2?'var(--fail)':v>1.5?'var(--marginal)':'var(--pass)'}}">${{v.toFixed(2)}}</span>
          </div>`).join('')}}
        <div style="margin-top:8px;font-size:12px;color:var(--text-dim)">最差: ${{prec.worst_case_illuminant||'?'}} (ΔE=${{(prec.worst_case_dE||0).toFixed(2)}})</div>
      </div>`;
    }}
    if (costR.total_risk !== undefined) {{
      html += `<div class="insight-card">
        <div class="insight-title">💰 色差风险量化</div>
        <div style="font-size:24px;font-weight:700;font-family:var(--mono);color:${{costR.total_risk>1000?'var(--fail)':costR.total_risk>100?'var(--marginal)':'var(--pass)'}};margin:8px 0">
          ¥${{costR.total_risk?.toLocaleString() || '0'}}</div>
        <div style="font-size:12px;color:var(--text-secondary)">预估退货率: ${{costR.return_rate||0}}% | 投诉率: ${{costR.complaint_rate||0}}%</div>
        <div style="margin-top:8px;padding:6px 12px;border-radius:6px;background:var(--bg-glass);font-size:13px">${{esc(costR.decision||'')}} — ${{esc(costR.reason||'')}}</div>
      </div>`;
    }}
    html += `</div>`;
  }}

  // 同色异谱警告
  if (met.risk_level === 'high' || met.risk_level === 'medium') {{
    html += `<div style="background:var(--marginal-bg);border:1px solid rgba(255,193,77,.3);border-radius:var(--radius);padding:16px;margin-bottom:16px">
      <div style="font-weight:600;color:var(--marginal);margin-bottom:6px">⚠️ 同色异谱风险: ${{met.risk_level === 'high' ? '高' : '中'}}</div>
      ${{(met.risk_factors||[]).map(f => `<div style="font-size:13px;color:var(--text-secondary);margin-top:4px">· ${{esc(f)}}</div>`).join('')}}
      <div style="font-size:12px;color:var(--text-dim);margin-top:8px">${{esc(met.recommendation||'')}}</div>
    </div>`;
  }}

  // 热图
  if (heatmapUrl) {{
    html += `<div class="heatmap-section">
      <div class="insight-title" style="text-align:left;margin-bottom:16px">🗺 色差热图</div>
      <img src="/v1/senia/artifact?path=${{encodeURIComponent(heatmapUrl)}}" alt="heatmap"
           onerror="this.style.display='none';this.nextElementSibling.style.display='block'">
      <p style="display:none;color:var(--text-dim);font-size:13px">热图暂不可用，请查看 report.json 获取原始数据</p>
    </div>`;
  }}

  // ── 操作员反馈 (自学习) ──
  html += `<div class="insights-row">
    <div class="insight-card" style="text-align:center">
      <div class="insight-title">💬 你同意这个判定吗？</div>
      <p style="color:var(--text-secondary);font-size:13px;margin-bottom:12px">你的反馈会让系统越来越准</p>
      <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
        <button onclick="sendFeedback('${{d.lot_id||""}}','${{tier}}','PASS',${{summary.avg_delta_e00||0}},'${{d.profile?.used||"auto"}}')"
          style="padding:8px 24px;border-radius:8px;border:1px solid var(--pass);background:var(--pass-bg);color:var(--pass);cursor:pointer;font-size:14px;font-weight:600">
          &#x1f44d; 应该合格</button>
        <button onclick="sendFeedback('${{d.lot_id||""}}','${{tier}}','MARGINAL',${{summary.avg_delta_e00||0}},'${{d.profile?.used||"auto"}}')"
          style="padding:8px 24px;border-radius:8px;border:1px solid var(--marginal);background:var(--marginal-bg);color:var(--marginal);cursor:pointer;font-size:14px;font-weight:600">
          &#x26a0; 应该临界</button>
        <button onclick="sendFeedback('${{d.lot_id||""}}','${{tier}}','FAIL',${{summary.avg_delta_e00||0}},'${{d.profile?.used||"auto"}}')"
          style="padding:8px 24px;border-radius:8px;border:1px solid var(--fail);background:var(--fail-bg);color:var(--fail);cursor:pointer;font-size:14px;font-weight:600">
          &#x1f44e; 应该不合格</button>
      </div>
      <div id="feedbackResult" style="margin-top:10px;font-size:12px;color:var(--text-dim)"></div>
    </div>
    <div class="insight-card">
      <div class="insight-title">📈 批次趋势</div>
      <div id="lotHistory" style="font-size:13px;color:var(--text-secondary)">
        ${{d.history?.has_baseline
          ? `<div style="margin-bottom:8px">
               <span style="color:var(--text-primary);font-weight:600">${{d.history.vs_baseline === 'better' ? '&#x2b06; 优于' : d.history.vs_baseline === 'worse' ? '&#x2b07; 劣于' : '&#x2194; 持平'}}历史基线</span>
               (历史均值 ΔE=${{d.history.baseline_avg?.toFixed(2)}})
             </div>
             <div>趋势: ${{d.history.trend === 'improving' ? '&#x2705; 改善中' : d.history.trend === 'degrading' ? '&#x26a0; 恶化中' : '&#x2796; 稳定'}}</div>
             ${{d.history.drift_detected ? '<div style="color:var(--fail);margin-top:4px">&#x26a0; 检测到色差漂移!</div>' : ''}}`
          : '<div style="color:var(--text-dim)">暂无历史数据, 后续分析将自动积累</div>'
        }}
      </div>
    </div>
  </div>`;

  resultArea.innerHTML = html;
  resultArea.classList.add('active');
  window.scrollTo({{ top: resultArea.offsetTop - 20, behavior: 'smooth' }});
}}

// ── 反馈提交 ──
async function sendFeedback(lotId, systemTier, operatorTier, dE, profile) {{
  const fb = $('feedbackResult');
  fb.textContent = 'Submitting...';
  try {{
    const form = new FormData();
    form.append('run_id', `fb_${{Date.now()}}`);
    form.append('system_tier', systemTier);
    form.append('operator_tier', operatorTier);
    form.append('dE00', dE.toString());
    form.append('profile', profile);
    const r = await fetch('/v1/senia/feedback', {{method:'POST', body:form}});
    const j = await r.json();
    fb.innerHTML = `<span style="color:var(--pass)">&#x2705; 反馈已记录! 系统正在学习你的判断标准 (累计 ${{j.total_feedbacks}} 条)</span>`;
  }} catch(e) {{
    fb.innerHTML = `<span style="color:var(--fail)">&#x274c; 提交失败: ${{e.message}}</span>`;
  }}
}}
</script>
</body>
</html>"""
