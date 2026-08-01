// Shared appliance catalog — keep in sync with services/iems/web/server.js
// Display order is the dashboard order.
export const NILM_APPLIANCES = [
  {key:'heat_pump',       label:'Heat Pump',       circuit:'Panel1 (HVAC)',    model:'panel1', icon:'❄',  c:'#38bdf8'},
  {key:'solar_pump',      label:'Solar Pump',      circuit:'Panel1 (HVAC)',    model:'panel1', icon:'☀',  c:'#fbbf24'},
  {key:'water_heater',    label:'Water Heater',    circuit:'Panel2 (H2O)',     model:'panel2', icon:'🔥', c:'#c084fc'},
  {key:'hair_dryer',      label:'Hair Dryer',      circuit:'Panel2 (H2O)',     model:'panel2', icon:'💨', c:'#f472b6'},
  {key:'sprinklers',      label:'Sprinklers',      circuit:'Panel2 (H2O)',     model:'panel2', icon:'💧', c:'#22d3ee'},
  {key:'bath_lights',     label:'Bath Lights',     circuit:'Panel2 (H2O)',     model:'panel2', icon:'💡', c:'#fde68a'},
  {key:'refrigerator',    label:'Refrigerator',    circuit:'Panel3 (Kitchen)', model:'panel3', icon:'🧊', c:'#4ade80'},
  {key:'dishwasher',      label:'Dishwasher',      circuit:'Panel3 (Kitchen)', model:'panel3', icon:'🍽', c:'#60a5fa'},
  {key:'microwave',       label:'Microwave',       circuit:'Panel3 (Kitchen)', model:'panel3', icon:'📡', c:'#fb923c'},
  {key:'dryer',           label:'Dryer',           circuit:'Shop',             model:'panel3', icon:'🌀', c:'#f87171'},
  {key:'washing_machine', label:'Washer',          circuit:'Shop',             model:'panel3', icon:'🧺', c:'#a78bfa'},
  {key:'pressure_pump',   label:'Pressure Pump',   circuit:'Shop',             model:'panel3', icon:'⛲', c:'#34d399'},
  {key:'computers',       label:'Computers',       circuit:'Panel3 (Kitchen)', model:'panel3', icon:'💻', c:'#818cf8'},
  {key:'tv_stereo',       label:'TV / Stereo',     circuit:'Panel3 (Kitchen)', model:'panel3', icon:'📺', c:'#fb7185'},
];
