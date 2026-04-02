import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const srgb = (v) => {
  const x = v / 255;
  return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
};
const rgbToLab = (r, g, b) => {
  const lr = srgb(r), lg = srgb(g), lb = srgb(b);
  const x = lr * 0.4124564 + lg * 0.3575761 + lb * 0.1804375;
  const y = lr * 0.2126729 + lg * 0.7151522 + lb * 0.072175;
  const z = lr * 0.0193339 + lg * 0.119192 + lb * 0.9503041;
  const f = (t) => (t > 0.008856 ? t ** (1 / 3) : 7.787 * t + 16 / 116);
  return { L: 116 * f(y) - 16, a: 500 * (f(x / 0.95047) - f(y)), b: 200 * (f(y) - f(z / 1.08883)) };
};
const de2000 = (a, b) => {
  const rad = Math.PI / 180, deg = 180 / Math.PI;
  const C1 = Math.hypot(a.a, a.b), C2 = Math.hypot(b.a, b.b), Cb = (C1 + C2) / 2;
  const G = 0.5 * (1 - Math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)));
  const ap1 = a.a * (1 + G), ap2 = b.a * (1 + G), Cp1 = Math.hypot(ap1, a.b), Cp2 = Math.hypot(ap2, b.b);
  let hp1 = Math.atan2(a.b, ap1) * deg, hp2 = Math.atan2(b.b, ap2) * deg;
  if (hp1 < 0) hp1 += 360;
  if (hp2 < 0) hp2 += 360;
  const dL = b.L - a.L, dC = Cp2 - Cp1;
  let dh = 0;
  if (Cp1 * Cp2 !== 0) dh = Math.abs(hp2 - hp1) <= 180 ? hp2 - hp1 : hp2 - hp1 > 180 ? hp2 - hp1 - 360 : hp2 - hp1 + 360;
  const dH = 2 * Math.sqrt(Cp1 * Cp2) * Math.sin((dh / 2) * rad), Lp = (a.L + b.L) / 2, Cp = (Cp1 + Cp2) / 2;
  let hp = hp1 + hp2;
  if (Cp1 * Cp2 !== 0) hp = Math.abs(hp1 - hp2) <= 180 ? (hp1 + hp2) / 2 : hp1 + hp2 < 360 ? (hp1 + hp2 + 360) / 2 : (hp1 + hp2 - 360) / 2;
  const T = 1 - 0.17 * Math.cos((hp - 30) * rad) + 0.24 * Math.cos(2 * hp * rad) + 0.32 * Math.cos((3 * hp + 6) * rad) - 0.2 * Math.cos((4 * hp - 63) * rad);
  const SL = 1 + (0.015 * (Lp - 50) ** 2) / Math.sqrt(20 + (Lp - 50) ** 2), SC = 1 + 0.045 * Cp, SH = 1 + 0.015 * Cp * T;
  const RT = -2 * Math.sqrt(Cp ** 7 / (Cp ** 7 + 25 ** 7)) * Math.sin(60 * Math.exp(-(((hp - 275) / 25) ** 2)) * rad);
  const vL = dL / SL, vC = dC / SC, vH = dH / SH;
  return { total: Math.sqrt(Math.max(0, vL ** 2 + vC ** 2 + vH ** 2 + RT * vC * vH)), dL: vL, dC: vC, dH: vH };
};
const clamp = (v, min, max) => Math.min(max, Math.max(min, v));
const num = (v, d = NaN) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
};
const mean = (arr) => (arr.length ? arr.reduce((s, v) => s + v, 0) / arr.length : 0);
const grade = (v) => (v < 0.5 ? ["Perfect", "#0ff0b4"] : v < 1 ? ["Excellent", "#34d399"] : v < 2 ? ["Good", "#a3e635"] : v < 3 ? ["Acceptable", "#fbbf24"] : v < 5 ? ["Need Tune", "#fb923c"] : ["Out", "#ef4444"]);
const T = { bg: "#060913", p: "#0f1628", b: "#24384f", tx: "#e7f2ff", dim: "#8ea3c0", m: "#4f6380", a: "#4cc9ff", w: "#f6ad55", r: "#ff7ab8", g: "#4ade80", rd: "#ff5d73", mono: "'IBM Plex Mono','JetBrains Mono',monospace", font: "'Outfit','Noto Sans SC',system-ui,sans-serif" };
const glow = (c, s = 10) => `0 0 ${s}px ${c}30,0 0 ${2 * s}px ${c}10`;
const tabs = [{ id: "overview", n: "Overview", c: T.a }, { id: "spc", n: "SPC", c: "#22d3ee" }, { id: "texture", n: "Texture", c: T.w }, { id: "spectral", n: "Spectral", c: "#a78bfa" }, { id: "aging", n: "Aging", c: T.r }, { id: "ink", n: "Ink", c: "#818cf8" }, { id: "observer", n: "Observer", c: "#f472b6" }, { id: "drift", n: "Drift", c: T.w }, { id: "blend", n: "Blend", c: "#22d3ee" }, { id: "supplier", n: "Supplier", c: "#fbbf24" }, { id: "shift", n: "Shift", c: T.g }, { id: "passport", n: "Passport", c: "#a78bfa" }];
const roleProfiles = {
  operator: { key: "operator", name: "操作工", color: T.g, tabs: ["overview", "ink", "drift", "passport"], mission: "先稳住产线，再做最小动作修正。" },
  process: { key: "process", name: "工艺", color: T.w, tabs: ["overview", "spc", "texture", "aging", "ink", "drift", "blend"], mission: "优先判断工艺耦合，不盲目调配方。" },
  quality: { key: "quality", name: "质量", color: "#22d3ee", tabs: ["overview", "spc", "spectral", "observer", "supplier", "shift", "passport"], mission: "先确认风险与证据，再决定放行策略。" },
  executive: { key: "executive", name: "老板", color: T.a, tabs: ["overview", "spc", "aging", "drift", "supplier", "shift", "passport"], mission: "关注放行风险、客诉概率与经营后果。" },
};
const focusTabsByRole = {
  operator: ["overview", "ink", "drift"],
  process: ["overview", "spc", "drift"],
  quality: ["overview", "spc", "spectral"],
  executive: ["overview", "spc", "aging"],
};
const NETWORK_TIMEOUT_MS = 14000;
const fallbackSpc = Array.from({ length: 24 }, (_, i) => 1.55 + Math.sin(i / 3) * 0.3 + i * 0.01);
const fallbackDrift = Array.from({ length: 28 }, (_, i) => 1.2 + i * 0.05);
const Panel = ({ t, c, children }) => <section style={{ background: `linear-gradient(180deg,${T.p},${T.bg})`, border: `1px solid ${T.b}`, borderRadius: 14, marginBottom: 14, overflow: "hidden", boxShadow: "inset 0 1px 0 rgba(255,255,255,.03), 0 14px 30px rgba(0,0,0,.24)" }}>{t ? <div style={{ padding: "10px 14px", borderBottom: `1px solid ${T.b}`, display: "flex", alignItems: "center", gap: 8, background: "rgba(6,12,22,.62)" }}><span style={{ width: 6, height: 6, borderRadius: 99, background: c || T.a, boxShadow: glow(c || T.a, 6) }} /><span style={{ fontSize: 11, color: T.dim, letterSpacing: 1, fontWeight: 700, textTransform: "uppercase" }}>{t}</span></div> : null}<div style={{ padding: "14px 16px" }}>{children}</div></section>;
const Tag = ({ t, c }) => <span style={{ display: "inline-block", padding: "2px 8px", borderRadius: 7, border: `1px solid ${(c || T.a)}35`, background: `${c || T.a}12`, color: c || T.a, fontSize: 10, fontWeight: 700 }}>{t}</span>;
const Spark = ({ d, th, c = T.a, h = 90 }) => {
  const arr = Array.isArray(d) && d.length > 1 ? d : [0, 1], mn = Math.min(...arr), mx = Math.max(...arr, Number.isFinite(th) ? th : mn + 1), rg = Math.max(0.0001, mx - mn), w = 320;
  const pts = arr.map((v, i) => `${(i / (arr.length - 1)) * w},${h - ((v - mn) / rg) * h * 0.85 - h * 0.05}`).join(" "), area = `${pts} ${w},${h} 0,${h}`;
  const ty = Number.isFinite(th) ? h - (((th - mn) / rg) * h * 0.85 + h * 0.05) : null;
  return <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none"><defs><linearGradient id={`s_${c.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={c} stopOpacity=".16" /><stop offset="100%" stopColor={c} stopOpacity="0" /></linearGradient></defs><polygon points={area} fill={`url(#s_${c.replace("#", "")})`} />{ty !== null ? <line x1="0" y1={ty} x2={w} y2={ty} stroke={T.rd} strokeDasharray="4,3" opacity=".7" /> : null}<polyline points={pts} fill="none" stroke={c} strokeWidth="2" /></svg>;
};
const Radar = ({ l, c, h, s = 166 }) => {
  const cx = s / 2, cy = s / 2, r = s * 0.34, mx = Math.max(3, Math.ceil(Math.max(Math.abs(l), Math.abs(c), Math.abs(h)) * 1.4));
  const ax = [{ n: "dL", v: Math.abs(l), a: -90 }, { n: "dC", v: Math.abs(c), a: 30 }, { n: "dH", v: Math.abs(h), a: 150 }];
  const p = (a, v) => { const rd = (a * Math.PI) / 180; return { x: cx + (v / mx) * r * Math.cos(rd), y: cy + (v / mx) * r * Math.sin(rd) }; };
  const pts = ax.map((x) => p(x.a, x.v));
  return <svg width={s} height={s} viewBox={`0 0 ${s} ${s}`}>{[.33, .66, 1].map((lv) => { const ring = ax.map((x) => p(x.a, mx * lv)); return <polygon key={lv} points={ring.map((v) => `${v.x},${v.y}`).join(" ")} fill="none" stroke={T.b} strokeWidth=".8" />; })}{ax.map((x) => { const e = p(x.a, mx); return <line key={`a_${x.n}`} x1={cx} y1={cy} x2={e.x} y2={e.y} stroke={T.b} strokeWidth=".8" />; })}<polygon points={pts.map((v) => `${v.x},${v.y}`).join(" ")} fill={`${T.a}22`} stroke={T.a} strokeWidth="2" />{pts.map((v, i) => <circle key={i} cx={v.x} cy={v.y} r="4" fill={T.a} stroke={T.bg} strokeWidth="2" />)}</svg>;
};
const bootDefaults = () => {
  if (typeof window === "undefined") return { dbPath: "", lineId: "", productCode: "", uiRole: "operator", focusMode: true, advancedMode: false };
  const b = window.__SENIA_OBS_DEFAULTS__ || {}, q = new URLSearchParams(window.location.search || "");
  const role = String(q.get("ui_role") || "operator").toLowerCase();
  const uiRole = roleProfiles[role] ? role : "operator";
  const adv = String(q.get("advanced") || "").toLowerCase();
  const focus = String(q.get("focus") || "").toLowerCase();
  const persistedRaw = (() => {
    try {
      return window.localStorage.getItem("senia_observatory_ui_v1");
    } catch (_err) {
      return "";
    }
  })();
  let persisted = {};
  try {
    persisted = persistedRaw ? JSON.parse(persistedRaw) : {};
  } catch (_err) {
    persisted = {};
  }
  const advancedMode = adv ? adv === "1" || adv === "true" : Boolean(persisted.advancedMode);
  const focusMode = focus ? focus === "1" || focus === "true" : (persisted.focusMode !== undefined ? Boolean(persisted.focusMode) : uiRole === "operator");
  return {
    dbPath: q.get("db_path") || b.dbPath || "",
    lineId: q.get("line_id") || b.lineId || "",
    productCode: q.get("product_code") || b.productCode || "",
    uiRole,
    focusMode,
    advancedMode,
  };
};
const agingMat = (m) => (m === "wood" ? "melamine" : m === "stone" ? "hpl" : m === "metallic" ? "uv_coating" : "pvc_film");
const agingEnv = (e) => (e === "outdoor_exposed" ? "outdoor_exposed" : e === "indoor_window" ? "indoor_window" : "indoor_normal");
const blendBatches = (lab) => [{ batch_id: "B001", lab: { L: +(lab.L - 0.8).toFixed(3), a: +(lab.a - 0.4).toFixed(3), b: +(lab.b - 0.5).toFixed(3) }, quantity: 980 }, { batch_id: "B002", lab: { L: +(lab.L + 0.3).toFixed(3), a: +(lab.a + 0.1).toFixed(3), b: +(lab.b + 0.3).toFixed(3) }, quantity: 860 }, { batch_id: "B003", lab: { L: +(lab.L + 0.9).toFixed(3), a: +(lab.a + 0.4).toFixed(3), b: +(lab.b + 0.8).toFixed(3) }, quantity: 910 }, { batch_id: "B004", lab: { L: +(lab.L - 1.2).toFixed(3), a: +(lab.a - 0.6).toFixed(3), b: +(lab.b - 0.8).toFixed(3) }, quantity: 740 }, { batch_id: "B005", lab: { L: +(lab.L + 1.4).toFixed(3), a: +(lab.a + 0.6).toFixed(3), b: +(lab.b + 1.2).toFixed(3) }, quantity: 680 }];
const perObs = (p) => {
  const x = p && p.per_observer && typeof p.per_observer === "object" ? p.per_observer : null;
  if (!x) return [];
  return Object.keys(x).map((k) => ({ k, n: x[k].name || k, de: num(x[k].de, NaN), dv: num(x[k].delta_vs_standard, 0) })).filter((r) => Number.isFinite(r.de)).sort((a, b) => b.de - a.de);
};
export default function EliteObservatory() {
  const dft = useMemo(() => bootDefaults(), []);
  const [tab, setTab] = useState("overview");
  const [sample, setSample] = useState({ r: 158, g: 149, b: 131 });
  const [film, setFilm] = useState({ r: 164, g: 152, b: 129 });
  const [mat, setMat] = useState("wood");
  const [env, setEnv] = useState("indoor_window");
  const [showCfg, setShowCfg] = useState(false);
  const [auto, setAuto] = useState(true);
  const [advancedMode, setAdvancedMode] = useState(Boolean(dft.advancedMode));
  const [focusMode, setFocusMode] = useState(Boolean(dft.focusMode));
  const [uiRole, setUiRole] = useState(dft.uiRole);
  const [cfg, setCfg] = useState({ dbPath: dft.dbPath, lineId: dft.lineId, productCode: dft.productCode, apiKey: "", window: 160, subgroup: 5, driftTh: 3 });
  const [live, setLive] = useState({ hBusy: false, aBusy: false, hErr: "", aErr: "", hAt: "", aAt: "", cockpit: null, nba: null, spc: null, drift: null, shift: null, supplier: null, waiverHealth: null, texture: null, spectral: null, observer: null, aging: null, ink: null, blend: null, passport: null });
  const hs = useRef(0), as = useRef(0);

  const sLab = useMemo(() => rgbToLab(sample.r, sample.g, sample.b), [sample]);
  const fLab = useMemo(() => rgbToLab(film.r, film.g, film.b), [film]);
  const de = useMemo(() => de2000(sLab, fLab), [sLab, fLab]);
  const [gl, gc] = useMemo(() => grade(de.total), [de.total]);
  const roleProfile = useMemo(() => roleProfiles[uiRole] || roleProfiles.operator, [uiRole]);
  const headers = useMemo(() => ({ Accept: "application/json", ...(cfg.apiKey.trim() ? { "x-api-key": cfg.apiKey.trim() } : {}) }), [cfg.apiKey]);
  const visibleTabs = useMemo(
    () => {
      if (advancedMode) return tabs;
      const base = focusMode ? (focusTabsByRole[uiRole] || roleProfile.tabs) : roleProfile.tabs;
      return tabs.filter((x) => base.includes(x.id));
    },
    [advancedMode, focusMode, roleProfile, uiRole]
  );

  const request = useCallback(async (path, opts = {}) => {
    const h = { ...headers };
    let body;
    if (opts.body !== undefined) { h["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
    const timeoutMs = Number.isFinite(Number(opts.timeoutMs)) ? Math.max(3000, Number(opts.timeoutMs)) : NETWORK_TIMEOUT_MS;
    const runOnce = async () => {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), timeoutMs);
      try {
        const resp = await fetch(path, { method: opts.method || "GET", headers: h, body, signal: ctl.signal });
        const txt = await resp.text();
        let p = {};
        try {
          p = txt ? JSON.parse(txt) : {};
        } catch (_e) {
          throw new Error(`bad json ${path}`);
        }
        if (!resp.ok) throw new Error(typeof p.detail === "string" ? p.detail : `${resp.status} ${resp.statusText}`);
        return p;
      } finally {
        clearTimeout(timer);
      }
    };
    try {
      return await runOnce();
    } catch (err) {
      const msg = String(err?.message || err || "");
      const retryable = msg.includes("Failed to fetch") || msg.includes("NetworkError") || msg.includes("aborted");
      if (!retryable || opts.noRetry) throw err;
      return runOnce();
    }
  }, [headers]);

  const q = useCallback((extra = {}) => {
    const p = new URLSearchParams(); p.set("window", String(clamp(num(cfg.window, 160), 20, 2000)));
    if (cfg.dbPath.trim()) p.set("db_path", cfg.dbPath.trim());
    if (cfg.lineId.trim()) p.set("line_id", cfg.lineId.trim());
    if (cfg.productCode.trim()) p.set("product_code", cfg.productCode.trim());
    Object.keys(extra).forEach((k) => p.set(k, String(extra[k]))); return p.toString();
  }, [cfg.dbPath, cfg.lineId, cfg.productCode, cfg.window]);

  const refreshHistory = useCallback(async (silent = false) => {
    const id = ++hs.current; if (!silent) setLive((x) => ({ ...x, hBusy: true, hErr: "" }));
    const waiverLot = (cfg.productCode || cfg.lineId || "OBS-LIVE").toUpperCase().replace(/[^A-Z0-9_-]/g, "").slice(0, 32) || "OBS-LIVE";
    const rs = await Promise.allSettled([
      request(`/v1/system/cockpit-snapshot?${q({ weekly_window: 500 })}`),
      request(`/v1/system/next-best-action?${q({ weekly_window: 500 })}`),
      request(`/v1/quality/spc/from-history?${q({ subgroup_size: clamp(num(cfg.subgroup, 5), 2, 10) })}`),
      request(`/v1/history/drift-prediction?${q({ threshold: clamp(num(cfg.driftTh, 3), 0.5, 10) })}`),
      request(`/v1/report/shift/from-history?${q()}`),
      request("/v1/supplier/scorecard"),
      request(`/v1/lifecycle/decision/waiver-health?lot_id=${encodeURIComponent(waiverLot)}&target_state=hold_for_review`),
    ]);
    if (id !== hs.current) return;
    const names = ["cockpit", "nba", "spc", "drift", "shift", "supplier", "waiverHealth"], nx = {}, errs = [];
    rs.forEach((r, i) => { if (r.status === "fulfilled") nx[names[i]] = r.value; else errs.push(`${names[i]}: ${String(r.reason?.message || r.reason || "error")}`); });
    setLive((x) => ({ ...x, ...nx, hBusy: false, hAt: new Date().toLocaleString(), hErr: errs.join(" | ") }));
  }, [cfg.driftTh, cfg.lineId, cfg.productCode, cfg.subgroup, q, request]);

  const refreshAlgo = useCallback(async (silent = false) => {
    const id = ++as.current; if (!silent) setLive((x) => ({ ...x, aBusy: true, aErr: "" }));
    const lot = `LOT-${(cfg.productCode || "OBS").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 10) || "OBS"}-${Date.now().toString().slice(-5)}`;
    const report = { mode: "observatory_live", result: { summary: { avg_delta_e00: +de.total.toFixed(4), p95_delta_e00: +(de.total * 1.16).toFixed(4), dL: +de.dL.toFixed(4), dC: +de.dC.toFixed(4), dH_deg: +de.dH.toFixed(4), sample_lab: { L: +sLab.L.toFixed(4), a: +sLab.a.toFixed(4), b: +sLab.b.toFixed(4) }, film_lab: { L: +fLab.L.toFixed(4), a: +fLab.a.toFixed(4), b: +fLab.b.toFixed(4) }, board_std: 12, sample_std: 15 }, confidence: { overall: .9 } }, profile: { used: mat }, preprocess: { shading_correction: true }, alignment: { correlation: .9 }, decision_center: { decision_code: "AUTO_RELEASE" } };
    const rs = await Promise.allSettled([request("/v1/analyze/spectral", { method: "POST", body: { sample_rgb: [sample.r, sample.g, sample.b], film_rgb: [film.r, film.g, film.b] } }), request("/v1/analyze/texture-aware", { method: "POST", body: { standard_delta_e: +de.total.toFixed(4), sample_texture_std: 12, film_texture_std: 15, texture_similarity: .9, material_type: mat } }), request("/v1/analyze/multi-observer", { method: "POST", body: { sample_lab: { L: +sLab.L.toFixed(4), a: +sLab.a.toFixed(4), b: +sLab.b.toFixed(4) }, film_lab: { L: +fLab.L.toFixed(4), a: +fLab.a.toFixed(4), b: +fLab.b.toFixed(4) }, standard_delta_e: +de.total.toFixed(4), target_age: 75, sensitivity: "high" } }), request("/v1/predict/aging", { method: "POST", body: { lab: { L: +fLab.L.toFixed(4), a: +fLab.a.toFixed(4), b: +fLab.b.toFixed(4) }, material: agingMat(mat), environment: agingEnv(env), years: [1, 3, 5, 10, 15] } }), request("/v1/correct/ink-recipe", { method: "POST", body: { dL: +de.dL.toFixed(4), dC: +de.dC.toFixed(4), dH: +de.dH.toFixed(4), confidence: .9 } }), request("/v1/optimize/batch-blend", { method: "POST", body: { batches: blendBatches(fLab), n_groups: 2, customer_tiers: ["VIP", "standard"] } }), request("/v1/passport/generate", { method: "POST", body: { lot_id: lot, report } })]);
    if (id !== as.current) return;
    const names = ["spectral", "texture", "observer", "aging", "ink", "blend", "passport"], nx = {}, errs = [];
    rs.forEach((r, i) => { if (r.status === "fulfilled") nx[names[i]] = r.value; else errs.push(`${names[i]}: ${String(r.reason?.message || r.reason || "error")}`); });
    setLive((x) => ({ ...x, ...nx, aBusy: false, aAt: new Date().toLocaleString(), aErr: errs.join(" | ") }));
  }, [cfg.productCode, de, env, fLab, film, mat, request, sLab, sample]);

  const refreshAll = useCallback(() => { refreshHistory(); refreshAlgo(); }, [refreshAlgo, refreshHistory]);
  useEffect(() => { refreshAll(); }, [refreshAll]);
  useEffect(() => {
    if (!visibleTabs.some((x) => x.id === tab)) {
      setTab((visibleTabs[0] || { id: "overview" }).id);
    }
  }, [tab, visibleTabs]);
  useEffect(() => {
    const payload = { uiRole, focusMode, advancedMode };
    try {
      window.localStorage.setItem("senia_observatory_ui_v1", JSON.stringify(payload));
    } catch (_err) {
    }
    if (typeof window !== "undefined") {
      const qs = new URLSearchParams(window.location.search || "");
      qs.set("ui_role", uiRole);
      qs.set("focus", focusMode ? "1" : "0");
      qs.set("advanced", advancedMode ? "1" : "0");
      window.history.replaceState({}, "", `${window.location.pathname}?${qs.toString()}`);
    }
  }, [advancedMode, focusMode, uiRole]);
  useEffect(() => {
    if (advancedMode) return;
    if (uiRole === "operator" && !focusMode) setFocusMode(true);
  }, [advancedMode, focusMode, uiRole]);
  useEffect(() => { if (!auto) return undefined; const t = setInterval(() => refreshHistory(true), 20000); return () => clearInterval(t); }, [auto, refreshHistory]);
  useEffect(() => { const t = setTimeout(() => refreshAlgo(true), 500); return () => clearTimeout(t); }, [refreshAlgo]);

  const busy = live.hBusy || live.aBusy, err = [live.hErr, live.aErr].filter(Boolean).join(" | ");
  const cockpit = live.cockpit?.cockpit || {}, nba = live.nba?.recommended_action || {}, signals = live.nba?.signals || {};
  const warn = String(cockpit.warning_level || signals.warning_level || "unknown").toUpperCase(), warnC = warn === "GREEN" ? T.g : warn === "YELLOW" || warn === "ORANGE" ? T.w : T.rd;
  const risk = num(cockpit.risk_index_0_100, num(signals.risk_index_0_100, 0)), autoRelease = num(cockpit.auto_release_rate, num(signals.auto_release_rate, 0)), complaint = num(cockpit.complaint_rate, num(signals.complaint_rate, 0)), saving = num(cockpit.annual_saving_cny, 0);
  const waiver = live.waiverHealth?.result || {}, waiverStatus = String(waiver.status || "unknown").toLowerCase(), waiverRequired = Boolean(waiver.waiver_required), waiverAction = String(waiver.next_action || "");
  const waiverC = waiverStatus === "approved" ? T.g : waiverStatus === "not_required" ? T.a : waiverStatus === "missing" ? T.rd : waiverStatus === "invalid" ? T.rd : T.w;
  const spcR = live.spc?.result || {}, spcV = (spcR.xbar?.values || fallbackSpc).slice(-30), spcM = num(spcR.xbar?.mean, mean(spcV)), spcU = num(spcR.xbar?.ucl, spcM + .6), spcL = num(spcR.xbar?.lcl, Math.max(0, spcM - .6)), cp = num(spcR.capability?.Cp, 1.2), cpk = num(spcR.capability?.Cpk, 1.1), ppm = num(spcR.capability?.ppm_est, 120), grd = String(spcR.capability?.grade || "B").replace("_", " ");
  const dPred = live.drift?.prediction || {}, driftF = Array.isArray(dPred.forecast_next_5) && dPred.forecast_next_5.length ? dPred.forecast_next_5 : fallbackDrift.slice(-5), driftS = spcV.slice(-20).concat(driftF), driftB = num(dPred.batches_remaining, 8), slope = num(dPred.slope_per_batch, .042), urg = String(dPred.urgency || "high").toUpperCase(), dRec = String(dPred.recommendation || "Monitor trend and schedule correction before threshold.");
  const sh = live.shift?.report || {}, shs = sh.summary || {}, dec = sh.decisions || {};
  const sumLike = (kw) => Object.keys(dec).filter((k) => k.toUpperCase().includes(kw)).reduce((s, k) => s + num(dec[k], 0), 0);
  const sTotal = num(shs.total_runs, 0), sPass = num(shs.pass_rate, 0), sDe = num(shs.avg_de, de.total), sAuto = sumLike("AUTO"), sMan = sumLike("MANUAL"), sRecap = sumLike("RECAPTURE"), sHold = sumLike("HOLD");
  const sup = Array.isArray(live.supplier?.suppliers) && live.supplier.suppliers.length ? live.supplier.suppliers : [{ id: "SUP-A", grade: "A", score: 91.2, avg_de: 1.38, std_de: .28, count: 86, trend: "stable", pass_rate: 98.2 }, { id: "SUP-B", grade: "B", score: 74.5, avg_de: 2.01, std_de: .45, count: 63, trend: "improving", pass_rate: 91.5 }];
  const tex = live.texture || {}, tDe = num(tex.texture_adjusted_deltaE, de.total * .8), tMask = num(tex.masking_factor, .72), tCx = num(tex.texture_complexity, 13.5), tImp = num(tex.impact_percent, ((tDe / Math.max(de.total, .001) - 1) * 100));
  const sp = live.spectral || {}, mi = num(sp.metamerism_index, .58), riskLv = String(sp.risk_level || "medium").toUpperCase(), ill = sp.per_illuminant && typeof sp.per_illuminant === "object" ? sp.per_illuminant : { D65: .9, A: .6, TL84: .7, LED_4000K: .75 };
  const obs = perObs(live.observer?.simulation || null), obsV = obs.length ? obs : [{ k: "std", n: "Standard", de: +de.total.toFixed(2), dv: 0 }, { k: "e75", n: "Elderly 75+", de: +(de.total * 1.28).toFixed(2), dv: +(de.total * .28).toFixed(2) }, { k: "deut", n: "Deuteranomaly", de: +(de.total * 1.05).toFixed(2), dv: +(de.total * .05).toFixed(2) }];
  const ag = live.aging || {}, agV = Array.isArray(ag.predictions) && ag.predictions.length ? ag.predictions : [1, 3, 5, 10, 15].map((y) => ({ year: y, deltaE_from_original: +(de.total + y * .42).toFixed(3) })), agRisk = ag.warranty_risk || {};
  const ink = live.ink || {}, adj = ink.adjustments || { C: +clamp(-de.dL * .35, -5, 5).toFixed(2), M: +clamp(-de.dC * .25, -5, 5).toFixed(2), Y: +clamp(-de.dH * .18, -5, 5).toFixed(2), K: +clamp(-de.dL * .32, -5, 5).toFixed(2) }, iRes = num(ink.predicted_residual_deltaE, de.total * .3), iSafe = ink.safety_check && typeof ink.safety_check.safe === "boolean" ? ink.safety_check.safe : true;
  const blend = Array.isArray(live.blend?.groups) && live.blend.groups.length ? live.blend.groups : [{ group: 1, customer_tier: "VIP", batches: ["B001", "B003"], max_intra_deltaE: 1.41, total_quantity: 1900 }, { group: 2, customer_tier: "Standard", batches: ["B002", "B004", "B005"], max_intra_deltaE: 2.53, total_quantity: 2550 }];
  const pass = live.passport?.passport || { passport_id: "CP-LOCAL-SIM", lot_id: cfg.productCode || "LOCAL", fingerprint: `${sample.r.toString(16)}${sample.g.toString(16)}${sample.b.toString(16)}${film.r.toString(16)}${film.g.toString(16)}${film.b.toString(16)}`.slice(0, 16), created_at: new Date().toISOString(), deltaE: +de.total.toFixed(3), decision_code: nba.code || "AUTO_RELEASE", confidence: num(nba.confidence, .9), verification_hash: "local-preview", conditions: { illuminant: "D65", camera_id: "preview" }, lab_values: { sample: { L: +sLab.L.toFixed(2), a: +sLab.a.toFixed(2), b: +sLab.b.toFixed(2) } } };
  const canShowScope = advancedMode || uiRole === "process" || uiRole === "quality";
  const roleActions = useMemo(() => {
    if (uiRole === "operator") {
      return {
        primary: warn === "GREEN" ? "继续生产并按节拍抽检" : "先复测并暂停自动放行",
        secondary: `建议先执行 ${nba.code || "RUN_OPS_CHECK"}，再决定是否调墨`,
        avoid: "不要连续多次加减墨，先确认采样与光源一致。",
      };
    }
    if (uiRole === "process") {
      return {
        primary: risk >= 70 ? "先查工艺耦合，再评估配方动作" : "先做SPC趋势判断，再优化工艺窗口",
        secondary: `当前Cpk ${cpk.toFixed(2)}，优先处理漂移斜率 ${slope >= 0 ? "+" : ""}${slope.toFixed(4)}`,
        avoid: "不要只看单点色差，避免忽略过程波动。",
      };
    }
    if (uiRole === "quality") {
      return {
        primary: warn === "GREEN" ? "维持放行监控并抽样复核" : "触发人工复核并保留争议证据链",
        secondary: `投诉风险 ${(complaint * 100).toFixed(2)}%，建议同步客诉敏感维度`,
        avoid: "不要在证据不足时直接给最终放行结论。",
      };
    }
    return {
      primary: autoRelease > 0.82 ? "可推进自动放行扩面" : "优先收敛风险再扩大放行",
      secondary: `风险指数 ${risk.toFixed(1)}，预估年化收益 ¥${Math.round(saving).toLocaleString()}`,
      avoid: "不要用业务紧急度覆盖质量事实。",
    };
  }, [uiRole, warn, nba.code, risk, cpk, slope, complaint, autoRelease, saving]);
  const laneSignals = useMemo(() => {
    const rows = [];
    if (warn !== "GREEN") rows.push({ code: "warning_not_green", level: "review", text: `Warning=${warn}` });
    if (risk >= 78) rows.push({ code: "risk_high", level: "block", text: `Risk ${risk.toFixed(1)} >= 78` });
    else if (risk >= 60) rows.push({ code: "risk_medium", level: "review", text: `Risk ${risk.toFixed(1)} >= 60` });
    if (cpk < 1.0) rows.push({ code: "cpk_low", level: "review", text: `Cpk ${cpk.toFixed(2)} < 1.00` });
    if (mi >= 0.8) rows.push({ code: "metamerism_high", level: "block", text: `Metamerism ${mi.toFixed(3)} high` });
    else if (mi >= 0.5) rows.push({ code: "metamerism_mid", level: "review", text: `Metamerism ${mi.toFixed(3)} medium` });
    if (waiverStatus === "missing") rows.push({ code: "waiver_missing", level: "block", text: "State requires waiver but none is valid" });
    else if (waiverStatus === "invalid") rows.push({ code: "waiver_invalid", level: "block", text: "Waiver approval metadata invalid" });
    else if (waiverRequired && waiverStatus === "approved") rows.push({ code: "waiver_approved_manual_release", level: "review", text: "Waiver approved: keep manual review before release" });
    if (urg === "HIGH") rows.push({ code: "drift_high", level: "review", text: "Drift urgency HIGH" });
    if (String(agRisk.level || "").toLowerCase() === "high") rows.push({ code: "aging_high", level: "review", text: "Aging warranty risk HIGH" });
    if (err) rows.push({ code: "pipeline_degraded", level: "review", text: "Pipeline degraded mode" });
    return rows;
  }, [agRisk.level, cpk, err, mi, risk, urg, waiverRequired, waiverStatus, warn]);
  const laneState = useMemo(() => {
    const blocks = laneSignals.filter((x) => x.level === "block");
    const reviews = laneSignals.filter((x) => x.level === "review");
    if (blocks.length) return { key: "MANUAL_ARBITRATION", color: T.rd, text: "Manual Arbitration", desc: "存在硬风险，禁止自动放行。" };
    if (reviews.length >= 2) return { key: "REVIEW_REQUIRED", color: T.w, text: "Review Required", desc: "存在多项风险，建议人工复核。" };
    if (warn === "GREEN" && cpk >= 1.33 && mi < 0.4 && autoRelease > 0.82 && !err) return { key: "AUTO_RELEASE", color: T.g, text: "Auto Release", desc: "风险可控，可自动放行。" };
    return { key: "MONITOR", color: T.a, text: "Monitor", desc: "持续监控并保持采样节拍。" };
  }, [autoRelease, cpk, err, laneSignals, mi, warn]);
  const exportSnapshot = useCallback(() => {
    const payload = {
      exported_at: new Date().toISOString(),
      ui_role: uiRole,
      lane: laneState,
      warnings: laneSignals,
      metrics: {
        warning: warn,
        risk_index: Number(risk.toFixed(3)),
        cpk: Number(cpk.toFixed(3)),
        metamerism_index: Number(mi.toFixed(4)),
        auto_release_rate: Number(autoRelease.toFixed(4)),
        complaint_rate: Number(complaint.toFixed(5)),
        delta_e: Number(de.total.toFixed(4)),
      },
      waiver_gate: {
        status: waiverStatus,
        required: waiverRequired,
        next_action: waiverAction,
        waiver_ids: Array.isArray(waiver.waiver_ids) ? waiver.waiver_ids : [],
      },
      next_action: nba,
      cockpit,
      module_errors: { history: live.hErr || null, algorithm: live.aErr || null },
      raw_modules: {
        spc: live.spc,
        drift: live.drift,
        aging: live.aging,
        spectral: live.spectral,
        ink: live.ink,
        blend: live.blend,
        passport: live.passport,
      },
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    const lotCode = String(cfg.productCode || "OBS").replace(/[^A-Za-z0-9_-]/g, "").slice(0, 18) || "OBS";
    link.download = `observatory_snapshot_${lotCode}_${Date.now()}.json`;
    link.href = URL.createObjectURL(blob);
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }, [autoRelease, cfg.productCode, cpk, cockpit, complaint, de.total, laneSignals, laneState, live.aErr, live.aging, live.blend, live.drift, live.hErr, live.ink, live.passport, live.spc, live.spectral, mi, nba, risk, uiRole, waiver.waiver_ids, waiverAction, waiverRequired, waiverStatus, warn]);

  const inp = { width: "100%", border: `1px solid ${T.b}`, background: "rgba(8,14,26,.86)", color: T.tx, borderRadius: 6, padding: "6px 8px", fontSize: 11, fontFamily: T.mono, boxShadow: "inset 0 1px 0 rgba(255,255,255,.03)" };
  const setRgb = (which, ch, v) => which === "s" ? setSample((x) => ({ ...x, [ch]: clamp(num(v, 0), 0, 255) })) : setFilm((x) => ({ ...x, [ch]: clamp(num(v, 0), 0, 255) }));
  const setCfgF = (k, v) => setCfg((x) => ({ ...x, [k]: v }));
  return <div style={{ minHeight: "100vh", background: `radial-gradient(1100px 560px at 12% -8%, rgba(76,201,255,.16), transparent 60%), radial-gradient(1000px 500px at 88% 0%, rgba(255,122,184,.12), transparent 60%), ${T.bg}`, color: T.tx, fontFamily: T.font }}>
    <header style={{ position: "sticky", top: 0, zIndex: 3, background: `linear-gradient(180deg,rgba(13,22,38,.96),rgba(6,9,19,.88))`, backdropFilter: "blur(8px)", padding: "14px 16px 10px", borderBottom: `1px solid ${T.b}` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><div style={{ display: "flex", gap: 10, alignItems: "center" }}><div style={{ width: 34, height: 34, borderRadius: 8, background: `linear-gradient(135deg,${T.a},#818cf8,${T.r})`, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: glow(T.a) }}><span style={{ fontWeight: 900, color: "#fff" }}>SE</span></div><div><div style={{ fontSize: 16, fontWeight: 800 }}>SENIA Elite Observatory</div><div style={{ fontSize: 8, color: T.m, letterSpacing: 2.4 }}>PRECISION COLOR INTELLIGENCE CONSOLE</div></div></div><Tag t={busy ? "SYNCING" : err ? "DEGRADED" : "LIVE"} c={busy ? T.w : err ? T.rd : T.g} /></div>
      <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6, overflowX: "auto" }}>{Object.keys(roleProfiles).map((k) => { const r = roleProfiles[k]; return <button key={k} onClick={() => setUiRole(k)} style={{ padding: "6px 10px", borderRadius: 6, border: `1px solid ${uiRole === k ? `${r.color}75` : T.b}`, background: uiRole === k ? `${r.color}1f` : "rgba(9,13,22,.6)", color: uiRole === k ? r.color : T.dim, fontSize: 10, fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap" }}>{r.name}</button>; })}<span style={{ marginLeft: "auto", fontSize: 10, color: T.dim, whiteSpace: "nowrap" }}>{roleProfile.mission}</span></div>
      <div style={{ marginTop: 10, display: "flex", gap: 4, overflowX: "auto" }}>{visibleTabs.map((x) => <button key={x.id} onClick={() => setTab(x.id)} style={{ padding: "6px 10px", borderRadius: 6, border: `1px solid ${tab === x.id ? `${x.c}65` : T.b}`, background: tab === x.id ? `${x.c}1e` : "rgba(9,13,22,.6)", color: tab === x.id ? x.c : T.dim, fontSize: 10, fontWeight: 700, whiteSpace: "nowrap", cursor: "pointer" }}>{x.n}</button>)}<button onClick={() => setFocusMode((v) => !v)} disabled={advancedMode} style={{ marginLeft: "auto", padding: "6px 10px", borderRadius: 6, border: `1px solid ${focusMode ? `${T.a}65` : T.b}`, background: focusMode ? `${T.a}14` : "rgba(9,13,22,.6)", color: focusMode ? T.a : T.dim, fontSize: 10, fontWeight: 700, whiteSpace: "nowrap", cursor: advancedMode ? "not-allowed" : "pointer", opacity: advancedMode ? .45 : 1 }}>{focusMode ? "Focused" : "Role Tabs"}</button><button onClick={() => setAdvancedMode((v) => !v)} style={{ padding: "6px 10px", borderRadius: 6, border: `1px solid ${advancedMode ? `${T.w}65` : T.b}`, background: advancedMode ? `${T.w}18` : "rgba(9,13,22,.6)", color: advancedMode ? T.w : T.dim, fontSize: 10, fontWeight: 700, whiteSpace: "nowrap", cursor: "pointer" }}>{advancedMode ? "Core Tabs" : "More Tabs"}</button></div>
    </header>
    <main style={{ maxWidth: "1480px", margin: "0 auto", padding: "12px 16px 24px" }}>
      <Panel t="Role Command" c={roleProfile.color}><div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr", gap: 8 }}><div style={{ border: `1px solid ${T.b}`, borderRadius: 8, background: T.bg, padding: "8px 10px" }}><div style={{ fontSize: 9, color: T.dim, marginBottom: 4 }}>Primary Action</div><div style={{ fontSize: 12, color: roleProfile.color, fontWeight: 700 }}>{roleActions.primary}</div></div><div style={{ border: `1px solid ${T.b}`, borderRadius: 8, background: T.bg, padding: "8px 10px" }}><div style={{ fontSize: 9, color: T.dim, marginBottom: 4 }}>Secondary</div><div style={{ fontSize: 11, color: T.tx }}>{roleActions.secondary}</div></div><div style={{ border: `1px solid ${T.b}`, borderRadius: 8, background: T.bg, padding: "8px 10px" }}><div style={{ fontSize: 9, color: T.dim, marginBottom: 4 }}>Do Not</div><div style={{ fontSize: 11, color: T.w }}>{roleActions.avoid}</div><div style={{ marginTop: 6, fontSize: 9, color: T.m }}>Scope panel: {canShowScope ? "enabled" : "hidden in this role"}</div></div></div></Panel>
      <Panel t="Decision Lane" c={laneState.color}><div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 8 }}><div style={{ border: `1px solid ${laneState.color}35`, borderRadius: 8, background: `${laneState.color}10`, padding: "8px 10px" }}><div style={{ fontSize: 9, color: T.dim, marginBottom: 4 }}>Current Lane</div><div style={{ fontSize: 16, color: laneState.color, fontWeight: 800, fontFamily: T.mono }}>{laneState.text}</div><div style={{ marginTop: 4, fontSize: 10, color: T.tx }}>{laneState.desc}</div><div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>{laneSignals.length ? laneSignals.slice(0, 4).map((x) => <Tag key={x.code} t={x.code} c={x.level === "block" ? T.rd : T.w} />) : <Tag t="no-major-conflict" c={T.g} />}</div></div><div style={{ border: `1px solid ${T.b}`, borderRadius: 8, background: T.bg, padding: "8px 10px", display: "flex", flexDirection: "column", gap: 8 }}><button onClick={exportSnapshot} style={{ border: `1px solid ${T.a}35`, background: `${T.a}14`, color: T.a, borderRadius: 8, padding: "7px 10px", fontSize: 11, fontWeight: 700, cursor: "pointer" }}>Export Snapshot JSON</button><div style={{ fontSize: 10, color: T.dim }}>Top evidence: {(laneSignals[0] && laneSignals[0].text) || "No blocking signal"}</div><div style={{ fontSize: 9, color: T.m }}>Lane key: {laneState.key}</div><div style={{ marginTop: 4, borderTop: `1px solid ${T.b}`, paddingTop: 6, fontSize: 10, color: T.dim }}>Waiver Gate: <span style={{ color: waiverC, fontWeight: 700, textTransform: "uppercase" }}>{waiverStatus}</span></div><div style={{ fontSize: 9, color: T.m }}>{waiverAction || "follow_standard_release_gate"}</div></div></div></Panel>
      <Panel t="Smart Control" c={busy ? T.w : err ? T.rd : T.g}><div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginBottom: 10 }}><Tag t={`History: ${live.hAt || "--"}`} c={T.a} /><Tag t={`AI: ${live.aAt || "--"}`} c={T.r} /><button onClick={refreshAll} style={{ marginLeft: "auto", border: `1px solid ${T.a}35`, background: `${T.a}14`, color: T.a, borderRadius: 8, padding: "6px 10px", fontSize: 11, fontWeight: 700, cursor: "pointer" }}>Refresh Full Pipeline</button><button onClick={() => setAuto((v) => !v)} style={{ border: `1px solid ${auto ? `${T.g}45` : T.b}`, background: auto ? `${T.g}14` : T.bg, color: auto ? T.g : T.dim, borderRadius: 8, padding: "6px 10px", fontSize: 11, fontWeight: 700, cursor: "pointer" }}>Auto {auto ? "On" : "Off"}</button>{canShowScope ? <button onClick={() => setShowCfg((v) => !v)} style={{ border: `1px solid ${T.b}`, background: T.bg, color: T.dim, borderRadius: 8, padding: "6px 10px", fontSize: 11, fontWeight: 700, cursor: "pointer" }}>{showCfg ? "Hide Scope" : "Show Scope"}</button> : null}</div>{err ? <div style={{ fontSize: 10, color: T.rd, marginBottom: 8 }}>Degraded mode: {err}</div> : null}{showCfg ? <div style={{ display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 8 }}><div style={{ gridColumn: "1 / span 2" }}><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>History DB Path</div><input value={cfg.dbPath} onChange={(e) => setCfgF("dbPath", e.target.value)} style={inp} /></div><div><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>Line ID</div><input value={cfg.lineId} onChange={(e) => setCfgF("lineId", e.target.value)} style={inp} /></div><div><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>Product Code</div><input value={cfg.productCode} onChange={(e) => setCfgF("productCode", e.target.value)} style={inp} /></div><div><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>API Key</div><input value={cfg.apiKey} onChange={(e) => setCfgF("apiKey", e.target.value)} style={inp} /></div><div><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>Window</div><input type="number" min={20} max={2000} value={cfg.window} onChange={(e) => setCfgF("window", e.target.value)} style={inp} /></div><div><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>Subgroup</div><input type="number" min={2} max={10} value={cfg.subgroup} onChange={(e) => setCfgF("subgroup", e.target.value)} style={inp} /></div><div><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>Drift Th</div><input type="number" min={0.5} max={10} step={0.1} value={cfg.driftTh} onChange={(e) => setCfgF("driftTh", e.target.value)} style={inp} /></div></div> : null}</Panel>
      <Panel t="Sampling Cockpit" c={gc}><div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>{["s", "f"].map((k) => <div key={k} style={{ border: `1px solid ${T.b}`, borderRadius: 8, padding: 8, background: T.bg }}><div style={{ fontSize: 10, color: T.dim, marginBottom: 6 }}>{k === "s" ? "Sample RGB" : "Film RGB"}</div>{["r", "g", "b"].map((ch) => <div key={`${k}_${ch}`} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}><span style={{ width: 12, fontSize: 10, color: T.dim, textTransform: "uppercase" }}>{ch}</span><input type="number" min={0} max={255} value={(k === "s" ? sample : film)[ch]} onChange={(e) => setRgb(k, ch, e.target.value)} style={{ ...inp, padding: "4px 6px" }} /></div>)}</div>)}</div><div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 16 }}><div style={{ width: 46, height: 46, borderRadius: 10, background: `rgb(${sample.r},${sample.g},${sample.b})`, border: `2px solid ${T.a}50`, boxShadow: `0 4px 20px rgba(${sample.r},${sample.g},${sample.b},.25)` }} /><div style={{ width: 34, height: 14, borderRadius: 8, background: `linear-gradient(90deg,rgb(${sample.r},${sample.g},${sample.b}),rgb(${film.r},${film.g},${film.b}))`, border: `1px solid ${T.b}` }} /><div style={{ width: 46, height: 46, borderRadius: 10, background: `rgb(${film.r},${film.g},${film.b})`, border: `2px solid ${T.r}50`, boxShadow: `0 4px 20px rgba(${film.r},${film.g},${film.b},.25)` }} /><div style={{ textAlign: "center", marginLeft: 6 }}><div style={{ fontSize: 34, fontWeight: 900, color: gc, fontFamily: T.mono, lineHeight: 1, textShadow: glow(gc, 7) }}>{de.total.toFixed(2)}</div><div style={{ fontSize: 9, color: T.dim }}>DeltaE - {gl}</div></div></div></Panel>
      {tab === "overview" ? <><Panel t="Decision Core" c={gc}><div style={{ display: "flex", gap: 14, alignItems: "center" }}><Radar l={de.dL} c={de.dC} h={de.dH} /><div style={{ flex: 1 }}><div style={{ marginBottom: 6, fontSize: 10, color: T.dim }}>Next Action</div><Tag t={nba.code || "RUN_OPS_CHECK"} c={warnC} /> <Tag t={`confidence ${num(nba.confidence, .8).toFixed(2)}`} c={T.a} /><div style={{ marginTop: 8, fontSize: 10, color: T.dim }}>{(Array.isArray(nba.reasons) && nba.reasons.length ? nba.reasons.slice(0, 2) : ["Balanced state detected, keep monitoring trend."]).join(" | ")}</div></div></div></Panel><Panel t="System Snapshot" c={T.a}><div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 6 }}>{[{ k: "Warning", v: warn, c: warnC }, { k: "Risk", v: risk.toFixed(1), c: risk < 45 ? T.g : risk < 70 ? T.w : T.rd }, { k: "Auto Release", v: `${(autoRelease * 100).toFixed(1)}%`, c: autoRelease > .82 ? T.g : T.w }, { k: "Complaint", v: `${(complaint * 100).toFixed(2)}%`, c: complaint < .03 ? T.g : T.w }, { k: "Annual Saving", v: `¥${Math.round(saving).toLocaleString()}`, c: T.g }, { k: "SPC Cpk", v: cpk.toFixed(2), c: cpk >= 1.33 ? T.g : cpk >= 1 ? "#a3e635" : T.rd }].map((x) => <div key={x.k} style={{ padding: "8px 10px", borderRadius: 8, border: `1px solid ${T.b}`, background: T.bg }}><div style={{ fontSize: 8, color: T.m, marginBottom: 3 }}>{x.k}</div><div style={{ fontSize: 15, color: x.c, fontWeight: 800, fontFamily: T.mono }}>{x.v}</div></div>)}</div></Panel></> : null}
      {tab === "spc" ? <Panel t="SPC Control" c="#22d3ee"><div style={{ display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 8, marginBottom: 10 }}><div><div style={{ fontSize: 22, color: cpk >= 1.33 ? T.g : cpk >= 1 ? "#a3e635" : T.rd, fontWeight: 800, fontFamily: T.mono }}>{cpk.toFixed(2)}</div><div style={{ fontSize: 9, color: T.dim }}>Cpk</div></div><div><div style={{ fontSize: 22, color: "#22d3ee", fontWeight: 800, fontFamily: T.mono }}>{cp.toFixed(2)}</div><div style={{ fontSize: 9, color: T.dim }}>Cp</div></div><div><div style={{ fontSize: 16, color: "#a3e635", fontWeight: 800, fontFamily: T.mono }}>{grd.toUpperCase()}</div><div style={{ fontSize: 9, color: T.dim }}>Grade</div></div><div><div style={{ fontSize: 16, color: T.dim, fontWeight: 800, fontFamily: T.mono }}>{Math.round(ppm)}</div><div style={{ fontSize: 9, color: T.dim }}>PPM</div></div></div><div style={{ background: T.bg, borderRadius: 8, padding: "8px 4px" }}><Spark d={spcV} th={spcU} c="#22d3ee" /><div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontSize: 8, color: T.m }}><span>UCL {spcU.toFixed(2)}</span><span style={{ color: T.g }}>Xbar {spcM.toFixed(2)}</span><span>LCL {spcL.toFixed(2)}</span></div></div><div style={{ marginTop: 8, fontSize: 10, color: spcR.in_control ? T.g : T.w }}>{spcR.in_control ? "In control. Capability improvement is now priority." : "Out-of-control trend. Check root cause and subgroup consistency."}</div></Panel> : null}
      {tab === "texture" ? <Panel t="Texture Aware DeltaE" c={T.w}><div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 16, marginBottom: 14 }}><div style={{ textAlign: "center" }}><div style={{ fontSize: 8, color: T.dim }}>Standard</div><div style={{ fontSize: 22, color: T.dim, fontWeight: 800, fontFamily: T.mono }}>{de.total.toFixed(2)}</div></div><div style={{ color: T.m }}>to</div><div style={{ textAlign: "center" }}><div style={{ fontSize: 8, color: T.w }}>Adjusted</div><div style={{ fontSize: 28, color: grade(tDe)[1], fontWeight: 900, fontFamily: T.mono, textShadow: glow(grade(tDe)[1], 8) }}>{tDe.toFixed(2)}</div></div></div><div style={{ display: "flex", gap: 4, marginBottom: 10 }}>{["solid", "wood", "stone", "metallic"].map((x) => <button key={x} onClick={() => setMat(x)} style={{ flex: 1, border: `1px solid ${mat === x ? `${T.w}35` : T.b}`, borderRadius: 6, padding: "7px 4px", background: mat === x ? `${T.w}12` : T.bg, color: mat === x ? T.w : T.dim, fontSize: 10, fontWeight: 700, cursor: "pointer" }}>{x}</button>)}</div><div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 8 }}><div><div style={{ fontSize: 18, color: T.w, fontFamily: T.mono, fontWeight: 800 }}>{tMask.toFixed(2)}</div><div style={{ fontSize: 9, color: T.dim }}>Masking</div></div><div><div style={{ fontSize: 18, color: T.dim, fontFamily: T.mono, fontWeight: 800 }}>{tCx.toFixed(1)}</div><div style={{ fontSize: 9, color: T.dim }}>Complexity</div></div><div><div style={{ fontSize: 18, color: tImp <= 0 ? T.g : T.rd, fontFamily: T.mono, fontWeight: 800 }}>{tImp.toFixed(0)}%</div><div style={{ fontSize: 9, color: T.dim }}>Impact</div></div></div></Panel> : null}
      {tab === "spectral" ? <Panel t="Spectral Metamerism" c="#a78bfa"><div style={{ textAlign: "center", marginBottom: 12 }}><div style={{ fontSize: 8, color: T.dim }}>Metamerism Index</div><div style={{ fontSize: 35, fontWeight: 900, color: mi < .4 ? T.g : mi < .8 ? T.w : T.rd, fontFamily: T.mono }}>{mi.toFixed(3)}</div><Tag t={`RISK ${riskLv}`} c={riskLv === "LOW" ? T.g : riskLv === "MEDIUM" ? T.w : T.rd} /></div>{Object.keys(ill).map((k) => { const v = num(ill[k], 0), c = v < 1 ? T.g : v < 2 ? T.w : T.rd; return <div key={k} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}><span style={{ width: 80, fontSize: 10, color: T.dim }}>{k}</span><div style={{ flex: 1, height: 4, borderRadius: 6, background: T.m }}><div style={{ width: `${clamp(v / 3 * 100, 0, 100)}%`, height: "100%", borderRadius: 6, background: c }} /></div><span style={{ width: 34, textAlign: "right", fontSize: 11, color: c, fontFamily: T.mono }}>{v.toFixed(3)}</span></div>; })}</Panel> : null}
      {tab === "aging" ? <Panel t="Aging Forecast" c={T.r}><div style={{ display: "flex", gap: 4, marginBottom: 10 }}>{[["indoor_normal", "Indoor"], ["indoor_window", "Window"], ["outdoor_exposed", "Outdoor"]].map(([k, n]) => <button key={k} onClick={() => setEnv(k)} style={{ flex: 1, border: `1px solid ${env === k ? `${T.r}35` : T.b}`, borderRadius: 6, padding: "7px 4px", background: env === k ? `${T.r}12` : T.bg, color: env === k ? T.r : T.dim, fontSize: 10, fontWeight: 700, cursor: "pointer" }}>{n}</button>)}</div>{agV.map((x, i) => { const v = num(x.deltaE_from_original, 0), [lbl, c] = grade(v); return <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}><span style={{ width: 32, fontSize: 11, color: T.dim, fontFamily: T.mono }}>{x.year}y</span><div style={{ flex: 1, height: 5, borderRadius: 6, background: T.m }}><div style={{ width: `${clamp(v / 8 * 100, 0, 100)}%`, height: "100%", borderRadius: 6, background: `linear-gradient(90deg,${c}88,${c})` }} /></div><span style={{ width: 40, textAlign: "right", fontSize: 12, color: c, fontFamily: T.mono }}>{v.toFixed(2)}</span><span style={{ width: 70, fontSize: 8, color: c }}>{lbl}</span></div>; })}<div style={{ marginTop: 8, fontSize: 10, color: String(agRisk.level || "").toLowerCase() === "high" ? T.rd : T.dim }}>{String(agRisk.message || "No warranty breach predicted in current horizon.")}</div></Panel> : null}
      {tab === "ink" ? <Panel t="Auto Ink Recipe" c="#818cf8"><div style={{ fontSize: 10, color: T.dim, marginBottom: 10, fontFamily: T.mono }}>dL={de.dL.toFixed(2)} dC={de.dC.toFixed(2)} dH={de.dH.toFixed(2)}</div><div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>{["C", "M", "Y", "K"].map((ch) => { const v = num(adj[ch], 0), cc = { C: "#06b6d4", M: "#ec4899", Y: "#eab308", K: "#71717a" }[ch]; return <div key={ch} style={{ border: `1px solid ${cc}25`, borderRadius: 9, background: T.bg, padding: "10px 12px" }}><div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}><span style={{ fontSize: 10, color: cc, fontWeight: 700 }}>{ch}</span><span style={{ fontSize: 20, color: v >= 0 ? T.g : T.rd, fontFamily: T.mono, fontWeight: 900 }}>{v > 0 ? "+" : ""}{v.toFixed(2)}%</span></div></div>; })}</div><div style={{ fontSize: 10, color: T.dim }}>Predicted residual DeltaE: <span style={{ color: T.g, fontWeight: 700, fontFamily: T.mono }}>{iRes.toFixed(3)}</span> | Safety: <span style={{ color: iSafe ? T.g : T.rd }}>{iSafe ? "SAFE" : "CHECK LIMIT"}</span></div></Panel> : null}
      {tab === "observer" ? <Panel t="Multi Observer Simulation" c="#f472b6"><div style={{ marginBottom: 10 }}><div style={{ fontSize: 9, color: T.dim }}>Most Sensitive Observer</div><div style={{ fontSize: 27, color: T.w, fontWeight: 900, fontFamily: T.mono, textShadow: glow(T.w) }}>{obsV[0].de.toFixed(2)}</div><Tag t={obsV[0].n} c={T.w} /></div>{obsV.map((o) => { const c = grade(o.de)[1]; return <div key={o.k} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}><div style={{ flex: 1 }}><div style={{ fontSize: 10, color: T.tx, fontWeight: 700 }}>{o.n}</div><div style={{ fontSize: 8, color: T.m }}>delta vs standard {num(o.dv, 0).toFixed(2)}</div></div><div style={{ width: 78, height: 4, borderRadius: 6, background: T.m }}><div style={{ width: `${clamp(o.de / 4 * 100, 0, 100)}%`, height: "100%", borderRadius: 6, background: c }} /></div><span style={{ width: 42, textAlign: "right", color: c, fontFamily: T.mono, fontWeight: 700 }}>{o.de.toFixed(2)}</span></div>; })}</Panel> : null}
      {tab === "drift" ? <Panel t="Drift Predictor" c={T.w}><div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 8, marginBottom: 10 }}><div><div style={{ fontSize: 22, color: T.w, fontFamily: T.mono, fontWeight: 800 }}>{Math.round(driftB)}</div><div style={{ fontSize: 9, color: T.dim }}>Batches Left</div></div><div><div style={{ fontSize: 15, color: "#fbbf24", fontFamily: T.mono, fontWeight: 800 }}>{slope >= 0 ? "+" : ""}{slope.toFixed(4)}</div><div style={{ fontSize: 9, color: T.dim }}>Slope/Batch</div></div><div><div style={{ fontSize: 15, color: urg === "LOW" ? T.g : urg === "MEDIUM" ? T.w : T.rd, fontFamily: T.mono, fontWeight: 800 }}>{urg}</div><div style={{ fontSize: 9, color: T.dim }}>Urgency</div></div></div><div style={{ background: T.bg, borderRadius: 8, padding: "6px 4px", marginBottom: 8 }}><Spark d={driftS} th={num(cfg.driftTh, 3)} c={T.w} /></div><div style={{ fontSize: 10, color: T.w }}>{dRec}</div></Panel> : null}
      {tab === "blend" ? <Panel t="Batch Blend Optimizer" c="#22d3ee"><div style={{ fontSize: 10, color: T.dim, marginBottom: 8 }}>Optimized groups from open algorithm. Same stock, lower complaint risk for priority customers.</div>{blend.map((g) => { const v = num(g.max_intra_deltaE, 0), [lbl, c] = grade(v); return <div key={g.group} style={{ border: `1px solid ${T.b}`, borderRadius: 10, background: T.bg, padding: "10px 12px", marginBottom: 8 }}><div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}><div style={{ display: "flex", gap: 6, alignItems: "center" }}><strong style={{ fontSize: 12 }}>Group {g.group}</strong><Tag t={String(g.customer_tier || "Standard")} c={String(g.customer_tier || "").toUpperCase() === "VIP" ? "#fbbf24" : T.a} /></div><span style={{ color: c, fontWeight: 800, fontFamily: T.mono }}>DeltaE {v.toFixed(2)}</span></div><div style={{ fontSize: 9, color: T.m, fontFamily: T.mono }}>{(Array.isArray(g.batches) ? g.batches : []).join(" | ")} | Qty {Math.round(num(g.total_quantity, 0))} | {lbl}</div></div>; })}</Panel> : null}
      {tab === "supplier" ? <Panel t="Supplier Scorecard" c="#fbbf24">{sup.map((s) => { const g = String(s.grade || "B").toUpperCase(), sc = num(s.score, 0), ad = num(s.avg_de, 0), sd = num(s.std_de, 0), n = Math.round(num(s.count, 0)), pr = num(s.pass_rate, NaN), c = g === "A" ? T.g : g === "B" ? "#a3e635" : g === "C" ? T.w : T.rd; return <div key={s.id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "9px 0", borderBottom: `1px solid ${T.b}` }}><div style={{ width: 34, height: 34, borderRadius: 9, border: `1px solid ${c}35`, background: `${c}15`, display: "flex", alignItems: "center", justifyContent: "center", color: c, fontWeight: 900 }}>{g}</div><div style={{ flex: 1 }}><div style={{ fontSize: 11, fontWeight: 700 }}>{s.id}</div><div style={{ fontSize: 8, color: T.m }}>avg de {ad.toFixed(2)} | sigma {sd.toFixed(2)} | n {n} {Number.isFinite(pr) ? `| pass ${pr.toFixed(1)}%` : ""}</div></div><div style={{ textAlign: "right" }}><div style={{ fontSize: 20, color: c, fontFamily: T.mono, fontWeight: 800 }}>{sc.toFixed(1)}</div><div style={{ fontSize: 8, color: T.m }}>{String(s.trend || "stable")}</div></div></div>; })}<div style={{ marginTop: 8, fontSize: 10, color: T.g }}>Preferred supplier now: {(sup[0] || {}).id || "--"}</div></Panel> : null}
      {tab === "shift" ? <Panel t="Shift Report" c={T.g}><div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 8, marginBottom: 10 }}><div><div style={{ fontSize: 20, fontFamily: T.mono, fontWeight: 800 }}>{Math.round(sTotal)}</div><div style={{ fontSize: 9, color: T.dim }}>Runs</div></div><div><div style={{ fontSize: 22, color: T.g, fontFamily: T.mono, fontWeight: 800 }}>{(sPass * 100).toFixed(1)}%</div><div style={{ fontSize: 9, color: T.dim }}>Pass Rate</div></div><div><div style={{ fontSize: 18, color: "#a3e635", fontFamily: T.mono, fontWeight: 800 }}>{sDe.toFixed(2)}</div><div style={{ fontSize: 9, color: T.dim }}>Avg DeltaE</div></div></div><div style={{ display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 5, marginBottom: 8 }}>{[{ n: "Auto", v: sAuto, c: T.g }, { n: "Manual", v: sMan, c: "#fbbf24" }, { n: "Recapture", v: sRecap, c: T.w }, { n: "Hold", v: sHold, c: T.rd }].map((x) => <div key={x.n} style={{ border: `1px solid ${T.b}`, borderRadius: 7, background: T.bg, textAlign: "center", padding: "8px 4px" }}><div style={{ fontSize: 17, color: x.c, fontWeight: 800, fontFamily: T.mono }}>{x.v}</div><div style={{ fontSize: 8, color: T.m }}>{x.n}</div></div>)}</div><div style={{ fontSize: 10, color: T.dim }}>{(sh.verdict || {}).message || "Shift quality trend is stable."}</div></Panel> : null}
      {tab === "passport" ? <Panel t="Color Passport" c="#a78bfa"><div style={{ border: `1px solid #a78bfa30`, borderRadius: 12, padding: "16px 14px", background: "linear-gradient(135deg,#0f101a,#15172c)", position: "relative", overflow: "hidden" }}><div style={{ position: "absolute", right: -20, top: -20, width: 120, height: 120, background: "radial-gradient(circle,#a78bfa16 0%,transparent 70%)" }} /><div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}><div><div style={{ fontSize: 8, color: T.m, letterSpacing: 2 }}>COLOR PASSPORT</div><div style={{ fontSize: 13, color: "#a78bfa", fontWeight: 800 }}>{pass.passport_id}</div></div><Tag t="VERIFIED" c={T.g} /></div><div style={{ display: "flex", gap: 10, marginBottom: 12 }}><div style={{ width: 50, height: 50, borderRadius: 10, background: `rgb(${sample.r},${sample.g},${sample.b})`, border: `2px solid #a78bfa44` }} /><div style={{ flex: 1 }}><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>Lab Fingerprint</div><div style={{ fontSize: 10, color: T.tx, fontFamily: T.mono }}>L={num(pass.lab_values?.sample?.L, sLab.L).toFixed(2)} a={num(pass.lab_values?.sample?.a, sLab.a).toFixed(2)} b={num(pass.lab_values?.sample?.b, sLab.b).toFixed(2)}</div><div style={{ fontSize: 9, color: T.m, marginTop: 2, fontFamily: T.mono }}>hash: {String(pass.verification_hash || pass.fingerprint || "--").slice(0, 20)}</div></div></div><div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>{[{ n: "DeltaE", v: num(pass.deltaE, de.total).toFixed(2), c: gc }, { n: "Decision", v: String(pass.decision_code || nba.code || "AUTO_RELEASE"), c: T.g }, { n: "Confidence", v: num(pass.confidence, .9).toFixed(2), c: T.a }].map((x) => <div key={x.n} style={{ textAlign: "center" }}><div style={{ fontSize: 8, color: T.m }}>{x.n}</div><div style={{ fontSize: 13, color: x.c, fontFamily: T.mono, fontWeight: 800 }}>{x.v}</div></div>)}</div><div style={{ marginTop: 10, borderTop: `1px solid ${T.b}`, paddingTop: 7, display: "flex", justifyContent: "space-between", fontSize: 8, color: T.m }}><span>{String(pass.created_at || "").replace("T", " ").slice(0, 19)}</span><span>{String(pass.conditions?.illuminant || "D65")} | {String(pass.conditions?.camera_id || "camera-01")}</span></div></div></Panel> : null}
      <footer style={{ textAlign: "center", paddingTop: 6, fontSize: 8, color: T.m, letterSpacing: 2 }}>SENIA ELITE | PRECISION COLOR OBSERVATORY | LIVE PIPELINE MODE</footer>
    </main>
  </div>;
}
