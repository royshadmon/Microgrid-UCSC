// Thin client for the IEMS plugin routes.
//
// Every path here is served by the plugin's router in the remote-gui backend,
// which forwards to the IEMS engine running on this host. Nothing in this file
// talks to the engine directly, so the GUI stays the single entry point.

import { getApiBaseUrl } from '../../utils/runtimeConfig';

const base = () => String(getApiBaseUrl() || '').replace(/\/+$/, '');

const asJson = async (res) => {
  const text = await res.text();
  let body;
  try {
    body = text ? JSON.parse(text) : null;
  } catch (err) {
    body = { raw: text };
  }
  if (!res.ok) {
    const detail = (body && (body.detail || body.error)) || res.statusText;
    throw new Error(`${res.status} ${detail}`);
  }
  return body;
};

const get = (path) => fetch(`${base()}/iems${path}`).then(asJson);

const post = (path, payload) =>
  fetch(`${base()}/iems${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  }).then(asJson);

export const iemsApi = {
  health: () => get('/health'),
  channels: () => get('/channels'),
  appliances: () => get('/appliances'),
  storage: () => get('/storage'),
  touRates: () => get('/tou_rates'),
  nilmRecent: (minutes = 10) => get(`/nilm/recent?minutes=${minutes}`),
  onnxModels: () => get('/onnx/models'),
  onnxSnapshot: () => get('/onnx/snapshot'),
  activeAnomalies: () => get('/anomalies/active'),
  preferences: () => get('/preferences'),
  savePreferences: (prefs) => post('/preferences', prefs),
  runCycle: (opts) => post('/cycle', opts),
  disaggregate: (opts) => post('/disaggregate', opts),
  acceptRecommendation: (id) => post(`/recommendations/${id}/accept`),
  deferRecommendation: (id) => post(`/recommendations/${id}/defer`),
  dismissRecommendation: (id) => post(`/recommendations/${id}/dismiss`),
  // Aggregated dashboard feeds, proxied to the IEMS dashboard service.
  dash: (path) => fetch(`${base()}/iems/dash/api/${path}`).then(asJson),
};

export default iemsApi;
