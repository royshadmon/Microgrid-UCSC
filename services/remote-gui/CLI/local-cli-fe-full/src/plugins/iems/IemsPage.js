import React, { useState, useEffect, useCallback } from "react";
import {
  getHealth, getModels, runCycle, disaggregatePanel,
  testModel, pullModel, setPreferences, acceptRec, deferRec, dismissRec,
  getStorage,
} from "./iems_api";

// ── Color palette from eGauge Grafana dashboard ───────────────────────────
const C = {
  grid:    "#f97316",  // orange
  gen:     "#fbbf24",  // amber
  hvac:    "#38bdf8",  // sky blue
  h2o:     "#f97316",  // orange (H2O panel)
  kitchen: "#4ade80",  // green
  shop:    "#fb923c",  // orange-red
  bg:      "#0f172a",  // slate-900
  card:    "rgba(30,41,59,0.85)",
  border:  "rgba(148,163,184,0.15)",
  text:    "#f1f5f9",
  muted:   "#94a3b8",
  red:     "#ef4444",
  green:   "#22c55e",
  yellow:  "#eab308",
};

const mono = { fontFamily: "'JetBrains Mono', 'Fira Mono', monospace" };

const glassy = {
  background: C.card,
  border: `1px solid ${C.border}`,
  borderRadius: 10,
  padding: "14px 18px",
  backdropFilter: "blur(8px)",
};

const badge = (color, text) => (
  <span style={{
    background: color + "22", color, border: `1px solid ${color}`,
    borderRadius: 6, padding: "2px 8px", fontSize: 11, fontWeight: 700,
    letterSpacing: 1, ...mono,
  }}>{text}</span>
);

const watt = (w) => {
  if (w == null) return "—";
  if (Math.abs(w) >= 1000) return `${(w / 1000).toFixed(2)} kW`;
  return `${Math.round(w)} W`;
};

const PANEL_COLORS = {
  "Panel1 (HVAC)": C.hvac,
  "Panel2 (H2O)": C.h2o,
  "Panel3 (Kitchen)": C.kitchen,
  "Shop": C.shop,
};

// ── Sub-components ────────────────────────────────────────────────────────

