from __future__ import annotations

import html
import shutil
import subprocess
from pathlib import Path

HOME_PAGE_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SENIA Elite Smart Console</title>
  <style>
    /* Google Fonts — loads async; system fonts below are used as fallback if CDN is unreachable */
    @import url("https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700&family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap");
    :root {
      --bg-0: #091322;
      --bg-1: #0f1f34;
      --bg-2: #13263f;
      --ink-0: #eef6ff;
      --ink-1: #bad0e8;
      --ink-2: #85a4c4;
      --line: rgba(147, 191, 232, 0.22);
      --accent-a: #00b7a8;
      --accent-b: #3fa8ff;
      --accent-c: #ff9f43;
      --good: #2ac670;
      --warn: #ffb145;
      --bad: #ff5d73;
      --card: rgba(13, 26, 43, 0.88);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Sora", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", "Hiragino Sans GB", "WenQuanYi Micro Hei", system-ui, sans-serif;
      color: var(--ink-0);
      background:
        radial-gradient(1200px 600px at 85% -10%, rgba(0, 183, 168, 0.16), transparent 55%),
        radial-gradient(1000px 550px at -10% -5%, rgba(63, 168, 255, 0.20), transparent 55%),
        linear-gradient(155deg, var(--bg-0), var(--bg-1) 50%, var(--bg-2));
      min-height: 100vh;
    }
    .grid-bg {
      pointer-events: none;
      position: fixed;
      inset: 0;
      background-image:
        linear-gradient(rgba(140, 181, 222, 0.06) 1px, transparent 1px),
        linear-gradient(90deg, rgba(140, 181, 222, 0.06) 1px, transparent 1px);
      background-size: 40px 40px;
      mask-image: radial-gradient(circle at 50% 30%, black, transparent 80%);
    }
    .wrap {
      max-width: 1220px;
      margin: 0 auto;
      padding: 24px 16px 42px;
    }
    .hero {
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 22px;
      background: linear-gradient(155deg, rgba(16, 33, 52, 0.82), rgba(10, 21, 36, 0.90));
      box-shadow: 0 14px 40px rgba(3, 10, 18, 0.55);
      backdrop-filter: blur(8px);
    }
    .hero-title {
      margin: 0;
      font-weight: 700;
      font-size: clamp(24px, 4vw, 36px);
      letter-spacing: 0.3px;
    }
    .hero-sub {
      margin: 8px 0 0;
      color: var(--ink-1);
      font-size: 14px;
      line-height: 1.7;
    }
    .badge-row {
      margin-top: 14px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .auth-row {
      margin-top: 12px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
    }
    .auth-row input {
      border: 1px solid rgba(143, 186, 227, 0.28);
      border-radius: 10px;
      padding: 10px 11px;
      font-size: 13px;
      color: var(--ink-0);
      background: rgba(14, 28, 47, 0.8);
    }
    .auth-help {
      color: var(--ink-2);
      font-size: 11px;
      margin: 0;
      text-align: right;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      height: 28px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(17, 36, 58, 0.7);
      color: var(--ink-0);
      padding: 0 12px;
      font-size: 12px;
      letter-spacing: 0.2px;
    }
    .status-grid {
      margin-top: 16px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }
    .status-card {
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px 14px;
      background: rgba(12, 26, 43, 0.75);
    }
    .status-k {
      margin: 0;
      color: var(--ink-2);
      font-size: 11px;
      letter-spacing: 0.35px;
      text-transform: uppercase;
    }
    .status-v {
      margin: 6px 0 0;
      font-size: 18px;
      font-weight: 600;
    }
    .main-grid {
      margin-top: 16px;
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 14px;
    }
    .panel {
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--card);
      box-shadow: 0 10px 30px rgba(5, 13, 23, 0.45);
      padding: 16px;
    }
    .panel h2 {
      margin: 0;
      font-size: 18px;
      letter-spacing: 0.2px;
    }
    .panel p.note {
      margin: 6px 0 0;
      color: var(--ink-2);
      font-size: 12px;
      line-height: 1.6;
    }
    .form-grid {
      margin-top: 14px;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .field.full { grid-column: span 2; }
    .field label {
      color: var(--ink-1);
      font-size: 12px;
      letter-spacing: 0.2px;
    }
    input[type="text"], input[type="file"], select {
      width: 100%;
      border: 1px solid rgba(143, 186, 227, 0.28);
      border-radius: 10px;
      padding: 10px 11px;
      font-size: 13px;
      color: var(--ink-0);
      background: rgba(14, 28, 47, 0.8);
    }
    input::file-selector-button {
      border: 1px solid rgba(143, 186, 227, 0.35);
      border-radius: 8px;
      background: rgba(25, 49, 78, 0.9);
      color: var(--ink-0);
      padding: 6px 8px;
      margin-right: 8px;
      cursor: pointer;
    }
    .btn-row {
      margin-top: 12px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    button {
      border: 0;
      border-radius: 10px;
      padding: 10px 14px;
      font-weight: 600;
      letter-spacing: 0.2px;
      color: #00171a;
      background: linear-gradient(140deg, #00dbc4, #43e7b0);
      cursor: pointer;
      box-shadow: 0 8px 20px rgba(0, 209, 166, 0.28);
    }
    button.secondary {
      color: #e7f2ff;
      background: linear-gradient(145deg, #2a6eb3, #3fa8ff);
      box-shadow: 0 8px 20px rgba(63, 168, 255, 0.26);
    }
    button:disabled {
      opacity: 0.66;
      cursor: not-allowed;
      box-shadow: none;
    }
    .link-row {
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .link-chip {
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: #d8edff;
      text-decoration: none;
      font-size: 12px;
      padding: 6px 10px;
      background: rgba(16, 31, 52, 0.72);
    }
    .result {
      margin-top: 10px;
      border: 1px dashed rgba(138, 185, 226, 0.36);
      border-radius: 12px;
      padding: 12px;
      background: rgba(9, 20, 35, 0.86);
      min-height: 180px;
    }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }
    .metric {
      border: 1px solid rgba(138, 185, 226, 0.2);
      border-radius: 10px;
      padding: 8px 10px;
      background: rgba(13, 26, 41, 0.8);
    }
    .metric .k {
      font-size: 11px;
      color: var(--ink-2);
      margin: 0;
    }
    .metric .v {
      margin: 5px 0 0;
      font-size: 15px;
      font-weight: 600;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      height: 24px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      padding: 0 10px;
    }
    .pill.good { color: #01341e; background: var(--good); }
    .pill.warn { color: #3a1f00; background: var(--warn); }
    .pill.bad { color: #3e0611; background: var(--bad); }
    .mono {
      margin-top: 10px;
      font-family: "JetBrains Mono", Consolas, monospace;
      font-size: 12px;
      line-height: 1.5;
      color: #d7ecff;
      border-radius: 10px;
      border: 1px solid rgba(138, 185, 226, 0.2);
      background: #071423;
      padding: 10px;
      max-height: 300px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .err {
      margin-top: 8px;
      color: #ffd6dd;
      background: rgba(122, 10, 30, 0.32);
      border: 1px solid rgba(255, 99, 132, 0.5);
      border-radius: 10px;
      padding: 8px 10px;
      font-size: 12px;
    }
    @media (max-width: 1080px) {
      .main-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 680px) {
      .form-grid { grid-template-columns: 1fr; }
      .field.full { grid-column: span 1; }
      .metric-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="grid-bg"></div>
  <div class="wrap">
    <section class="hero">
      <h1 class="hero-title">SENIA Elite 智能对色控制台</h1>
      <p class="hero-sub">
        行业级无人化对色入口。浏览器直接上传样板和彩膜，自动完成评估、决策与创新引擎分析，并输出可追溯报告。
      </p>
      <div class="badge-row">
        <span class="badge">Version __APP_VERSION__</span>
        <span class="badge">v14 Innovation Engine</span>
        <span class="badge">Request Trace + Runtime Status</span>
      </div>
      <div class="auth-row">
        <input id="api-key" type="text" placeholder="可选：输入 API Key（开启鉴权时需要）" />
        <p class="auth-help">Header: x-api-key</p>
      </div>
      <div class="status-grid">
        <div class="status-card">
          <p class="status-k">服务状态</p>
          <p class="status-v" id="svc-ok">...</p>
        </div>
        <div class="status-card">
          <p class="status-k">运行时长</p>
          <p class="status-v" id="svc-uptime">...</p>
        </div>
        <div class="status-card">
          <p class="status-k">总路由数</p>
          <p class="status-v" id="svc-routes">...</p>
        </div>
        <div class="status-card">
          <p class="status-k">默认输出目录</p>
          <p class="status-v" id="svc-out">...</p>
        </div>
      </div>
      <div class="link-row">
        <a class="link-chip" href="/docs" target="_blank">Swagger 文档</a>
        <a class="link-chip" href="/health" target="_blank">健康检查</a>
        <a class="link-chip" href="/ready" target="_blank">Readiness</a>
        <a class="link-chip" href="/v1/system/status" target="_blank">系统状态</a>
        <a class="link-chip" href="/v1/system/self-test" target="_blank">系统自检</a>
        <a class="link-chip" href="/v1/system/metrics" target="_blank">系统指标</a>
        <a class="link-chip" href="/v1/system/slo" target="_blank">SLO</a>
        <a class="link-chip" href="/v1/system/auth-info" target="_blank">鉴权状态</a>
        <a class="link-chip" href="/v1/system/tenant-info" target="_blank">租户状态</a>
        <a class="link-chip" href="/v1/system/alert-test?level=warning&title=console-test&message=hello" target="_blank">告警测试</a>
        <a class="link-chip" href="/v1/system/alert-dead-letter" target="_blank">告警失败队列</a>
        <a class="link-chip" href="/v1/system/audit-tail" target="_blank">审计日志</a>
        <a class="link-chip" href="/v1/system/ops-summary" target="_blank">运维总览</a>
        <a class="link-chip" href="/v1/system/executive-brief" target="_blank">执行简报</a>
        <a class="link-chip" href="/v1/system/release-gate-report" target="_blank">Release Gate</a>
        <a class="link-chip" href="/v1/web/executive-dashboard" target="_blank">经营看板</a>
        <a class="link-chip" href="/v1/web/executive-brief" target="_blank">简报页面</a>
        <a class="link-chip" href="/v1/web/innovation-v3" target="_blank">创新作战看板</a>
        <a class="link-chip" href="/v1/history/executive-export" target="_blank">经营导出</a>
        <a class="link-chip" href="/v1/innovation/manifest" target="_blank">创新能力清单</a>
      </div>
    </section>

    <section class="main-grid">
      <div class="panel">
        <h2>Dual 智能对色</h2>
        <p class="note">上传样板图与彩膜图，适合标准对色场景。支持客户层级策略、创新引擎与自动决策链路。</p>
        <form id="dual-form">
          <div class="form-grid">
            <div class="field">
              <label>样板图（reference）</label>
              <input type="file" name="reference" accept="image/*" required />
            </div>
            <div class="field">
              <label>彩膜图（film）</label>
              <input type="file" name="film" accept="image/*" required />
            </div>
            <div class="field">
              <label>材质档位</label>
              <select name="profile">
                <option value="auto">auto</option>
                <option value="solid">solid</option>
                <option value="wood">wood</option>
                <option value="stone">stone</option>
                <option value="metallic">metallic</option>
                <option value="high_gloss">high_gloss</option>
              </select>
            </div>
            <div class="field">
              <label>网格</label>
              <input type="text" name="grid" value="6x8" />
            </div>
            <div class="field">
              <label>客户 ID（可选）</label>
              <input type="text" name="customer_id" placeholder="例如 CUST-001" />
            </div>
            <div class="field">
              <label>客户层级（可选）</label>
              <select name="customer_tier">
                <option value="">auto / none</option>
                <option value="vip">vip</option>
                <option value="standard">standard</option>
                <option value="growth">growth</option>
                <option value="economy">economy</option>
              </select>
            </div>
            <div class="field">
              <label>创新引擎</label>
              <select name="with_innovation_engine">
                <option value="true">开启</option>
                <option value="false">关闭</option>
              </select>
            </div>
            <div class="field">
              <label>决策中心</label>
              <select name="with_decision_center">
                <option value="true">开启</option>
                <option value="false">关闭</option>
              </select>
            </div>
            <div class="field">
              <label>工艺建议</label>
              <select name="with_process_advice">
                <option value="true">开启</option>
                <option value="false">关闭</option>
              </select>
            </div>
            <div class="field">
              <label>HTML 报告</label>
              <select name="html_report">
                <option value="true">生成</option>
                <option value="false">不生成</option>
              </select>
            </div>
          </div>
          <div class="btn-row">
            <button id="dual-btn" type="submit">运行 Dual 分析</button>
            <button class="secondary" type="button" id="refresh-btn">刷新系统状态</button>
          </div>
        </form>

        <div class="result" id="result-dual">
          <div class="note">结果将显示在这里。</div>
        </div>
      </div>

      <div class="panel">
        <h2>Single 现场对色</h2>
        <p class="note">上传现场照片自动识别大板+小样。适合无人采集、手机拍照回传与快速抽检。</p>
        <form id="single-form">
          <div class="form-grid">
            <div class="field full">
              <label>现场图（image）</label>
              <input type="file" name="image" accept="image/*" required />
            </div>
            <div class="field">
              <label>材质档位</label>
              <select name="profile">
                <option value="auto">auto</option>
                <option value="solid">solid</option>
                <option value="wood">wood</option>
                <option value="stone">stone</option>
                <option value="metallic">metallic</option>
                <option value="high_gloss">high_gloss</option>
              </select>
            </div>
            <div class="field">
              <label>网格</label>
              <input type="text" name="grid" value="6x8" />
            </div>
            <div class="field">
              <label>客户 ID（可选）</label>
              <input type="text" name="customer_id" placeholder="例如 CUST-002" />
            </div>
            <div class="field">
              <label>客户层级（可选）</label>
              <select name="customer_tier">
                <option value="">auto / none</option>
                <option value="vip">vip</option>
                <option value="standard">standard</option>
                <option value="growth">growth</option>
                <option value="economy">economy</option>
              </select>
            </div>
            <div class="field">
              <label>创新引擎</label>
              <select name="with_innovation_engine">
                <option value="true">开启</option>
                <option value="false">关闭</option>
              </select>
            </div>
            <div class="field">
              <label>决策中心</label>
              <select name="with_decision_center">
                <option value="true">开启</option>
                <option value="false">关闭</option>
              </select>
            </div>
            <div class="field">
              <label>工艺建议</label>
              <select name="with_process_advice">
                <option value="true">开启</option>
                <option value="false">关闭</option>
              </select>
            </div>
            <div class="field">
              <label>HTML 报告</label>
              <select name="html_report">
                <option value="true">生成</option>
                <option value="false">不生成</option>
              </select>
            </div>
          </div>
          <div class="btn-row">
            <button id="single-btn" type="submit">运行 Single 分析</button>
          </div>
        </form>
        <div class="result" id="result-single">
          <div class="note">结果将显示在这里。</div>
        </div>
      </div>
    </section>

    <section class="panel" style="margin-top: 14px;">
      <h2>响应快照</h2>
      <p class="note">保留最近一次分析的完整 JSON 响应，便于技术排查与二次集成。</p>
      <pre class="mono" id="json-preview">{"status":"ready"}</pre>
    </section>
  </div>

  <script>
    const q = (s) => document.querySelector(s);

    function authHeaders() {
      const key = (q("#api-key")?.value || "").trim();
      if (!key) return {};
      return { "x-api-key": key };
    }

    function esc(v) {
      return String(v ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
    }

    function yesNo(v) {
      if (v === true) return '<span class="pill good">PASS</span>';
      if (v === false) return '<span class="pill bad">FAIL</span>';
      return '<span class="pill warn">N/A</span>';
    }

    function fmt(n, digits = 3) {
      if (typeof n !== "number" || Number.isNaN(n)) return "--";
      return n.toFixed(digits);
    }

    function uptimeText(sec) {
      if (typeof sec !== "number") return "--";
      if (sec < 60) return `${Math.round(sec)}s`;
      const m = Math.floor(sec / 60);
      const s = Math.round(sec % 60);
      if (m < 60) return `${m}m ${s}s`;
      const h = Math.floor(m / 60);
      const mm = m % 60;
      return `${h}h ${mm}m`;
    }

    function reportLink(path) {
      if (!path) return "";
      const encoded = encodeURIComponent(path);
      return `<a class="link-chip" target="_blank" href="/v1/report/html?path=${encoded}">打开 HTML 报告</a>`;
    }

    function jsonLink(path) {
      if (!path) return "";
      return `<span class="link-chip">${esc(path)}</span>`;
    }

    function setError(target, message) {
      target.innerHTML = `<div class="err">${esc(message || "请求失败")}</div>`;
    }

    function colorClass(de, avgTarget) {
      if (typeof de !== "number" || Number.isNaN(de) || typeof avgTarget !== "number") return "";
      if (de <= avgTarget) return "color:#2ac670";
      if (de <= avgTarget * 1.5) return "color:#ffb145";
      return "color:#ff5d73";
    }

    function renderResult(target, title, data) {
      const process = data.process_advice || {};
      const decision = data.decision_center || {};
      const innovation = data.innovation_engine || {};
      const summary = (data.result || {}).summary || {};
      const profile = (data.profile || {});
      const avgTarget = (profile.targets_used || {}).avg_delta_e00 || (profile.targets || {}).avg_delta_e00;

      // Support both single/dual (avg_delta_e00) and ensemble (median_avg_delta_e00)
      const avgDE = summary.avg_delta_e00 ?? summary.median_avg_delta_e00;
      const p95DE = summary.p95_delta_e00 ?? summary.median_p95_delta_e00;
      const maxDE = summary.max_delta_e00 ?? summary.median_max_delta_e00;
      const dL = summary.dL ?? summary.median_dL;
      const dC = summary.dC ?? summary.median_dC;
      const dH = summary.dH_deg ?? summary.median_dH_deg;

      target.innerHTML = `
        <div style="display:flex;align-items:center;gap:10px;">
          <strong>${esc(title)}</strong> ${yesNo(data.pass)}
          <span style="font-size:11px;color:#85a4c4;">profile: ${esc(profile.used || "--")}</span>
        </div>
        <div style="margin-top:8px;font-size:11px;font-weight:600;color:#85a4c4;letter-spacing:.3px;text-transform:uppercase;">色差指标</div>
        <div class="metric-grid">
          <div class="metric"><p class="k">ΔE₀₀ 平均</p><p class="v" style="${colorClass(avgDE, avgTarget)}">${fmt(avgDE, 3)}</p></div>
          <div class="metric"><p class="k">ΔE₀₀ P95</p><p class="v">${fmt(p95DE, 3)}</p></div>
          <div class="metric"><p class="k">ΔE₀₀ 最大</p><p class="v">${fmt(maxDE, 3)}</p></div>
          <div class="metric"><p class="k">dL / dC / dH</p><p class="v" style="font-size:13px;">${fmt(dL,2)} / ${fmt(dC,2)} / ${fmt(dH,1)}°</p></div>
        </div>
        <div style="margin-top:8px;font-size:11px;font-weight:600;color:#85a4c4;letter-spacing:.3px;text-transform:uppercase;">决策与质量</div>
        <div class="metric-grid">
          <div class="metric"><p class="k">置信度</p><p class="v">${fmt(data.confidence, 3)}</p></div>
          <div class="metric"><p class="k">风险等级</p><p class="v">${esc(process.risk_level || "--")}</p></div>
          <div class="metric"><p class="k">决策码</p><p class="v" style="font-size:12px;">${esc(decision.decision_code || "--")}</p></div>
          <div class="metric"><p class="k">老化风险</p><p class="v">${esc(innovation.aging_warranty_risk || "--")}</p></div>
        </div>
        <div class="link-row" style="margin-top:10px;">
          ${reportLink(data.html_path)}
          ${jsonLink(data.report_path)}
        </div>
      `;
      q("#json-preview").textContent = JSON.stringify(data, null, 2);
    }

    async function refreshStatus() {
      try {
        const hdrs = authHeaders();
        const [h, r, s] = await Promise.all([
          fetch("/health", { headers: hdrs }),
          fetch("/ready", { headers: hdrs }),
          fetch("/v1/system/status", { headers: hdrs }),
        ]);
        if (!h.ok || !r.ok || !s.ok) throw new Error("status endpoint unavailable");
        const [health, ready, status] = await Promise.all([h.json(), r.json(), s.json()]);
        q("#svc-ok").textContent = (health.ok && ready.ok) ? "ONLINE" : "DEGRADED";
        q("#svc-uptime").textContent = uptimeText(status?.service?.uptime_sec);
        q("#svc-routes").textContent = String(status?.routes?.count ?? "--");
        q("#svc-out").textContent = status?.paths?.output_root ?? "--";
      } catch (err) {
        q("#svc-ok").textContent = "OFFLINE";
        q("#svc-uptime").textContent = "--";
        q("#svc-routes").textContent = "--";
        q("#svc-out").textContent = "--";
      }
    }

    const MAX_UPLOAD_MB = 20;
    const ALLOWED_IMAGE_EXTS = /\.(jpe?g|png|bmp|tiff?|webp|gif)$/i;

    function validateFiles(form, out) {
      for (const [k, v] of new FormData(form).entries()) {
        if (!(v instanceof File) || v.size === 0) continue;
        if (v.size > MAX_UPLOAD_MB * 1024 * 1024) {
          setError(out, `${k} 文件大小超过 ${MAX_UPLOAD_MB}MB 限制（当前 ${(v.size/1024/1024).toFixed(1)}MB）`);
          return false;
        }
        if (!ALLOWED_IMAGE_EXTS.test(v.name)) {
          setError(out, `${k} 格式不支持（${esc(v.name)}），请上传 JPEG/PNG/BMP/TIFF/WebP`);
          return false;
        }
      }
      return true;
    }

    function normalizeForm(form) {
      const fd = new FormData(form);
      for (const [k, v] of [...fd.entries()]) {
        if (typeof v === "string" && v.trim() === "") fd.delete(k);
      }
      return fd;
    }

    async function submitDual(ev) {
      ev.preventDefault();
      const form = ev.currentTarget;
      const btn = q("#dual-btn");
      const out = q("#result-dual");
      if (!validateFiles(form, out)) return;
      btn.disabled = true;
      btn.textContent = "分析中...";
      out.innerHTML = '<div class="note">正在运行 Dual 分析，请稍候...</div>';
      try {
        const resp = await fetch("/v1/web/analyze/dual-upload", {
          method: "POST",
          headers: authHeaders(),
          body: normalizeForm(form),
        });
        const data = await resp.json();
        if (!resp.ok) {
          const msg = resp.status === 415
            ? "图片格式不支持，请上传 JPEG/PNG/BMP/TIFF/WebP"
            : (data?.detail || "Dual 分析失败");
          throw new Error(msg);
        }
        renderResult(out, "Dual 分析完成", data);
        refreshStatus();
      } catch (err) {
        setError(out, err?.message || "Dual 分析失败");
      } finally {
        btn.disabled = false;
        btn.textContent = "运行 Dual 分析";
      }
    }

    async function submitSingle(ev) {
      ev.preventDefault();
      const form = ev.currentTarget;
      const btn = q("#single-btn");
      const out = q("#result-single");
      if (!validateFiles(form, out)) return;
      btn.disabled = true;
      btn.textContent = "分析中...";
      out.innerHTML = '<div class="note">正在运行 Single 分析，请稍候...</div>';
      try {
        const resp = await fetch("/v1/web/analyze/single-upload", {
          method: "POST",
          headers: authHeaders(),
          body: normalizeForm(form),
        });
        const data = await resp.json();
        if (!resp.ok) {
          const msg = resp.status === 415
            ? "图片格式不支持，请上传 JPEG/PNG/BMP/TIFF/WebP"
            : (data?.detail || "Single 分析失败");
          throw new Error(msg);
        }
        renderResult(out, "Single 分析完成", data);
        refreshStatus();
      } catch (err) {
        setError(out, err?.message || "Single 分析失败");
      } finally {
        btn.disabled = false;
        btn.textContent = "运行 Single 分析";
      }
    }

    document.addEventListener("DOMContentLoaded", () => {
      q("#dual-form").addEventListener("submit", submitDual);
      q("#single-form").addEventListener("submit", submitSingle);
      q("#refresh-btn").addEventListener("click", refreshStatus);
      refreshStatus();
      setInterval(refreshStatus, 15000);
    });
  </script>
</body>
</html>
""".strip()


SMART_HOME_PAGE_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SENIA Elite 智能工作台</title>
  <style>
    /* Google Fonts — loads async; system fonts below are used as fallback if CDN is unreachable */
    @import url("https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap");
    :root {
      --bg0: #091423;
      --bg1: #11263f;
      --line: rgba(148, 198, 240, 0.25);
      --ink: #edf6ff;
      --sub: #9fbddd;
      --ok: #31ca76;
      --warn: #ffb347;
      --bad: #ff5f79;
      --card: rgba(10, 24, 40, 0.86);
      --accent: #33a3ff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Space Grotesk", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", "Hiragino Sans GB", "WenQuanYi Micro Hei", system-ui, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(900px 450px at 88% -10%, rgba(0, 191, 155, 0.16), transparent 60%),
        radial-gradient(980px 580px at -10% -10%, rgba(65, 166, 255, 0.22), transparent 62%),
        linear-gradient(160deg, #081220, var(--bg0) 52%, var(--bg1));
      min-height: 100vh;
    }
    .wrap {
      max-width: 1680px;
      margin: 0 auto;
      padding: 14px;
      display: grid;
      grid-template-columns: 272px minmax(0, 1fr);
      gap: 12px;
    }
    .main { min-width: 0; }
    .side {
      border: 1px solid var(--line);
      border-radius: 26px;
      background: rgba(10, 24, 40, 0.76);
      box-shadow: 0 12px 34px rgba(4, 12, 22, 0.46);
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-height: calc(100vh - 28px);
      position: sticky;
      top: 14px;
    }
    .side .brand {
      border: 1px solid rgba(83, 198, 255, 0.28);
      border-radius: 16px;
      background: linear-gradient(145deg, rgba(51, 163, 255, 0.2), rgba(51, 163, 255, 0.06));
      padding: 10px;
    }
    .side .brand b { display: block; font-size: 15px; }
    .side .brand span { color: var(--sub); font-size: 11px; }
    .side-nav {
      border: 1px solid rgba(148, 198, 240, 0.24);
      border-radius: 14px;
      background: rgba(8, 20, 33, 0.72);
      padding: 6px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .side-nav .item {
      border: 1px solid rgba(148, 198, 240, 0.18);
      border-radius: 10px;
      background: rgba(15, 30, 48, 0.72);
      color: #d9edff;
      padding: 7px 9px;
      font-size: 12px;
    }
    .side-nav .item.active {
      border-color: rgba(83, 198, 255, 0.45);
      background: linear-gradient(145deg, rgba(51, 163, 255, 0.24), rgba(51, 163, 255, 0.08));
      color: #ebf8ff;
      font-weight: 700;
    }
    .side-box {
      border: 1px solid rgba(148, 198, 240, 0.24);
      border-radius: 14px;
      background: rgba(8, 20, 33, 0.72);
      padding: 9px;
    }
    .side-box .t { margin: 0; font-size: 11px; color: var(--sub); text-transform: uppercase; }
    .side-box .v { margin: 6px 0 0; font-size: 22px; font-weight: 700; font-family: "JetBrains Mono", Consolas, monospace; }
    .side-box .d { margin: 6px 0 0; font-size: 11px; color: var(--sub); line-height: 1.6; }
    .health-bar {
      margin-top: 7px;
      height: 8px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.08);
      overflow: hidden;
    }
    .health-bar > span {
      display: block;
      height: 100%;
      width: 88%;
      background: linear-gradient(145deg, #31ca76, #33a3ff);
    }
    .stat-strip {
      margin-top: 10px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }
    .stat-card {
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(10, 24, 40, 0.86);
      box-shadow: 0 8px 20px rgba(4, 12, 22, 0.3);
      padding: 9px 10px;
    }
    .stat-card .k { margin: 0; font-size: 11px; color: var(--sub); }
    .stat-card .v { margin: 6px 0 0; font-size: 20px; font-weight: 700; font-family: "JetBrains Mono", Consolas, monospace; }
    .stat-card .d { margin: 6px 0 0; font-size: 11px; color: #9ee6c6; }
    .hero, .card {
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--card);
      box-shadow: 0 12px 34px rgba(4, 12, 22, 0.46);
    }
    .hero { padding: 16px; }
    .hero h1 { margin: 0; font-size: clamp(24px, 4vw, 34px); }
    .hero p { margin: 8px 0 0; color: var(--sub); font-size: 13px; line-height: 1.7; }
    .badge-row { margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap; }
    .badge {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 12px;
      color: #d7ecff;
      background: rgba(18, 36, 58, 0.72);
    }
    .link-row { margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap; }
    .link {
      text-decoration: none;
      color: #d9edff;
      font-size: 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 10px;
      background: rgba(17, 34, 56, 0.74);
    }
    .role-row { margin-top: 10px; }
    .role-row .seg { margin-top: 4px; }
    .grid {
      margin-top: 12px;
      display: grid;
      grid-template-columns: 1.06fr 0.94fr;
      gap: 10px;
    }
    .card { padding: 12px; }
    .card h2 { margin: 0; font-size: 16px; }
    .note { margin: 6px 0 0; color: var(--sub); font-size: 12px; line-height: 1.6; }
    .field-grid {
      margin-top: 9px;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: 5px;
    }
    .field label {
      font-size: 11px;
      color: var(--sub);
      letter-spacing: 0.3px;
      text-transform: uppercase;
    }
    .field.full { grid-column: span 2; }
    input[type="text"], input[type="file"], select {
      width: 100%;
      border: 1px solid rgba(149, 199, 241, 0.3);
      border-radius: 9px;
      background: rgba(14, 30, 48, 0.86);
      color: var(--ink);
      padding: 8px 10px;
      font-size: 12px;
    }
    input::file-selector-button {
      border: 1px solid rgba(149, 199, 241, 0.34);
      border-radius: 7px;
      background: rgba(25, 52, 83, 0.92);
      color: var(--ink);
      padding: 5px 8px;
      margin-right: 8px;
      cursor: pointer;
    }
    .seg {
      margin-top: 8px;
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .seg button {
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(16, 34, 55, 0.75);
      color: #d6ebff;
      padding: 7px 12px;
      font-size: 12px;
      cursor: pointer;
    }
    .seg button.active {
      background: linear-gradient(145deg, #339eff, #4ac1ff);
      color: #002138;
      border-color: rgba(77, 190, 255, 0.52);
      font-weight: 700;
    }
    .mode-hint {
      margin-top: 6px;
      font-size: 12px;
      color: var(--sub);
      line-height: 1.6;
      border-left: 2px solid rgba(77, 190, 255, 0.6);
      padding-left: 8px;
    }
    .workflow {
      margin-top: 8px;
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 11px;
      color: #d6ebff;
      background: rgba(16, 34, 55, 0.72);
    }
    .pill.done {
      color: #032723;
      background: linear-gradient(145deg, #00ddc3, #44e6b0);
      border-color: rgba(67, 230, 176, 0.56);
      font-weight: 700;
    }
    .btn-row {
      margin-top: 10px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    button.primary {
      border: 0;
      border-radius: 9px;
      padding: 9px 13px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      color: #032723;
      background: linear-gradient(145deg, #00ddc3, #44e6b0);
      box-shadow: 0 8px 18px rgba(0, 205, 167, 0.25);
    }
    button.secondary {
      border: 0;
      border-radius: 9px;
      padding: 9px 13px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      color: #e9f5ff;
      background: linear-gradient(145deg, #2f71bb, #42a8ff);
      box-shadow: 0 8px 18px rgba(65, 166, 255, 0.22);
    }
    button.ghost {
      border: 1px solid var(--line);
      border-radius: 9px;
      padding: 8px 12px;
      font-size: 12px;
      color: #d6ebff;
      cursor: pointer;
      background: rgba(15, 32, 52, 0.7);
    }
    button:disabled {
      opacity: 0.46;
      cursor: not-allowed;
      filter: grayscale(0.18);
    }
    details {
      margin-top: 10px;
      border: 1px dashed rgba(148, 198, 240, 0.35);
      border-radius: 10px;
      padding: 8px;
      background: rgba(12, 26, 42, 0.55);
    }
    details > summary {
      cursor: pointer;
      font-size: 12px;
      color: #cfe5fb;
      font-weight: 700;
      outline: none;
    }
    .kpi-grid {
      margin-top: 8px;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .kpi {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px 10px;
      background: rgba(11, 26, 43, 0.85);
    }
    .kpi .k { margin: 0; font-size: 10px; color: var(--sub); text-transform: uppercase; }
    .kpi .v { margin: 5px 0 0; font-size: 19px; font-weight: 700; font-family: "JetBrains Mono", Consolas, monospace; }
    .ok { color: var(--ok); }
    .warn { color: var(--warn); }
    .bad { color: var(--bad); }
    .list {
      margin: 8px 0 0;
      padding-left: 18px;
      color: #d6eaff;
      font-size: 13px;
      line-height: 1.7;
    }
    .summary-box {
      margin-top: 8px;
      border: 1px solid rgba(148, 198, 240, 0.25);
      border-radius: 10px;
      background: rgba(11, 24, 39, 0.9);
      padding: 9px 10px;
      font-size: 12px;
      color: #d6eaff;
      line-height: 1.6;
    }
    .intel-grid {
      margin-top: 8px;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .intel-card {
      border: 1px solid rgba(148, 198, 240, 0.22);
      border-radius: 10px;
      padding: 8px 10px;
      background: rgba(8, 20, 33, 0.8);
    }
    .intel-card .k { margin: 0; font-size: 10px; color: var(--sub); text-transform: uppercase; }
    .intel-card .v { margin: 5px 0 0; font-size: 16px; font-weight: 700; font-family: "JetBrains Mono", Consolas, monospace; }
    body.role-operator #ops_btn,
    body.role-operator #deep_btn,
    body.role-operator #weekly_btn {
      display: none !important;
    }
    body.role-executive #mode-seg,
    body.role-executive #preset-seg,
    body.role-executive #scene-seg,
    body.role-executive #workflow_row,
    body.role-executive #single-input-wrap,
    body.role-executive #dual-reference-wrap,
    body.role-executive #dual-film-wrap,
    body.role-executive #analyze_btn,
    body.role-executive #full_btn,
    body.role-executive #deep_btn,
    body.role-executive #clear_btn {
      display: none !important;
    }
    .mono {
      margin-top: 8px;
      border: 1px solid rgba(148, 198, 240, 0.2);
      border-radius: 10px;
      background: #061324;
      color: #d8ecff;
      font-family: "JetBrains Mono", Consolas, monospace;
      font-size: 12px;
      line-height: 1.5;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 320px;
      overflow: auto;
      padding: 10px;
    }
    .err {
      margin-top: 8px;
      color: #ffd9df;
      border: 1px solid rgba(255, 98, 121, 0.45);
      border-radius: 10px;
      background: rgba(118, 14, 31, 0.3);
      padding: 8px 10px;
      font-size: 12px;
      display: none;
    }
    @media (max-width: 1040px) {
      .grid { grid-template-columns: 1fr; }
      .stat-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 1320px) {
      .wrap { grid-template-columns: 1fr; }
      .side { display: none; }
    }
    @media (max-width: 640px) {
      .field-grid { grid-template-columns: 1fr; }
      .field.full { grid-column: span 1; }
      .kpi-grid { grid-template-columns: 1fr; }
      .intel-grid { grid-template-columns: 1fr; }
      .stat-strip { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <aside class="side">
      <div class="brand">
        <b>SENIA Elite</b>
        <span>Industrial Intelligence Console</span>
      </div>
      <div class="side-nav">
        <div class="item active">智能工作台</div>
        <div class="item">上传任务流</div>
        <div class="item">模型能力</div>
        <div class="item">风险总览</div>
        <div class="item">系统编排</div>
      </div>
      <div class="side-box">
        <p class="t">System Health</p>
        <p class="v" id="side_health">--</p>
        <div class="health-bar"><span></span></div>
        <p class="d" id="side_health_desc">等待系统状态…</p>
      </div>
      <div class="side-box">
        <p class="t">Risk Radar</p>
        <p class="v" id="side_risk">--</p>
        <p class="d" id="side_risk_desc">等待风险评估…</p>
      </div>
      <div class="side-box">
        <p class="t">Business ROI</p>
        <p class="v" id="side_roi">--</p>
        <p class="d">按真实历史数据自动估算年化收益</p>
      </div>
    </aside>

    <main class="main">
    <section class="hero">
      <h1>SENIA Elite 智能工作台</h1>
      <p>面向一线使用者的简化入口：上传图片后一键得到放行结论、风险解释和下一步动作。完整能力仍保留在高级设置与专业页面。</p>
      <div class="badge-row">
        <span class="badge">Version __APP_VERSION__</span>
        <span class="badge">智能模式：极速 / 平衡 / 高质量</span>
        <span class="badge">完整能力：可一键展开高级设置</span>
      </div>
      <div class="link-row">
        <a class="link" href="/v1/web/executive-dashboard" target="_blank">经营驾驶舱</a>
        <a class="link" href="/v1/web/executive-brief" target="_blank">执行简报</a>
        <a class="link" href="/v1/web/precision-observatory" target="_blank">Precision Observatory</a>
        <a class="link" href="/v1/web/innovation-v3" target="_blank">创新作战看板</a>
        <a class="link" href="/docs" target="_blank">API 文档</a>
      </div>
      <div class="role-row">
        <div class="seg" id="role-seg">
          <button type="button" data-role="operator" class="active">操作员视图</button>
          <button type="button" data-role="supervisor">主管视图</button>
          <button type="button" data-role="executive">老板视图</button>
        </div>
        <div class="mode-hint" id="role_hint">已切换为操作员视图：聚焦拍照、分析与快速放行。</div>
      </div>
    </section>

    <section class="stat-strip">
      <div class="stat-card"><p class="k">今日样本处理</p><p class="v" id="stat_samples">--</p><p class="d" id="stat_samples_delta">--</p></div>
      <div class="stat-card"><p class="k">自动放行率</p><p class="v" id="stat_auto_release">--</p><p class="d" id="stat_auto_release_delta">--</p></div>
      <div class="stat-card"><p class="k">异常召回率</p><p class="v" id="stat_alert_recall">--</p><p class="d" id="stat_alert_recall_delta">--</p></div>
      <div class="stat-card"><p class="k">平均延迟</p><p class="v" id="stat_latency">--</p><p class="d" id="stat_latency_delta">--</p></div>
    </section>

    <section class="grid">
      <div class="card">
        <h2>一键分析流程</h2>
        <p class="note">三步即可使用：选模式 → 选策略 → 上传图片。系统会自动融合相近能力并返回可执行建议。</p>

        <div class="field">
          <label>1) 检测模式</label>
          <div class="seg" id="mode-seg">
            <button type="button" data-mode="single" class="active">单图智能识别</button>
            <button type="button" data-mode="dual">样板-彩膜对比</button>
          </div>
          <div class="mode-hint" id="mode-hint">单图模式适合现场拍照快速抽检，系统自动识别区域并给出结论。</div>
          <div class="workflow" id="workflow_row">
            <span class="pill" id="wf_mode">1. 模式已选</span>
            <span class="pill" id="wf_upload">2. 待上传图片</span>
            <span class="pill" id="wf_run">3. 待执行分析</span>
          </div>
        </div>

        <div class="field-grid">
          <div class="field full" id="single-input-wrap">
            <label>上传现场图（image）</label>
            <input id="single-image" type="file" accept="image/*" />
          </div>
          <div class="field" id="dual-reference-wrap" style="display:none;">
            <label>上传样板图（reference）</label>
            <input id="dual-reference" type="file" accept="image/*" />
          </div>
          <div class="field" id="dual-film-wrap" style="display:none;">
            <label>上传彩膜图（film）</label>
            <input id="dual-film" type="file" accept="image/*" />
          </div>
        </div>
        <div class="summary-box" id="capture_summary">拍摄质量：等待上传图片。</div>

        <div class="field">
          <label>2) 智能策略</label>
          <div class="seg" id="preset-seg">
            <button type="button" data-preset="fast">极速放行</button>
            <button type="button" data-preset="balanced" class="active">平衡推荐</button>
            <button type="button" data-preset="quality">高质量优先</button>
          </div>
          <div class="mode-hint" id="preset_hint">当前策略：平衡推荐（默认）。</div>
        </div>

        <div class="field">
          <label>3) 场景模板（可选）</label>
          <div class="seg" id="scene-seg">
            <button type="button" data-scene="default" class="active">标准室内</button>
            <button type="button" data-scene="window">靠窗老化</button>
            <button type="button" data-scene="outdoor">户外严苛</button>
          </div>
          <div class="mode-hint" id="scene_hint">模板会自动设置材质、环境和推荐策略。</div>
        </div>

        <div class="field-grid">
          <div class="field">
            <label>材质（快速）</label>
            <select id="material">
              <option value="pvc_film">pvc_film</option>
              <option value="pet_film">pet_film</option>
              <option value="melamine">melamine</option>
              <option value="hpl">hpl</option>
              <option value="uv_coating">uv_coating</option>
            </select>
          </div>
          <div class="field">
            <label>使用环境（快速）</label>
            <select id="environment">
              <option value="indoor_normal">indoor_normal</option>
              <option value="indoor_window">indoor_window</option>
              <option value="indoor_humid">indoor_humid</option>
              <option value="outdoor_covered">outdoor_covered</option>
              <option value="outdoor_exposed">outdoor_exposed</option>
            </select>
          </div>
        </div>

        <details class="role-advanced">
          <summary>高级设置（完整能力与专家参数）</summary>
          <div class="field-grid">
            <div class="field">
              <label>客户 ID（可选）</label>
              <input id="customer_id" type="text" placeholder="例如 CUST-001" />
            </div>
            <div class="field">
              <label>客户层级（可选）</label>
              <select id="customer_tier">
                <option value="">auto / none</option>
                <option value="vip">vip</option>
                <option value="standard">standard</option>
                <option value="growth">growth</option>
                <option value="economy">economy</option>
              </select>
            </div>
            <div class="field full">
              <label>API Key（可选，开启鉴权时填写）</label>
              <input id="api_key" type="text" placeholder="Header: x-api-key" />
            </div>
            <div class="field full">
              <label>历史库路径（经营体检用）</label>
              <input id="history_db_path" type="text" placeholder="自动读取系统默认值" />
            </div>
            <div class="field">
              <label>profile</label>
              <select id="profile">
                <option value="auto">auto</option>
                <option value="solid">solid</option>
                <option value="wood">wood</option>
                <option value="stone">stone</option>
                <option value="metallic">metallic</option>
                <option value="high_gloss">high_gloss</option>
              </select>
            </div>
            <div class="field">
              <label>grid</label>
              <input id="grid" type="text" value="6x8" />
            </div>
            <div class="field">
              <label>创新引擎</label>
              <select id="with_innovation_engine"><option value="true">true</option><option value="false">false</option></select>
            </div>
            <div class="field">
              <label>决策中心</label>
              <select id="with_decision_center"><option value="true">true</option><option value="false">false</option></select>
            </div>
            <div class="field">
              <label>工艺建议</label>
              <select id="with_process_advice"><option value="true">true</option><option value="false">false</option></select>
            </div>
            <div class="field">
              <label>HTML 报告</label>
              <select id="html_report"><option value="true">true</option><option value="false">false</option></select>
            </div>
          </div>
        </details>

        <div class="btn-row">
          <button class="primary" id="analyze_btn" type="button">一键智能分析</button>
          <button class="primary" id="full_btn" type="button">全自动流程</button>
          <button class="secondary" id="next_btn" type="button">推荐下一步</button>
          <button class="secondary" id="ops_btn" type="button">一键经营体检</button>
          <button class="secondary" id="weekly_btn" type="button">老板周报卡片</button>
          <button class="secondary" id="deep_btn" type="button">一键创新深度分析</button>
          <button class="ghost" id="clear_btn" type="button">清空结果</button>
        </div>
        <div class="err" id="error_box"></div>
      </div>

      <div class="card">
        <h2>结果面板（自动融合）</h2>
        <p class="note">相似能力会自动融合为统一输出，不需要用户理解底层模块细节。</p>

        <div class="kpi-grid">
          <div class="kpi"><p class="k">放行结论</p><p class="v" id="kpi_pass">--</p></div>
          <div class="kpi"><p class="k">置信度</p><p class="v" id="kpi_conf">--</p></div>
          <div class="kpi"><p class="k">决策码</p><p class="v" id="kpi_decision">--</p></div>
          <div class="kpi"><p class="k">风险概率</p><p class="v" id="kpi_risk">--</p></div>
        </div>
        <div class="intel-grid">
          <div class="intel-card"><p class="k">稳定指数</p><p class="v" id="kpi_stability">--</p></div>
          <div class="intel-card"><p class="k">证据条数</p><p class="v" id="kpi_evidence">--</p></div>
          <div class="intel-card"><p class="k">风险依据</p><p class="v" id="kpi_risk_basis">--</p></div>
        </div>

        <div id="de_metrics_box" style="display:none;margin-top:8px;border:1px solid rgba(148,198,240,.24);border-radius:10px;padding:9px 10px;background:rgba(8,20,33,.8);"></div>

        <div class="field" style="margin-top:8px;">
          <label>风险与证据</label>
          <ul class="list" id="evidence_list">
            <li>等待分析结果…</li>
          </ul>
        </div>

        <div class="field" style="margin-top:8px;">
          <label>系统建议动作</label>
          <ul class="list" id="actions_list">
            <li>等待分析结果…</li>
          </ul>
        </div>
        <div class="summary-box" id="exec_summary">系统摘要：等待分析结果。</div>

        <div class="btn-row">
          <a id="report_link" class="link" href="#" target="_blank" style="display:none;">打开 HTML 报告</a>
          <a class="link" href="/v1/innovation/manifest" target="_blank">能力清单</a>
          <a class="link" href="/v1/system/status" target="_blank">系统状态</a>
        </div>
        <details class="role-json">
          <summary>查看原始 JSON（高级）</summary>
          <pre class="mono" id="result_json">{"status":"ready"}</pre>
        </details>
      </div>
    </section>
    </main>
  </div>

  <script>
    const q = (s) => document.querySelector(s);
    const state = {
      role: "operator",
      mode: "single",
      preset: "balanced",
      scene: "default",
      lastAnalyze: null,
      lastWeeklyCard: null,
      nextBestAction: null,
      defaultHistoryDb: "",
      userPresetLocked: false,
    };

    function toBool(v) { return String(v).toLowerCase() === "true"; }
    function authHeaders() {
      const key = (q("#api_key").value || "").trim();
      if (!key) return {};
      return { "x-api-key": key };
    }
    function setError(msg) {
      const box = q("#error_box");
      if (!msg) {
        box.style.display = "none";
        box.textContent = "";
        return;
      }
      box.style.display = "block";
      box.textContent = msg;
    }
    function num(v, d = NaN) {
      const n = Number(v);
      return Number.isFinite(n) ? n : d;
    }
    function fmtPct(v) {
      const n = num(v);
      if (!Number.isFinite(n)) return "--";
      return (n * 100).toFixed(1) + "%";
    }
    function fmtNum(v, digits = 1) {
      const n = num(v);
      if (!Number.isFinite(n)) return "--";
      return n.toFixed(digits);
    }
    function fmtInt(v) {
      const n = Math.round(num(v));
      if (!Number.isFinite(n)) return "--";
      return n.toLocaleString();
    }
    function setClassByLevel(el, level) {
      el.classList.remove("ok", "warn", "bad");
      if (level === "ok") el.classList.add("ok");
      if (level === "warn") el.classList.add("warn");
      if (level === "bad") el.classList.add("bad");
    }
    function syncActionButtons() {
      const deep = q("#deep_btn");
      const full = q("#full_btn");
      const next = q("#next_btn");
      const weekly = q("#weekly_btn");
      if (deep) deep.disabled = !state.lastAnalyze;
      if (full) full.disabled = !hasRequiredUploads();
      if (next) {
        const hasDb = Boolean((q("#history_db_path").value || "").trim() || state.defaultHistoryDb);
        const ready = state.role === "executive"
          ? true
          : (hasRequiredUploads() || Boolean(state.lastAnalyze) || hasDb);
        next.disabled = !ready;
      }
      if (weekly) {
        const hasDb = Boolean((q("#history_db_path").value || "").trim() || state.defaultHistoryDb);
        weekly.disabled = state.role === "operator" || !hasDb;
      }
    }
    function applyRole(role, persist = true) {
      const roleSafe = ["operator", "supervisor", "executive"].includes(role) ? role : "operator";
      state.role = roleSafe;
      document.body.classList.remove("role-operator", "role-supervisor", "role-executive");
      document.body.classList.add(`role-${roleSafe}`);
      q("#role-seg").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.role === roleSafe));
      const hint = roleSafe === "operator"
        ? "已切换为操作员视图：聚焦拍照、分析与快速放行。"
        : roleSafe === "supervisor"
          ? "已切换为主管视图：查看分析、经营体检和深度创新。"
          : "已切换为老板视图：聚焦经营状态与决策结论。";
      q("#role_hint").textContent = hint;
      if (roleSafe !== "supervisor") {
        const rawPanel = q("details.role-json");
        if (rawPanel) rawPanel.open = false;
      }
      if (roleSafe === "operator") {
        const adv = q("details.role-advanced");
        if (adv) adv.open = false;
      }
      if (persist) saveQuickSettings();
      syncActionButtons();
      fetchNextBestAction();
    }
    function setSummary(text) {
      const el = q("#exec_summary");
      if (el) el.textContent = `System Summary: ${text}`;
    }
    function buildOpsQuery(windowValue = "200", dbPathOverride = "") {
      const dbPath = (dbPathOverride || q("#history_db_path").value || "").trim() || state.defaultHistoryDb;
      const params = new URLSearchParams({ window: String(windowValue || "200") });
      if (dbPath) params.set("db_path", dbPath);
      const line = (q("#customer_id").value || "").trim();
      if (line) params.set("line_id", line);
      return params;
    }
    function updateNextActionUI(plan) {
      const btn = q("#next_btn");
      if (!btn) return;
      const rec = plan?.recommended_action || {};
      const code = String(rec?.code || "").trim();
      const labels = {
        RUN_OPS_CHECK: "Smart Next: Ops Check",
        DEEP_INNOVATION_REVIEW: "Smart Next: Deep Innovation",
        EXECUTIVE_WEEKLY_CARD: "Smart Next: Weekly Card",
        HOLD_AND_ESCALATE: "Smart Next: Escalate",
        MAINTAIN_MONITOR: "Smart Next: Monitor",
      };
      btn.textContent = labels[code] || rec?.button_label || "Smart Next";
      const reasons = Array.isArray(rec?.reasons) ? rec.reasons.filter(Boolean) : [];
      if (!state.lastAnalyze && reasons.length) {
        q("#actions_list").innerHTML = reasons.slice(0, 4).map((x) => `<li>${x}</li>`).join("");
      }
    }
    async function fetchNextBestAction(force = false) {
      try {
        const query = buildOpsQuery("200");
        query.set("weekly_window", "500");
        query.set("ui_role", state.role || "operator");
        const plan = await apiCall("GET", "/v1/system/next-best-action?" + query.toString());
        state.nextBestAction = plan;
        updateNextActionUI(plan);
        return plan;
      } catch (e) {
        if (force) setError(e?.message || String(e));
        return null;
      }
    }
    function hasRequiredUploads() {
      if (state.mode === "single") return Boolean(q("#single-image").files?.[0]);
      return Boolean(q("#dual-reference").files?.[0] && q("#dual-film").files?.[0]);
    }
    function setWorkflowPill(id, done, label) {
      const el = q(id);
      if (!el) return;
      el.classList.toggle("done", Boolean(done));
      if (label) el.textContent = label;
    }
    function updateWorkflowStatus() {
      setWorkflowPill("#wf_mode", true, "1. 模式已选");
      setWorkflowPill("#wf_upload", hasRequiredUploads(), hasRequiredUploads() ? "2. 图片已就绪" : "2. 待上传图片");
      setWorkflowPill("#wf_run", Boolean(state.lastAnalyze), state.lastAnalyze ? "3. 已完成分析" : "3. 待执行分析");
      syncActionButtons();
    }
    function saveQuickSettings() {
      const payload = {
        role: state.role,
        mode: state.mode,
        preset: state.preset,
        scene: state.scene,
        material: q("#material").value,
        environment: q("#environment").value,
        profile: q("#profile").value,
        grid: q("#grid").value,
        history_db_path: q("#history_db_path").value,
      };
      try {
        localStorage.setItem("senia_elite_home_v2", JSON.stringify(payload));
      } catch (_) {
      }
    }
    function restoreQuickSettings() {
      try {
        const raw = localStorage.getItem("senia_elite_home_v2");
        if (!raw) return;
        const cfg = JSON.parse(raw);
        if (cfg?.role) state.role = cfg.role;
        if (cfg?.mode === "dual" || cfg?.mode === "single") state.mode = cfg.mode;
        if (cfg?.material) q("#material").value = cfg.material;
        if (cfg?.environment) q("#environment").value = cfg.environment;
        if (cfg?.profile) q("#profile").value = cfg.profile;
        if (cfg?.grid) q("#grid").value = cfg.grid;
        if (cfg?.history_db_path) q("#history_db_path").value = cfg.history_db_path;
        if (cfg?.scene) state.scene = cfg.scene;
        if (cfg?.preset) {
          state.userPresetLocked = true;
          applyPreset(cfg.preset, true);
        }
      } catch (_) {
      }
    }

    function syncModeUI() {
      const single = state.mode === "single";
      q("#single-input-wrap").style.display = single ? "" : "none";
      q("#dual-reference-wrap").style.display = single ? "none" : "";
      q("#dual-film-wrap").style.display = single ? "none" : "";
      q("#mode-hint").textContent = single
        ? "单图模式适合现场拍照快速抽检，系统自动识别区域并给出结论。"
        : "双图模式适合样板和彩膜的标准化比对，结果更稳定、可追溯。";
      q("#mode-seg").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.mode === state.mode));
      updateWorkflowStatus();
      refreshCaptureAssessment();
      saveQuickSettings();
    }

    function applyPreset(preset, lockedByUser = false) {
      state.preset = preset;
      if (lockedByUser) state.userPresetLocked = true;
      q("#preset-seg").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.preset === preset));
      if (preset === "fast") {
        q("#with_innovation_engine").value = "false";
        q("#with_decision_center").value = "true";
        q("#with_process_advice").value = "false";
        q("#html_report").value = "false";
        q("#preset_hint").textContent = "当前策略：极速放行（优先速度，自动关闭部分深度模块）。";
      } else if (preset === "balanced") {
        q("#with_innovation_engine").value = "true";
        q("#with_decision_center").value = "true";
        q("#with_process_advice").value = "true";
        q("#html_report").value = "true";
        q("#preset_hint").textContent = "当前策略：平衡推荐（速度与准确度均衡，默认建议）。";
      } else {
        q("#with_innovation_engine").value = "true";
        q("#with_decision_center").value = "true";
        q("#with_process_advice").value = "true";
        q("#html_report").value = "true";
        if (!q("#customer_tier").value) q("#customer_tier").value = "vip";
        q("#preset_hint").textContent = "当前策略：高质量优先（更严格，适合高风险与高价值客户）。";
      }
      saveQuickSettings();
    }

    function applyScene(scene) {
      state.scene = scene;
      q("#scene-seg").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.scene === scene));
      if (scene === "window") {
        q("#material").value = "pvc_film";
        q("#environment").value = "indoor_window";
        q("#scene_hint").textContent = "模板：靠窗老化。自动切到 indoor_window，并建议高质量优先。";
        if (!state.userPresetLocked) applyPreset("quality");
      } else if (scene === "outdoor") {
        q("#material").value = "pet_film";
        q("#environment").value = "outdoor_exposed";
        q("#scene_hint").textContent = "模板：户外严苛。自动切到 outdoor_exposed，并建议高质量优先。";
        if (!state.userPresetLocked) applyPreset("quality");
      } else {
        q("#material").value = "pvc_film";
        q("#environment").value = "indoor_normal";
        q("#scene_hint").textContent = "模板：标准室内。适用于大部分常规生产。";
        if (!state.userPresetLocked) applyPreset("balanced");
      }
      saveQuickSettings();
    }

    async function apiCall(method, path, payload = null) {
      const headers = { ...authHeaders() };
      const opts = { method, headers };
      if (payload !== null) {
        headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(payload);
      }
      const resp = await fetch(path, opts);
      const data = await resp.json();
      if (!resp.ok) throw new Error(data?.detail || JSON.stringify(data));
      return data;
    }

    function buildInnovationContext() {
      return {
        customer_id: (q("#customer_id").value || "").trim() || null,
        material: q("#material").value || "pvc_film",
        sample_material: "melamine",
        film_material: q("#material").value || "pvc_film",
        environment: q("#environment").value || "indoor_normal",
      };
    }
    async function readImageInfo(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const img = new Image();
          img.onload = () => {
            const w = Math.max(1, Math.min(160, img.width));
            const h = Math.max(1, Math.round((img.height * w) / Math.max(1, img.width)));
            const canvas = document.createElement("canvas");
            canvas.width = w;
            canvas.height = h;
            const ctx = canvas.getContext("2d");
            let brightness = 128;
            if (ctx) {
              ctx.drawImage(img, 0, 0, w, h);
              const pixels = ctx.getImageData(0, 0, w, h).data;
              let sum = 0;
              for (let i = 0; i < pixels.length; i += 4) {
                sum += 0.2126 * pixels[i] + 0.7152 * pixels[i + 1] + 0.0722 * pixels[i + 2];
              }
              brightness = sum / Math.max(1, pixels.length / 4);
            }
            resolve({ width: img.width, height: img.height, size: file.size, brightness });
          };
          img.onerror = () => reject(new Error(`无法读取图片：${file.name}`));
          img.src = String(reader.result || "");
        };
        reader.onerror = () => reject(new Error(`无法读取图片：${file.name}`));
        reader.readAsDataURL(file);
      });
    }
    async function refreshCaptureAssessment() {
      const box = q("#capture_summary");
      if (!box) return;
      const files = [];
      if (state.mode === "single") {
        const f = q("#single-image").files?.[0];
        if (f) files.push({ name: "现场图", file: f });
      } else {
        const ref = q("#dual-reference").files?.[0];
        const film = q("#dual-film").files?.[0];
        if (ref) files.push({ name: "样板图", file: ref });
        if (film) files.push({ name: "彩膜图", file: film });
      }
      if (!files.length) {
        box.textContent = "拍摄质量：等待上传图片。";
        return;
      }
      try {
        const notes = [];
        for (const item of files) {
          const meta = await readImageInfo(item.file);
          let tag = "良好";
          if (meta.width < 900 || meta.height < 900) tag = "建议重拍更清晰";
          if (meta.brightness < 45) tag = "偏暗建议补光";
          if (meta.brightness > 220) tag = "偏亮建议降曝光";
          notes.push(`${item.name} ${meta.width}x${meta.height} / 亮度${meta.brightness.toFixed(0)} / ${tag}`);
        }
        box.textContent = `拍摄质量：${notes.join("；")}`;
      } catch (_) {
        box.textContent = "拍摄质量：无法读取上传图片，请重新上传。";
      }
    }
    async function checkUploadsQuality() {
      const minW = 500;
      const minH = 500;
      const checks = [];
      if (state.mode === "single") {
        const f = q("#single-image").files?.[0];
        if (f) checks.push({ tag: "现场图", file: f });
      } else {
        const ref = q("#dual-reference").files?.[0];
        const film = q("#dual-film").files?.[0];
        if (ref) checks.push({ tag: "样板图", file: ref });
        if (film) checks.push({ tag: "彩膜图", file: film });
      }
      for (const item of checks) {
        const meta = await readImageInfo(item.file);
        if (meta.width < minW || meta.height < minH) {
          throw new Error(`${item.tag}分辨率过低（${meta.width}x${meta.height}），建议至少 ${minW}x${minH}。`);
        }
      }
    }

    function buildAnalyzeForm() {
      const fd = new FormData();
      const profile = (q("#profile").value || "auto").trim();
      const grid = (q("#grid").value || "6x8").trim();
      const customerId = (q("#customer_id").value || "").trim();
      const customerTier = (q("#customer_tier").value || "").trim();
      const innovationContext = buildInnovationContext();

      fd.append("profile", profile);
      fd.append("grid", grid);
      fd.append("include_report", "false");
      fd.append("with_innovation_engine", q("#with_innovation_engine").value);
      fd.append("with_decision_center", q("#with_decision_center").value);
      fd.append("with_process_advice", q("#with_process_advice").value);
      fd.append("html_report", q("#html_report").value);
      fd.append("innovation_context_json", JSON.stringify(innovationContext));
      if (customerId) fd.append("customer_id", customerId);
      if (customerTier) fd.append("customer_tier", customerTier);

      if (state.mode === "single") {
        const f = q("#single-image").files?.[0];
        if (!f) throw new Error("请先上传现场图。");
        fd.append("image", f);
        return { path: "/v1/web/analyze/single-upload", formData: fd };
      }
      const ref = q("#dual-reference").files?.[0];
      const film = q("#dual-film").files?.[0];
      if (!ref || !film) throw new Error("请先上传样板图和彩膜图。");
      fd.append("reference", ref);
      fd.append("film", film);
      return { path: "/v1/web/analyze/dual-upload", formData: fd };
    }

    function buildActions(data) {
      const actions = [];
      if (data?.pass === false) actions.push("建议先复拍或人工复核，再执行调色。");
      const conf = num(data?.confidence);
      if (Number.isFinite(conf) && conf < 0.65) actions.push("当前置信度偏低，优先优化拍摄光照与对焦。");
      const dc = data?.decision_center || {};
      if (dc?.decision_code === "RECAPTURE_REQUIRED") actions.push("系统判定需重拍，建议按重拍提示执行。");
      if (dc?.decision_code === "HOLD_AND_ESCALATE") actions.push("建议停线排查并通知质量负责人。");
      const ie = data?.innovation_engine || {};
      if (ie?.drift_urgency === "high" || ie?.drift_urgency === "critical") actions.push("检测到漂移风险，建议立刻做批次隔离。");
      if (ie?.aging_warranty_risk === "high") actions.push("老化风险偏高，建议评估材质或环境策略。");
      if (!actions.length) actions.push("当前状态稳定，建议继续按当前参数批量执行。");
      return actions.slice(0, 6);
    }

    function buildEvidence(data) {
      const ev = [];
      const dc = data?.decision_center || {};
      const ie = data?.innovation_engine || {};
      const pa = data?.process_advice || {};
      if (dc?.decision_code) ev.push(`决策中心输出码：${dc.decision_code}`);
      const rp = num(dc?.risk_probability);
      if (Number.isFinite(rp)) ev.push(`风险概率估计：${fmtPct(rp)}`);
      if (pa?.risk_level) ev.push(`工艺风险等级：${String(pa.risk_level)}`);
      if (ie?.drift_urgency) ev.push(`漂移紧急度：${String(ie.drift_urgency)}`);
      if (ie?.aging_warranty_risk) ev.push(`老化风险：${String(ie.aging_warranty_risk)}`);
      const weekly = data?.weekly_card || {};
      if (weekly?.risk?.warning_level) ev.push(`周报预警等级：${String(weekly.risk.warning_level)}`);
      const topRecs = Array.isArray(weekly?.recommendations) ? weekly.recommendations : [];
      if (topRecs.length) ev.push(`策略建议：${String(topRecs[0])}`);
      if (!ev.length) ev.push("暂无可解释证据，建议先执行一次分析。");
      return ev.slice(0, 6);
    }

    function renderAnalyze(data) {
      const pass = data?.pass;
      const conf = num(data?.confidence);
      const dc = data?.decision_center || {};
      const risk = num(dc?.risk_probability);

      const passEl = q("#kpi_pass");
      passEl.textContent = pass === true ? "PASS" : pass === false ? "HOLD" : "--";
      setClassByLevel(passEl, pass === true ? "ok" : pass === false ? "bad" : "warn");

      const confEl = q("#kpi_conf");
      confEl.textContent = Number.isFinite(conf) ? fmtPct(conf) : "--";
      setClassByLevel(confEl, Number.isFinite(conf) ? (conf >= 0.8 ? "ok" : conf >= 0.65 ? "warn" : "bad") : "warn");

      const decisionEl = q("#kpi_decision");
      decisionEl.textContent = dc?.decision_code || "--";
      const d = String(dc?.decision_code || "");
      setClassByLevel(decisionEl, d === "AUTO_RELEASE" ? "ok" : d === "MANUAL_REVIEW" ? "warn" : "bad");

      const riskEl = q("#kpi_risk");
      riskEl.textContent = Number.isFinite(risk) ? fmtPct(risk) : "--";
      setClassByLevel(riskEl, Number.isFinite(risk) ? (risk <= 0.35 ? "ok" : risk <= 0.65 ? "warn" : "bad") : "warn");

      const stability = Number.isFinite(conf)
        ? Math.max(0, Math.min(100, ((conf * 100) * 0.7) + ((1 - (Number.isFinite(risk) ? risk : 0.5)) * 30)))
        : NaN;
      q("#kpi_stability").textContent = Number.isFinite(stability) ? `${fmtNum(stability, 1)}` : "--";

      // Render delta-E color metrics panel
      const summary = (data?.result || {}).summary || {};
      const avgDE = num(summary.avg_delta_e00 ?? summary.median_avg_delta_e00);
      const p95DE = num(summary.p95_delta_e00 ?? summary.median_p95_delta_e00);
      const maxDE = num(summary.max_delta_e00 ?? summary.median_max_delta_e00);
      const dL = num(summary.dL ?? summary.median_dL);
      const dC = num(summary.dC ?? summary.median_dC);
      const dH = num(summary.dH_deg ?? summary.median_dH_deg);
      const avgTarget = num((data?.profile?.targets_used || data?.profile?.targets || {}).avg_delta_e00);
      const deColor = (v, tgt) => {
        if (!Number.isFinite(v) || !Number.isFinite(tgt)) return "";
        return v <= tgt ? "color:var(--ok)" : v <= tgt * 1.5 ? "color:var(--warn)" : "color:var(--bad)";
      };
      const deBox = q("#de_metrics_box");
      if (deBox && Number.isFinite(avgDE)) {
        deBox.style.display = "";
        deBox.innerHTML = `
          <p class="t" style="margin:0 0 6px;font-size:10px;color:var(--sub);text-transform:uppercase;letter-spacing:.3px;">色差 ΔE₀₀ 详情</p>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;">
            <div style="border:1px solid var(--line);border-radius:8px;padding:6px 8px;background:rgba(8,20,33,.8);">
              <p style="margin:0;font-size:10px;color:var(--sub);">AVG</p>
              <p style="margin:4px 0 0;font-size:17px;font-weight:700;font-family:'JetBrains Mono',monospace;${deColor(avgDE, avgTarget)}">${fmtNum(avgDE, 3)}</p>
            </div>
            <div style="border:1px solid var(--line);border-radius:8px;padding:6px 8px;background:rgba(8,20,33,.8);">
              <p style="margin:0;font-size:10px;color:var(--sub);">P95</p>
              <p style="margin:4px 0 0;font-size:17px;font-weight:700;font-family:'JetBrains Mono',monospace;">${fmtNum(p95DE, 3)}</p>
            </div>
            <div style="border:1px solid var(--line);border-radius:8px;padding:6px 8px;background:rgba(8,20,33,.8);">
              <p style="margin:0;font-size:10px;color:var(--sub);">MAX</p>
              <p style="margin:4px 0 0;font-size:17px;font-weight:700;font-family:'JetBrains Mono',monospace;">${fmtNum(maxDE, 3)}</p>
            </div>
          </div>
          <p style="margin:6px 0 0;font-size:11px;color:var(--sub);">
            dL&nbsp;<b style="color:var(--ink)">${fmtNum(dL,2)}</b>&nbsp;&nbsp;
            dC&nbsp;<b style="color:var(--ink)">${fmtNum(dC,2)}</b>&nbsp;&nbsp;
            dH&nbsp;<b style="color:var(--ink)">${fmtNum(dH,1)}°</b>
            ${Number.isFinite(avgTarget) ? `&nbsp;&nbsp;<span style="opacity:.55">目标 ≤ ${fmtNum(avgTarget,2)}</span>` : ""}
          </p>`;
      } else if (deBox) {
        deBox.style.display = "none";
      }

      const actions = buildActions(data);
      q("#actions_list").innerHTML = actions.map((x) => `<li>${x}</li>`).join("");
      const evidences = buildEvidence(data);
      q("#evidence_list").innerHTML = evidences.map((x) => `<li>${x}</li>`).join("");
      q("#kpi_evidence").textContent = String(evidences.length);
      q("#kpi_risk_basis").textContent = evidences.length ? evidences[0].slice(0, 18) : "--";
      const summaryText = pass === true
        ? `建议放行，决策码 ${dc?.decision_code || "--"}，风险 ${Number.isFinite(risk) ? fmtPct(risk) : "--"}。`
        : `建议拦截/复核，决策码 ${dc?.decision_code || "--"}，风险 ${Number.isFinite(risk) ? fmtPct(risk) : "--"}。`;
      setSummary(summaryText);

      const htmlPath = data?.html_path;
      const reportLink = q("#report_link");
      if (htmlPath) {
        reportLink.style.display = "";
        reportLink.href = "/v1/report/html?path=" + encodeURIComponent(htmlPath);
      } else {
        reportLink.style.display = "none";
        reportLink.href = "#";
      }
      q("#result_json").textContent = JSON.stringify(data, null, 2);
      updateWorkflowStatus();
      refreshCockpitStats();
    }

    const MAX_UPLOAD_BYTES_SMART = 20 * 1024 * 1024;
    const ALLOWED_IMG_RE = /\.(jpe?g|png|bmp|tiff?|webp|gif)$/i;

    function validateSmartFiles() {
      const inputs = ["#single-image", "#dual-reference", "#dual-film"];
      for (const sel of inputs) {
        const el = q(sel);
        if (!el) continue;
        const f = el.files?.[0];
        if (!f) continue;
        if (f.size > MAX_UPLOAD_BYTES_SMART) {
          return `文件 "${f.name}" 超过 20MB 上传限制（当前 ${(f.size/1024/1024).toFixed(1)}MB）`;
        }
        if (!ALLOWED_IMG_RE.test(f.name)) {
          return `文件 "${f.name}" 格式不支持，请上传 JPEG/PNG/BMP/TIFF/WebP`;
        }
      }
      return null;
    }

    async function runAnalyze() {
      setError("");
      const fileErr = validateSmartFiles();
      if (fileErr) { setError(fileErr); return null; }
      const btn = q("#analyze_btn");
      btn.disabled = true;
      btn.textContent = "分析中…";
      let result = null;
      try {
        await checkUploadsQuality();
        const req = buildAnalyzeForm();
        const resp = await fetch(req.path, { method: "POST", headers: authHeaders(), body: req.formData });
        const data = await resp.json();
        if (!resp.ok) {
          const msg = resp.status === 415
            ? "图片格式不支持，请上传 JPEG/PNG/BMP/TIFF/WebP"
            : (data?.detail || "分析失败");
          throw new Error(msg);
        }
        state.lastAnalyze = data;
        renderAnalyze(data);
        syncActionButtons();
        result = data;
      } catch (e) {
        setError(e?.message || String(e));
      } finally {
        btn.disabled = false;
        btn.textContent = "一键智能分析";
      }
      return result;
    }

    async function runOpsCheck() {
      setError("");
      const btn = q("#ops_btn");
      btn.disabled = true;
      btn.textContent = "体检中…";
      let summary = null;
      try {
        const dbPath = (q("#history_db_path").value || "").trim() || state.defaultHistoryDb;
        if (!dbPath) throw new Error("未找到历史库路径，请先填写。");
        const query = buildOpsQuery("120", dbPath);
        const [brief, ew] = await Promise.all([
          apiCall("GET", "/v1/system/executive-brief?" + query.toString()),
          apiCall("GET", "/v1/history/early-warning?" + query.toString()),
        ]);
        summary = {
          mode: "ops_check",
          go_no_go: brief?.decision?.summary || "--",
          grade: brief?.decision?.grade || "--",
          score_0_100: brief?.decision?.score_0_100,
          risk_level_30d: ew?.risk_level,
          complaint_prob_30d: ew?.complaint_prob_30d,
          recommendations: brief?.recommendations || [],
          reasons: brief?.reasons || [],
        };
        renderAnalyze({
          pass: summary.go_no_go === "GO",
          confidence: null,
          decision_center: { decision_code: summary.go_no_go, risk_probability: summary.complaint_prob_30d },
          innovation_engine: {},
          html_path: state.lastAnalyze?.html_path || null,
          ops_summary: summary,
        });
        setSummary(`经营体检完成：${summary.go_no_go}（等级 ${summary.grade || "--"}）。`);
      } catch (e) {
        setError(e?.message || String(e));
      } finally {
        btn.disabled = false;
        btn.textContent = "一键经营体检";
      }
      return summary;
    }

    async function runWeeklyCard() {
      setError("");
      const btn = q("#weekly_btn");
      if (btn) {
        btn.disabled = true;
        btn.textContent = "生成中…";
      }
      let card = null;
      try {
        const dbPath = (q("#history_db_path").value || "").trim() || state.defaultHistoryDb;
        if (!dbPath) throw new Error("未找到历史库路径，请先填写。");
        const query = buildOpsQuery("500", dbPath);
        card = await apiCall("GET", "/v1/system/executive-weekly-card?" + query.toString());
        state.lastWeeklyCard = card;
        const score = num(card?.decision?.score_0_100);
        const go = Boolean(card?.decision?.go_live_recommended);
        const riskIndex = num(card?.risk?.risk_index_0_100);
        const recommendations = Array.isArray(card?.recommendations) ? card.recommendations : [];
        renderAnalyze({
          pass: go,
          confidence: Number.isFinite(score) ? score / 100 : null,
          decision_center: {
            decision_code: card?.decision?.summary || card?.decision?.grade || "--",
            risk_probability: Number.isFinite(riskIndex) ? (riskIndex / 100) : null,
          },
          innovation_engine: {},
          html_path: state.lastAnalyze?.html_path || null,
          weekly_card: card,
        });
        if (recommendations.length) {
          q("#actions_list").innerHTML = recommendations.slice(0, 6).map((x) => `<li>${x}</li>`).join("");
        }
        const roi = num(card?.roi?.annual_saving_cny);
        const scoreText = Number.isFinite(score) ? score.toFixed(1) : "--";
        const riskText = Number.isFinite(riskIndex) ? riskIndex.toFixed(1) : "--";
        const roiText = Number.isFinite(roi) ? `¥${roi.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "--";
        setSummary(`老板周报：${card?.decision?.summary || "--"} / 评分${scoreText} / 风险${riskText} / 年化收益${roiText}。`);
        q("#result_json").textContent = JSON.stringify({ ...(state.lastAnalyze || {}), weekly_card: card }, null, 2);
      } catch (e) {
        setError(e?.message || String(e));
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = "老板周报卡片";
        }
        syncActionButtons();
      }
      return card;
    }

    async function runDeepInnovation() {
      setError("");
      const btn = q("#deep_btn");
      btn.disabled = true;
      btn.textContent = "分析中…";
      let merged = null;
      try {
        const reportPath = state.lastAnalyze?.report_path;
        if (!reportPath) throw new Error("请先执行一次智能分析，再做深度创新分析。");
        const payload = {
          report_path: reportPath,
          context: buildInnovationContext(),
        };
        const data = await apiCall("POST", "/v1/analyze/full-innovation", payload);
        merged = {
          ...(state.lastAnalyze || {}),
          deep_innovation: data,
        };
        state.lastAnalyze = merged;
        setSummary("已完成深度创新分析，建议结合老化风险与墨量处方复核放行策略。");
        q("#result_json").textContent = JSON.stringify(merged, null, 2);
        updateWorkflowStatus();
      } catch (e) {
        setError(e?.message || String(e));
      } finally {
        btn.disabled = false;
        btn.textContent = "一键创新深度分析";
      }
      return merged;
    }

    async function runAutoPilot() {
      setError("");
      const btn = q("#full_btn");
      btn.disabled = true;
      btn.textContent = "全流程执行中…";
      try {
        const analyzed = await runAnalyze();
        if (!analyzed) return;
        if (analyzed?.report_path) await runDeepInnovation();
        setSummary("全自动流程完成：已执行智能分析 + 深度创新。可按需继续经营体检。");
      } catch (e) {
        setError(e?.message || String(e));
      } finally {
        btn.disabled = false;
        btn.textContent = "全自动流程";
      }
    }

    async function runRecommendedNext() {
      setError("");
      const btn = q("#next_btn");
      btn.disabled = true;
      btn.textContent = "Executing...";
      try {
        const plan = (await fetchNextBestAction(true)) || state.nextBestAction || {};
        const rec = plan?.recommended_action || {};
        const code = String(rec?.code || "").trim();

        if (code === "EXECUTIVE_WEEKLY_CARD") {
          const weekly = await runWeeklyCard();
          if (!weekly) await runOpsCheck();
          setSummary(`Smart action executed: ${code}`);
          return;
        }

        if (code === "DEEP_INNOVATION_REVIEW") {
          if (!state.lastAnalyze) {
            const analyzed = await runAnalyze();
            if (!analyzed) return;
          }
          if (state.lastAnalyze?.report_path) {
            await runDeepInnovation();
          } else {
            await runOpsCheck();
          }
          setSummary(`Smart action executed: ${code}`);
          return;
        }

        if (code === "HOLD_AND_ESCALATE") {
          await runOpsCheck();
          setError("Risk is high. Recommendation: hold release and trigger escalation workflow.");
          setSummary("Smart action executed: HOLD_AND_ESCALATE");
          return;
        }

        if (code === "MAINTAIN_MONITOR") {
          await runOpsCheck();
          setSummary("Smart action executed: MAINTAIN_MONITOR");
          return;
        }

        if (state.role === "executive") {
          const weekly = await runWeeklyCard();
          if (!weekly) await runOpsCheck();
          setSummary("Smart action executed: EXECUTIVE_WEEKLY_CARD");
          return;
        }

        await runOpsCheck();
        setSummary(`Smart action executed: ${code || "RUN_OPS_CHECK"}`);
      } catch (e) {
        setError(e?.message || String(e));
      } finally {
        btn.disabled = false;
        updateNextActionUI(state.nextBestAction || null);
        syncActionButtons();
      }
    }

    async function loadStatusDefaults() {
      try {
        const data = await apiCall("GET", "/v1/system/status");
        const db = data?.paths?.history_db_default || "";
        state.defaultHistoryDb = db;
        if (!q("#history_db_path").value && db) q("#history_db_path").value = db;
      } catch (_) {
      } finally {
        refreshCockpitStats();
      }
    }

    async function refreshCockpitStats() {
      const params = buildOpsQuery("200");
      try {
        let data = null;
        try {
          data = await apiCall("GET", "/v1/system/cockpit-snapshot?" + params.toString());
        } catch (_) {
          data = await apiCall("GET", "/v1/system/ops-summary?" + params.toString());
        }
        const cockpit = data?.cockpit || {};
        const ex = data?.history?.executive || {};
        const out = data?.history?.outcome_kpis || {};
        const ew = data?.history?.early_warning || {};
        const metrics = data?.metrics?.totals || {};

        const autoRelease = num(cockpit?.auto_release_rate, num(ex?.auto_release_rate));
        const escape = num(out?.escape_rate);
        const alertRecallFromCockpit = num(cockpit?.alert_recall_rate);
        const alertRecall = Number.isFinite(alertRecallFromCockpit)
          ? alertRecallFromCockpit
          : (Number.isFinite(escape) ? (1 - Math.max(0, escape)) : NaN);
        const latency = num(cockpit?.latency_p95_ms, num(metrics?.latency_p95_ms, num(metrics?.latency_avg_ms)));
        const riskIndex = num(cockpit?.risk_index_0_100, num(ew?.risk_index_0_100));
        const warningLevel = ew?.warning_level || cockpit?.warning_level;

        q("#stat_samples").textContent = fmtInt(cockpit?.sample_count || ex?.count || 0);
        q("#stat_samples_delta").textContent = "Historical DB live aggregation";
        q("#stat_auto_release").textContent = Number.isFinite(autoRelease) ? fmtPct(autoRelease) : "--";
        q("#stat_auto_release_delta").textContent = Number.isFinite(autoRelease) && autoRelease >= 0.82
          ? "Above recommended threshold"
          : "Keep optimizing";
        q("#stat_alert_recall").textContent = Number.isFinite(alertRecall) ? fmtPct(alertRecall) : "--";
        q("#stat_alert_recall_delta").textContent = Number.isFinite(escape) ? `escape=${fmtPct(escape)}` : "--";
        q("#stat_latency").textContent = Number.isFinite(latency) ? `${fmtNum(latency, 1)}ms` : "--";
        q("#stat_latency_delta").textContent = "system processing chain";

        q("#side_health").textContent = Number.isFinite(autoRelease) ? `${fmtNum(autoRelease * 100, 1)}%` : "--";
        q("#side_health_desc").textContent = Number.isFinite(latency)
          ? `P95 latency ${fmtNum(latency, 1)}ms, link is stable.`
          : "Waiting for real-time performance data.";
        q("#side_risk").textContent = Number.isFinite(riskIndex) ? fmtNum(riskIndex, 1) : "--";
        q("#side_risk_desc").textContent = warningLevel
          ? `Risk warning level: ${String(warningLevel)}`
          : "Waiting for risk assessment data.";

        const weekly = data?.weekly_card || state.lastWeeklyCard || null;
        if (data?.weekly_card) state.lastWeeklyCard = data.weekly_card;
        if (weekly?.roi?.annual_saving_cny) {
          const roi = num(weekly.roi.annual_saving_cny);
          q("#side_roi").textContent = Number.isFinite(roi)
            ? `CNY ${Math.round(roi).toLocaleString()}`
            : "--";
        }
        await fetchNextBestAction();
      } catch (_) {
      }
    }

    function clearResult() {
      state.lastAnalyze = null;
      q("#kpi_pass").textContent = "--";
      q("#kpi_conf").textContent = "--";
      q("#kpi_decision").textContent = "--";
      q("#kpi_risk").textContent = "--";
      q("#kpi_stability").textContent = "--";
      q("#kpi_evidence").textContent = "--";
      q("#kpi_risk_basis").textContent = "--";
      const deBox = q("#de_metrics_box"); if (deBox) deBox.style.display = "none";
      q("#actions_list").innerHTML = "<li>等待分析结果…</li>";
      q("#evidence_list").innerHTML = "<li>等待分析结果…</li>";
      q("#result_json").textContent = '{"status":"ready"}';
      q("#report_link").style.display = "none";
      q("#report_link").href = "#";
      setSummary("等待分析结果。");
      setError("");
      refreshCaptureAssessment();
      refreshCockpitStats();
      syncActionButtons();
      updateWorkflowStatus();
    }

    document.addEventListener("DOMContentLoaded", () => {
      q("#role-seg").addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-role]");
        if (!btn) return;
        applyRole(btn.dataset.role);
      });
      q("#mode-seg").addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-mode]");
        if (!btn) return;
        state.mode = btn.dataset.mode;
        syncModeUI();
      });
      q("#preset-seg").addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-preset]");
        if (!btn) return;
        applyPreset(btn.dataset.preset, true);
      });
      q("#scene-seg").addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-scene]");
        if (!btn) return;
        applyScene(btn.dataset.scene);
      });
      q("#analyze_btn").addEventListener("click", runAnalyze);
      q("#full_btn").addEventListener("click", runAutoPilot);
      q("#next_btn").addEventListener("click", runRecommendedNext);
      q("#ops_btn").addEventListener("click", runOpsCheck);
      q("#weekly_btn").addEventListener("click", runWeeklyCard);
      q("#deep_btn").addEventListener("click", runDeepInnovation);
      q("#clear_btn").addEventListener("click", clearResult);
      q("#single-image").addEventListener("change", () => {
        if (q("#single-image").files?.length) {
          state.mode = "single";
          syncModeUI();
        }
        refreshCaptureAssessment();
        updateWorkflowStatus();
      });
      q("#dual-reference").addEventListener("change", () => {
        if (q("#dual-reference").files?.length) {
          state.mode = "dual";
          syncModeUI();
        }
        refreshCaptureAssessment();
        updateWorkflowStatus();
      });
      q("#dual-film").addEventListener("change", () => {
        if (q("#dual-film").files?.length) {
          state.mode = "dual";
          syncModeUI();
        }
        refreshCaptureAssessment();
        updateWorkflowStatus();
      });
      ["#material", "#environment", "#profile", "#grid", "#history_db_path"].forEach((id) => {
        q(id).addEventListener("change", saveQuickSettings);
      });
      q("#history_db_path").addEventListener("input", () => {
        saveQuickSettings();
        syncActionButtons();
        fetchNextBestAction();
      });
      q("#customer_id").addEventListener("input", () => {
        refreshCockpitStats();
      });

      restoreQuickSettings();
      syncModeUI();
      applyScene(state.scene || "default");
      if (!state.userPresetLocked) applyPreset(state.preset || "balanced");
      applyRole(state.role || "operator", false);
      loadStatusDefaults();
      refreshCaptureAssessment();
      setInterval(refreshCockpitStats, 20000);
      syncActionButtons();
      updateWorkflowStatus();
      setSummary("等待分析结果。");
    });
  </script>
</body>
</html>
""".strip()


def render_home_page(app_version: str) -> str:
    return SMART_HOME_PAGE_TEMPLATE.replace("__APP_VERSION__", html.escape(app_version))


EXECUTIVE_DASHBOARD_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SENIA Elite Executive Dashboard</title>
  <style>
    /* Google Fonts — loads async; system fonts below are used as fallback if CDN is unreachable */
    @import url("https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700&family=Noto+Sans+SC:wght@400;500;700&display=swap");
    :root {
      --bg: #0c1828;
      --bg-alt: #0f2238;
      --line: rgba(157, 199, 241, 0.22);
      --ink: #e7f2ff;
      --sub: #96b6d8;
      --good: #29c56f;
      --warn: #ffb347;
      --bad: #ff617a;
      --card: rgba(10, 23, 38, 0.84);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Sora", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", "Hiragino Sans GB", "WenQuanYi Micro Hei", system-ui, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(1000px 500px at 90% -10%, rgba(37, 188, 131, 0.15), transparent 60%),
        radial-gradient(1100px 700px at -20% -20%, rgba(61, 160, 255, 0.18), transparent 65%),
        linear-gradient(160deg, #08121f, var(--bg) 50%, var(--bg-alt));
      min-height: 100vh;
    }
    .wrap { max-width: 1180px; margin: 0 auto; padding: 20px 14px 36px; }
    .hero, .card {
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--card);
      box-shadow: 0 10px 30px rgba(6, 14, 23, 0.45);
    }
    .hero { padding: 18px; }
    .title { margin: 0; font-size: clamp(20px, 3vw, 30px); }
    .sub { margin: 8px 0 0; color: var(--sub); font-size: 13px; line-height: 1.6; }
    .badge { display: inline-block; margin-top: 10px; border: 1px solid var(--line); border-radius: 999px; font-size: 12px; padding: 4px 10px; color: #d7eaff; }
    .card { margin-top: 12px; padding: 14px; }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }
    .field { display: flex; flex-direction: column; gap: 5px; }
    .field label { font-size: 11px; color: var(--sub); letter-spacing: 0.2px; text-transform: uppercase; }
    input {
      border: 1px solid rgba(157, 199, 241, 0.26);
      border-radius: 9px;
      background: rgba(14, 30, 50, 0.82);
      color: var(--ink);
      padding: 9px 10px;
      font-size: 13px;
    }
    .btn-row { margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap; }
    button {
      border: 0;
      border-radius: 9px;
      padding: 9px 14px;
      font-weight: 600;
      cursor: pointer;
      color: #0a1d1d;
      background: linear-gradient(140deg, #00dfc8, #48e6af);
    }
    button.secondary {
      color: #e7f2ff;
      background: linear-gradient(145deg, #2f70b8, #42a8ff);
    }
    .kpi-grid {
      margin-top: 12px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .kpi {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px;
      background: rgba(11, 25, 42, 0.8);
    }
    .kpi .k { margin: 0; font-size: 11px; color: var(--sub); text-transform: uppercase; }
    .kpi .v { margin: 6px 0 0; font-size: 20px; font-weight: 700; }
    .kpi.good .v { color: var(--good); }
    .kpi.warn .v { color: var(--warn); }
    .kpi.bad .v { color: var(--bad); }
    .row {
      margin-top: 12px;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    .log {
      margin-top: 8px;
      font-size: 12px;
      color: #d6ebff;
      background: #071423;
      border: 1px solid rgba(157, 199, 241, 0.2);
      border-radius: 9px;
      max-height: 260px;
      overflow: auto;
      padding: 10px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .link {
      display: inline-block;
      margin-top: 8px;
      font-size: 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 10px;
      color: #dceeff;
      text-decoration: none;
      background: rgba(17, 32, 51, 0.72);
    }
    @media (max-width: 980px) {
      .form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .row { grid-template-columns: 1fr; }
    }
    @media (max-width: 560px) {
      .form-grid { grid-template-columns: 1fr; }
      .kpi-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1 class="title">SENIA 经营驾驶舱</h1>
      <p class="sub">老板视角实时关注放行效率、客诉风险和综合成本，支持按产线/产品/批次快速筛选。可直接复用历史数据库。</p>
      <span class="badge">Version __APP_VERSION__</span>
      <a class="link" href="/" target="_blank">返回智能对色控制台</a>
      <a class="link" href="/v1/web/innovation-v3" target="_blank">创新作战看板</a>
    </section>

    <section class="card">
      <div class="form-grid">
        <div class="field">
          <label>DB Path</label>
          <input id="db_path" value="__DEFAULT_DB_PATH__" />
        </div>
        <div class="field">
          <label>Line ID</label>
          <input id="line_id" value="__DEFAULT_LINE_ID__" placeholder="SMIS-L1" />
        </div>
        <div class="field">
          <label>Product Code</label>
          <input id="product_code" value="__DEFAULT_PRODUCT_CODE__" placeholder="oak-gray" />
        </div>
        <div class="field">
          <label>Lot ID</label>
          <input id="lot_id" value="__DEFAULT_LOT_ID__" placeholder="LOT-XXXX" />
        </div>
        <div class="field">
          <label>API Key (可选)</label>
          <input id="api_key" value="" placeholder="开启鉴权时填写" />
        </div>
      </div>
      <div class="btn-row">
        <button id="load-btn">刷新经营指标</button>
        <button class="secondary" id="risk-btn">刷新风险视图</button>
        <button class="secondary" id="export-btn">导出 CSV</button>
      </div>
    </section>

    <section class="kpi-grid">
      <div class="kpi good"><p class="k">放行率</p><p class="v" id="kpi-pass-rate">--</p></div>
      <div class="kpi"><p class="k">平均 DeltaE</p><p class="v" id="kpi-avg-de">--</p></div>
      <div class="kpi warn"><p class="k">30天客诉概率</p><p class="v" id="kpi-p30">--</p></div>
      <div class="kpi bad"><p class="k">综合风险等级</p><p class="v" id="kpi-risk-level">--</p></div>
    </section>

    <section class="row">
      <div class="card">
        <h3 style="margin:0;font-size:16px;">经营概览</h3>
        <pre class="log" id="exec-json">{"status":"ready"}</pre>
      </div>
      <div class="card">
        <h3 style="margin:0;font-size:16px;">风险与闭环</h3>
        <pre class="log" id="risk-json">{"status":"ready"}</pre>
      </div>
    </section>
  </div>

  <script>
    const q = (s) => document.querySelector(s);

    function authHeaders() {
      const key = (q("#api_key")?.value || "").trim();
      if (!key) return {};
      return { "x-api-key": key };
    }

    function fmtPct(v) {
      if (typeof v !== "number" || Number.isNaN(v)) return "--";
      return (v * 100).toFixed(1) + "%";
    }
    function fmtNum(v, digits = 2) {
      if (typeof v !== "number" || Number.isNaN(v)) return "--";
      return v.toFixed(digits);
    }
    function params() {
      return {
        db_path: q("#db_path").value.trim(),
        line_id: q("#line_id").value.trim(),
        product_code: q("#product_code").value.trim(),
        lot_id: q("#lot_id").value.trim(),
        window: "__DEFAULT_WINDOW__",
      };
    }
    function toQuery(obj) {
      const usp = new URLSearchParams();
      for (const [k, v] of Object.entries(obj)) {
        if (v) usp.set(k, v);
      }
      return usp.toString();
    }
    async function loadExecutive() {
      const p = params();
      const execResp = await fetch("/v1/history/executive?" + toQuery(p), { headers: authHeaders() });
      if (!execResp.ok) throw new Error("history/executive failed");
      const execData = await execResp.json();
      q("#exec-json").textContent = JSON.stringify(execData, null, 2);

      const passRate = Number(execData?.acceptance?.pass_rate ?? NaN);
      const avgDeltaE = Number(execData?.quality?.avg_delta_e ?? NaN);
      q("#kpi-pass-rate").textContent = fmtPct(passRate);
      q("#kpi-avg-de").textContent = fmtNum(avgDeltaE, 2);
    }
    async function loadRisk() {
      const p = params();
      const ewResp = await fetch("/v1/history/early-warning?" + toQuery(p), { headers: authHeaders() });
      if (!ewResp.ok) throw new Error("history/early-warning failed");
      const ewData = await ewResp.json();

      const okResp = await fetch("/v1/history/outcome-kpis?" + toQuery(p), { headers: authHeaders() });
      if (!okResp.ok) throw new Error("history/outcome-kpis failed");
      const okData = await okResp.json();
      q("#risk-json").textContent = JSON.stringify({ early_warning: ewData, outcome_kpis: okData }, null, 2);

      q("#kpi-p30").textContent = fmtPct(Number(ewData?.complaint_prob_30d ?? NaN));
      q("#kpi-risk-level").textContent = String(ewData?.risk_level || "--").toUpperCase();
    }
    async function exportCsv() {
      const p = params();
      const resp = await fetch("/v1/history/executive-export?" + toQuery(p), { headers: authHeaders() });
      if (!resp.ok) throw new Error("history/executive-export failed");
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "executive_export.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }
    async function refreshAll() {
      try {
        await loadExecutive();
        await loadRisk();
      } catch (err) {
        const msg = err?.message || "load failed";
        q("#exec-json").textContent = msg;
        q("#risk-json").textContent = msg;
      }
    }
    document.addEventListener("DOMContentLoaded", () => {
      q("#load-btn").addEventListener("click", refreshAll);
      q("#risk-btn").addEventListener("click", loadRisk);
      q("#export-btn").addEventListener("click", exportCsv);
      refreshAll();
    });
  </script>
</body>
</html>
""".strip()


def render_executive_dashboard(
    app_version: str,
    default_db_path: str,
    default_line_id: str = "",
    default_product_code: str = "",
    default_lot_id: str = "",
    default_window: int = 200,
) -> str:
    return (
        EXECUTIVE_DASHBOARD_TEMPLATE.replace("__APP_VERSION__", html.escape(app_version))
        .replace("__DEFAULT_DB_PATH__", html.escape(default_db_path))
        .replace("__DEFAULT_LINE_ID__", html.escape(default_line_id))
        .replace("__DEFAULT_PRODUCT_CODE__", html.escape(default_product_code))
        .replace("__DEFAULT_LOT_ID__", html.escape(default_lot_id))
        .replace("__DEFAULT_WINDOW__", str(max(1, int(default_window))))
    )


EXECUTIVE_BRIEF_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SENIA Executive Brief</title>
  <style>
    /* Google Fonts — loads async; system fonts below are used as fallback if CDN is unreachable */
    @import url("https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700&family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap");
    :root {
      --bg0: #081425;
      --bg1: #0f2238;
      --ink: #edf6ff;
      --sub: #9db8d2;
      --line: rgba(144, 191, 235, 0.26);
      --good: #2ac670;
      --warn: #ffb145;
      --bad: #ff5d73;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Sora", "Noto Sans SC", "PingFang SC", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(1100px 520px at 80% -10%, rgba(62, 164, 255, 0.18), transparent 55%),
        radial-gradient(900px 520px at -10% -10%, rgba(0, 194, 167, 0.14), transparent 55%),
        linear-gradient(155deg, var(--bg0), var(--bg1));
      min-height: 100vh;
    }
    .wrap { max-width: 1100px; margin: 0 auto; padding: 24px 16px 40px; }
    .card {
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(10, 24, 41, 0.85);
      box-shadow: 0 12px 34px rgba(3, 10, 19, 0.45);
      padding: 14px;
    }
    .hero h1 { margin: 0; font-size: clamp(22px, 3.6vw, 34px); }
    .hero p { margin: 8px 0 0; color: var(--sub); line-height: 1.6; font-size: 13px; }
    .badge { display: inline-block; margin-top: 10px; border: 1px solid var(--line); border-radius: 999px; font-size: 12px; padding: 4px 10px; }
    .link { display: inline-block; margin-top: 8px; border: 1px solid var(--line); border-radius: 999px; color: #dcedff; text-decoration: none; padding: 6px 10px; font-size: 12px; }
    .grid {
      margin-top: 12px;
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
    }
    .field { display: flex; flex-direction: column; gap: 5px; }
    .field label { font-size: 11px; text-transform: uppercase; color: var(--sub); }
    input {
      border: 1px solid rgba(157, 199, 241, 0.26);
      border-radius: 9px;
      background: rgba(14, 30, 50, 0.82);
      color: var(--ink);
      padding: 9px 10px;
      font-size: 13px;
    }
    .btn-row { margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap; }
    button {
      border: 0;
      border-radius: 9px;
      padding: 9px 14px;
      font-weight: 600;
      cursor: pointer;
      color: #05231f;
      background: linear-gradient(140deg, #00dfc8, #48e6af);
    }
    .kpis {
      margin-top: 12px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .kpi {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px;
      background: rgba(11, 25, 42, 0.82);
    }
    .kpi .k { margin: 0; font-size: 11px; text-transform: uppercase; color: var(--sub); }
    .kpi .v { margin: 6px 0 0; font-size: 22px; font-weight: 700; }
    .kpi.good .v { color: var(--good); }
    .kpi.warn .v { color: var(--warn); }
    .kpi.bad .v { color: var(--bad); }
    .row {
      margin-top: 12px;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    .log {
      margin-top: 8px;
      font-family: "JetBrains Mono", Consolas, monospace;
      font-size: 12px;
      color: #d8ecff;
      background: #071423;
      border: 1px solid rgba(157, 199, 241, 0.2);
      border-radius: 9px;
      max-height: 380px;
      overflow: auto;
      padding: 10px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    ul { margin: 8px 0 0; padding-left: 18px; color: #cfe4ff; font-size: 13px; line-height: 1.6; }
    @media (max-width: 1000px) {
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .row { grid-template-columns: 1fr; }
    }
    @media (max-width: 620px) {
      .grid { grid-template-columns: 1fr; }
      .kpis { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="card hero">
      <h1>SENIA 执行简报</h1>
      <p>老板视角一页汇总：是否建议上线（GO/NO_GO）、评分等级、关键风险信号、可执行动作建议。</p>
      <span class="badge">Version __APP_VERSION__</span>
      <div>
        <a class="link" href="/" target="_blank">返回智能控制台</a>
        <a class="link" href="/v1/web/executive-dashboard" target="_blank">经营看板</a>
        <a class="link" href="/v1/web/innovation-v3" target="_blank">创新作战看板</a>
      </div>
    </section>

    <section class="card" style="margin-top:12px;">
      <div class="grid">
        <div class="field"><label>DB Path</label><input id="db_path" value="__DEFAULT_DB_PATH__" /></div>
        <div class="field"><label>Line ID</label><input id="line_id" value="__DEFAULT_LINE_ID__" placeholder="SMIS-L1" /></div>
        <div class="field"><label>Product</label><input id="product_code" value="__DEFAULT_PRODUCT_CODE__" placeholder="oak-gray" /></div>
        <div class="field"><label>Lot ID</label><input id="lot_id" value="__DEFAULT_LOT_ID__" placeholder="LOT-2026" /></div>
        <div class="field"><label>API Key</label><input id="api_key" value="" placeholder="启用鉴权时填写" /></div>
      </div>
      <div class="btn-row">
        <button id="refresh-btn">刷新执行简报</button>
      </div>
    </section>

    <section class="kpis">
      <div class="kpi"><p class="k">上线结论</p><p class="v" id="go">--</p></div>
      <div class="kpi"><p class="k">综合评级</p><p class="v" id="grade">--</p></div>
      <div class="kpi warn"><p class="k">风险评分</p><p class="v" id="score">--</p></div>
      <div class="kpi bad"><p class="k">SLO 状态</p><p class="v" id="slo">--</p></div>
    </section>

    <section class="row">
      <div class="card">
        <h3 style="margin:0;font-size:16px;">关键原因</h3>
        <ul id="reasons"></ul>
        <h3 style="margin:12px 0 0;font-size:16px;">行动建议</h3>
        <ul id="actions"></ul>
      </div>
      <div class="card">
        <h3 style="margin:0;font-size:16px;">原始 JSON</h3>
        <pre class="log" id="json">{"status":"ready"}</pre>
      </div>
    </section>
  </div>

  <script>
    const q = (s) => document.querySelector(s);
    const esc = (v) => String(v ?? "").replace(/[&<>"]/g, (ch) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[ch]));
    function authHeaders() {
      const key = (q("#api_key").value || "").trim();
      if (!key) return {};
      return { "x-api-key": key };
    }
    function params() {
      const p = new URLSearchParams();
      for (const id of ["db_path", "line_id", "product_code", "lot_id"]) {
        const v = (q("#" + id).value || "").trim();
        if (v) p.set(id, v);
      }
      p.set("window", "120");
      return p.toString();
    }
    function listToHtml(items) {
      if (!Array.isArray(items) || !items.length) return "<li>--</li>";
      return items.map((x) => `<li>${esc(x)}</li>`).join("");
    }
    async function refreshBrief() {
      try {
        const resp = await fetch("/v1/system/executive-brief?" + params(), { headers: authHeaders() });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data?.detail || "load failed");
        q("#go").textContent = String(data?.decision?.summary || "--");
        q("#grade").textContent = String(data?.decision?.grade || "--");
        q("#score").textContent = String(data?.decision?.score_0_100 ?? "--");
        q("#slo").textContent = String(data?.signals?.slo_status || "--").toUpperCase();
        q("#reasons").innerHTML = listToHtml(data?.reasons);
        q("#actions").innerHTML = listToHtml(data?.recommendations);
        q("#json").textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        q("#json").textContent = String(err?.message || "load failed");
      }
    }
    document.addEventListener("DOMContentLoaded", () => {
      q("#refresh-btn").addEventListener("click", refreshBrief);
      refreshBrief();
    });
  </script>
</body>
</html>
""".strip()


def render_executive_brief_page(
    app_version: str,
    default_db_path: str,
    default_line_id: str = "",
    default_product_code: str = "",
    default_lot_id: str = "",
) -> str:
    return (
        EXECUTIVE_BRIEF_TEMPLATE.replace("__APP_VERSION__", html.escape(app_version))
        .replace("__DEFAULT_DB_PATH__", html.escape(default_db_path))
        .replace("__DEFAULT_LINE_ID__", html.escape(default_line_id))
        .replace("__DEFAULT_PRODUCT_CODE__", html.escape(default_product_code))
        .replace("__DEFAULT_LOT_ID__", html.escape(default_lot_id))
    )


INNOVATION_V3_DASHBOARD_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SENIA Innovation v3 Dashboard</title>
  <style>
    /* Google Fonts — loads async; system fonts below are used as fallback if CDN is unreachable */
    @import url("https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap");
    :root {
      --bg-0: #091523;
      --bg-1: #102236;
      --line: rgba(149, 199, 241, 0.22);
      --ink: #ecf5ff;
      --sub: #9bb9d6;
      --ok: #33cc7a;
      --warn: #ffb04c;
      --bad: #ff627a;
      --card: rgba(9, 24, 40, 0.84);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: "Space Grotesk", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", "Hiragino Sans GB", "WenQuanYi Micro Hei", system-ui, sans-serif;
      background:
        radial-gradient(900px 450px at 90% -10%, rgba(0, 194, 157, 0.18), transparent 56%),
        radial-gradient(1100px 650px at -10% -10%, rgba(63, 168, 255, 0.22), transparent 62%),
        linear-gradient(160deg, #081321, var(--bg-0) 52%, var(--bg-1));
      min-height: 100vh;
    }
    .wrap { max-width: 1260px; margin: 0 auto; padding: 20px 14px 36px; }
    .hero {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      background: linear-gradient(155deg, rgba(14, 32, 52, 0.82), rgba(10, 22, 37, 0.92));
      box-shadow: 0 12px 34px rgba(4, 12, 21, 0.46);
    }
    .hero h1 { margin: 0; font-size: clamp(24px, 4vw, 34px); letter-spacing: 0.2px; }
    .hero p { margin: 8px 0 0; color: var(--sub); font-size: 13px; line-height: 1.7; }
    .badge {
      display: inline-block;
      margin-top: 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 11px;
      font-size: 12px;
      color: #dbeeff;
    }
    .links { margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap; }
    .link {
      text-decoration: none;
      font-size: 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 10px;
      color: #daedff;
      background: rgba(16, 31, 50, 0.72);
    }
    .card {
      margin-top: 12px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--card);
      box-shadow: 0 10px 26px rgba(4, 12, 22, 0.42);
      padding: 12px;
    }
    .card h2 {
      margin: 0;
      font-size: 15px;
      letter-spacing: 0.15px;
    }
    .note { margin: 6px 0 0; color: var(--sub); font-size: 12px; line-height: 1.6; }
    .cfg-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-top: 10px;
    }
    .field { display: flex; flex-direction: column; gap: 5px; }
    .field label { color: var(--sub); font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px; }
    input, select, textarea {
      width: 100%;
      border: 1px solid rgba(149, 199, 241, 0.3);
      border-radius: 9px;
      background: rgba(14, 30, 48, 0.84);
      color: var(--ink);
      padding: 8px 10px;
      font-size: 12px;
      font-family: "JetBrains Mono", Consolas, monospace;
    }
    textarea { min-height: 64px; resize: vertical; }
    button {
      border: 0;
      border-radius: 9px;
      padding: 8px 12px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.2px;
      cursor: pointer;
      color: #082322;
      background: linear-gradient(145deg, #00ddc3, #44e7b0);
    }
    button.secondary {
      color: #e5f2ff;
      background: linear-gradient(145deg, #2e71ba, #43a8ff);
    }
    .btn-row { margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap; }
    .layout {
      margin-top: 12px;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    .mono {
      margin-top: 8px;
      border: 1px solid rgba(149, 199, 241, 0.2);
      border-radius: 9px;
      background: #061324;
      color: #d9ecff;
      font-family: "JetBrains Mono", Consolas, monospace;
      font-size: 12px;
      line-height: 1.5;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 260px;
      overflow: auto;
      padding: 9px;
    }
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }
    .kpi {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: rgba(11, 26, 42, 0.82);
      padding: 8px;
    }
    .kpi .k { margin: 0; font-size: 10px; color: var(--sub); text-transform: uppercase; }
    .kpi .v { margin: 5px 0 0; font-size: 18px; font-weight: 700; font-family: "JetBrains Mono", Consolas, monospace; }
    .ok { color: var(--ok); }
    .warn { color: var(--warn); }
    .bad { color: var(--bad); }
    @media (max-width: 1020px) {
      .cfg-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .layout { grid-template-columns: 1fr; }
      .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 620px) {
      .cfg-grid { grid-template-columns: 1fr; }
      .kpi-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>SENIA Innovation v3 作战看板</h1>
      <p>支持直接操作新增 5 大模块：SPC、观察者仿真、班次报告、供应商评分、色彩标准库。所有动作均调用后端真实 API。</p>
      <span class="badge">Version __APP_VERSION__</span>
      <div class="links">
        <a class="link" href="/" target="_blank">控制台首页</a>
        <a class="link" href="/v1/web/executive-dashboard" target="_blank">经营驾驶舱</a>
      </div>
    </section>

    <section class="card">
      <h2>全局参数</h2>
      <div class="cfg-grid">
        <div class="field"><label>API Key</label><input id="api_key" placeholder="启用鉴权时填写" /></div>
        <div class="field"><label>DB Path</label><input id="db_path" value="__DEFAULT_DB_PATH__" /></div>
        <div class="field"><label>Line ID</label><input id="line_id" value="__DEFAULT_LINE_ID__" placeholder="SMIS-L1" /></div>
        <div class="field"><label>Product Code</label><input id="product_code" value="__DEFAULT_PRODUCT_CODE__" placeholder="oak-gray" /></div>
      </div>
      <p class="note">建议流程：先跑 SPC 和班次报告看过程状态，再跑观察者和标准库做风险验证，最后用供应商评分驱动采购治理。</p>
    </section>

    <section class="layout">
      <div class="card">
        <h2>模块9: SPC 过程控制</h2>
        <div class="cfg-grid" style="margin-top:8px;">
          <div class="field"><label>Window</label><input id="spc_window" value="120" /></div>
          <div class="field"><label>Subgroup Size</label><input id="spc_size" value="5" /></div>
          <div class="field"><label>Spec Lower</label><input id="spc_lsl" value="0" /></div>
          <div class="field"><label>Spec Upper</label><input id="spc_usl" value="3.0" /></div>
        </div>
        <div class="btn-row">
          <button id="spc_btn">从历史生成 SPC</button>
        </div>
        <div class="kpi-grid">
          <div class="kpi"><p class="k">Cpk</p><p class="v" id="spc_cpk">--</p></div>
          <div class="kpi"><p class="k">Cp</p><p class="v" id="spc_cp">--</p></div>
          <div class="kpi"><p class="k">等级</p><p class="v" id="spc_grade">--</p></div>
          <div class="kpi"><p class="k">OOC</p><p class="v" id="spc_ooc">--</p></div>
        </div>
        <pre class="mono" id="spc_out">{"status":"ready"}</pre>
      </div>

      <div class="card">
        <h2>模块10: 多观察者仿真</h2>
        <div class="cfg-grid" style="margin-top:8px;">
          <div class="field"><label>Sample L</label><input id="obs_sL" value="62.5" /></div>
          <div class="field"><label>Sample a</label><input id="obs_sa" value="3.2" /></div>
          <div class="field"><label>Sample b</label><input id="obs_sb" value="14.8" /></div>
          <div class="field"><label>Film L</label><input id="obs_fL" value="64.1" /></div>
          <div class="field"><label>Film a</label><input id="obs_fa" value="3.8" /></div>
          <div class="field"><label>Film b</label><input id="obs_fb" value="16.1" /></div>
          <div class="field"><label>Target Age</label><input id="obs_age" value="65" /></div>
          <div class="field"><label>Sensitivity</label><select id="obs_sens"><option value="normal">normal</option><option value="high">high</option></select></div>
        </div>
        <div class="btn-row">
          <button id="obs_btn">运行观察者仿真</button>
        </div>
        <pre class="mono" id="obs_out">{"status":"ready"}</pre>
      </div>

      <div class="card">
        <h2>模块11: 班次报告</h2>
        <div class="cfg-grid" style="margin-top:8px;">
          <div class="field"><label>Shift ID</label><input id="shift_id" value="" placeholder="自动生成" /></div>
          <div class="field"><label>Hours</label><input id="shift_hours" value="8" /></div>
          <div class="field"><label>Window</label><input id="shift_window" value="160" /></div>
          <div class="field"><label>Line ID Override</label><input id="shift_line" value="" placeholder="可空" /></div>
        </div>
        <div class="btn-row">
          <button id="shift_btn">从历史生成班报</button>
        </div>
        <pre class="mono" id="shift_out">{"status":"ready"}</pre>
      </div>

      <div class="card">
        <h2>模块12: 供应商评分</h2>
        <div class="cfg-grid" style="margin-top:8px;">
          <div class="field"><label>Supplier ID</label><input id="sup_id" value="SUP-A" /></div>
          <div class="field"><label>Delta E</label><input id="sup_de" value="1.85" /></div>
          <div class="field"><label>Product</label><input id="sup_product" value="oak-gray" /></div>
          <div class="field"><label>Passed</label><select id="sup_pass"><option value="true">true</option><option value="false">false</option></select></div>
        </div>
        <div class="btn-row">
          <button id="sup_record_btn">记录一条</button>
          <button class="secondary" id="sup_score_btn">刷新评分卡</button>
        </div>
        <pre class="mono" id="sup_out">{"status":"ready"}</pre>
      </div>

      <div class="card">
        <h2>模块13: 色彩标准库</h2>
        <div class="cfg-grid" style="margin-top:8px;">
          <div class="field"><label>Code</label><input id="std_code" value="OAK-GRAY-001" /></div>
          <div class="field"><label>L</label><input id="std_L" value="62.5" /></div>
          <div class="field"><label>a</label><input id="std_a" value="3.2" /></div>
          <div class="field"><label>b</label><input id="std_b" value="14.8" /></div>
          <div class="field"><label>Source</label><input id="std_source" value="manual" /></div>
          <div class="field"><label>Notes</label><input id="std_notes" value="v1 baseline" /></div>
          <div class="field"><label>Measured L</label><input id="cmp_L" value="63.9" /></div>
          <div class="field"><label>Measured a</label><input id="cmp_a" value="3.9" /></div>
          <div class="field"><label>Measured b</label><input id="cmp_b" value="16.0" /></div>
        </div>
        <div class="btn-row">
          <button id="std_reg_btn">登记标准</button>
          <button class="secondary" id="std_cmp_btn">对比实测</button>
          <button class="secondary" id="std_list_btn">列出标准</button>
        </div>
        <pre class="mono" id="std_out">{"status":"ready"}</pre>
      </div>

      <div class="card">
        <h2>系统摘要</h2>
        <p class="note">用于确认新增模块和页面接入是否生效。</p>
        <div class="btn-row"><button id="manifest_btn">刷新 Manifest</button></div>
        <pre class="mono" id="manifest_out">{"status":"ready"}</pre>
      </div>
    </section>
  </div>

  <script>
    const q = (s) => document.querySelector(s);
    const num = (id, def = 0) => {
      const v = Number((q("#" + id)?.value || "").trim());
      return Number.isFinite(v) ? v : def;
    };
    function headers() {
      const key = (q("#api_key").value || "").trim();
      const h = { "Accept": "application/json" };
      if (key) h["x-api-key"] = key;
      return h;
    }
    function g(id) { return (q("#" + id)?.value || "").trim(); }
    async function call(method, path, payload) {
      const opts = { method, headers: headers() };
      if (payload !== undefined) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(payload);
      }
      const resp = await fetch(path, opts);
      const data = await resp.json();
      if (!resp.ok) throw new Error(data?.detail || JSON.stringify(data));
      return data;
    }
    function pretty(el, data) { q(el).textContent = JSON.stringify(data, null, 2); }

    function commonQuery(extra = {}) {
      const p = new URLSearchParams();
      const db = g("db_path");
      const line = g("line_id");
      const product = g("product_code");
      if (db) p.set("db_path", db);
      if (line) p.set("line_id", line);
      if (product) p.set("product_code", product);
      Object.entries(extra).forEach(([k, v]) => { if (v !== "" && v !== null && v !== undefined) p.set(k, String(v)); });
      return p.toString();
    }

    async function runSpc() {
      const qs = commonQuery({
        window: num("spc_window", 120),
        subgroup_size: num("spc_size", 5),
        spec_lower: num("spc_lsl", 0),
        spec_upper: num("spc_usl", 3.0),
      });
      const data = await call("GET", "/v1/quality/spc/from-history?" + qs);
      const cap = data?.result?.capability || {};
      q("#spc_cpk").textContent = cap.Cpk ?? "--";
      q("#spc_cp").textContent = cap.Cp ?? "--";
      q("#spc_grade").textContent = cap.grade ?? "--";
      q("#spc_ooc").textContent = data?.result?.ooc_count ?? "--";
      pretty("#spc_out", data);
    }

    async function runObserver() {
      const payload = {
        sample_lab: { L: num("obs_sL"), a: num("obs_sa"), b: num("obs_sb") },
        film_lab: { L: num("obs_fL"), a: num("obs_fa"), b: num("obs_fb") },
        target_age: Math.round(num("obs_age", 35)),
        sensitivity: g("obs_sens") || "normal"
      };
      const data = await call("POST", "/v1/analyze/multi-observer", payload);
      pretty("#obs_out", data);
    }

    async function runShift() {
      const qs = commonQuery({
        window: num("shift_window", 160),
        shift_id: g("shift_id"),
        hours: num("shift_hours", 8),
        line_id: g("shift_line") || g("line_id")
      });
      const data = await call("GET", "/v1/report/shift/from-history?" + qs);
      pretty("#shift_out", data);
    }

    async function recordSupplier() {
      const payload = {
        supplier_id: g("sup_id"),
        delta_e: num("sup_de"),
        product: g("sup_product"),
        passed: (g("sup_pass") || "true").toLowerCase() === "true",
        db_path: g("db_path")
      };
      const data = await call("POST", "/v1/supplier/record", payload);
      pretty("#sup_out", data);
    }

    async function loadSupplierScore() {
      const sid = g("sup_id");
      const p = new URLSearchParams();
      if (sid) p.set("supplier_id", sid);
      if (g("db_path")) p.set("db_path", g("db_path"));
      const qs = p.toString() ? ("?" + p.toString()) : "";
      const data = await call("GET", "/v1/supplier/scorecard" + qs);
      pretty("#sup_out", data);
    }

    async function registerStandard() {
      const payload = {
        code: g("std_code"),
        lab: { L: num("std_L"), a: num("std_a"), b: num("std_b") },
        source: g("std_source"),
        notes: g("std_notes"),
        db_path: g("db_path")
      };
      const data = await call("POST", "/v1/standards/register", payload);
      pretty("#std_out", data);
    }

    async function compareStandard() {
      const payload = {
        code: g("std_code"),
        measured_lab: { L: num("cmp_L"), a: num("cmp_a"), b: num("cmp_b") },
        db_path: g("db_path")
      };
      const data = await call("POST", "/v1/standards/compare", payload);
      pretty("#std_out", data);
    }

    async function listStandards() {
      const p = new URLSearchParams();
      if (g("db_path")) p.set("db_path", g("db_path"));
      const qs = p.toString() ? ("?" + p.toString()) : "";
      const data = await call("GET", "/v1/standards/list" + qs);
      pretty("#std_out", data);
    }

    async function loadManifest() {
      const data = await call("GET", "/v1/innovation/manifest");
      pretty("#manifest_out", data);
    }

    function bind(btn, fn) {
      q(btn).addEventListener("click", async () => {
        try { await fn(); }
        catch (err) { alert(err?.message || String(err)); }
      });
    }

    document.addEventListener("DOMContentLoaded", () => {
      bind("#spc_btn", runSpc);
      bind("#obs_btn", runObserver);
      bind("#shift_btn", runShift);
      bind("#sup_record_btn", recordSupplier);
      bind("#sup_score_btn", loadSupplierScore);
      bind("#std_reg_btn", registerStandard);
      bind("#std_cmp_btn", compareStandard);
      bind("#std_list_btn", listStandards);
      bind("#manifest_btn", loadManifest);
      loadManifest();
    });
  </script>
</body>
</html>
""".strip()


def render_innovation_v3_dashboard_page(
    app_version: str,
    default_db_path: str,
    default_line_id: str = "",
    default_product_code: str = "",
) -> str:
    return (
        INNOVATION_V3_DASHBOARD_TEMPLATE.replace("__APP_VERSION__", html.escape(app_version))
        .replace("__DEFAULT_DB_PATH__", html.escape(default_db_path))
        .replace("__DEFAULT_LINE_ID__", html.escape(default_line_id))
        .replace("__DEFAULT_PRODUCT_CODE__", html.escape(default_product_code))
    )


WEB_CONSOLE_ROOT = Path(__file__).resolve().parent
OBSERVATORY_ASSET_DIR = WEB_CONSOLE_ROOT / "web_assets"
OBSERVATORY_MODULE_PATH = OBSERVATORY_ASSET_DIR / "senia-elite-observatory.module.js"
OBSERVATORY_BUILD_INPUT_PATH = OBSERVATORY_ASSET_DIR / "_observatory_build_input.jsx"
OBSERVATORY_SOURCE_CANDIDATES = (
    OBSERVATORY_ASSET_DIR / "senia-elite-observatory.jsx",
    Path(r"C:\Users\86150\Downloads\senia-elite-observatory.jsx"),
)

OBSERVATORY_FALLBACK_MODULE = """
import React from "react";

export default function EliteObservatoryFallback() {
  return React.createElement(
    "div",
    {
      style: {
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background: "#05060b",
        color: "#d4d4e0",
        fontFamily: "'Outfit','Noto Sans SC',system-ui,sans-serif",
        padding: "24px",
      },
    },
    React.createElement(
      "div",
      {
        style: {
          maxWidth: "920px",
          border: "1px solid #1f2430",
          borderRadius: "16px",
          background: "#0a0b12",
          padding: "20px 22px",
        },
      },
      React.createElement("h2", { style: { margin: 0, color: "#38bdf8" } }, "Precision Color Observatory"),
      React.createElement(
        "p",
        { style: { marginTop: "10px", color: "#a1a1b0", lineHeight: 1.7 } },
        "The observatory component could not be built. Keep using the rest of the Elite system while we fix the frontend bundle."
      ),
      React.createElement(
        "pre",
        {
          style: {
            marginTop: "12px",
            padding: "10px 12px",
            background: "#05060b",
            border: "1px solid #1f2430",
            borderRadius: "10px",
            color: "#fb923c",
            whiteSpace: "pre-wrap",
          },
        },
        "__BUILD_ERROR__"
      )
    )
  );
}
""".strip()

PRECISION_OBSERVATORY_PAGE_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SENIA Elite Precision Color Observatory</title>
  <style>
    html, body { margin: 0; background: #05060b; }
    .top-bar {
      position: fixed;
      top: 12px;
      left: 12px;
      right: 12px;
      z-index: 50;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      pointer-events: none;
    }
    .chip-row {
      display: flex;
      align-items: center;
      gap: 8px;
      pointer-events: auto;
    }
    .chip {
      color: #d4d4e0;
      text-decoration: none;
      border: 1px solid #1f2430;
      background: rgba(10, 11, 18, 0.84);
      border-radius: 999px;
      padding: 6px 10px;
      font: 600 12px/1 "Outfit", "Noto Sans SC", system-ui, sans-serif;
    }
    .chip strong { color: #38bdf8; }
    #precision-root { min-height: 100vh; }
    .live-pod {
      position: fixed;
      right: 12px;
      bottom: 12px;
      width: min(360px, calc(100vw - 24px));
      z-index: 55;
      border: 1px solid #1f2430;
      border-radius: 14px;
      background: rgba(10, 11, 18, 0.94);
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
      backdrop-filter: blur(10px);
      overflow: hidden;
      font-family: "Outfit", "Noto Sans SC", system-ui, sans-serif;
      color: #d4d4e0;
    }
    .live-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 10px 12px;
      border-bottom: 1px solid #1f2430;
      background: linear-gradient(90deg, rgba(56, 189, 248, 0.12), rgba(244, 114, 182, 0.08));
    }
    .live-title {
      margin: 0;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.4px;
      color: #e5f4ff;
    }
    .live-status {
      font-size: 10px;
      color: #9aa4ba;
      font-weight: 700;
    }
    .live-body { padding: 10px 12px 12px; }
    .f-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
      margin-bottom: 8px;
    }
    .f-grid .full { grid-column: 1 / -1; }
    .f-grid input {
      width: 100%;
      border: 1px solid #1f2430;
      border-radius: 8px;
      background: #07080f;
      color: #d4d4e0;
      padding: 7px 8px;
      font-size: 11px;
      outline: none;
      transition: border-color .2s ease;
    }
    .f-grid input:focus { border-color: #38bdf8; }
    .btn-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
      margin-bottom: 10px;
    }
    .btn-row button {
      border: 1px solid #1f2430;
      border-radius: 8px;
      padding: 8px 9px;
      background: #0a0c14;
      color: #cfd7ea;
      font-size: 11px;
      font-weight: 700;
      cursor: pointer;
      transition: all .2s ease;
    }
    .btn-row button.primary {
      border-color: rgba(56, 189, 248, 0.45);
      color: #38bdf8;
      box-shadow: 0 0 0 1px rgba(56, 189, 248, 0.15) inset;
    }
    .btn-row button:hover {
      transform: translateY(-1px);
      border-color: rgba(56, 189, 248, 0.55);
    }
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
      margin-bottom: 8px;
    }
    .kpi {
      border: 1px solid #1f2430;
      border-radius: 8px;
      padding: 8px;
      background: #07080f;
    }
    .kpi .t {
      margin: 0;
      font-size: 9px;
      color: #7f89a2;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .4px;
    }
    .kpi .v {
      margin: 4px 0 0;
      font-size: 14px;
      font-weight: 800;
      color: #dff4ff;
      font-family: "JetBrains Mono", "IBM Plex Mono", monospace;
    }
    .kpi .v.warn { color: #fb923c; text-shadow: 0 0 10px rgba(251, 146, 60, 0.32); }
    .kpi .v.bad { color: #f472b6; text-shadow: 0 0 10px rgba(244, 114, 182, 0.32); }
    .kpi .v.good { color: #38bdf8; text-shadow: 0 0 10px rgba(56, 189, 248, 0.32); }
    .nba-line {
      margin-top: 4px;
      font-size: 11px;
      color: #b9c5de;
      line-height: 1.4;
      min-height: 30px;
    }
    .out {
      margin-top: 8px;
      border: 1px solid #1f2430;
      border-radius: 8px;
      background: #07080f;
      padding: 8px;
      font: 11px/1.5 "JetBrains Mono", "IBM Plex Mono", monospace;
      color: #9eb0d3;
      max-height: 130px;
      overflow: auto;
      white-space: pre-wrap;
    }
    @media (max-width: 900px) {
      .live-pod { position: static; width: auto; margin: 8px 12px 16px; }
      .top-bar { position: static; padding: 12px; }
      #precision-root { min-height: auto; }
    }
  </style>
  <script type="importmap">
  {
    "imports": {
      "react": "https://esm.sh/react@18.3.1",
      "react-dom/client": "https://esm.sh/react-dom@18.3.1/client"
    }
  }
  </script>
</head>
<body>
  <div class="top-bar">
    <div class="chip-row">
      <a class="chip" href="/">Home</a>
      <a class="chip" href="/v1/web/innovation-v3" target="_blank">Innovation V3</a>
      <a class="chip" href="/docs" target="_blank">API Docs</a>
    </div>
    <div class="chip-row">
      <span class="chip"><strong>Precision Observatory</strong> v__APP_VERSION__</span>
    </div>
  </div>
  <div id="precision-root"></div>
  <section class="live-pod" aria-label="Live Command Pod">
    <div class="live-head">
      <h2 class="live-title">Live Command Pod</h2>
      <span class="live-status" id="live_status">IDLE</span>
    </div>
    <div class="live-body">
      <div class="f-grid">
        <input id="live_db_path" class="full" type="text" placeholder="History DB path" />
        <input id="live_line_id" type="text" placeholder="line_id (optional)" />
        <input id="live_product_code" type="text" placeholder="product_code (optional)" />
        <input id="live_api_key" class="full" type="text" placeholder="x-api-key (optional)" />
      </div>
      <div class="btn-row">
        <button id="live_refresh_btn" class="primary" type="button">Refresh Live</button>
        <button id="live_next_btn" type="button">Run Smart Next</button>
      </div>
      <div class="kpi-grid">
        <div class="kpi"><p class="t">Warning</p><p class="v" id="live_warning">--</p></div>
        <div class="kpi"><p class="t">Risk Index</p><p class="v" id="live_risk">--</p></div>
        <div class="kpi"><p class="t">Auto Release</p><p class="v" id="live_auto_release">--</p></div>
        <div class="kpi"><p class="t">Action</p><p class="v" id="live_action">--</p></div>
      </div>
      <div class="nba-line" id="live_reasons">Waiting for data...</div>
      <pre class="out" id="live_out">{"status":"ready"}</pre>
    </div>
  </section>

  <script type="module">
    import React from "react";
    import { createRoot } from "react-dom/client";
    import EliteObservatory from "/v1/web/assets/observatory-module.js?v=__APP_VERSION__";

    const mount = document.getElementById("precision-root");
    const root = createRoot(mount);
    root.render(React.createElement(EliteObservatory));

    const defaults = {
      dbPath: "__DEFAULT_DB_PATH__",
      lineId: "__DEFAULT_LINE_ID__",
      productCode: "__DEFAULT_PRODUCT_CODE__",
    };
    window.__SENIA_OBS_DEFAULTS__ = { ...defaults };

    const q = (id) => document.getElementById(id);
    const setStatus = (text) => { q("live_status").textContent = text; };
    const toNum = (v, d = NaN) => {
      const n = Number(v);
      return Number.isFinite(n) ? n : d;
    };
    const pct = (v) => {
      const n = toNum(v);
      if (!Number.isFinite(n)) return "--";
      return `${(n * 100).toFixed(1)}%`;
    };
    const applyLevelClass = (el, value, goodLow = true) => {
      if (!el) return;
      el.classList.remove("good", "warn", "bad");
      const n = toNum(value);
      if (!Number.isFinite(n)) return;
      if (goodLow) {
        el.classList.add(n < 45 ? "good" : n < 70 ? "warn" : "bad");
      } else {
        el.classList.add(n > 0.82 ? "good" : n > 0.7 ? "warn" : "bad");
      }
    };

    q("live_db_path").value = defaults.dbPath || "";
    q("live_line_id").value = defaults.lineId || "";
    q("live_product_code").value = defaults.productCode || "";

    let latestPlan = null;
    let latestSnapshot = null;

    function authHeaders() {
      const key = (q("live_api_key").value || "").trim();
      return key ? { "x-api-key": key } : {};
    }

    function buildQuery(windowValue = "200") {
      const params = new URLSearchParams();
      params.set("window", String(windowValue || "200"));
      params.set("weekly_window", "500");
      const dbPath = (q("live_db_path").value || "").trim();
      const lineId = (q("live_line_id").value || "").trim();
      const productCode = (q("live_product_code").value || "").trim();
      if (dbPath) params.set("db_path", dbPath);
      if (lineId) params.set("line_id", lineId);
      if (productCode) params.set("product_code", productCode);
      return params;
    }

    async function callJson(path) {
      const resp = await fetch(path, {
        method: "GET",
        headers: { Accept: "application/json", ...authHeaders() },
      });
      const text = await resp.text();
      let payload = null;
      try {
        payload = JSON.parse(text);
      } catch (_) {
        payload = { raw: text };
      }
      if (!resp.ok) {
        const detail = payload?.detail || payload?.raw || `${resp.status} ${resp.statusText}`;
        throw new Error(String(detail));
      }
      return payload;
    }

    function renderLive(snapshot, plan) {
      const cockpit = snapshot?.cockpit || {};
      const rec = plan?.recommended_action || {};
      const warning = String(cockpit?.warning_level || plan?.signals?.warning_level || "--").toUpperCase();
      const risk = toNum(cockpit?.risk_index_0_100, toNum(plan?.signals?.risk_index_0_100));
      const autoRelease = toNum(cockpit?.auto_release_rate, toNum(plan?.signals?.auto_release_rate));

      const warningEl = q("live_warning");
      const riskEl = q("live_risk");
      const autoEl = q("live_auto_release");
      const actionEl = q("live_action");

      warningEl.textContent = warning;
      riskEl.textContent = Number.isFinite(risk) ? risk.toFixed(1) : "--";
      autoEl.textContent = Number.isFinite(autoRelease) ? pct(autoRelease) : "--";
      actionEl.textContent = rec?.code || "--";

      warningEl.classList.remove("good", "warn", "bad");
      warningEl.classList.add(
        warning === "GREEN" ? "good" : warning === "YELLOW" || warning === "ORANGE" ? "warn" : warning === "--" ? "" : "bad"
      );
      applyLevelClass(riskEl, risk, true);
      applyLevelClass(autoEl, autoRelease, false);
      actionEl.classList.remove("good", "warn", "bad");
      actionEl.classList.add(rec?.code === "HOLD_AND_ESCALATE" ? "bad" : rec?.code === "DEEP_INNOVATION_REVIEW" ? "warn" : "good");

      const reasons = Array.isArray(rec?.reasons) ? rec.reasons.slice(0, 2) : [];
      q("live_reasons").textContent = reasons.length
        ? reasons.join(" | ")
        : "No recommendation reason yet.";
      q("live_out").textContent = JSON.stringify(
        {
          generated_at: snapshot?.generated_at || null,
          action: rec?.code || null,
          confidence: rec?.confidence || null,
          signals: plan?.signals || null,
        },
        null,
        2
      );
    }

    async function refreshLive() {
      setStatus("SYNCING");
      const query = buildQuery("200");
      try {
        const [snapshot, plan] = await Promise.all([
          callJson("/v1/system/cockpit-snapshot?" + query.toString()),
          callJson("/v1/system/next-best-action?" + query.toString() + "&ui_role=executive"),
        ]);
        latestSnapshot = snapshot;
        latestPlan = plan;
        renderLive(snapshot, plan);
        setStatus("LIVE");
      } catch (err) {
        setStatus("ERROR");
        q("live_reasons").textContent = String(err?.message || err || "request failed");
      }
    }

    async function runSmartNext() {
      setStatus("EXECUTING");
      const query = buildQuery("200");
      try {
        if (!latestPlan) {
          latestPlan = await callJson("/v1/system/next-best-action?" + query.toString() + "&ui_role=executive");
        }
        const code = String(latestPlan?.recommended_action?.code || "RUN_OPS_CHECK");
        let result = null;
        if (code === "EXECUTIVE_WEEKLY_CARD") {
          result = await callJson("/v1/system/executive-weekly-card?" + query.toString());
        } else {
          result = await callJson("/v1/system/executive-brief?" + query.toString());
        }
        q("live_out").textContent = JSON.stringify(
          {
            executed_action: code,
            result: result,
          },
          null,
          2
        );
        await refreshLive();
        setStatus("DONE");
      } catch (err) {
        setStatus("ERROR");
        q("live_reasons").textContent = String(err?.message || err || "smart next failed");
      }
    }

    q("live_refresh_btn").addEventListener("click", refreshLive);
    q("live_next_btn").addEventListener("click", runSmartNext);
    q("live_db_path").addEventListener("change", refreshLive);
    q("live_line_id").addEventListener("change", refreshLive);
    q("live_product_code").addEventListener("change", refreshLive);

    refreshLive();
    setInterval(refreshLive, 20000);
  </script>
</body>
</html>
""".strip()


def _pick_observatory_source_path() -> Path | None:
    for candidate in OBSERVATORY_SOURCE_CANDIDATES:
        try:
            if candidate.exists() and candidate.is_file():
                return candidate
        except Exception:
            continue
    return None


def _sanitize_observatory_source(raw_text: str) -> str:
    text = raw_text.replace("\r\n", "\n")
    # The original formula contains "-x**2", which is invalid JS syntax.
    text = text.replace("Math.exp(-((hp-275)/25)**2)", "Math.exp(-(((hp-275)/25)**2))")
    return text


def _resolve_npx_path() -> str | None:
    for candidate in (
        shutil.which("npx"),
        shutil.which("npx.cmd"),
        r"C:\Program Files\nodejs\npx.cmd",
        r"C:\Program Files\nodejs\npx.exe",
    ):
        if not candidate:
            continue
        path_obj = Path(candidate)
        if path_obj.exists():
            return str(path_obj)
    return None


def _build_observatory_module_if_needed() -> str:
    source_path = _pick_observatory_source_path()
    OBSERVATORY_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    if source_path is None:
        if OBSERVATORY_MODULE_PATH.exists():
            return ""
        return "observatory source file not found"

    needs_build = (
        (not OBSERVATORY_MODULE_PATH.exists())
        or (OBSERVATORY_MODULE_PATH.stat().st_mtime < source_path.stat().st_mtime)
    )
    if not needs_build:
        return ""

    try:
        npx_path = _resolve_npx_path()
        if not npx_path:
            return "npx not found in PATH"
        OBSERVATORY_BUILD_INPUT_PATH.write_text(
            _sanitize_observatory_source(source_path.read_text(encoding="utf-8", errors="replace")),
            encoding="utf-8",
        )
        cmd = [
            npx_path,
            "--yes",
            "esbuild",
            str(OBSERVATORY_BUILD_INPUT_PATH),
            "--loader:.jsx=jsx",
            "--format=esm",
            "--target=es2020",
            f"--outfile={OBSERVATORY_MODULE_PATH}",
            "--log-level=error",
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(WEB_CONSOLE_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            return (proc.stderr or proc.stdout or "esbuild failed").strip()
        return ""
    except Exception as exc:
        return str(exc)
    finally:
        OBSERVATORY_BUILD_INPUT_PATH.unlink(missing_ok=True)


def get_precision_observatory_module_js() -> str:
    build_error = _build_observatory_module_if_needed()
    if OBSERVATORY_MODULE_PATH.exists():
        body = OBSERVATORY_MODULE_PATH.read_text(encoding="utf-8", errors="replace")
        if build_error:
            return f"/* observatory build warning: {build_error} */\n{body}"
        return body
    fallback_error = (build_error or "observatory module unavailable").replace("</script>", "<\\/script>")
    return OBSERVATORY_FALLBACK_MODULE.replace("__BUILD_ERROR__", fallback_error)


def render_precision_observatory_page(
    app_version: str,
    default_db_path: str = "",
    default_line_id: str = "",
    default_product_code: str = "",
) -> str:
    return (
        PRECISION_OBSERVATORY_PAGE_TEMPLATE.replace("__APP_VERSION__", html.escape(app_version))
        .replace("__DEFAULT_DB_PATH__", html.escape(default_db_path))
        .replace("__DEFAULT_LINE_ID__", html.escape(default_line_id))
        .replace("__DEFAULT_PRODUCT_CODE__", html.escape(default_product_code))
    )
