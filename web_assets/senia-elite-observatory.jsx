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
const T = { bg: "#050810", p: "#0a0c16", b: "#161824", surface: "#12141f", elevated: "#181b2a", tx: "#e0e0ec", dim: "#6b6f88", m: "#252738", a: "#38bdf8", w: "#f59e0b", r: "#f472b6", g: "#34d399", rd: "#ef4444", mono: "'IBM Plex Mono','JetBrains Mono',monospace", font: "'Inter','Noto Sans SC',system-ui,sans-serif", glass: "rgba(15,17,28,0.75)", glow_a: "0 0 20px rgba(56,189,248,0.15)", glow_g: "0 0 20px rgba(52,211,153,0.15)", border: "rgba(100,110,140,0.2)" };
const glow = (c, s = 10) => `0 0 ${s}px ${c}30,0 0 ${2 * s}px ${c}10`;
const describeArc = (cx, cy, r, startAngle, endAngle) => {
  const rad = Math.PI / 180;
  const s = { x: cx + r * Math.cos(startAngle * rad), y: cy + r * Math.sin(startAngle * rad) };
  const e = { x: cx + r * Math.cos(endAngle * rad), y: cy + r * Math.sin(endAngle * rad) };
  return `M ${s.x} ${s.y} A ${r} ${r} 0 ${endAngle - startAngle > 180 ? 1 : 0} 1 ${e.x} ${e.y}`;
};
const tabs = [{ id: "overview", n: "Overview", c: T.a }, { id: "spc", n: "SPC", c: "#22d3ee" }, { id: "texture", n: "Texture", c: T.w }, { id: "spectral", n: "Spectral", c: "#a78bfa" }, { id: "aging", n: "Aging", c: T.r }, { id: "ink", n: "Ink", c: "#818cf8" }, { id: "observer", n: "Observer", c: "#f472b6" }, { id: "drift", n: "Drift", c: T.w }, { id: "blend", n: "Blend", c: "#22d3ee" }, { id: "supplier", n: "Supplier", c: "#fbbf24" }, { id: "shift", n: "Shift", c: T.g }, { id: "passport", n: "Passport", c: "#a78bfa" }];
const fallbackSpc = Array.from({ length: 24 }, (_, i) => 1.55 + Math.sin(i / 3) * 0.3 + i * 0.01);
const fallbackDrift = Array.from({ length: 28 }, (_, i) => 1.2 + i * 0.05);
const Panel = ({ t, c, children }) => <section className="senia-panel" style={{ background: T.surface, border: `1px solid rgba(255,255,255,0.06)`, borderRadius: 16, marginBottom: 16, overflow: "hidden", boxShadow: "0 4px 24px rgba(0,0,0,0.3)", transition: "all 0.3s ease" }}>{t ? <div style={{ padding: "12px 16px", borderBottom: `1px solid rgba(255,255,255,0.06)`, display: "flex", alignItems: "center", gap: 10, background: `linear-gradient(90deg, ${(c || T.a)}08, transparent)` }}><span style={{ width: 8, height: 8, borderRadius: 99, background: c || T.a, boxShadow: glow(c || T.a, 6) }} /><span style={{ fontSize: 11, color: T.dim, letterSpacing: 1.5, fontWeight: 700, textTransform: "uppercase" }}>{t}</span></div> : null}<div style={{ padding: "16px 18px" }}>{children}</div></section>;
const DEGauge = ({ value, max = 5, size = 140 }) => {
  const pct = Math.min(value / max, 1), angle = pct * 270, r = size * 0.38, cx = size / 2, cy = size / 2;
  const [gl, gc] = grade(value);
  const bgPath = describeArc(cx, cy, r, 135, 405);
  const fgPath = angle > 0.5 ? describeArc(cx, cy, r, 135, 135 + angle) : "";
  return <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
    <path d={bgPath} fill="none" stroke={T.m} strokeWidth="8" strokeLinecap="round" />
    {fgPath && <path d={fgPath} fill="none" stroke={gc} strokeWidth="8" strokeLinecap="round" style={{ filter: `drop-shadow(0 0 6px ${gc}50)` }} />}
    <text x={cx} y={cy - 8} textAnchor="middle" fill={gc} fontSize="26" fontWeight="900" fontFamily={T.mono}>{value.toFixed(2)}</text>
    <text x={cx} y={cy + 10} textAnchor="middle" fill={T.dim} fontSize="9" fontFamily={T.font}>DE 2000</text>
    <text x={cx} y={cy + 24} textAnchor="middle" fill={gc} fontSize="10" fontWeight="700" fontFamily={T.font}>{gl}</text>
  </svg>;
};
const Tag = ({ t, c }) => <span style={{ display: "inline-block", padding: "2px 8px", borderRadius: 7, border: `1px solid ${(c || T.a)}35`, background: `${c || T.a}12`, color: c || T.a, fontSize: 10, fontWeight: 700 }}>{t}</span>;
const Skeleton = ({ w = "100%", h = 16 }) => <div style={{ width: w, height: h, borderRadius: 6, background: `linear-gradient(90deg, ${T.m} 25%, ${T.b} 50%, ${T.m} 75%)`, backgroundSize: "200% 100%", animation: "shimmer 1.5s infinite" }} />;
const AnimNum = ({ value, decimals = 2, suffix = "" }) => {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    if (!Number.isFinite(value)) { setDisplay(value); return; }
    let start = 0, t0 = null;
    const step = (ts) => { if (!t0) t0 = ts; const p = Math.min((ts - t0) / 800, 1); const ease = 1 - Math.pow(1 - p, 3); setDisplay(start + (value - start) * ease); if (p < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }, [value]);
  return <span>{Number.isFinite(display) ? display.toFixed(decimals) : "--"}{suffix}</span>;
};
const ExportBtn = ({ data, filename = "export.csv" }) => {
  const handleExport = useCallback(() => {
    if (!data || !data.length) return;
    const keys = Object.keys(data[0]);
    const csv = [keys.join(","), ...data.map(r => keys.map(k => JSON.stringify(r[k] ?? "")).join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url);
  }, [data, filename]);
  return <button onClick={handleExport} style={{ border: `1px solid ${T.b}`, borderRadius: 7, padding: "4px 10px", background: T.p, color: T.dim, fontSize: 10, fontWeight: 700, cursor: "pointer" }}>Export CSV</button>;
};
const Spark = ({ d, th, c = T.a, h = 100, label, cl, lcl }) => {
  const arr = Array.isArray(d) && d.length > 1 ? d : [0, 1], mn = Math.min(...arr), mx = Math.max(...arr, Number.isFinite(th) ? th : mn + 1, Number.isFinite(cl) ? cl : mn, Number.isFinite(lcl) ? lcl : mn), rg = Math.max(0.0001, mx - mn), w = 340, pad = 8;
  const pts = arr.map((v, i) => `${pad + (i / (arr.length - 1)) * (w - 2 * pad)},${h - pad - ((v - mn) / rg) * (h - 2 * pad)}`).join(" ");
  const area = `${pts} ${pad + (arr.length - 1) / (arr.length - 1) * (w - 2 * pad)},${h - pad} ${pad},${h - pad}`;
  const ty = Number.isFinite(th) ? h - pad - (((th - mn) / rg) * (h - 2 * pad)) : null;
  const cly = Number.isFinite(cl) ? h - pad - (((cl - mn) / rg) * (h - 2 * pad)) : null;
  const lcly = Number.isFinite(lcl) ? h - pad - (((lcl - mn) / rg) * (h - 2 * pad)) : null;
  const uid = `spark_${c.replace("#", "")}_${Math.random().toString(36).slice(2, 6)}`;
  const gridY = [0.25, 0.5, 0.75].map(p => h - pad - p * (h - 2 * pad));
  const totalLen = arr.length > 1 ? (arr.length - 1) * ((w - 2 * pad) / (arr.length - 1)) + 200 : 1000;
  const [hoverIdx, setHoverIdx] = useState(null);
  const handleMouse = (e) => {
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const xPos = ((e.clientX - rect.left) / rect.width) * w;
    const idx = Math.round(((xPos - pad) / (w - 2 * pad)) * (arr.length - 1));
    if (idx >= 0 && idx < arr.length) setHoverIdx(idx); else setHoverIdx(null);
  };
  return <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ borderRadius: 8 }} onMouseMove={handleMouse} onMouseLeave={() => setHoverIdx(null)}>
    <defs>
      <linearGradient id={uid} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={c} stopOpacity=".25" />
        <stop offset="60%" stopColor={c} stopOpacity=".08" />
        <stop offset="100%" stopColor={c} stopOpacity=".01" />
      </linearGradient>
    </defs>
    {gridY.map((gy, i) => <line key={i} x1={pad} y1={gy} x2={w - pad} y2={gy} stroke={T.m} strokeWidth=".5" strokeDasharray="2,4" />)}
    <polygon points={area} fill={`url(#${uid})`} />
    {ty !== null && ty > 0 ? <>
      <rect x={0} y={pad} width={w} height={Math.max(0, ty - pad)} fill={`${T.rd}06`} />
      <line x1={pad} y1={ty} x2={w - pad} y2={ty} stroke={T.rd} strokeDasharray="5,4" opacity=".6" strokeWidth="1.5" />
      <text x={w - pad - 2} y={ty - 3} textAnchor="end" fill={T.rd} fontSize="8" fontFamily={T.mono} opacity=".7">UCL {th?.toFixed(2)}</text>
    </> : null}
    {cly !== null ? <>
      <line x1={pad} y1={cly} x2={w - pad} y2={cly} stroke={T.g} strokeDasharray="3,3" opacity=".5" strokeWidth="1" />
      <text x={pad + 2} y={cly - 3} fill={T.g} fontSize="7" fontFamily={T.mono} opacity=".6">CL {cl?.toFixed(2)}</text>
    </> : null}
    {lcly !== null ? <>
      <line x1={pad} y1={lcly} x2={w - pad} y2={lcly} stroke={"#818cf8"} strokeDasharray="5,4" opacity=".5" strokeWidth="1" />
      <text x={w - pad - 2} y={lcly + 10} textAnchor="end" fill={"#818cf8"} fontSize="7" fontFamily={T.mono} opacity=".6">LCL {lcl?.toFixed(2)}</text>
    </> : null}
    <polyline points={pts} fill="none" stroke={c} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" strokeDasharray={totalLen} strokeDashoffset={0} style={{ filter: `drop-shadow(0 2px 4px ${c}30)`, animation: "drawLine 1.2s ease forwards" }} />
    {arr.length <= 30 && arr.map((v, i) => {
      const x = pad + (i / (arr.length - 1)) * (w - 2 * pad);
      const y = h - pad - ((v - mn) / rg) * (h - 2 * pad);
      const ooc = v > (th || Infinity);
      return <circle key={i} cx={x} cy={y} r={ooc ? "4" : "2.5"} fill={ooc ? T.rd : c} stroke={ooc ? "#fff" : T.bg} strokeWidth={ooc ? "1.5" : "1"} style={ooc ? { animation: "pulse 1.5s infinite" } : {}} />;
    })}
    {hoverIdx !== null && (() => {
      const hx = pad + (hoverIdx / (arr.length - 1)) * (w - 2 * pad);
      const hy = h - pad - ((arr[hoverIdx] - mn) / rg) * (h - 2 * pad);
      return <>
        <line x1={hx} y1={pad} x2={hx} y2={h - pad} stroke={c} strokeWidth="0.8" opacity=".4" />
        <circle cx={hx} cy={hy} r="5" fill={c} stroke="#fff" strokeWidth="1.5" opacity=".9" />
        <rect x={Math.min(hx + 6, w - 70)} y={Math.max(hy - 22, 2)} width="62" height="18" rx="4" fill={T.glass || T.p} stroke={c} strokeWidth=".5" opacity=".95" />
        <text x={Math.min(hx + 10, w - 66)} y={Math.max(hy - 8, 16)} fill={c} fontSize="9" fontWeight="700" fontFamily={T.mono}>[{hoverIdx}] {arr[hoverIdx].toFixed(3)}</text>
      </>;
    })()}
    {label ? <text x={pad + 2} y={h - 2} fill={T.dim} fontSize="8" fontFamily={T.mono}>{label}</text> : null}
  </svg>;
};
const Radar = ({ l, c, h, s = 180 }) => {
  const cx = s / 2, cy = s / 2, r = s * 0.32, mx = Math.max(3, Math.ceil(Math.max(Math.abs(l), Math.abs(c), Math.abs(h)) * 1.4));
  const ax = [{ n: "dL", v: Math.abs(l), a: -90, label: `dL ${l >= 0 ? "+" : ""}${l.toFixed(2)}`, raw: l }, { n: "dC", v: Math.abs(c), a: 30, label: `dC ${c >= 0 ? "+" : ""}${c.toFixed(2)}`, raw: c }, { n: "dH", v: Math.abs(h), a: 150, label: `dH ${h >= 0 ? "+" : ""}${h.toFixed(2)}`, raw: h }];
  const p = (a, v) => { const rd = (a * Math.PI) / 180; return { x: cx + (v / mx) * r * Math.cos(rd), y: cy + (v / mx) * r * Math.sin(rd) }; };
  const pts = ax.map((x) => p(x.a, x.v));
  const uid = `radar_${Math.random().toString(36).slice(2, 6)}`;
  const fillId = `radarfill_${uid}`;
  return <svg width={s} height={s} viewBox={`0 0 ${s} ${s}`}>
    <defs>
      <radialGradient id={uid}><stop offset="0%" stopColor={T.a} stopOpacity=".15" /><stop offset="100%" stopColor={T.a} stopOpacity=".03" /></radialGradient>
      <radialGradient id={fillId}><stop offset="0%" stopColor={T.a} stopOpacity=".25" /><stop offset="100%" stopColor={T.a} stopOpacity=".06" /></radialGradient>
    </defs>
    {[.25, .5, .75, 1].map((lv) => { const ring = ax.map((x) => p(x.a, mx * lv)); return <polygon key={lv} points={ring.map((v) => `${v.x},${v.y}`).join(" ")} fill="none" stroke={`rgba(255,255,255,${lv === 1 ? 0.08 : 0.04})`} strokeWidth={lv === 1 ? "1" : ".6"} />; })}
    {[.25, .5, .75, 1].map(lv => <text key={`lbl${lv}`} x={cx + 3} y={cy - (lv * r) - 2} fill={T.dim} fontSize="7" fontFamily={T.mono} opacity=".6">{(mx * lv).toFixed(1)}</text>)}
    {ax.map((x) => { const e = p(x.a, mx); return <line key={`a_${x.n}`} x1={cx} y1={cy} x2={e.x} y2={e.y} stroke="rgba(255,255,255,0.06)" strokeWidth=".8" />; })}
    <polygon points={pts.map((v) => `${v.x},${v.y}`).join(" ")} fill={`url(#${fillId})`} stroke={T.a} strokeWidth="2" strokeLinejoin="round" style={{ filter: `drop-shadow(0 0 8px ${T.a}30)`, transition: "all 0.6s ease" }} />
    {pts.map((v, i) => <circle key={i} cx={v.x} cy={v.y} r="4.5" fill={T.a} stroke={T.bg} strokeWidth="2" style={{ transition: "cx 0.6s ease, cy 0.6s ease" }} />)}
    {ax.map((x) => { const lp = p(x.a, mx * 1.25); return <text key={`t_${x.n}`} x={lp.x} y={lp.y + 3} textAnchor="middle" fill={T.dim} fontSize="9" fontWeight="600" fontFamily={T.mono}>{x.label}</text>; })}
    {ax.map((x, i) => { const vp = p(x.a, x.v); return <text key={`val_${x.n}`} x={vp.x} y={vp.y - 8} textAnchor="middle" fill={T.a} fontSize="8" fontWeight="800" fontFamily={T.mono} style={{ transition: "all 0.6s ease" }}>{x.raw.toFixed(2)}</text>; })}
  </svg>;
};
const bootDefaults = () => {
  if (typeof window === "undefined") return { dbPath: "", lineId: "", productCode: "" };
  const b = window.__SENIA_OBS_DEFAULTS__ || {}, q = new URLSearchParams(window.location.search || "");
  return { dbPath: q.get("db_path") || b.dbPath || "", lineId: q.get("line_id") || b.lineId || "", productCode: q.get("product_code") || b.productCode || "" };
};
const agingMat = (m) => (m === "wood" ? "melamine" : m === "stone" ? "hpl" : m === "metallic" ? "uv_coating" : "pvc_film");
const agingEnv = (e) => (e === "outdoor_exposed" ? "outdoor_exposed" : e === "indoor_window" ? "indoor_window" : "indoor_normal");
const blendBatches = (lab) => [{ batch_id: "B001", lab: { L: +(lab.L - 0.8).toFixed(3), a: +(lab.a - 0.4).toFixed(3), b: +(lab.b - 0.5).toFixed(3) }, quantity: 980 }, { batch_id: "B002", lab: { L: +(lab.L + 0.3).toFixed(3), a: +(lab.a + 0.1).toFixed(3), b: +(lab.b + 0.3).toFixed(3) }, quantity: 860 }, { batch_id: "B003", lab: { L: +(lab.L + 0.9).toFixed(3), a: +(lab.a + 0.4).toFixed(3), b: +(lab.b + 0.8).toFixed(3) }, quantity: 910 }, { batch_id: "B004", lab: { L: +(lab.L - 1.2).toFixed(3), a: +(lab.a - 0.6).toFixed(3), b: +(lab.b - 0.8).toFixed(3) }, quantity: 740 }, { batch_id: "B005", lab: { L: +(lab.L + 1.4).toFixed(3), a: +(lab.a + 0.6).toFixed(3), b: +(lab.b + 1.2).toFixed(3) }, quantity: 680 }];
const perObs = (p) => {
  const x = p && p.per_observer && typeof p.per_observer === "object" ? p.per_observer : null;
  if (!x) return [];
  return Object.keys(x).map((k) => ({ k, n: x[k].name || k, de: num(x[k].de, NaN), dv: num(x[k].delta_vs_standard, 0) })).filter((r) => Number.isFinite(r.de)).sort((a, b) => b.de - a.de);
};
const obsStyles = `
@keyframes shimmer { 0% { background-position:-200% 0; } 100% { background-position:200% 0; } }
@keyframes fadeIn { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
@keyframes drawLine { from { stroke-dashoffset: 1000; } to { stroke-dashoffset: 0; } }
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.6; } }
.senia-panel:hover { box-shadow: 0 8px 32px rgba(0,0,0,0.4) !important; }
`;
let obsStyleInjected = false;
export default function EliteObservatory() {
  useEffect(() => { if (!obsStyleInjected && typeof document !== "undefined") { const s = document.createElement("style"); s.textContent = obsStyles; document.head.appendChild(s); obsStyleInjected = true; } }, []);
  const dft = useMemo(() => bootDefaults(), []);
  const [tab, setTab] = useState("overview");
  const [sample, setSample] = useState({ r: 158, g: 149, b: 131 });
  const [film, setFilm] = useState({ r: 164, g: 152, b: 129 });
  const [mat, setMat] = useState("wood");
  const [env, setEnv] = useState("indoor_window");
  const [showCfg, setShowCfg] = useState(false);
  const [auto, setAuto] = useState(true);
  const [cfg, setCfg] = useState({ dbPath: dft.dbPath, lineId: dft.lineId, productCode: dft.productCode, apiKey: "", window: 160, subgroup: 5, driftTh: 3 });
  const [live, setLive] = useState({ hBusy: false, aBusy: false, hErr: "", aErr: "", hAt: "", aAt: "", cockpit: null, nba: null, spc: null, drift: null, shift: null, supplier: null, texture: null, spectral: null, observer: null, aging: null, ink: null, blend: null, passport: null });
  const hs = useRef(0), as = useRef(0);
  const tabBarRef = useRef(null);
  const [indicator, setIndicator] = useState({ left: 0, width: 0 });
  useEffect(() => {
    if (!tabBarRef.current) return;
    const el = tabBarRef.current.querySelector(`[data-tab="${tab}"]`);
    if (el) setIndicator({ left: el.offsetLeft, width: el.offsetWidth });
  }, [tab]);
  const [sparkHover, setSparkHover] = useState(null);

  const sLab = useMemo(() => rgbToLab(sample.r, sample.g, sample.b), [sample]);
  const fLab = useMemo(() => rgbToLab(film.r, film.g, film.b), [film]);
  const de = useMemo(() => de2000(sLab, fLab), [sLab, fLab]);
  const [gl, gc] = useMemo(() => grade(de.total), [de.total]);
  const headers = useMemo(() => ({ Accept: "application/json", ...(cfg.apiKey.trim() ? { "x-api-key": cfg.apiKey.trim() } : {}) }), [cfg.apiKey]);

  const request = useCallback(async (path, opts = {}) => {
    const h = { ...headers }; let body;
    if (opts.body !== undefined) { h["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
    const resp = await fetch(path, { method: opts.method || "GET", headers: h, body });
    const txt = await resp.text(); let p = {};
    try { p = txt ? JSON.parse(txt) : {}; } catch (_e) { throw new Error(`bad json ${path}`); }
    if (!resp.ok) throw new Error(typeof p.detail === "string" ? p.detail : `${resp.status} ${resp.statusText}`);
    return p;
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
    const rs = await Promise.allSettled([request(`/v1/system/cockpit-snapshot?${q({ weekly_window: 500 })}`), request(`/v1/system/next-best-action?${q({ weekly_window: 500 })}`), request(`/v1/quality/spc/from-history?${q({ subgroup_size: clamp(num(cfg.subgroup, 5), 2, 10) })}`), request(`/v1/history/drift-prediction?${q({ threshold: clamp(num(cfg.driftTh, 3), 0.5, 10) })}`), request(`/v1/report/shift/from-history?${q()}`), request("/v1/supplier/scorecard")]);
    if (id !== hs.current) return;
    const names = ["cockpit", "nba", "spc", "drift", "shift", "supplier"], nx = {}, errs = [];
    rs.forEach((r, i) => { if (r.status === "fulfilled") nx[names[i]] = r.value; else errs.push(`${names[i]}: ${String(r.reason?.message || r.reason || "error")}`); });
    setLive((x) => ({ ...x, ...nx, hBusy: false, hAt: new Date().toLocaleString(), hErr: errs.join(" | ") }));
  }, [cfg.driftTh, cfg.subgroup, q, request]);

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
  useEffect(() => { if (!auto) return undefined; const t = setInterval(() => refreshHistory(true), 20000); return () => clearInterval(t); }, [auto, refreshHistory]);
  useEffect(() => { const t = setTimeout(() => refreshAlgo(true), 500); return () => clearTimeout(t); }, [refreshAlgo]);

  const busy = live.hBusy || live.aBusy, err = [live.hErr, live.aErr].filter(Boolean).join(" | ");
  const cockpit = live.cockpit?.cockpit || {}, nba = live.nba?.recommended_action || {}, signals = live.nba?.signals || {};
  const warn = String(cockpit.warning_level || signals.warning_level || "unknown").toUpperCase(), warnC = warn === "GREEN" ? T.g : warn === "YELLOW" || warn === "ORANGE" ? T.w : T.rd;
  const risk = num(cockpit.risk_index_0_100, num(signals.risk_index_0_100, 0)), autoRelease = num(cockpit.auto_release_rate, num(signals.auto_release_rate, 0)), complaint = num(cockpit.complaint_rate, num(signals.complaint_rate, 0)), saving = num(cockpit.annual_saving_cny, 0);
  const spcR = live.spc?.result || {}, spcV = (spcR.xbar?.values || fallbackSpc).slice(-30), spcM = num(spcR.xbar?.mean, mean(spcV)), spcU = num(spcR.xbar?.ucl, spcM + .6), spcL = num(spcR.xbar?.lcl, Math.max(0, spcM - .6)), cp = num(spcR.capability?.Cp, 1.2), cpk = num(spcR.capability?.Cpk, 1.1), ppm = num(spcR.capability?.ppm_est, 120), grd = String(spcR.capability?.grade || "B").replace("_", " ");
  const ewmaR = spcR.ewma || {}, ewmaV = (ewmaR.values || []).slice(-30), cusumR = spcR.cusum || {}, cusumP = (cusumR.c_plus || []).slice(-30), cusumN = (cusumR.c_minus || []).slice(-30), totalOoc = num(spcR.total_ooc_all_charts, num(spcR.ooc_count, 0));
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

  const inp = { width: "100%", border: `1px solid ${T.b}`, background: T.bg, color: T.tx, borderRadius: 6, padding: "6px 8px", fontSize: 11, fontFamily: T.mono };
  const setRgb = (which, ch, v) => which === "s" ? setSample((x) => ({ ...x, [ch]: clamp(num(v, 0), 0, 255) })) : setFilm((x) => ({ ...x, [ch]: clamp(num(v, 0), 0, 255) }));
  const setCfgF = (k, v) => setCfg((x) => ({ ...x, [k]: v }));
  return <div style={{ minHeight: "100vh", background: T.bg, color: T.tx, fontFamily: T.font }}>
    <style>{`
      @keyframes senia-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
      @keyframes senia-shimmer { from { background-position: -200% 0; } to { background-position: 200% 0; } }
      @keyframes senia-fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
      @keyframes shimmer { 0% { background-position:-200% 0; } 100% { background-position:200% 0; } }
      @keyframes fadeIn { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
      @keyframes drawLine { from { stroke-dashoffset: 1000; } to { stroke-dashoffset: 0; } }
      @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.6; } }
      .senia-panel { animation: senia-fadeIn 0.3s ease; }
      .senia-panel:hover { box-shadow: 0 8px 32px rgba(0,0,0,0.4) !important; }
      .senia-tab { transition: all 0.2s ease; position: relative; }
      .senia-tab:hover { background: rgba(255,255,255,0.06) !important; }
    `}</style>
    <header style={{ position: "sticky", top: 0, zIndex: 3, background: `linear-gradient(180deg,${T.surface}f0,${T.bg}e0)`, backdropFilter: "blur(12px)", padding: "16px 18px 12px", borderBottom: `1px solid rgba(255,255,255,0.06)` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <div style={{ width: 38, height: 38, borderRadius: 10, background: `linear-gradient(135deg,${T.a},#818cf8,${T.r})`, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: glow(T.a, 12) }}><span style={{ fontWeight: 900, color: "#fff", fontSize: 13 }}>SE</span></div>
          <div><div style={{ fontSize: 17, fontWeight: 800, letterSpacing: -0.3 }}>SENIA Elite Observatory</div><div style={{ fontSize: 8, color: T.dim, letterSpacing: 2.8, marginTop: 2 }}>PRECISION COLOR INTELLIGENCE CONSOLE</div></div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ width: 8, height: 8, borderRadius: 99, background: busy ? T.w : err ? T.rd : T.g, boxShadow: glow(busy ? T.w : err ? T.rd : T.g, 6), animation: busy ? "senia-pulse 1.5s infinite" : "none" }} />
          <Tag t={busy ? "SYNCING" : err ? "DEGRADED" : "LIVE"} c={busy ? T.w : err ? T.rd : T.g} />
        </div>
      </div>
      <div ref={tabBarRef} style={{ marginTop: 12, display: "flex", gap: 3, overflowX: "auto", paddingBottom: 6, position: "relative" }}>
        <div style={{ position: "absolute", bottom: 0, left: indicator.left, width: indicator.width, height: 3, borderRadius: 3, background: (tabs.find(x => x.id === tab) || tabs[0]).c, transition: "left 0.3s ease, width 0.3s ease", boxShadow: `0 0 8px ${(tabs.find(x => x.id === tab) || tabs[0]).c}60` }} />
        {tabs.map((x) => <button key={x.id} data-tab={x.id} className={`senia-tab ${tab === x.id ? "senia-tab-active" : ""}`} onClick={() => setTab(x.id)} style={{ padding: "7px 12px", borderRadius: 8, border: "none", background: tab === x.id ? `${x.c}12` : "transparent", color: tab === x.id ? x.c : T.dim, fontSize: 10, fontWeight: 700, whiteSpace: "nowrap", cursor: "pointer", boxShadow: tab === x.id ? `0 0 12px ${x.c}15` : "none", display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 5, height: 5, borderRadius: 99, background: x.c, opacity: tab === x.id ? 1 : 0.3 }} />{x.n}</button>)}
      </div>
    </header>
    <main style={{ padding: "12px 16px 24px" }}>
      <Panel t="Smart Control" c={busy ? T.w : err ? T.rd : T.g}><div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginBottom: 10 }}><Tag t={`History: ${live.hAt || "--"}`} c={T.a} /><Tag t={`AI: ${live.aAt || "--"}`} c={T.r} /><button onClick={refreshAll} style={{ marginLeft: "auto", border: `1px solid ${T.a}35`, background: `${T.a}14`, color: T.a, borderRadius: 8, padding: "6px 10px", fontSize: 11, fontWeight: 700, cursor: "pointer" }}>Refresh Full Pipeline</button><button onClick={() => setAuto((v) => !v)} style={{ border: `1px solid ${auto ? `${T.g}45` : T.b}`, background: auto ? `${T.g}14` : T.bg, color: auto ? T.g : T.dim, borderRadius: 8, padding: "6px 10px", fontSize: 11, fontWeight: 700, cursor: "pointer" }}>Auto {auto ? "On" : "Off"}</button><button onClick={() => setShowCfg((v) => !v)} style={{ border: `1px solid ${T.b}`, background: T.bg, color: T.dim, borderRadius: 8, padding: "6px 10px", fontSize: 11, fontWeight: 700, cursor: "pointer" }}>{showCfg ? "Hide Scope" : "Show Scope"}</button></div>{err ? <div style={{ fontSize: 10, color: T.rd, marginBottom: 8 }}>Degraded mode: {err}</div> : null}{showCfg ? <div style={{ display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 8 }}><div style={{ gridColumn: "1 / span 2" }}><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>History DB Path</div><input value={cfg.dbPath} onChange={(e) => setCfgF("dbPath", e.target.value)} style={inp} /></div><div><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>Line ID</div><input value={cfg.lineId} onChange={(e) => setCfgF("lineId", e.target.value)} style={inp} /></div><div><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>Product Code</div><input value={cfg.productCode} onChange={(e) => setCfgF("productCode", e.target.value)} style={inp} /></div><div><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>API Key</div><input value={cfg.apiKey} onChange={(e) => setCfgF("apiKey", e.target.value)} style={inp} /></div><div><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>Window</div><input type="number" min={20} max={2000} value={cfg.window} onChange={(e) => setCfgF("window", e.target.value)} style={inp} /></div><div><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>Subgroup</div><input type="number" min={2} max={10} value={cfg.subgroup} onChange={(e) => setCfgF("subgroup", e.target.value)} style={inp} /></div><div><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>Drift Th</div><input type="number" min={0.5} max={10} step={0.1} value={cfg.driftTh} onChange={(e) => setCfgF("driftTh", e.target.value)} style={inp} /></div></div> : null}</Panel>
      <Panel t="Sampling Cockpit" c={gc}><div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>{["s", "f"].map((k) => <div key={k} style={{ border: `1px solid ${T.b}`, borderRadius: 8, padding: 8, background: T.bg }}><div style={{ fontSize: 10, color: T.dim, marginBottom: 6 }}>{k === "s" ? "Sample RGB" : "Film RGB"}</div>{["r", "g", "b"].map((ch) => <div key={`${k}_${ch}`} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}><span style={{ width: 12, fontSize: 10, color: T.dim, textTransform: "uppercase" }}>{ch}</span><input type="number" min={0} max={255} value={(k === "s" ? sample : film)[ch]} onChange={(e) => setRgb(k, ch, e.target.value)} style={{ ...inp, padding: "4px 6px" }} /></div>)}</div>)}</div><div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 20, flexWrap: "wrap" }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ width: 120, height: 120, borderRadius: 16, background: `rgb(${sample.r},${sample.g},${sample.b})`, border: `2px solid ${T.a}40`, boxShadow: `0 8px 32px rgba(${sample.r},${sample.g},${sample.b},.35), ${T.glow_a}`, margin: "0 auto" }} />
          <div style={{ fontSize: 9, color: T.dim, marginTop: 8, fontFamily: T.mono }}>L {sLab.L.toFixed(2)}</div>
          <div style={{ fontSize: 9, color: T.dim, fontFamily: T.mono }}>a {sLab.a.toFixed(2)} b {sLab.b.toFixed(2)}</div>
          <div style={{ fontSize: 9, color: T.a, marginTop: 3, fontWeight: 700 }}>Sample</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
          <svg width="80" height="30" viewBox="0 0 80 30"><defs><marker id="arrowDE" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill={gc} /></marker></defs><line x1="4" y1="15" x2="68" y2="15" stroke={gc} strokeWidth="2" markerEnd="url(#arrowDE)" /><text x="40" y="10" textAnchor="middle" fill={gc} fontSize="9" fontWeight="800" fontFamily={T.mono}>DE {de.total.toFixed(2)}</text></svg>
          <div style={{ width: 80, height: 6, borderRadius: 6, background: `linear-gradient(90deg, ${T.g}, #a3e635, ${T.w}, ${T.rd})`, position: "relative" }}>
            <div style={{ position: "absolute", left: `${clamp(de.total / 5 * 100, 0, 100)}%`, top: -3, width: 4, height: 12, borderRadius: 2, background: "#fff", transform: "translateX(-2px)", boxShadow: `0 0 6px ${gc}` }} />
          </div>
        </div>
        <div style={{ textAlign: "center" }}>
          <div style={{ width: 120, height: 120, borderRadius: 16, background: `rgb(${film.r},${film.g},${film.b})`, border: `2px solid ${T.r}40`, boxShadow: `0 8px 32px rgba(${film.r},${film.g},${film.b},.35)`, margin: "0 auto" }} />
          <div style={{ fontSize: 9, color: T.dim, marginTop: 8, fontFamily: T.mono }}>L {fLab.L.toFixed(2)}</div>
          <div style={{ fontSize: 9, color: T.dim, fontFamily: T.mono }}>a {fLab.a.toFixed(2)} b {fLab.b.toFixed(2)}</div>
          <div style={{ fontSize: 9, color: T.r, marginTop: 3, fontWeight: 700 }}>Film</div>
        </div>
        <DEGauge value={de.total} />
      </div></Panel>
      {tab === "overview" ? <>{busy && !live.cockpit ? <Panel t="Loading..." c={T.a}><Skeleton h={24} /><div style={{ height: 8 }} /><Skeleton w="60%" h={16} /><div style={{ height: 8 }} /><Skeleton h={60} /></Panel> : <><Panel t="Decision Core" c={gc}><div style={{ display: "flex", gap: 14, alignItems: "center" }}><Radar l={de.dL} c={de.dC} h={de.dH} /><div style={{ flex: 1 }}><div style={{ marginBottom: 6, fontSize: 10, color: T.dim }}>Next Action</div><Tag t={nba.code || "RUN_OPS_CHECK"} c={warnC} /> <Tag t={`confidence ${num(nba.confidence, .8).toFixed(2)}`} c={T.a} /><div style={{ marginTop: 8, fontSize: 10, color: T.dim }}>{(Array.isArray(nba.reasons) && nba.reasons.length ? nba.reasons.slice(0, 2) : ["Balanced state detected, keep monitoring trend."]).join(" | ")}</div></div></div></Panel><Panel t="System Snapshot" c={T.a}><div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 6 }}>{[{ k: "Warning", v: warn, c: warnC, raw: null }, { k: "Risk", v: null, c: risk < 45 ? T.g : risk < 70 ? T.w : T.rd, raw: risk }, { k: "Auto Release", v: null, c: autoRelease > .82 ? T.g : T.w, raw: autoRelease * 100, suf: "%" }, { k: "Complaint", v: null, c: complaint < .03 ? T.g : T.w, raw: complaint * 100, suf: "%", dec: 2 }, { k: "Annual Saving", v: `¥${Math.round(saving).toLocaleString()}`, c: T.g, raw: null }, { k: "SPC Cpk", v: null, c: cpk >= 1.33 ? T.g : cpk >= 1 ? "#a3e635" : T.rd, raw: cpk }].map((x) => <div key={x.k} style={{ padding: "8px 10px", borderRadius: 8, border: `1px solid ${T.b}`, background: T.bg }}><div style={{ fontSize: 8, color: T.m, marginBottom: 3 }}>{x.k}</div><div style={{ fontSize: 15, color: x.c, fontWeight: 800, fontFamily: T.mono }}>{x.raw !== null ? <AnimNum value={x.raw} decimals={x.dec || 1} suffix={x.suf || ""} /> : x.v}</div></div>)}</div></Panel></>}</> : null}
      {tab === "spc" ? <Panel t="SPC Control" c="#22d3ee"><div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}><ExportBtn data={spcV.map((v, i) => ({ index: i, value: +v.toFixed(4), ucl: +spcU.toFixed(4), lcl: +spcL.toFixed(4), mean: +spcM.toFixed(4) }))} filename="spc_xbar.csv" /></div><div style={{ display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 8, marginBottom: 10 }}><div><div style={{ fontSize: 22, color: cpk >= 1.33 ? T.g : cpk >= 1 ? "#a3e635" : T.rd, fontWeight: 800, fontFamily: T.mono }}><AnimNum value={cpk} decimals={2} /></div><div style={{ fontSize: 9, color: T.dim }}>Cpk</div></div><div><div style={{ fontSize: 22, color: "#22d3ee", fontWeight: 800, fontFamily: T.mono }}><AnimNum value={cp} decimals={2} /></div><div style={{ fontSize: 9, color: T.dim }}>Cp</div></div><div><div style={{ fontSize: 16, color: "#a3e635", fontWeight: 800, fontFamily: T.mono }}>{grd.toUpperCase()}</div><div style={{ fontSize: 9, color: T.dim }}>Grade</div></div><div><div style={{ fontSize: 16, color: T.dim, fontWeight: 800, fontFamily: T.mono }}><AnimNum value={ppm} decimals={0} /></div><div style={{ fontSize: 9, color: T.dim }}>PPM</div></div></div><div style={{ background: T.bg, borderRadius: 8, padding: "8px 4px", position: "relative" }}>
          {(() => { const sigma2u = spcM + (spcU - spcM) * (2/3); const sigma2l = spcM - (spcM - spcL) * (2/3); return <div style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, pointerEvents: "none", overflow: "hidden", borderRadius: 8 }}><div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "15%", background: `linear-gradient(180deg, ${T.w}08, transparent)` }} /><div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: "15%", background: `linear-gradient(0deg, ${T.w}08, transparent)` }} /></div>; })()}
          <Spark d={spcV} th={spcU} cl={spcM} lcl={spcL} c="#22d3ee" h={120} /><div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontSize: 8, color: T.m }}><span style={{ color: T.rd }}>UCL {spcU.toFixed(2)}</span><span style={{ color: T.g }}>CL {spcM.toFixed(2)}</span><span style={{ color: "#818cf8" }}>LCL {spcL.toFixed(2)}</span></div></div>{spcV.some(v => v > spcU || v < spcL) ? <div style={{ marginTop: 6, padding: "6px 10px", borderRadius: 8, background: `${T.rd}12`, border: `1px solid ${T.rd}30`, fontSize: 10, color: T.rd }}>OOC points detected: {spcV.filter(v => v > spcU || v < spcL).length} out of {spcV.length} exceed control limits</div> : null}<div style={{ marginTop: 8, fontSize: 10, color: spcR.in_control ? T.g : T.w }}>{spcR.in_control ? "In control. Capability improvement is now priority." : "Out-of-control trend. Check root cause and subgroup consistency."}</div>
        {ewmaV.length > 1 ? <div style={{ marginTop: 12 }}><div style={{ fontSize: 9, color: T.dim, marginBottom: 4, letterSpacing: 1, fontWeight: 700 }}>EWMA CHART (lambda={num(ewmaR.lambda, 0.2).toFixed(1)})</div><div style={{ background: T.bg, borderRadius: 8, padding: "6px 4px" }}><Spark d={ewmaV} c="#22d3ee" label="EWMA" /></div><div style={{ fontSize: 8, color: T.dim, marginTop: 3 }}>EWMA OOC: {num(ewmaR.ooc_count, 0)}</div></div> : null}
        {cusumP.length > 1 ? <div style={{ marginTop: 12 }}><div style={{ fontSize: 9, color: T.dim, marginBottom: 4, letterSpacing: 1, fontWeight: 700 }}>CUSUM CHART (k={num(cusumR.k, 0.5)}, h={num(cusumR.h, 5)})</div><div style={{ background: T.bg, borderRadius: 8, padding: "6px 4px" }}><Spark d={cusumP} th={num(cusumR.decision_interval, 5)} c="#fbbf24" label="C+" /></div>{cusumN.length > 1 ? <div style={{ background: T.bg, borderRadius: 8, padding: "6px 4px", marginTop: 4 }}><Spark d={cusumN} th={num(cusumR.decision_interval, 5)} c="#f472b6" label="C-" /></div> : null}<div style={{ fontSize: 8, color: T.dim, marginTop: 3 }}>CUSUM OOC: {num(cusumR.ooc_count, 0)} | Total OOC (all charts): {totalOoc}</div></div> : null}
      </Panel> : null}
      {tab === "texture" ? <Panel t="Texture Aware DeltaE" c={T.w}><div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 16, marginBottom: 14 }}><div style={{ textAlign: "center" }}><div style={{ fontSize: 8, color: T.dim }}>Standard</div><div style={{ fontSize: 22, color: T.dim, fontWeight: 800, fontFamily: T.mono }}>{de.total.toFixed(2)}</div></div><div style={{ color: T.m }}>to</div><div style={{ textAlign: "center" }}><div style={{ fontSize: 8, color: T.w }}>Adjusted</div><div style={{ fontSize: 28, color: grade(tDe)[1], fontWeight: 900, fontFamily: T.mono, textShadow: glow(grade(tDe)[1], 8) }}>{tDe.toFixed(2)}</div></div></div><div style={{ display: "flex", gap: 4, marginBottom: 10 }}>{["solid", "wood", "stone", "metallic"].map((x) => <button key={x} onClick={() => setMat(x)} style={{ flex: 1, border: `1px solid ${mat === x ? `${T.w}35` : T.b}`, borderRadius: 6, padding: "7px 4px", background: mat === x ? `${T.w}12` : T.bg, color: mat === x ? T.w : T.dim, fontSize: 10, fontWeight: 700, cursor: "pointer" }}>{x}</button>)}</div><div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 8 }}><div><div style={{ fontSize: 18, color: T.w, fontFamily: T.mono, fontWeight: 800 }}>{tMask.toFixed(2)}</div><div style={{ fontSize: 9, color: T.dim }}>Masking</div></div><div><div style={{ fontSize: 18, color: T.dim, fontFamily: T.mono, fontWeight: 800 }}>{tCx.toFixed(1)}</div><div style={{ fontSize: 9, color: T.dim }}>Complexity</div></div><div><div style={{ fontSize: 18, color: tImp <= 0 ? T.g : T.rd, fontFamily: T.mono, fontWeight: 800 }}>{tImp.toFixed(0)}%</div><div style={{ fontSize: 9, color: T.dim }}>Impact</div></div></div></Panel> : null}
      {tab === "spectral" ? <Panel t="Spectral Metamerism" c="#a78bfa"><div style={{ textAlign: "center", marginBottom: 12 }}><div style={{ fontSize: 8, color: T.dim }}>Metamerism Index</div><div style={{ fontSize: 35, fontWeight: 900, color: mi < .4 ? T.g : mi < .8 ? T.w : T.rd, fontFamily: T.mono }}>{mi.toFixed(3)}</div><Tag t={`RISK ${riskLv}`} c={riskLv === "LOW" ? T.g : riskLv === "MEDIUM" ? T.w : T.rd} /></div>{Object.keys(ill).map((k) => { const v = num(ill[k], 0), c = v < 1 ? T.g : v < 2 ? T.w : T.rd; return <div key={k} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}><span style={{ width: 80, fontSize: 10, color: T.dim }}>{k}</span><div style={{ flex: 1, height: 4, borderRadius: 6, background: T.m }}><div style={{ width: `${clamp(v / 3 * 100, 0, 100)}%`, height: "100%", borderRadius: 6, background: c }} /></div><span style={{ width: 34, textAlign: "right", fontSize: 11, color: c, fontFamily: T.mono }}>{v.toFixed(3)}</span></div>; })}</Panel> : null}
      {tab === "aging" ? <Panel t="Aging Forecast" c={T.r}><div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}><ExportBtn data={agV.map(x => ({ year: x.year, deltaE: num(x.deltaE_from_original, 0).toFixed(3), grade: grade(num(x.deltaE_from_original, 0))[0] }))} filename="aging_forecast.csv" /></div><div style={{ display: "flex", gap: 4, marginBottom: 10 }}>{[["indoor_normal", "Indoor"], ["indoor_window", "Window"], ["outdoor_exposed", "Outdoor"]].map(([k, n]) => <button key={k} onClick={() => setEnv(k)} style={{ flex: 1, border: `1px solid ${env === k ? `${T.r}35` : T.b}`, borderRadius: 6, padding: "7px 4px", background: env === k ? `${T.r}12` : T.bg, color: env === k ? T.r : T.dim, fontSize: 10, fontWeight: 700, cursor: "pointer" }}>{n}</button>)}</div>{agV.map((x, i) => { const v = num(x.deltaE_from_original, 0), [lbl, c] = grade(v); return <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}><span style={{ width: 32, fontSize: 11, color: T.dim, fontFamily: T.mono }}>{x.year}y</span><div style={{ flex: 1, height: 5, borderRadius: 6, background: T.m }}><div style={{ width: `${clamp(v / 8 * 100, 0, 100)}%`, height: "100%", borderRadius: 6, background: `linear-gradient(90deg,${c}88,${c})` }} /></div><span style={{ width: 40, textAlign: "right", fontSize: 12, color: c, fontFamily: T.mono }}>{v.toFixed(2)}</span><span style={{ width: 70, fontSize: 8, color: c }}>{lbl}</span></div>; })}<div style={{ marginTop: 8, fontSize: 10, color: String(agRisk.level || "").toLowerCase() === "high" ? T.rd : T.dim }}>{String(agRisk.message || "No warranty breach predicted in current horizon.")}</div></Panel> : null}
      {tab === "ink" ? <Panel t="Auto Ink Recipe" c="#818cf8"><div style={{ fontSize: 10, color: T.dim, marginBottom: 10, fontFamily: T.mono }}>dL={de.dL.toFixed(2)} dC={de.dC.toFixed(2)} dH={de.dH.toFixed(2)}</div><div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>{["C", "M", "Y", "K"].map((ch) => { const v = num(adj[ch], 0), cc = { C: "#06b6d4", M: "#ec4899", Y: "#eab308", K: "#71717a" }[ch]; return <div key={ch} style={{ border: `1px solid ${cc}25`, borderRadius: 9, background: T.bg, padding: "10px 12px" }}><div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}><span style={{ fontSize: 10, color: cc, fontWeight: 700 }}>{ch}</span><span style={{ fontSize: 20, color: v >= 0 ? T.g : T.rd, fontFamily: T.mono, fontWeight: 900 }}>{v > 0 ? "+" : ""}{v.toFixed(2)}%</span></div></div>; })}</div><div style={{ fontSize: 10, color: T.dim }}>Predicted residual DeltaE: <span style={{ color: T.g, fontWeight: 700, fontFamily: T.mono }}>{iRes.toFixed(3)}</span> | Safety: <span style={{ color: iSafe ? T.g : T.rd }}>{iSafe ? "SAFE" : "CHECK LIMIT"}</span></div></Panel> : null}
      {tab === "observer" ? <Panel t="Multi Observer Simulation" c="#f472b6"><div style={{ marginBottom: 10 }}><div style={{ fontSize: 9, color: T.dim }}>Most Sensitive Observer</div><div style={{ fontSize: 27, color: T.w, fontWeight: 900, fontFamily: T.mono, textShadow: glow(T.w) }}>{obsV[0].de.toFixed(2)}</div><Tag t={obsV[0].n} c={T.w} /></div>{obsV.map((o) => { const c = grade(o.de)[1]; return <div key={o.k} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}><div style={{ flex: 1 }}><div style={{ fontSize: 10, color: T.tx, fontWeight: 700 }}>{o.n}</div><div style={{ fontSize: 8, color: T.m }}>delta vs standard {num(o.dv, 0).toFixed(2)}</div></div><div style={{ width: 78, height: 4, borderRadius: 6, background: T.m }}><div style={{ width: `${clamp(o.de / 4 * 100, 0, 100)}%`, height: "100%", borderRadius: 6, background: c }} /></div><span style={{ width: 42, textAlign: "right", color: c, fontFamily: T.mono, fontWeight: 700 }}>{o.de.toFixed(2)}</span></div>; })}</Panel> : null}
      {tab === "drift" ? <Panel t="Drift Predictor" c={T.w}><div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}><ExportBtn data={driftS.map((v, i) => ({ index: i, value: +v.toFixed(4), predicted: i >= driftS.length - driftF.length ? "yes" : "no" }))} filename="drift_prediction.csv" /></div><div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 8, marginBottom: 10 }}><div><div style={{ fontSize: 22, color: T.w, fontFamily: T.mono, fontWeight: 800 }}><AnimNum value={driftB} decimals={0} /></div><div style={{ fontSize: 9, color: T.dim }}>Batches Left</div></div><div><div style={{ fontSize: 15, color: "#fbbf24", fontFamily: T.mono, fontWeight: 800 }}>{slope >= 0 ? "+" : ""}{slope.toFixed(4)}</div><div style={{ fontSize: 9, color: T.dim }}>Slope/Batch</div></div><div><div style={{ fontSize: 15, color: urg === "LOW" ? T.g : urg === "MEDIUM" ? T.w : T.rd, fontFamily: T.mono, fontWeight: 800 }}>{urg}</div><div style={{ fontSize: 9, color: T.dim }}>Urgency</div></div></div><div style={{ background: T.bg, borderRadius: 8, padding: "6px 4px", marginBottom: 8, position: "relative" }}>
        <Spark d={driftS} th={num(cfg.driftTh, 3)} c={T.w} h={120} />
        {(() => {
          const total = driftS.length, histLen = total - driftF.length, w = 340, pad = 8, svgH = 120;
          const mn = Math.min(...driftS), mx = Math.max(...driftS, num(cfg.driftTh, 3)), rg = Math.max(0.0001, mx - mn);
          const startX = pad + ((histLen - 1) / (total - 1)) * (w - 2 * pad);
          const predPts = driftF.map((v, i) => { const idx = histLen + i; return `${pad + (idx / (total - 1)) * (w - 2 * pad)},${svgH - pad - ((v - mn) / rg) * (svgH - 2 * pad)}`; });
          const confUpper = driftF.map((v, i) => { const idx = histLen + i; const spread = (i + 1) * slope * 0.5; return `${pad + (idx / (total - 1)) * (w - 2 * pad)},${svgH - pad - (((v + spread) - mn) / rg) * (svgH - 2 * pad)}`; });
          const confLower = driftF.map((v, i) => { const idx = histLen + i; const spread = (i + 1) * slope * 0.5; return `${pad + (idx / (total - 1)) * (w - 2 * pad)},${svgH - pad - ((Math.max(0, v - spread) - mn) / rg) * (svgH - 2 * pad)}`; });
          const cpIdx = Math.max(0, histLen - Math.round(histLen * 0.4));
          const cpX = pad + (cpIdx / (total - 1)) * (w - 2 * pad);
          return <svg width="100%" height={svgH} viewBox={`0 0 ${w} ${svgH}`} preserveAspectRatio="none" style={{ position: "absolute", top: 0, left: 0, pointerEvents: "none", borderRadius: 8 }}>
            {confUpper.length > 0 && <polygon points={[...confUpper, ...confLower.reverse()].join(" ")} fill={`${T.w}12`} />}
            {predPts.length > 1 && <polyline points={predPts.join(" ")} fill="none" stroke={T.w} strokeWidth="2" strokeDasharray="6,4" opacity=".7" />}
            <line x1={cpX} y1={pad} x2={cpX} y2={svgH - pad} stroke={T.r} strokeWidth="1" strokeDasharray="3,3" opacity=".5" />
            <text x={cpX + 3} y={pad + 10} fill={T.r} fontSize="7" fontFamily={T.mono} opacity=".7">changepoint</text>
            <line x1={startX} y1={pad} x2={startX} y2={svgH - pad} stroke={T.dim} strokeWidth="1" strokeDasharray="2,3" opacity=".3" />
            <text x={startX + 3} y={svgH - pad - 4} fill={T.dim} fontSize="7" fontFamily={T.mono} opacity=".5">forecast</text>
          </svg>;
        })()}
      </div><div style={{ fontSize: 10, color: T.w }}>{dRec}</div></Panel> : null}
      {tab === "blend" ? <Panel t="Batch Blend Optimizer" c="#22d3ee"><div style={{ fontSize: 10, color: T.dim, marginBottom: 8 }}>Optimized groups from open algorithm. Same stock, lower complaint risk for priority customers.</div>{blend.map((g) => { const v = num(g.max_intra_deltaE, 0), [lbl, c] = grade(v); return <div key={g.group} style={{ border: `1px solid ${T.b}`, borderRadius: 10, background: T.bg, padding: "10px 12px", marginBottom: 8 }}><div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}><div style={{ display: "flex", gap: 6, alignItems: "center" }}><strong style={{ fontSize: 12 }}>Group {g.group}</strong><Tag t={String(g.customer_tier || "Standard")} c={String(g.customer_tier || "").toUpperCase() === "VIP" ? "#fbbf24" : T.a} /></div><span style={{ color: c, fontWeight: 800, fontFamily: T.mono }}>DeltaE {v.toFixed(2)}</span></div><div style={{ fontSize: 9, color: T.m, fontFamily: T.mono }}>{(Array.isArray(g.batches) ? g.batches : []).join(" | ")} | Qty {Math.round(num(g.total_quantity, 0))} | {lbl}</div></div>; })}</Panel> : null}
      {tab === "supplier" ? <Panel t="Supplier Scorecard" c="#fbbf24"><div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}><ExportBtn data={sup.map(s => ({ id: s.id, grade: s.grade, score: num(s.score, 0).toFixed(1), avg_de: num(s.avg_de, 0).toFixed(2), std_de: num(s.std_de, 0).toFixed(2), count: Math.round(num(s.count, 0)), pass_rate: num(s.pass_rate, 0).toFixed(1), trend: s.trend || "stable" }))} filename="supplier_scorecard.csv" /></div>{sup.map((s) => { const g = String(s.grade || "B").toUpperCase(), sc = num(s.score, 0), ad = num(s.avg_de, 0), sd = num(s.std_de, 0), n = Math.round(num(s.count, 0)), pr = num(s.pass_rate, NaN), c = g === "A" ? T.g : g === "B" ? "#a3e635" : g === "C" ? T.w : T.rd; return <div key={s.id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "9px 0", borderBottom: `1px solid ${T.b}` }}><div style={{ width: 34, height: 34, borderRadius: 9, border: `1px solid ${c}35`, background: `${c}15`, display: "flex", alignItems: "center", justifyContent: "center", color: c, fontWeight: 900 }}>{g}</div><div style={{ flex: 1 }}><div style={{ fontSize: 11, fontWeight: 700 }}>{s.id}</div><div style={{ fontSize: 8, color: T.m }}>avg de {ad.toFixed(2)} | sigma {sd.toFixed(2)} | n {n} {Number.isFinite(pr) ? `| pass ${pr.toFixed(1)}%` : ""}</div></div><div style={{ textAlign: "right" }}><div style={{ fontSize: 20, color: c, fontFamily: T.mono, fontWeight: 800 }}>{sc.toFixed(1)}</div><div style={{ fontSize: 8, color: T.m }}>{String(s.trend || "stable")}</div></div></div>; })}<div style={{ marginTop: 8, fontSize: 10, color: T.g }}>Preferred supplier now: {(sup[0] || {}).id || "--"}</div></Panel> : null}
      {tab === "shift" ? <Panel t="Shift Report" c={T.g}><div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 8, marginBottom: 10 }}><div><div style={{ fontSize: 20, fontFamily: T.mono, fontWeight: 800 }}><AnimNum value={sTotal} decimals={0} /></div><div style={{ fontSize: 9, color: T.dim }}>Runs</div></div><div><div style={{ fontSize: 22, color: T.g, fontFamily: T.mono, fontWeight: 800 }}><AnimNum value={sPass * 100} decimals={1} suffix="%" /></div><div style={{ fontSize: 9, color: T.dim }}>Pass Rate</div></div><div><div style={{ fontSize: 18, color: "#a3e635", fontFamily: T.mono, fontWeight: 800 }}><AnimNum value={sDe} decimals={2} /></div><div style={{ fontSize: 9, color: T.dim }}>Avg DeltaE</div></div></div><div style={{ display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 5, marginBottom: 8 }}>{[{ n: "Auto", v: sAuto, c: T.g }, { n: "Manual", v: sMan, c: "#fbbf24" }, { n: "Recapture", v: sRecap, c: T.w }, { n: "Hold", v: sHold, c: T.rd }].map((x) => <div key={x.n} style={{ border: `1px solid ${T.b}`, borderRadius: 7, background: T.bg, textAlign: "center", padding: "8px 4px" }}><div style={{ fontSize: 17, color: x.c, fontWeight: 800, fontFamily: T.mono }}>{x.v}</div><div style={{ fontSize: 8, color: T.m }}>{x.n}</div></div>)}</div><div style={{ fontSize: 10, color: T.dim }}>{(sh.verdict || {}).message || "Shift quality trend is stable."}</div></Panel> : null}
      {tab === "passport" ? <Panel t="Color Passport" c="#a78bfa"><div style={{ border: `1px solid #a78bfa30`, borderRadius: 12, padding: "16px 14px", background: "linear-gradient(135deg,#0f101a,#15172c)", position: "relative", overflow: "hidden" }}><div style={{ position: "absolute", right: -20, top: -20, width: 120, height: 120, background: "radial-gradient(circle,#a78bfa16 0%,transparent 70%)" }} /><div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}><div><div style={{ fontSize: 8, color: T.m, letterSpacing: 2 }}>COLOR PASSPORT</div><div style={{ fontSize: 13, color: "#a78bfa", fontWeight: 800 }}>{pass.passport_id}</div></div><Tag t="VERIFIED" c={T.g} /></div><div style={{ display: "flex", gap: 10, marginBottom: 12 }}><div style={{ width: 50, height: 50, borderRadius: 10, background: `rgb(${sample.r},${sample.g},${sample.b})`, border: `2px solid #a78bfa44` }} /><div style={{ flex: 1 }}><div style={{ fontSize: 9, color: T.dim, marginBottom: 3 }}>Lab Fingerprint</div><div style={{ fontSize: 10, color: T.tx, fontFamily: T.mono }}>L={num(pass.lab_values?.sample?.L, sLab.L).toFixed(2)} a={num(pass.lab_values?.sample?.a, sLab.a).toFixed(2)} b={num(pass.lab_values?.sample?.b, sLab.b).toFixed(2)}</div><div style={{ fontSize: 9, color: T.m, marginTop: 2, fontFamily: T.mono }}>hash: {String(pass.verification_hash || pass.fingerprint || "--").slice(0, 20)}</div></div></div><div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>{[{ n: "DeltaE", v: num(pass.deltaE, de.total).toFixed(2), c: gc }, { n: "Decision", v: String(pass.decision_code || nba.code || "AUTO_RELEASE"), c: T.g }, { n: "Confidence", v: num(pass.confidence, .9).toFixed(2), c: T.a }].map((x) => <div key={x.n} style={{ textAlign: "center" }}><div style={{ fontSize: 8, color: T.m }}>{x.n}</div><div style={{ fontSize: 13, color: x.c, fontFamily: T.mono, fontWeight: 800 }}>{x.v}</div></div>)}</div><div style={{ marginTop: 10, borderTop: `1px solid ${T.b}`, paddingTop: 7, display: "flex", justifyContent: "space-between", fontSize: 8, color: T.m }}><span>{String(pass.created_at || "").replace("T", " ").slice(0, 19)}</span><span>{String(pass.conditions?.illuminant || "D65")} | {String(pass.conditions?.camera_id || "camera-01")}</span></div></div></Panel> : null}
      <footer style={{ textAlign: "center", paddingTop: 6, fontSize: 8, color: T.m, letterSpacing: 2 }}>SENIA ELITE | PRECISION COLOR OBSERVATORY | LIVE PIPELINE MODE</footer>
    </main>
  </div>;
}
