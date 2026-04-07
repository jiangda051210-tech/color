"""
SENIA 首页前端 Hotfix
=====================
可直接替换 render_senia_home 的实现，用于修复首页单拍/双拍联调问题。
"""

from __future__ import annotations


def render_senia_home_hotfix(app_version: str = "2.4.0") -> str:
    return f"""<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
<meta name=\"theme-color\" content=\"#08101f\">
<title>SENIA 智能对色</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#08101f; color:#e8edf5; }}
.wrap {{ max-width:1080px; margin:0 auto; padding:18px; }}
.top {{ display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:24px; }}
.brand {{ font-size:20px; font-weight:700; }}
.brand small {{ color:#8fa4c2; font-weight:500; margin-left:8px; }}
.links a {{ color:#9ecbff; text-decoration:none; margin-left:12px; font-size:13px; }}
.hero {{ margin-bottom:20px; }}
.hero h1 {{ margin:0 0 8px; font-size:32px; }}
.hero p {{ margin:0; color:#9fb0c8; line-height:1.6; }}
.card {{ background:rgba(15,25,44,.9); border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:18px; margin-bottom:16px; }}
.row {{ display:flex; gap:12px; flex-wrap:wrap; }}
.field {{ flex:1; min-width:150px; }}
.field label {{ display:block; font-size:12px; color:#8ea0ba; margin-bottom:6px; }}
.field input,.field select {{ width:100%; padding:12px 14px; border-radius:10px; border:1px solid rgba(255,255,255,.08); background:#0d1830; color:#e8edf5; font-size:14px; }}
.mode-switch {{ display:flex; gap:10px; margin-bottom:16px; }}
.mode-btn {{ flex:1; padding:12px 16px; border-radius:12px; border:1px solid rgba(255,255,255,.1); background:#0d1830; color:#b5c4d9; cursor:pointer; font-size:14px; font-weight:700; }}
.mode-btn.active {{ border-color:#4ea8ff; background:rgba(78,168,255,.12); color:#9ed0ff; }}
.uploads {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
.upload-box {{ border:1.5px dashed rgba(78,168,255,.35); border-radius:14px; padding:20px; text-align:center; cursor:pointer; background:rgba(255,255,255,.02); }}
.upload-box.has-file {{ border-style:solid; border-color:#00d27d; }}
.upload-box h3 {{ margin:0 0 6px; font-size:16px; }}
.upload-box p {{ margin:0; color:#8ea0ba; font-size:13px; }}
.preview {{ display:none; margin-top:14px; max-width:100%; max-height:220px; border-radius:10px; }}
.upload-box.has-file .preview {{ display:block; margin-left:auto; margin-right:auto; }}
.single-only {{ display:block; }}
.dual-only {{ display:none; }}
.btn {{ padding:12px 20px; border:none; border-radius:12px; cursor:pointer; font-size:15px; font-weight:700; background:linear-gradient(135deg,#4ea8ff,#00d6b6); color:#06111f; }}
.btn:disabled {{ opacity:.45; cursor:not-allowed; }}
.muted {{ color:#8ea0ba; }}
.status {{ font-size:13px; color:#9ecbff; min-height:20px; }}
.result {{ display:none; }}
.result.active {{ display:block; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin:14px 0; }}
.kpi {{ background:#0d1830; border:1px solid rgba(255,255,255,.06); border-radius:12px; padding:14px; text-align:center; }}
.kpi .label {{ font-size:11px; color:#8ea0ba; margin-bottom:6px; text-transform:uppercase; }}
.kpi .value {{ font-size:22px; font-weight:800; }}
.verdict {{ display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }}
.badge {{ padding:10px 18px; border-radius:12px; font-size:24px; font-weight:800; }}
.pass {{ background:rgba(0,230,138,.12); color:#00e68a; }}
.marginal {{ background:rgba(255,193,77,.12); color:#ffc14d; }}
.fail {{ background:rgba(255,92,114,.12); color:#ff5c72; }}
.tags {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }}
.tag {{ padding:6px 12px; border-radius:999px; background:#0d1830; border:1px solid rgba(255,255,255,.06); font-size:13px; }}
.split {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:14px; }}
.list {{ display:flex; flex-direction:column; gap:8px; }}
.item {{ padding:10px 12px; background:#0d1830; border-radius:10px; font-size:14px; line-height:1.5; }}
.heatmap img {{ max-width:100%; border-radius:12px; border:1px solid rgba(255,255,255,.08); }}
.feedback {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }}
.feedback button {{ padding:10px 16px; border-radius:10px; cursor:pointer; border:1px solid rgba(255,255,255,.08); background:#0d1830; color:#dce8f7; }}
.small {{ font-size:12px; color:#8ea0ba; }}
@media (max-width:760px) {{ .wrap {{ padding:12px; }} .hero h1 {{ font-size:24px; }} .uploads,.split {{ grid-template-columns:1fr; }} .field input,.field select,.btn,.mode-btn {{ min-height:44px; font-size:16px; }} }}
</style>
</head>
<body>
<div class=\"wrap\">
  <div class=\"top\">
    <div class=\"brand\">SENIA 智能对色 <small>v{app_version}</small></div>
    <div class=\"links\"><a href=\"/v1/web/dashboard\">Full Dashboard</a><a href=\"/docs\">API</a></div>
  </div>
  <div class=\"hero\"><h1>拍照即出结果</h1><p>首页直接对接后端分析接口，修复单拍/双拍切换、请求构造、结果渲染和反馈提交链路。</p></div>
  <div class=\"card\">
    <div class=\"mode-switch\">
      <button id=\"modeSingle\" class=\"mode-btn active\" type=\"button\">📷 一张照片（快速）</button>
      <button id=\"modeDual\" class=\"mode-btn\" type=\"button\">📷📷 两张照片（精准）</button>
    </div>
    <div id=\"singleArea\" class=\"single-only\">
      <div id=\"singleBox\" class=\"upload-box\"><h3>上传一张同时包含大货和标样的照片</h3><p>点击选择图片，或在手机上直接拍照上传</p><img id=\"singlePreview\" class=\"preview\" alt=\"single preview\"><input id=\"singleInput\" type=\"file\" accept=\"image/*\" style=\"display:none\"></div>
    </div>
    <div id=\"dualArea\" class=\"dual-only\">
      <div class=\"uploads\">
        <div id=\"refBox\" class=\"upload-box\"><h3>标样照片</h3><p>只拍标样，占满画面</p><img id=\"refPreview\" class=\"preview\" alt=\"reference preview\"><input id=\"refInput\" type=\"file\" accept=\"image/*\" style=\"display:none\"></div>
        <div id=\"sampleBox\" class=\"upload-box\"><h3>大货照片</h3><p>只拍大货，占满画面</p><img id=\"samplePreview\" class=\"preview\" alt=\"sample preview\"><input id=\"sampleInput\" type=\"file\" accept=\"image/*\" style=\"display:none\"></div>
      </div>
    </div>
    <div style=\"height:12px\"></div>
    <div class=\"row\">
      <div class=\"field\"><label>材质类型</label><select id=\"profile\"><option value=\"auto\">自动识别</option><option value=\"wood\">木纹</option><option value=\"solid\">纯色</option><option value=\"stone\">石纹</option><option value=\"metallic\">金属</option><option value=\"high_gloss\">高光</option></select></div>
      <div class=\"field\"><label>批次号</label><input id=\"lotId\" placeholder=\"选填，如 L20240728-01\"></div>
      <div class=\"field\"><label>产品编号</label><input id=\"productCode\" placeholder=\"选填，如 AW-125470\"></div>
    </div>
    <div style=\"height:12px\"></div>
    <div class=\"row\" style=\"align-items:center\"><button id=\"analyzeBtn\" class=\"btn\" type=\"button\" disabled>开始对色</button><button id=\"resetBtn\" class=\"mode-btn\" type=\"button\" style=\"max-width:160px\">重置</button><div id=\"status\" class=\"status\"></div></div>
  </div>
  <div id=\"result\" class=\"result\"></div>
</div>
<script>
const $ = (id) => document.getElementById(id);
let mode = 'single';
let singleFile = null;
let refFile = null;
let sampleFile = null;
function esc(v) {{ const d = document.createElement('div'); d.textContent = v == null ? '' : String(v); return d.innerHTML; }}
function setMode(nextMode) {{ mode = nextMode; $('modeSingle').classList.toggle('active', nextMode === 'single'); $('modeDual').classList.toggle('active', nextMode === 'dual'); $('singleArea').style.display = nextMode === 'single' ? 'block' : 'none'; $('dualArea').style.display = nextMode === 'dual' ? 'block' : 'none'; updateAnalyzeButton(); }}
function updateAnalyzeButton() {{ const ready = mode === 'single' ? !!singleFile : !!(refFile && sampleFile); $('analyzeBtn').disabled = !ready; }}
function setPreview(file, imgId, boxId) {{ const reader = new FileReader(); reader.onload = (e) => {{ $(imgId).src = e.target.result; $(boxId).classList.add('has-file'); }}; reader.readAsDataURL(file); }}
function clearBox(imgId, boxId, inputId) {{ $(imgId).src=''; $(boxId).classList.remove('has-file'); $(inputId).value=''; }}
function resetUploads() {{ singleFile=null; refFile=null; sampleFile=null; clearBox('singlePreview','singleBox','singleInput'); clearBox('refPreview','refBox','refInput'); clearBox('samplePreview','sampleBox','sampleInput'); $('status').textContent=''; $('result').classList.remove('active'); $('result').innerHTML=''; updateAnalyzeButton(); }}
$('modeSingle').addEventListener('click', () => setMode('single')); $('modeDual').addEventListener('click', () => setMode('dual')); $('resetBtn').addEventListener('click', resetUploads);
$('singleBox').addEventListener('click', () => $('singleInput').click()); $('refBox').addEventListener('click', () => $('refInput').click()); $('sampleBox').addEventListener('click', () => $('sampleInput').click());
$('singleInput').addEventListener('change', () => {{ const file = $('singleInput').files[0]; if (!file) return; singleFile = file; setPreview(file,'singlePreview','singleBox'); updateAnalyzeButton(); }});
$('refInput').addEventListener('change', () => {{ const file = $('refInput').files[0]; if (!file) return; refFile = file; setPreview(file,'refPreview','refBox'); updateAnalyzeButton(); }});
$('sampleInput').addEventListener('change', () => {{ const file = $('sampleInput').files[0]; if (!file) return; sampleFile = file; setPreview(file,'samplePreview','sampleBox'); updateAnalyzeButton(); }});
async function analyze() {{ if (mode === 'single' && !singleFile) return; if (mode === 'dual' && !(refFile && sampleFile)) return; $('analyzeBtn').disabled = true; $('status').textContent = '正在调用后端分析，请稍候…'; try {{ const form = new FormData(); let url = '/v1/senia/analyze'; if (mode === 'single') {{ form.append('image', singleFile); form.append('grid', '6x8'); }} else {{ url = '/v1/senia/dual-shot'; form.append('reference', refFile); form.append('sample', sampleFile); }} form.append('profile', $('profile').value); form.append('lot_id', $('lotId').value); form.append('product_code', $('productCode').value); const resp = await fetch(url, {{ method:'POST', body:form }}); let payload = null; try {{ payload = await resp.json(); }} catch (e) {{ payload = {{ detail: resp.statusText || '请求失败' }}; }} if (!resp.ok) throw new Error(payload.detail || '分析失败'); renderResult(payload.report || payload); $('status').textContent = '分析完成'; }} catch (err) {{ $('result').innerHTML = `<div class=\"card\"><div class=\"verdict\"><div class=\"badge fail\">分析失败</div><div class=\"muted\">${{esc(err.message || '请求失败')}}</div></div></div>`; $('result').classList.add('active'); $('status').textContent = '分析失败'; }} finally {{ updateAnalyzeButton(); }} }}
$('analyzeBtn').addEventListener('click', analyze);
async function sendFeedback(systemTier, operatorTier, dE00, profile) {{ const fb = $('feedbackHint'); fb.textContent = '反馈提交中…'; try {{ const form = new FormData(); form.append('run_id', 'ui_' + Date.now()); form.append('system_tier', systemTier || 'UNKNOWN'); form.append('operator_tier', operatorTier); form.append('dE00', String(dE00 || 0)); form.append('profile', profile || 'auto'); const r = await fetch('/v1/senia/feedback', {{ method:'POST', body:form }}); await r.json(); fb.textContent = '反馈已记录，系统会继续学习。'; }} catch (e) {{ fb.textContent = '反馈提交失败：' + (e.message || 'unknown error'); }} }}
function renderResult(d) {{ const tier = d.tier || 'UNKNOWN'; const tierClass = tier === 'PASS' ? 'pass' : tier === 'MARGINAL' ? 'marginal' : 'fail'; const tierLabel = tier === 'PASS' ? '合格' : tier === 'MARGINAL' ? '临界' : '不合格'; const summary = (d.result && d.result.summary) || {{}}; const dev = d.deviation || {{}}; const recipe = d.recipe_advice || {{ advices: [] }}; const uniformity = d.uniformity || {{}}; const dirs = Array.isArray(dev.directions) ? dev.directions : []; const heatmap = d.artifacts && d.artifacts.heatmap ? d.artifacts.heatmap : ''; const metamerism = d.metamerism || {{}}; const costRisk = d.cost_risk || {{}}; const usedProfile = (d.profile && d.profile.used) || 'auto'; $('result').innerHTML = `<div class=\"card\"><div class=\"verdict\"><div><div class=\"badge ${{tierClass}}\">${{tierLabel}}</div><div class=\"small\" style=\"margin-top:8px\">${{esc(d.lot_id || '')}} ${{d.product_code ? '· ' + esc(d.product_code) : ''}}</div></div><div style=\"text-align:right\"><div class=\"small\">平均 ΔE00</div><div style=\"font-size:34px;font-weight:800\">${{Number(summary.avg_delta_e00 || 0).toFixed(2)}}</div></div></div><div class=\"tags\">${{dirs.length ? dirs.map(x => `<span class=\"tag\">${{esc(x)}}</span>`).join('') : '<span class=\"tag\">色差极小</span>'}}</div><div class=\"kpis\"><div class=\"kpi\"><div class=\"label\">P95</div><div class=\"value\">${{Number(summary.p95_delta_e00 || 0).toFixed(2)}}</div></div><div class=\"kpi\"><div class=\"label\">Max</div><div class=\"value\">${{Number(summary.max_delta_e00 || 0).toFixed(2)}}</div></div><div class=\"kpi\"><div class=\"label\">ΔL</div><div class=\"value\">${{Number(dev.dL || 0).toFixed(2)}}</div></div><div class=\"kpi\"><div class=\"label\">Δa</div><div class=\"value\">${{Number(dev.da || 0).toFixed(2)}}</div></div><div class=\"kpi\"><div class=\"label\">Δb</div><div class=\"value\">${{Number(dev.db || 0).toFixed(2)}}</div></div><div class=\"kpi\"><div class=\"label\">置信度</div><div class=\"value\">${{Math.round(((d.result && d.result.confidence && d.result.confidence.overall) || 0) * 100)}}%</div></div></div></div><div class=\"split\"><div class=\"card\"><div class=\"muted\" style=\"font-size:12px;margin-bottom:10px\">调色建议</div><div class=\"list\">${{recipe.advices && recipe.advices.length ? recipe.advices.slice(0,6).map(a => `<div class=\"item\">${{esc(a.action)}}</div>`).join('') : '<div class=\"item\">当前无额外调色建议</div>'}}</div></div><div class=\"card\"><div class=\"muted\" style=\"font-size:12px;margin-bottom:10px\">根因分析</div><div class=\"item\"><strong>${{esc(uniformity.root_cause || 'unknown')}}</strong></div><div class=\"item\">${{esc(uniformity.explanation || '暂无说明')}}</div></div></div><div class=\"split\"><div class=\"card\"><div class=\"muted\" style=\"font-size:12px;margin-bottom:10px\">同色异谱 / 成本风险</div><div class=\"item\">同色异谱风险：${{esc(metamerism.risk_level || 'unknown')}}</div><div class=\"item\">成本风险：${{costRisk.total_risk != null ? '¥' + Number(costRisk.total_risk).toLocaleString() : 'N/A'}}</div></div><div class=\"card\"><div class=\"muted\" style=\"font-size:12px;margin-bottom:10px\">操作员反馈</div><div class=\"feedback\"><button type=\"button\" onclick=\"sendFeedback('${{tier}}','PASS',${{Number(summary.avg_delta_e00 || 0)}},'${{usedProfile}}')\">应该合格</button><button type=\"button\" onclick=\"sendFeedback('${{tier}}','MARGINAL',${{Number(summary.avg_delta_e00 || 0)}},'${{usedProfile}}')\">应该临界</button><button type=\"button\" onclick=\"sendFeedback('${{tier}}','FAIL',${{Number(summary.avg_delta_e00 || 0)}},'${{usedProfile}}')\">应该不合格</button></div><div id=\"feedbackHint\" class=\"small\" style=\"margin-top:10px\"></div></div></div>${{heatmap ? `<div class=\"card heatmap\"><div class=\"muted\" style=\"font-size:12px;margin-bottom:10px\">色差热图</div><img src=\"/v1/senia/artifact?path=${{encodeURIComponent(heatmap)}}\" alt=\"heatmap\"></div>` : ''}}`; $('result').classList.add('active'); window.scrollTo({{ top: $('result').offsetTop - 10, behavior:'smooth' }}); }}
setMode('single'); updateAnalyzeButton();
</script>
</body>
</html>"""