function LLMControlStrip({ health, models, onRefreshModels }) {
  const [backend, setBackend] = useState("ollama");
  const [selectedModel, setSelectedModel] = useState("mistral:7b");
  const [showPullModal, setShowPullModal] = useState(false);
  const [pullName, setPullName] = useState("");
  const [pullProgress, setPullProgress] = useState([]);
  const [pulling, setPulling] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [testing, setTesting] = useState(false);

  const ollama_ok = health?.ollama;
  const modelList = models?.models || [];
  const found = modelList.find(m => m.name === selectedModel);

  const handlePull = async () => {
    setPulling(true);
    setPullProgress([]);
    await pullModel(pullName, (chunk) => {
      setPullProgress(prev => [...prev.slice(-8), chunk.status || JSON.stringify(chunk)]);
    });
    setPulling(false);
    setShowPullModal(false);
    onRefreshModels();
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    const r = await testModel(selectedModel, backend);
    setTestResult(r);
    setTesting(false);
  };

  return (
    <div style={{ ...glassy, marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span style={{ color: C.gen, fontWeight: 700, fontSize: 13, ...mono }}>LOCAL LLM</span>

        <div style={{ display: "flex", gap: 6 }}>
          {["ollama", "llama_cpp"].map(b => (
            <button key={b} onClick={() => setBackend(b)} style={{
              background: backend === b ? C.hvac + "33" : "transparent",
              color: backend === b ? C.hvac : C.muted,
              border: `1px solid ${backend === b ? C.hvac : C.border}`,
              borderRadius: 6, padding: "3px 10px", cursor: "pointer", fontSize: 12, ...mono,
            }}>{b}</button>
          ))}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ width: 10, height: 10, borderRadius: "50%",
            background: ollama_ok ? C.green : C.red, display: "inline-block" }} />
          <span style={{ color: C.muted, fontSize: 12 }}>{ollama_ok ? "Connected" : "Offline"}</span>
        </div>

        <select value={selectedModel} onChange={e => setSelectedModel(e.target.value)}
          style={{ background: "#1e293b", color: C.text, border: `1px solid ${C.border}`,
            borderRadius: 6, padding: "4px 8px", fontSize: 12, ...mono }}>
          {modelList.length === 0 && <option value="mistral:7b">mistral:7b</option>}
          {modelList.map(m => (
            <option key={m.name} value={m.name}>{m.name}</option>
          ))}
        </select>
        {found && <span style={{ color: C.muted, fontSize: 11, ...mono }}>{found.size_gb} GB</span>}

        <button onClick={() => setShowPullModal(true)} style={{
          background: "transparent", color: C.gen, border: `1px solid ${C.gen}`,
          borderRadius: 6, padding: "4px 12px", cursor: "pointer", fontSize: 12,
        }}>+ Pull model</button>

        <button onClick={handleTest} disabled={testing} style={{
          background: "transparent", color: C.hvac, border: `1px solid ${C.hvac}`,
          borderRadius: 6, padding: "4px 12px", cursor: "pointer", fontSize: 12,
        }}>{testing ? "Testing…" : "Test prompt"}</button>
        {testResult && (
          <span style={{ fontSize: 11, color: testResult.ok ? C.green : C.red, ...mono }}>
            {testResult.ok ? `${testResult.latency_ms}ms` : testResult.error}
          </span>
        )}
      </div>

      {showPullModal && (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <input value={pullName} onChange={e => setPullName(e.target.value)}
              placeholder="e.g. deepseek-r1:7b"
              style={{ flex: 1, background: "#1e293b", color: C.text,
                border: `1px solid ${C.border}`, borderRadius: 6,
                padding: "6px 10px", fontSize: 12, ...mono }} />
            <button onClick={handlePull} disabled={pulling || !pullName} style={{
              background: C.gen + "22", color: C.gen, border: `1px solid ${C.gen}`,
              borderRadius: 6, padding: "6px 14px", cursor: "pointer",
            }}>{pulling ? "Pulling…" : "Pull"}</button>
            <button onClick={() => setShowPullModal(false)} style={{
              background: "transparent", color: C.muted, border: `1px solid ${C.border}`,
              borderRadius: 6, padding: "6px 10px", cursor: "pointer",
            }}>✕</button>
          </div>
          {pullProgress.map((line, i) => (
            <div key={i} style={{ fontSize: 11, color: C.muted, ...mono }}>{line}</div>
          ))}
        </div>
      )}
    </div>
  );
}


function PanelCard({ panelName, states, onDisaggregate, disaggLoading }) {
  const color = PANEL_COLORS[panelName] || C.muted;
  const stateEntries = Object.entries(states || {}).filter(([k]) => !k.includes("vacuum_cleaner"));
  const vacuumOn = states?.vacuum_cleaner_status?.slice(-1)[0] === 1;

  return (
    <div style={{ ...glassy, borderLeft: `3px solid ${color}`, flex: "1 1 200px", minWidth: 180 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ color, fontWeight: 700, fontSize: 12, ...mono }}>{panelName}</span>
        <button onClick={onDisaggregate} disabled={disaggLoading} style={{
          background: "transparent", color: C.muted, border: `1px solid ${C.border}`,
          borderRadius: 5, padding: "2px 8px", fontSize: 10, cursor: "pointer",
        }}>{disaggLoading ? "…" : "NILM"}</button>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {stateEntries.length === 0 && (
          <span style={{ color: C.muted, fontSize: 11 }}>No states yet — run NILM</span>
        )}
        {stateEntries.map(([field, values]) => {
          const label = field.replace("_status", "").replace(/_/g, " ");
          const on = Array.isArray(values) ? values.slice(-1)[0] === 1 : values === 1;
          return (
            <div key={field} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: 11, color: C.text }}>{label}</span>
              <span style={{
                fontSize: 10, borderRadius: 4, padding: "1px 6px", ...mono,
                background: on ? C.green + "33" : C.muted + "22",
                color: on ? C.green : C.muted,
              }}>{on ? "ON" : "OFF"}</span>
            </div>
          );
        })}
        {vacuumOn && (
          <div style={{ fontSize: 11, color: C.yellow, marginTop: 4 }}>
            ⚡ Vacuum detected
          </div>
        )}
      </div>
    </div>
  );
}


