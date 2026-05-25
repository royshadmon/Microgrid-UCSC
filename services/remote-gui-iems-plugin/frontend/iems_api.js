// IEMS API client — proxies to /iems/* on the FastAPI backend
const API_URL = window._env_?.REACT_APP_API_URL || "http://localhost:8000";

async function _get(path) {
  const res = await fetch(`${API_URL}${path}`);
  if (!res.ok) throw new Error(`IEMS API ${path}: ${res.status}`);
  return res.json();
}

async function _post(path, body) {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`IEMS API POST ${path}: ${res.status}`);
  return res.json();
}

export const getHealth = () => _get("/iems/health");
export const getModels = () => _get("/iems/models");
export const getAppliances = () => _get("/iems/appliances");
export const getTouRates = () => _get("/iems/tou_rates");
export const getPreferences = () => _get("/iems/preferences");
export const getActiveAnomalies = () => _get("/iems/anomalies/active");

export const runCycle = (opts = {}) =>
  _post("/iems/cycle", {
    mode: opts.mode || "on_grid",
    llm_model: opts.model || "mistral:7b",
    llm_backend: opts.backend || "ollama",
    window_minutes: opts.windowMinutes || 10,
  });

export const disaggregatePanel = (panel, model, backend, minutes) =>
  _post("/iems/disaggregate", {
    panel,
    llm_model: model || "mistral:7b",
    llm_backend: backend || "ollama",
    window_minutes: minutes || 10,
  });

export const testModel = (model, backend) =>
  _post("/iems/models/test", { model, backend: backend || "ollama" });

export const setPreferences = (prefs) => _post("/iems/preferences", prefs);

export const acceptRec = (id) => _post(`/iems/recommendations/${id}/accept`, {});
export const deferRec = (id) => _post(`/iems/recommendations/${id}/defer`, {});
export const dismissRec = (id) => _post(`/iems/recommendations/${id}/dismiss`, {});

export async function pullModel(modelName, onChunk) {
  const res = await fetch(`${API_URL}/iems/models/pull`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_name: modelName }),
  });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const lines = decoder.decode(value).split("\n").filter(Boolean);
    for (const line of lines) {
      try {
        onChunk(JSON.parse(line));
      } catch (_) {
        onChunk({ status: line });
      }
    }
  }
}