function RecommendationCard({ rec, onAccept, onDefer, onDismiss }) {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;

  const isAnomaly = rec.is_anomaly;
  const borderColor = isAnomaly ? C.red : C.gen;

  return (
    <div style={{ ...glassy, borderLeft: `3px solid ${borderColor}`, marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
            {isAnomaly && badge(C.red, "ANOMALY")}
            {badge(rec.audience === "auto" ? C.hvac : C.yellow,
              rec.audience === "auto" ? "AUTO" : "USER")}
            <span style={{ fontSize: 12, color: C.text }}>{rec.action}</span>
          </div>
          {rec.savings_dollars > 0 && (
            <div style={{ fontSize: 11, color: C.green, ...mono }}>
              Save ${rec.savings_dollars.toFixed(2)} today
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          <button onClick={() => onAccept(rec.id)} style={_btnStyle(C.green)}>Accept</button>
          <button onClick={() => onDefer(rec.id)} style={_btnStyle(C.yellow)}>Defer</button>
          <button onClick={() => { onDismiss(rec.id); setDismissed(true); }}
            style={_btnStyle(C.muted)}>✕</button>
        </div>
      </div>
    </div>
  );
}

function _btnStyle(color) {
  return {
    background: "transparent", color, border: `1px solid ${color}`,
    borderRadius: 5, padding: "2px 8px", fontSize: 10, cursor: "pointer",
  };
}


// ── Main IEMS Page ────────────────────────────────────────────────────────

const IemsPage = () => {
  const [health, setHealth] = useState(null);
  const [models, setModels] = useState(null);
  const [cycleData, setCycleData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState("on_grid");
  const [selectedModel, setSelectedModel] = useState("mistral:7b");
  const [backend, setBackend] = useState("ollama");
  const [panelLoading, setPanelLoading] = useState({});
  const [error, setError] = useState(null);
  const [recStates, setRecStates] = useState({});
  const [liveStorage, setLiveStorage] = useState(null);

  const refreshHealth = useCallback(async () => {
    try { setHealth(await getHealth()); } catch (e) { setHealth(null); }
  }, []);

  const refreshModels = useCallback(async () => {
    try { setModels(await getModels()); } catch (e) { setModels(null); }
  }, []);

  useEffect(() => {
    refreshHealth();
    refreshModels();
    const t = setInterval(refreshHealth, 30000);
    return () => clearInterval(t);
  }, [refreshHealth, refreshModels]);

  useEffect(() => {
    let alive = true;
    const tick = async () => { try { const d = await getStorage(); if (alive) setLiveStorage(d); } catch (e) {} };
    tick();
    const t = setInterval(tick, 8000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const handleRunCycle = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await runCycle({ mode, model: selectedModel, backend });
      setCycleData(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDisaggregatePanel = async (panel) => {
    setPanelLoading(prev => ({ ...prev, [panel]: true }));
    try {
      const res = await disaggregatePanel(panel, selectedModel, backend);
      setCycleData(prev => ({
        ...(prev || {}),
        panel_states: { ...(prev?.panel_states || {}), [panel]: res.states },
      }));
    } catch (e) {
      setError(e.message);
    } finally {
      setPanelLoading(prev => ({ ...prev, [panel]: false }));
    }
  };

  const handleAccept = async (id) => {
    await acceptRec(id);
    setRecStates(s => ({ ...s, [id]: "accepted" }));
  };
  const handleDefer = async (id) => {
    await deferRec(id);
    setRecStates(s => ({ ...s, [id]: "deferred" }));
  };
  const handleDismiss = async (id) => {
    await dismissRec(id);
    setRecStates(s => ({ ...s, [id]: "dismissed" }));
  };

  const anomalies = cycleData?.anomalies || [];
  const recs = (cycleData?.dss_recommendations || []).filter(
    r => !recStates[r.id]
  );
  const tou = cycleData?.tou || {};
  const weather = cycleData?.weather || {};
  const gen = cycleData?.generation || {};
  const storage = cycleData?.storage || {};
  const panelStates = cycleData?.panel_states || {};
  const vacuumPanel = cycleData?.vacuum_active_panel;
  const flowBranch = cycleData?.flow_chart_branch || "—";
  const meta = cycleData?.metadata || {};

  const LOAD_PANELS = ["Panel1 (HVAC)", "Panel2 (H2O)", "Panel3 (Kitchen)", "Shop"];

  const touColor = tou.period === "peak" ? C.red : tou.period === "partial_peak" ? C.yellow : C.green;

  return (
    <div style={{ background: C.bg, minHeight: "100vh", padding: 20, color: C.text }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: 0, color: C.gen, fontSize: 18, ...mono }}>
            ⚡ IEMS — Intelligent Energy Management
          </h2>
          <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>
            Adabi 2016 architecture · LLM4NILM (Xue 2025) · eGauge18646
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <div style={{ display: "flex", gap: 6 }}>
            {["on_grid", "off_grid"].map(m => (
              <button key={m} onClick={() => setMode(m)} style={{
                background: mode === m ? C.grid + "33" : "transparent",
                color: mode === m ? C.grid : C.muted,
                border: `1px solid ${mode === m ? C.grid : C.border}`,
                borderRadius: 6, padding: "4px 12px", cursor: "pointer", fontSize: 12, ...mono,
              }}>{m === "on_grid" ? "On-Grid" : "Off-Grid"}</button>
            ))}
          </div>
          <button onClick={handleRunCycle} disabled={loading} style={{
            background: C.gen + "22", color: C.gen, border: `1px solid ${C.gen}`,
            borderRadius: 8, padding: "8px 20px", cursor: "pointer",
            fontSize: 13, fontWeight: 700, ...mono,
            opacity: loading ? 0.6 : 1,
          }}>{loading ? "Running…" : "▶ Run IEMS Cycle"}</button>
        </div>
      </div>

      {error && (
        <div style={{ background: C.red + "22", border: `1px solid ${C.red}`,
          borderRadius: 8, padding: "8px 14px", marginBottom: 12, color: C.red, fontSize: 12 }}>
          {error}
        </div>
      )}

      {/* TOP STRIP — LOCAL LLM CONTROL */}
      <LLMControlStrip health={health} models={models} onRefreshModels={refreshModels} />

      {/* LIVE SOLAR (derived via energy balance) + BATTERY (13.5 kWh, modeled) */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <div style={{ ...glassy, borderLeft: `3px solid ${C.gen}`, flex: "1 1 260px", minWidth: 240 }}>
          <div style={{ fontSize: 12, color: C.gen, ...mono, marginBottom: 6 }}>
            ☀ SOLAR PRODUCTION <span style={{ color: C.muted, fontSize: 9 }}>(derived)</span>
          </div>
          <div style={{ fontSize: 28, fontWeight: 700, ...mono }}>
            {liveStorage?.solar ? (liveStorage.solar.production_w / 1000).toFixed(2) : "—"}
            <span style={{ fontSize: 14, color: C.muted }}> kW</span>
          </div>
          <div style={{ fontSize: 11, color: C.muted, marginTop: 6, ...mono }}>
            {liveStorage?.solar ? `house ${liveStorage.solar.house_load_w} W · exporting ${liveStorage.solar.exporting_w} W` : "—"}
          </div>
        </div>
        <div style={{ ...glassy, borderLeft: `3px solid ${C.green}`, flex: "1 1 260px", minWidth: 240 }}>
          <div style={{ fontSize: 12, color: C.green, ...mono, marginBottom: 6 }}>
            🔋 BATTERY SOC <span style={{ color: C.muted, fontSize: 9 }}>(13.5 kWh · {liveStorage?.battery?.soc_floor_pct ?? 10}% floor · modeled)</span>
          </div>
          <div style={{ fontSize: 28, fontWeight: 700, ...mono }}>
            {liveStorage?.battery ? liveStorage.battery.soc_pct.toFixed(1) : "—"}
            <span style={{ fontSize: 14, color: C.muted }}> %</span>
          </div>
          <div style={{ fontSize: 11, color: C.muted, marginTop: 6, ...mono }}>
            {liveStorage?.battery ? `${liveStorage.battery.flow} · ${liveStorage.battery.available_kwh} kWh available` : "—"}
          </div>
        </div>
      </div>

      {/* Anomaly banner */}
      {anomalies.length > 0 && (
        <div style={{ background: C.red + "22", border: `1px solid ${C.red}`,
          borderRadius: 8, padding: "8px 14px", marginBottom: 12 }}>
          <span style={{ color: C.red, fontWeight: 700, fontSize: 12 }}>
            ⚠ {anomalies.length} Anomaly{anomalies.length > 1 ? "s" : ""} Detected:
          </span>
          {anomalies.map((a, i) => (
            <div key={i} style={{ color: C.red, fontSize: 11, marginTop: 4 }}>{a.message}</div>
          ))}
        </div>
      )}

      {/* Vacuum mobile load banner */}
      {vacuumPanel && (
        <div style={{ background: C.yellow + "22", border: `1px solid ${C.yellow}`,
          borderRadius: 8, padding: "6px 14px", marginBottom: 12 }}>
          <span style={{ color: C.yellow, fontSize: 12 }}>
            🧹 Vacuum detected on {vacuumPanel}
          </span>
        </div>
      )}

      {/* ROW 1 — USER DOMAIN */}
      <div style={{ ...glassy, marginBottom: 16 }}>
        <div style={{ color: C.muted, fontSize: 11, fontWeight: 700, marginBottom: 8, ...mono }}>
          USER DOMAIN
        </div>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 11, color: C.muted, marginBottom: 4 }}>Critical (never shed)</div>
            <div style={{ display: "flex", gap: 6 }}>
              {["Refrigerator", "Pressure Pump", "Networking"].map(l => badge(C.red, l))}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: C.muted, marginBottom: 4 }}>Deferrable</div>
            <div style={{ display: "flex", gap: 6 }}>
              {["Dryer", "Washer", "Dishwasher", "Sprinklers"].map(l => badge(C.yellow, l))}
            </div>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 11, color: C.muted }}>Model</span>
            <select value={selectedModel} onChange={e => setSelectedModel(e.target.value)}
              style={{ background: "#1e293b", color: C.text, border: `1px solid ${C.border}`,
                borderRadius: 6, padding: "3px 8px", fontSize: 11, ...mono }}>
              {(models?.models || [{ name: "mistral:7b" }]).map(m => (
                <option key={m.name} value={m.name}>{m.name}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* ROW 2 — LOAD DOMAIN */}
      <div style={{ ...glassy, marginBottom: 16 }}>
        <div style={{ color: C.muted, fontSize: 11, fontWeight: 700, marginBottom: 12, ...mono }}>
          LOAD DOMAIN — LLM4NILM
        </div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {LOAD_PANELS.map(panel => (
            <PanelCard
              key={panel}
              panelName={panel}
              states={panelStates[panel] || {}}
              onDisaggregate={() => handleDisaggregatePanel(panel)}
              disaggLoading={panelLoading[panel]}
            />
          ))}
        </div>
        {meta.n_windows > 0 && (
          <div style={{ marginTop: 10, fontSize: 11, color: C.muted, ...mono }}>
            {meta.n_windows} windows · {meta.llm_correction_count} corrections ·
            {meta.latency_ms}ms · model: {meta.model}
          </div>
        )}
      </div>

      {/* ROW 3 — GENERATION + GRID */}
      <div style={{ ...glassy, marginBottom: 16 }}>
        <div style={{ color: C.muted, fontSize: 11, fontWeight: 700, marginBottom: 12, ...mono }}>
          GENERATION + GRID
        </div>
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 11, color: C.muted }}>Grid Power</div>
            <div style={{ fontSize: 22, color: C.grid, ...mono }}>
              {watt(gen.grid_w)}
            </div>
            <div style={{ fontSize: 10, color: C.muted }}>
              {gen.grid_w < 0 ? "Exporting" : "Importing"}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: C.muted }}>Generac</div>
            <div style={{ fontSize: 22, color: C.gen, ...mono }}>{watt(gen.generac_w)}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: C.muted }}>Outside Temp</div>
            <div style={{ fontSize: 22, color: C.hvac, ...mono }}>
              {weather.outside_temp_f != null ? `${weather.outside_temp_f}°F` : "—"}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: C.muted }}>Cloud Cover</div>
            <div style={{ fontSize: 22, color: C.muted, ...mono }}>
              {weather.cloud_cover_pct != null ? `${weather.cloud_cover_pct}%` : "—"}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: C.muted }}>Solar Irradiance</div>
            <div style={{ fontSize: 22, color: C.gen, ...mono }}>
              {weather.irradiance_6h_avg != null ? `${weather.irradiance_6h_avg} W/m²` : "—"}
            </div>
            <div style={{ fontSize: 10, color: C.muted }}>
              {weather.irradiance_label || "—"} (6h avg)
            </div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: C.muted }}>TOU Period</div>
            <div style={{ marginTop: 4 }}>
              {badge(touColor, (tou.period || "—").replace("_", " ").toUpperCase())}
            </div>
            <div style={{ fontSize: 10, color: C.muted, marginTop: 4, ...mono }}>
              ${tou.rate_per_kwh?.toFixed(2)}/kWh · {tou.season}
            </div>
          </div>
        </div>
        {/* TOU rate strip */}
        {cycleData?.rate_strip && (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 10, color: C.muted, marginBottom: 4 }}>PG&E E6 hourly rates today</div>
            <div style={{ display: "flex", gap: 2 }}>
              {cycleData.rate_strip.map(h => {
                const rc = h.period === "peak" ? C.red : h.period === "partial_peak" ? C.yellow : C.green;
                const isCurrent = h.hour === (tou.hour || 0);
                return (
                  <div key={h.hour} title={`${h.hour}:00 — ${h.period} $${h.rate}/kWh`}
                    style={{ flex: 1, height: 20, background: rc + (isCurrent ? "ff" : "55"),
                      borderRadius: 2, border: isCurrent ? `1px solid ${rc}` : "none",
                      cursor: "default" }} />
                );
              })}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between",
              fontSize: 9, color: C.muted, marginTop: 2 }}>
              <span>12 AM</span><span>6 AM</span><span>12 PM</span>
              <span>6 PM</span><span>11 PM</span>
            </div>
          </div>
        )}
      </div>

      {/* ROW 4 — STORAGE + DSS */}
      <div style={{ ...glassy }}>
        <div style={{ color: C.muted, fontSize: 11, fontWeight: 700, marginBottom: 12, ...mono }}>
          STORAGE + DECISION SUPPORT
        </div>
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 11, color: C.muted }}>Virtual Battery SOC</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 4 }}>
              <span style={{ fontSize: 32, color: C.gen, ...mono }}>
                {storage.soc_virtual?.soc_pct ?? "—"}%
              </span>
              <span style={{ fontSize: 11, color: C.muted }}>
                ({storage.soc_virtual?.available_kwh ?? "—"} kWh available)
              </span>
            </div>
            <div style={{ fontSize: 10, color: C.muted, marginTop: 2 }}>
              What-if: 13.5 kWh Powerwall — no battery installed
            </div>
            {/* SOC bar */}
            <div style={{ background: C.muted + "33", borderRadius: 4, height: 8,
              width: 160, marginTop: 6, overflow: "hidden" }}>
              <div style={{ background: C.gen, height: "100%",
                width: `${storage.soc_virtual?.soc_pct ?? 50}%`,
                borderRadius: 4, transition: "width 0.5s" }} />
            </div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: C.muted }}>Dispatch</div>
            <div style={{ marginTop: 4 }}>
              {badge(
                storage.dispatch_recommendation?.action === "discharge" ? C.yellow :
                storage.dispatch_recommendation?.action === "charge" ? C.green : C.muted,
                (storage.dispatch_recommendation?.action || "idle").toUpperCase()
              )}
            </div>
            <div style={{ fontSize: 11, color: C.muted, marginTop: 6, maxWidth: 250 }}>
              {storage.dispatch_recommendation?.rationale}
            </div>
          </div>
          <div style={{ marginLeft: "auto" }}>
            <div style={{ fontSize: 11, color: C.muted }}>Flow Branch (Adabi Fig 5.16)</div>
            <div style={{ fontSize: 12, color: C.text, marginTop: 4, ...mono }}>{flowBranch}</div>
          </div>
        </div>

        <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 12 }}>
          <div style={{ fontSize: 12, color: C.muted, marginBottom: 10 }}>
            Recommendations ({recs.length})
          </div>
          {recs.length === 0 && !loading && (
            <div style={{ fontSize: 12, color: C.muted }}>
              Run a cycle to see recommendations.
            </div>
          )}
          {recs.map(rec => (
            <RecommendationCard
              key={rec.id}
              rec={rec}
              onAccept={handleAccept}
              onDefer={handleDefer}
              onDismiss={handleDismiss}
            />
          ))}
        </div>
      </div>
    </div>
  );
};

export const pluginMetadata = {
  name: "IEMS",
  icon: "⚡",
};

export default IemsPage;
