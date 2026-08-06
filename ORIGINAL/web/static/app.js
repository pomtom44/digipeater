'use strict';

// ── State ─────────────────────────────────────────────────────
const state = {
  token: localStorage.getItem('token') || null,
  config: {},
  direwolfState: 'stopped',
  gps_fix: null,
  tracesEnabled: true,
  mapFilter: 'all',       // 'all' | 'direct' | 'position'
  stations: {},           // callsign → {marker, polyline, packet}
  map: null,
  logWs: null,
  mapWs: null,
  statusInterval: null,
  cacheInterval: null,
  agingInterval: null,
};

// ── API helper ────────────────────────────────────────────────
async function api(method, path, body = null) {
  const res = await _apiFetch(method, path, body);
  if (res.status === 401 && path !== '/api/auth/login') {
    await showLogin();
    return api(method, path, body);  // retry with new token
  }
  return res.ok ? res.json() : null;
}

async function _apiFetch(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (state.token) opts.headers['Authorization'] = `Bearer ${state.token}`;
  if (body !== null) opts.body = JSON.stringify(body);
  return fetch(path, opts);
}

// ── Boot ──────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  const status = await api('GET', '/api/status');
  if (!status) return;

  // If full security and no stored token, require login before proceeding
  if (status.security_mode === 'full' && !state.token) {
    await showLogin();
  }

  if (!status.setup_complete) {
    showWizard();
  } else {
    await loadConfig();
    showApp();
  }
});

// ── App ───────────────────────────────────────────────────────
function showApp() {
  document.getElementById('app').classList.remove('hidden');
  document.getElementById('wizard-page').classList.add('hidden');
  initMap();
  connectWebSockets();
  startStatusPoll();
  startAgingTimer();
  bindAppEvents();
  updateAuthUI();
}

function bindAppEvents() {
  document.getElementById('btn-start').addEventListener('click', () => api('POST', '/api/direwolf/start'));
  document.getElementById('btn-stop').addEventListener('click', () => api('POST', '/api/direwolf/stop'));
  document.getElementById('btn-config').addEventListener('click', openConfig);
  document.getElementById('btn-logout').addEventListener('click', logout);
  document.getElementById('btn-reboot').addEventListener('click', async () => {
    if (confirm('Reboot the device?')) await api('POST', '/api/system/reboot');
  });
  document.getElementById('config-back').addEventListener('click', closeConfig);
  document.getElementById('btn-save-config').addEventListener('click', saveConfig);
  document.getElementById('btn-export-config').addEventListener('click', exportConfig);
  document.getElementById('btn-import-config').addEventListener('change', importConfig);
  document.getElementById('btn-reset-packets').addEventListener('click', async () => {
    if (confirm('Clear all map data?')) {
      await api('DELETE', '/api/packets');
      clearMapStations();
    }
  });


  // Map toolbar
  ['all', 'direct', 'position'].forEach(f => {
    document.getElementById(`filter-${f}`).addEventListener('click', () => setFilter(f));
  });
  document.getElementById('toggle-traces').addEventListener('click', toggleTraces);
  document.getElementById('btn-clear-map').addEventListener('click', clearMapStations);

  // Config page events
  document.getElementById('cfg-interface-type').addEventListener('change', updateInterfaceFields);
  document.getElementById('cfg-mode-rx').addEventListener('change', updateModeFields);
  document.getElementById('cfg-ptt-method').addEventListener('change', updatePttFields);
  document.getElementById('cfg-digi-enabled').addEventListener('change', e => toggleSection('cfg-digi-fields', e.target.checked));
  document.getElementById('cfg-igate-enabled').addEventListener('change', e => toggleSection('cfg-igate-fields', e.target.checked));
  document.getElementById('cfg-rfb-enabled').addEventListener('change', e => toggleSection('cfg-rfb-fields', e.target.checked));
  document.getElementById('cfg-rfb-gps').addEventListener('change', e => toggleSection('cfg-rfb-fixed', !e.target.checked));
  document.getElementById('btn-rfb-fetch-gps').addEventListener('click', () => fetchGpsToForm('cfg-rfb-lat', 'cfg-rfb-lon'));
  document.getElementById('cfg-igb-enabled').addEventListener('change', e => toggleSection('cfg-igb-fields', e.target.checked));
  document.getElementById('cfg-igb-gps').addEventListener('change', e => toggleSection('cfg-igb-fixed', !e.target.checked));
  document.getElementById('btn-igb-fetch-gps').addEventListener('click', () => fetchGpsToForm('cfg-igb-lat', 'cfg-igb-lon'));
  document.getElementById('cfg-net-mode').addEventListener('change', updateNetFields);
  document.getElementById('cfg-display-driver').addEventListener('change', updateDisplayFields);
  document.getElementById('cfg-radio-enabled').addEventListener('change', updateRadioFields);
  document.getElementById('cfg-prog-radio').addEventListener('change', updateProgPower);
  document.getElementById('cfg-prog-ctcss-on').addEventListener('change', e => toggleSection('cfg-prog-ctcss-fields', e.target.checked));
  document.getElementById('btn-prog-run').addEventListener('click', programRadio);
  document.getElementById('cfg-map-mode').addEventListener('change', e => toggleSection('cfg-cache-fields', e.target.value === 'cached'));
  document.getElementById('cfg-callsign').addEventListener('blur', autoPasscode);
  document.getElementById('btn-gen-passcode').addEventListener('click', autoPasscode);
  document.getElementById('btn-ptt-test').addEventListener('click', () => api('POST', '/api/ptt-test'));
  document.getElementById('btn-wifi-scan').addEventListener('click', () => scanWifi('cfg-wifi-list'));
  document.getElementById('btn-estimate').addEventListener('click', estimateTiles);
  document.getElementById('btn-cache-start').addEventListener('click', startTileCache);
  document.getElementById('btn-cache-cancel').addEventListener('click', () => api('POST', '/api/map/cache/cancel'));
}

// ── Status polling ────────────────────────────────────────────
function startStatusPoll() {
  fetchStatus();
  state.statusInterval = setInterval(fetchStatus, 3000);
}

async function fetchStatus() {
  const s = await api('GET', '/api/status');
  if (!s) return;

  const dw = s.direwolf;
  state.direwolfState = dw.state;
  state.gps_fix = s.gps?.fix || null;

  // Dot & text
  const dot = document.getElementById('status-dot');
  dot.className = `status-dot ${dw.state}`;
  document.getElementById('status-text').textContent = dw.state.charAt(0).toUpperCase() + dw.state.slice(1);

  // Buttons
  const running = dw.state === 'running';
  document.getElementById('btn-start').disabled = running;
  document.getElementById('btn-stop').disabled = !running;
  document.getElementById('btn-config').disabled = running;
  document.getElementById('config-stop-warning').classList.toggle('hidden', !running);

  // Stats
  document.getElementById('stat-heard').textContent = s.stats.heard;
  document.getElementById('stat-digi').textContent = s.stats.digipeated;
  document.getElementById('stat-gated').textContent = s.stats.gated;
  document.getElementById('stat-uptime').textContent = dw.uptime || '—';
  document.getElementById('stat-version').textContent = dw.version || '—';

  // APRS-IS connection
  const isEl = document.getElementById('stat-is');
  if (s.aprs_is?.connected) {
    const srv = s.aprs_is.server !== '—' ? s.aprs_is.server : 'server';
    isEl.textContent = `Connected (${srv})`;
    isEl.className = 'stat-value is-connected';
  } else {
    const igateEnabled = state.config?.mode?.igate;
    isEl.textContent = igateEnabled && dw.state === 'running' ? 'Disconnected' : '—';
    isEl.className = `stat-value${igateEnabled && dw.state === 'running' ? ' is-disconnected' : ''}`;
  }

  // Radio frequency
  const radioSection = document.getElementById('radio-section');
  if (s.radio?.enabled) {
    radioSection.classList.remove('hidden');
    document.getElementById('stat-freq').textContent =
      s.radio.frequency != null ? (s.radio.frequency / 1e6).toFixed(3) + ' MHz' : '—';
  } else {
    radioSection.classList.add('hidden');
  }

  // Header callsign
  if (state.config.callsign) {
    const ssid = state.config.ssid ? `-${state.config.ssid}` : '';
    document.getElementById('header-callsign').textContent = state.config.callsign + ssid;
  }
}

// ── WebSockets ────────────────────────────────────────────────
function connectWebSockets() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const base = `${proto}://${location.host}`;

  state.logWs = new WebSocket(`${base}/ws/log`);
  state.logWs.onmessage = e => handleLogMessage(JSON.parse(e.data));
  state.logWs.onclose = () => setTimeout(connectWebSockets, 3000);

  state.mapWs = new WebSocket(`${base}/ws/map`);
  state.mapWs.onmessage = e => handleMapMessage(JSON.parse(e.data));
  state.mapWs.onclose = () => {};
}

function handleLogMessage(msg) {
  const panel = document.getElementById('log-panel');
  const el = document.createElement('div');
  el.className = `log-entry ${msg.level}`;
  el.innerHTML = `<span class="log-time">${msg.time}</span>${escHtml(msg.message)}`;
  panel.appendChild(el);
  // Keep last 500 entries
  while (panel.children.length > 500) panel.removeChild(panel.firstChild);
  panel.scrollTop = panel.scrollHeight;
}

function handleMapMessage(msg) {
  if (msg.type !== 'station') return;
  plotStation(msg);
}

// ── Map ───────────────────────────────────────────────────────
function initMap() {
  const cfg = state.config.map || {};
  const mode = cfg.mode || 'live';
  const tileUrl = mode === 'cached'
    ? '/tiles/{z}/{x}/{y}.png'
    : (cfg.tile_server || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png');

  state.map = L.map('map').setView([0, 0], 4);

  L.tileLayer(tileUrl, {
    attribution: mode === 'live' ? '© OpenStreetMap' : 'Cached tiles',
    maxZoom: 19,
    errorTileUrl: 'data:image/png;base64,iVBORw0KGgo=',
  }).addTo(state.map);

  // If GPS fix available, centre on it
  api('GET', '/api/status').then(s => {
    if (s?.gps?.fix) {
      state.map.setView([s.gps.fix.latitude, s.gps.fix.longitude], 11);
    }
  });

  // Load existing stations
  api('GET', '/api/packets/latest').then(packets => {
    if (packets) packets.forEach(plotStation);
  });
}

function formatPacketTime(packet) {
  if (!packet.timestamp) return packet.time || '';
  const d = new Date(packet.timestamp * 1000);
  const today = new Date();
  const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  if (d.toDateString() === today.toDateString()) return timeStr;
  return `${d.toLocaleDateString([], { day: 'numeric', month: 'short' })} ${timeStr}`;
}

function buildPopupHtml(packet) {
  const call = packet.callsign;
  const lat = packet.latitude;
  const lon = packet.longitude;
  const type = packet.packet_type || 'position';
  const wx = packet.weather || {};
  const hasWx = Object.keys(wx).length > 0;

  const typeBadge = type === 'object'
    ? `<div class="popup-type-badge">Object</div>`
    : type === 'wx' || type === 'weather'
      ? `<div class="popup-type-badge popup-type-wx">Weather</div>`
      : '';

  let wxRows = '';
  if (hasWx) {
    const rows = [];
    if (wx.temperature != null) {
      const c = Math.round((wx.temperature - 32) * 5 / 9 * 10) / 10;
      rows.push(`Temp: ${c} °C`);
    }
    if (wx.humidity != null) rows.push(`Humidity: ${wx.humidity}%`);
    if (wx.wind_speed != null) {
      const kmh = Math.round(wx.wind_speed * 1.852);
      const dir = wx.wind_direction != null ? ` @ ${wx.wind_direction}°` : '';
      rows.push(`Wind: ${kmh} km/h${dir}`);
    }
    if (wx.pressure != null) rows.push(`Pressure: ${wx.pressure} hPa`);
    if (wx.rain_1h != null) {
      const mm = Math.round(wx.rain_1h * 25.4 * 10) / 10;
      rows.push(`Rain (1h): ${mm} mm`);
    }
    wxRows = rows.map(r => `<div class="popup-detail popup-wx-row">${r}</div>`).join('');
  }

  const commentHtml = packet.comment
    ? `<div class="popup-detail">${escHtml(packet.comment)}</div>`
    : '';

  return `
    <div class="popup-call">${escHtml(call)}${typeBadge}</div>
    <div class="popup-detail">${lat.toFixed(4)}° ${lon.toFixed(4)}°</div>
    <div class="popup-detail">${packet.direct ? 'Direct' : 'Via digi'} · ${formatPacketTime(packet)}</div>
    ${wxRows}
    ${commentHtml}
  `;
}

function plotStation(packet) {
  const call = packet.callsign;
  const lat = packet.latitude;
  const lon = packet.longitude;
  if (!lat || !lon) return;

  const aging = (state.config.map?.station_aging || 7200) * 1000;
  if (aging > 0 && Date.now() - (packet.timestamp * 1000) > aging) return;

  const visible = passesFilter(packet);
  const digipeaterPos = getDigipeaterPos();
  const popupHtml = buildPopupHtml(packet);

  if (state.stations[call]) {
    const s = state.stations[call];
    s.marker.setLatLng([lat, lon]).setPopupContent(popupHtml);
    s.marker.setOpacity(visible ? 1 : 0);
    if (s.polyline) {
      if (digipeaterPos) s.polyline.setLatLngs([[lat, lon], digipeaterPos]);
      s.polyline.setStyle({ opacity: visible && state.tracesEnabled ? 0.5 : 0 });
    }
    s.lastSeen = packet.timestamp;
    s.packet = packet;
  } else {
    const icon = buildIcon(packet.symbol_table, packet.symbol_code);
    const marker = L.marker([lat, lon], { icon, opacity: visible ? 1 : 0 })
      .addTo(state.map)
      .bindPopup(popupHtml);

    marker.on('popupopen',  () => showTrack(call));
    marker.on('popupclose', () => hideTrack(call));

    let polyline = null;
    if (digipeaterPos) {
      polyline = L.polyline([[lat, lon], digipeaterPos], {
        color: '#3b82f6', weight: 1,
        opacity: visible && state.tracesEnabled ? 0.5 : 0,
        dashArray: '4,4',
      }).addTo(state.map);
    }

    state.stations[call] = { marker, polyline, track: null, lastSeen: packet.timestamp, packet };
  }
}

function buildIcon(symTable, symCode) {
  if (symCode && symTable) {
    const index = symCode.charCodeAt(0) - 33;
    if (index >= 0 && index < 96) {
      const sheet = (symTable === '\\' || symTable === '1') ? 1 : 0;
      const col = index % 16;
      const row = Math.floor(index / 16);
      return L.divIcon({
        className: 'aprs-icon',
        html: `<div style="width:24px;height:24px;background:url('/symbols/aprs-symbols-24-${sheet}.png') -${col * 24}px -${row * 24}px"></div>`,
        iconSize: [24, 24],
        iconAnchor: [12, 12],
        popupAnchor: [0, -14],
      });
    }
  }
  return L.divIcon({
    className: '',
    html: `<div style="width:10px;height:10px;border-radius:50%;background:#3b82f6;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.5)"></div>`,
    iconSize: [10, 10],
    iconAnchor: [5, 5],
    popupAnchor: [0, -8],
  });
}

async function showTrack(call) {
  const s = state.stations[call];
  if (!s) return;
  if (s.track) {
    s.track.addTo(state.map);
    return;
  }
  const history = await api('GET', `/api/packets?callsign=${encodeURIComponent(call)}&limit=500`);
  if (!history || history.length < 2) return;
  // API returns newest-first; reverse for chronological order
  const coords = history.slice().reverse().filter(p => p.latitude != null && p.longitude != null).map(p => [p.latitude, p.longitude]);
  s.track = L.polyline(coords, { color: '#f59e0b', weight: 2, opacity: 0.85 }).addTo(state.map);
}

function hideTrack(call) {
  const s = state.stations[call];
  if (s?.track) state.map.removeLayer(s.track);
}

function getDigipeaterPos() {
  if (state.config.rf_beacon?.location?.source === 'gps') {
    const fix = state.gps_fix;
    return fix ? [fix.latitude, fix.longitude] : null;
  }
  const lat = state.config.rf_beacon?.location?.latitude;
  const lon = state.config.rf_beacon?.location?.longitude;
  return lat && lon ? [lat, lon] : null;
}

function setFilter(f) {
  state.mapFilter = f;
  ['all', 'direct', 'position'].forEach(id => {
    document.getElementById(`filter-${id}`).classList.toggle('btn-primary', id === f);
    document.getElementById(`filter-${id}`).classList.toggle('btn-secondary', id !== f);
  });
  Object.values(state.stations).forEach(s => {
    const visible = passesFilter(s.packet);
    s.marker.setOpacity(visible ? 1 : 0);
    if (s.polyline) s.polyline.setStyle({ opacity: visible && state.tracesEnabled ? 0.5 : 0 });
  });
}

function passesFilter(packet) {
  if (state.mapFilter === 'direct') return packet.direct;
  if (state.mapFilter === 'position') return !!packet.latitude;
  return true;
}

function toggleTraces() {
  state.tracesEnabled = !state.tracesEnabled;
  document.getElementById('toggle-traces').textContent = `Traces: ${state.tracesEnabled ? 'ON' : 'OFF'}`;
  Object.values(state.stations).forEach(s => {
    if (s.polyline) {
      const visible = passesFilter(s.packet);
      s.polyline.setStyle({ opacity: state.tracesEnabled && visible ? 0.5 : 0 });
    }
  });
}

function removeStation(s) {
  if (s.marker) { s.marker.off(); state.map.removeLayer(s.marker); }
  if (s.polyline) { s.polyline.off(); state.map.removeLayer(s.polyline); }
  if (s.track) { s.track.off(); state.map.removeLayer(s.track); }
}

function clearMapStations() {
  Object.values(state.stations).forEach(removeStation);
  state.stations = {};
}

// ── Station aging ─────────────────────────────────────────────
function startAgingTimer() {
  state.agingInterval = setInterval(() => {
    const aging = (state.config.map?.station_aging || 7200) * 1000;
    if (aging === 0) return;
    const now = Date.now();
    Object.entries(state.stations).forEach(([call, s]) => {
      if ((now - s.lastSeen * 1000) > aging) {
        removeStation(s);
        delete state.stations[call];
      }
    });
  }, 60000);
}

// ── Config page ───────────────────────────────────────────────
async function openConfig() {
  const cfg = await api('GET', '/api/config');
  if (!cfg) return;
  state.config = cfg;

  await loadAudioDevices();
  await loadSerialPorts();
  await loadDisplayModels();
  populateConfigForm(cfg);
  renderDisplayPages(cfg.display?.pages || []);
  renderPinout(cfg);

  document.getElementById('config-page').classList.remove('hidden');
}

function closeConfig() {
  document.getElementById('config-page').classList.add('hidden');
}

function populateConfigForm(cfg) {
  const iface = cfg.interface || {};
  setVal('cfg-interface-type', iface.type || 'audio');
  setVal('cfg-audio-in', iface.audio_input || 'default');
  setVal('cfg-audio-out', iface.audio_output || 'default');
  setVal('cfg-serial-device', iface.device || '');
  setVal('cfg-baud', iface.baud || '9600');

  const mode = cfg.mode || {};
  setCheck('cfg-mode-rx', mode.rx_only || false);
  setVal('cfg-callsign', cfg.callsign || '');
  setVal('cfg-ssid', cfg.ssid ?? 0);
  setVal('cfg-passcode', cfg.aprs_passcode || '');

  const ptt = cfg.ptt || {};
  setVal('cfg-ptt-method', ptt.method || 'gpio');
  setVal('cfg-ptt-pin', ptt.pin || 17);
  setVal('cfg-ptt-port', ptt.port || '');

  setCheck('cfg-digi-enabled', mode.digipeater || false);
  const digiAliasEl = document.getElementById('cfg-digi-alias');
  const savedAliases = cfg.digipeater?.aliases || [];
  Array.from(digiAliasEl.options).forEach(o => { o.selected = savedAliases.includes(o.value); });
  setVal('cfg-digi-source-filter', (cfg.digipeater?.source_filter || []).join(', '));

  setCheck('cfg-igate-enabled', mode.igate || false);
  setVal('cfg-igate-server', cfg.igate?.server || 'rotate.aprs2.net');
  setVal('cfg-igate-port', cfg.igate?.port || 14580);
  setVal('cfg-igate-filter', cfg.igate?.filter || 'r/0/0/100');

  const rfb = cfg.rf_beacon || {};
  setCheck('cfg-rfb-enabled', rfb.enabled || false);
  setVal('cfg-rfb-delay', rfb.delay || 1);
  setVal('cfg-rfb-every', rfb.every || 30);
  setVal('cfg-rfb-symbol', rfb.symbol || '#');
  setVal('cfg-rfb-overlay', rfb.overlay || 'S');
  setVal('cfg-rfb-comment', rfb.comment || 'Digipeater');
  const rfbGps = rfb.location?.source !== 'fixed';
  setCheck('cfg-rfb-gps', rfbGps);
  setVal('cfg-rfb-lat', rfb.location?.latitude || '');
  setVal('cfg-rfb-lon', rfb.location?.longitude || '');

  const igb = cfg.igate_beacon || {};
  setCheck('cfg-igb-enabled', igb.enabled || false);
  setVal('cfg-igb-delay', igb.delay || 1);
  setVal('cfg-igb-every', igb.every || 30);
  setVal('cfg-igb-symbol', igb.symbol || '#');
  setVal('cfg-igb-overlay', igb.overlay || 'S');
  setVal('cfg-igb-comment', igb.comment || 'Digipeater');
  setCheck('cfg-igb-gps', igb.location?.source !== 'fixed');

  setVal('cfg-start-mode', cfg.direwolf?.start_mode || 'manual');
  setVal('cfg-map-mode', cfg.map?.mode || 'live');
  setVal('cfg-aging', cfg.map?.station_aging ?? 7200);
  setVal('cfg-zoom-min', cfg.map?.cache?.zoom_min || 8);
  setVal('cfg-zoom-max', cfg.map?.cache?.zoom_max || 14);

  const net = cfg.network || {};
  setVal('cfg-net-mode', net.mode || 'hotspot');
  setVal('cfg-hotspot-ssid', net.hotspot?.ssid || 'Digipeater');
  setVal('cfg-hotspot-pass', net.hotspot?.password || 'Digipeater');
  setVal('cfg-wifi-ssid', net.wifi_client?.ssid || '');

  const sec = cfg.web?.security || {};
  setVal('cfg-sec-mode', sec.mode || 'none');
  setVal('cfg-sec-pass', sec.password || '');

  const disp = cfg.display || {};
  setVal('cfg-display-driver', disp.driver || 'none');
  setVal('cfg-display-model', disp.model || 'epd1in54_v2');
  updateDisplayFields();

  const radio = cfg.radio || {};
  setCheck('cfg-radio-enabled', radio.enabled || false);
  setVal('cfg-radio-model', radio.model || 1);
  setVal('cfg-radio-port', radio.port || '/dev/ttyUSB0');
  setVal('cfg-radio-baud', radio.baud || 9600);
  updateRadioFields();

  const prog = cfg.radio_programmer || {};
  setVal('cfg-prog-radio', prog.radio || 'alinco_dr138t');
  setVal('cfg-prog-freq-mhz', prog.frequency_hz ? (prog.frequency_hz / 1e6).toFixed(3) : '144.575');
  updateProgPower();
  setVal('cfg-prog-power', prog.power || RADIO_MODELS['alinco_dr138t'].power[0].value);
  const ctcssOn = !!prog.ctcss_hz;
  setCheck('cfg-prog-ctcss-on', ctcssOn);
  toggleSection('cfg-prog-ctcss-fields', ctcssOn);
  if (ctcssOn) setVal('cfg-prog-ctcss', prog.ctcss_hz);

  // Trigger conditional field visibility
  updateInterfaceFields();
  updateModeFields();
  updatePttFields();
  updateNetFields();
  toggleSection('cfg-digi-fields', mode.digipeater || false);
  toggleSection('cfg-igate-fields', mode.igate || false);
  toggleSection('cfg-rfb-fields', rfb.enabled || false);
  toggleSection('cfg-rfb-fixed', !rfbGps);
  toggleSection('cfg-igb-fields', igb.enabled || false);
  toggleSection('cfg-cache-fields', (cfg.map?.mode || 'live') === 'cached');

  if (!getVal('cfg-passcode')) autoPasscode();
}

async function saveConfig() {
  const cfg = buildConfigFromForm();
  const res = await api('POST', '/api/config', cfg);
  if (res?.ok) {
    state.config = cfg;
    closeConfig();
  }
}

function buildConfigFromForm() {
  const rxOnly = getCheck('cfg-mode-rx');
  return {
    callsign: getVal('cfg-callsign').toUpperCase(),
    ssid: parseInt(getVal('cfg-ssid')) || 0,
    aprs_passcode: parseInt(getVal('cfg-passcode')) || '',
    mode: {
      rx_only: rxOnly,
      igate: !rxOnly && getCheck('cfg-igate-enabled'),
      digipeater: !rxOnly && getCheck('cfg-digi-enabled'),
      beacon: !rxOnly && getCheck('cfg-rfb-enabled'),
    },
    interface: {
      type: getVal('cfg-interface-type'),
      audio_input: getVal('cfg-audio-in'),
      audio_output: getVal('cfg-audio-out'),
      device: getVal('cfg-serial-device'),
      baud: parseInt(getVal('cfg-baud')) || 9600,
    },
    ptt: {
      method: getVal('cfg-ptt-method'),
      pin: parseInt(getVal('cfg-ptt-pin')) || 17,
      port: getVal('cfg-ptt-port'),
    },
    digipeater: {
      aliases: [...document.getElementById('cfg-digi-alias').selectedOptions].map(o => o.value),
      source_filter: getVal('cfg-digi-source-filter').split(',').map(s => s.trim().toUpperCase()).filter(Boolean),
    },
    igate: {
      server: getVal('cfg-igate-server'),
      port: parseInt(getVal('cfg-igate-port')) || 14580,
      filter: getVal('cfg-igate-filter'),
    },
    rf_beacon: {
      enabled: getCheck('cfg-rfb-enabled'),
      delay: parseInt(getVal('cfg-rfb-delay')) || 1,
      every: parseInt(getVal('cfg-rfb-every')) || 30,
      symbol: getVal('cfg-rfb-symbol') || '#',
      overlay: getVal('cfg-rfb-overlay') || 'S',
      comment: getVal('cfg-rfb-comment'),
      location: {
        source: getCheck('cfg-rfb-gps') ? 'gps' : 'fixed',
        latitude: parseFloat(getVal('cfg-rfb-lat')) || 0,
        longitude: parseFloat(getVal('cfg-rfb-lon')) || 0,
      },
    },
    igate_beacon: {
      enabled: getCheck('cfg-igb-enabled'),
      delay: parseInt(getVal('cfg-igb-delay')) || 1,
      every: parseInt(getVal('cfg-igb-every')) || 30,
      symbol: getVal('cfg-igb-symbol') || '#',
      overlay: getVal('cfg-igb-overlay') || 'S',
      comment: getVal('cfg-igb-comment'),
      location: {
        source: getCheck('cfg-igb-gps') ? 'gps' : 'fixed',
        latitude: parseFloat(getVal('cfg-igb-lat')) || 0,
        longitude: parseFloat(getVal('cfg-igb-lon')) || 0,
      },
    },
    direwolf: {
      binary: '/usr/bin/direwolf',
      config_path: '/etc/direwolf/direwolf.conf',
      start_mode: getVal('cfg-start-mode'),
      restart_attempts: 3,
      restart_delays: [10, 30, 60],
    },
    map: {
      mode: getVal('cfg-map-mode'),
      tile_server: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      station_aging: parseInt(getVal('cfg-aging')) || 7200,
      cache: {
        zoom_min: parseInt(getVal('cfg-zoom-min')) || 8,
        zoom_max: parseInt(getVal('cfg-zoom-max')) || 14,
        tile_dir: '/var/digipeater/tiles',
      },
    },
    display: {
      driver: getVal('cfg-display-driver') || 'none',
      model: getVal('cfg-display-model') || 'epd1in54_v2',
      pages: collectDisplayPages(),
    },
    radio: {
      enabled: getCheck('cfg-radio-enabled'),
      model: parseInt(getVal('cfg-radio-model')) || 1,
      port: getVal('cfg-radio-port') || '/dev/ttyUSB0',
      baud: parseInt(getVal('cfg-radio-baud')) || 9600,
    },
    radio_programmer: _buildProgConfig(),
    hardware: {
      relay_pin: 27,
      radio_boot_delay: 10,
      gps: { device: '/dev/ttyAMA0', baud: 9600 },
    },
    network: {
      mode: getVal('cfg-net-mode'),
      hotspot: { ssid: getVal('cfg-hotspot-ssid'), password: getVal('cfg-hotspot-pass') },
      wifi_client: { ssid: getVal('cfg-wifi-ssid'), password: getVal('cfg-wifi-pass') },
    },
    web: {
      host: '0.0.0.0',
      port: 8080,
      security: { mode: getVal('cfg-sec-mode'), password: getVal('cfg-sec-pass') },
    },
    time: { ntp_servers: ['pool.ntp.org', 'time.google.com'] },
  };
}

// ── Config helpers ────────────────────────────────────────────
function updateInterfaceFields() {
  const isAudio = getVal('cfg-interface-type') === 'audio';
  document.getElementById('cfg-audio-fields').classList.toggle('hidden', !isAudio);
  document.getElementById('cfg-serial-fields').classList.toggle('hidden', isAudio);
}

function updateModeFields() {
  const rxOnly = getCheck('cfg-mode-rx');
  document.getElementById('cfg-tx-fields').classList.toggle('hidden', rxOnly);
  document.getElementById('cfg-digi-section').classList.toggle('hidden', rxOnly);
  document.getElementById('cfg-rfbeacon-section').classList.toggle('hidden', rxOnly);
}

function updatePttFields() {
  const method = getVal('cfg-ptt-method');
  document.getElementById('cfg-ptt-gpio').classList.toggle('hidden', method !== 'gpio');
  document.getElementById('cfg-ptt-serial').classList.toggle('hidden', !['serial_rts','serial_dtr'].includes(method));
}

function updateNetFields() {
  const mode = getVal('cfg-net-mode');
  document.getElementById('cfg-net-hotspot').classList.toggle('hidden', mode !== 'hotspot');
  document.getElementById('cfg-net-wifi').classList.toggle('hidden', mode !== 'wifi_client');
}

function updateDisplayFields() {
  const isWaveshare = getVal('cfg-display-driver') === 'waveshare';
  document.getElementById('cfg-display-model-wrap').classList.toggle('hidden', !isWaveshare);
  document.getElementById('cfg-display-pin-note').classList.toggle('hidden', !isWaveshare);
}

function updateRadioFields() {
  toggleSection('cfg-radio-fields', getCheck('cfg-radio-enabled'));
}

// ── Frequency control ─────────────────────────────────────────
async function setFrequency(hz) {
  const res = await api('POST', '/api/radio/frequency', { frequency: hz });
  if (!res?.ok) alert('Failed to set frequency — check radio connection.');
}

function applyPreset(hz) {
  setFrequency(hz);
}

function applyFreqInput() {
  const mhz = parseFloat(document.getElementById('freq-input').value);
  if (!mhz || mhz < 1 || mhz > 1300) return;
  setFrequency(mhz * 1e6);
}

function toggleSection(id, show) {
  document.getElementById(id).classList.toggle('hidden', !show);
}

async function fetchGpsToForm(latId, lonId) {
  const s = await api('GET', '/api/status');
  const fix = s?.gps?.fix;
  if (!fix) {
    alert('No GPS fix available — check GPS hardware and wait for a fix.');
    return;
  }
  setVal(latId, fix.latitude.toFixed(6));
  setVal(lonId, fix.longitude.toFixed(6));
}

async function autoPasscode() {
  const call = getVal('cfg-callsign').toUpperCase();
  if (!call || call === 'NOCALL') return;
  const res = await api('GET', `/api/passcode?callsign=${encodeURIComponent(call)}`);
  if (res?.passcode !== undefined) setVal('cfg-passcode', res.passcode);
}

const DEFAULT_DISPLAY_MODEL = 'epd1in54_v2'; // UI preference only, not a hardware fact — see display/waveshare/__init__.py for the actual model registry

async function loadDisplayModels() {
  const res = await api('GET', '/api/display/models');
  const sel = document.getElementById('cfg-display-model');
  const current = sel.value;
  sel.innerHTML = '';
  (res?.models || []).forEach(m => {
    const label = m.value === DEFAULT_DISPLAY_MODEL ? `${m.desc} (recommended)` : m.desc;
    sel.appendChild(new Option(label, m.value));
  });
  sel.value = current || DEFAULT_DISPLAY_MODEL;
}

async function loadAudioDevices() {
  const res = await api('GET', '/api/audio-devices');
  const sel1 = document.getElementById('cfg-audio-in');
  const sel2 = document.getElementById('cfg-audio-out');
  [sel1, sel2].forEach(sel => {
    sel.innerHTML = '';
    (res?.devices || ['default']).forEach(d => {
      sel.appendChild(new Option(d, d));
    });
  });
}

async function loadSerialPorts() {
  const res = await api('GET', '/api/serial-ports');
  const sels = [
    document.getElementById('cfg-serial-device'),
    document.getElementById('cfg-ptt-port'),
  ];
  sels.forEach(sel => {
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '';
    (res?.ports || []).forEach(p => sel.appendChild(new Option(`${p.device} (${p.description})`, p.device)));
    if (!res?.ports?.length) sel.appendChild(new Option('/dev/ttyUSB0', '/dev/ttyUSB0'));
    if (current) sel.value = current;
  });
}

// ── Radio programmer ──────────────────────────────────────────

const RADIO_MODELS = {
  alinco_dr138t: {
    label: 'Alinco DR-138T MK2',
    port: '/dev/ttyUSB0',
    baud: 9600,
    channel: 0,
    power: [
      { value: 'HIGH', label: 'High (25W)' },
      { value: 'LOW',  label: 'Low (5W)'  },
    ],
  },
};

function updateProgPower() {
  const radio = getVal('cfg-prog-radio') || 'alinco_dr138t';
  const model = RADIO_MODELS[radio] || RADIO_MODELS['alinco_dr138t'];
  const sel = document.getElementById('cfg-prog-power');
  const current = sel.value;
  sel.innerHTML = '';
  model.power.forEach(p => sel.appendChild(new Option(p.label, p.value)));
  if (current) sel.value = current;
}

function setProgFreq(hz) {
  document.getElementById('cfg-prog-freq-mhz').value = (hz / 1e6).toFixed(3);
}

function _buildProgConfig() {
  const radio = getVal('cfg-prog-radio') || 'alinco_dr138t';
  const model = RADIO_MODELS[radio] || RADIO_MODELS['alinco_dr138t'];
  const ctcssOn = getCheck('cfg-prog-ctcss-on');
  return {
    radio,
    port: model.port,
    baud: model.baud,
    channel: model.channel,
    frequency_hz: Math.round(parseFloat(getVal('cfg-prog-freq-mhz') || 144.575) * 1e6),
    power: getVal('cfg-prog-power') || model.power[0].value,
    ctcss_hz: ctcssOn ? (parseFloat(getVal('cfg-prog-ctcss')) || 0) : 0,
  };
}

async function programRadio() {
  const btn = document.getElementById('btn-prog-run');
  const statusEl = document.getElementById('prog-status');
  const errorEl = document.getElementById('prog-error');

  const cfg = _buildProgConfig();
  const freqMhz = cfg.frequency_hz / 1e6;
  const name = freqMhz.toFixed(3).slice(0, 6);

  btn.disabled = true;
  statusEl.textContent = 'Connecting to radio…';
  errorEl.classList.add('hidden');

  const res = await api('POST', '/api/radio/programmer/run', {
    frequency_hz: cfg.frequency_hz,
    power: cfg.power,
    ctcss_hz: cfg.ctcss_hz,
    name,
  });

  if (!res?.ok) {
    btn.disabled = false;
    statusEl.textContent = '';
    errorEl.textContent = 'Failed to start programming job.';
    errorEl.classList.remove('hidden');
    return;
  }

  const poll = setInterval(async () => {
    const s = await api('GET', '/api/radio/programmer/status');
    if (!s) return;
    const labels = {
      idle: 'Idle', connecting: 'Connecting…', reading: 'Reading radio memory…',
      writing: 'Writing channel data…', done: 'Done!',
      error: 'Error', not_implemented: 'Protocol not yet captured',
    };
    statusEl.textContent = labels[s.state] || s.state;
    if (s.state === 'done' || s.state === 'error' || s.state === 'not_implemented') {
      clearInterval(poll);
      btn.disabled = false;
      if (s.error) {
        errorEl.textContent = s.error;
        errorEl.classList.remove('hidden');
      }
    }
  }, 500);
}

async function scanWifi(listId = 'cfg-wifi-list') {
  const res = await api('GET', '/api/network/scan');
  const list = document.getElementById(listId);
  list.innerHTML = '';
  (res?.networks || []).forEach(n => {
    const opt = document.createElement('option');
    opt.value = n.ssid;
    opt.label = `${n.ssid} (${n.signal}%)`;
    list.appendChild(opt);
  });
}

// ── Display pages drag-and-drop ───────────────────────────────
const PAGE_LABELS = {
  status: 'Status', config_summary: 'Config Summary',
  location: 'Location', last_beacon: 'Last Beacon', last_heard: 'Last Heard',
};

function renderDisplayPages(pages) {
  const container = document.getElementById('display-pages');
  container.innerHTML = '';
  pages.forEach((page, i) => {
    const row = document.createElement('div');
    row.className = 'toggle-row';
    row.draggable = true;
    row.dataset.id = page.id;
    row.style.cursor = 'grab';
    row.innerHTML = `
      <span class="toggle-label">⠿ ${PAGE_LABELS[page.id] || page.id}</span>
      <div style="display:flex;align-items:center;gap:8px">
        <input type="number" value="${page.duration}" min="1" max="120" style="width:50px;padding:3px 6px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text)" data-dur="${page.id}">
        <span class="text-muted" style="font-size:11px">sec</span>
        <label class="toggle"><input type="checkbox" data-en="${page.id}" ${page.enabled ? 'checked' : ''}><span class="toggle-slider"></span></label>
      </div>
    `;
    container.appendChild(row);
  });
  makeDraggable(container);
}

function collectDisplayPages() {
  const container = document.getElementById('display-pages');
  return [...container.children].map(row => ({
    id: row.dataset.id,
    enabled: row.querySelector(`[data-en="${row.dataset.id}"]`).checked,
    duration: parseInt(row.querySelector(`[data-dur="${row.dataset.id}"]`).value) || 10,
  }));
}

function makeDraggable(container) {
  let dragging = null;
  container.addEventListener('dragstart', e => { dragging = e.currentTarget.closest('[draggable]'); });
  container.addEventListener('dragover', e => {
    e.preventDefault();
    const target = e.target.closest('[draggable]');
    if (target && target !== dragging) container.insertBefore(dragging, target.nextSibling);
  });
}

// ── Pinout diagram ────────────────────────────────────────────
const PI_PINS = [
  ['3.3V','5V'],['GPIO2 (SDA)','5V'],['GPIO3 (SCL)','GND'],
  ['GPIO4','GPIO14 (TXD)'],['GND','GPIO15 (RXD)'],
  ['GPIO17','GPIO18'],['GPIO27','GND'],['GPIO22','GPIO23'],
  ['3.3V','GPIO24'],['GPIO10 (MOSI)','GND'],
  ['GPIO9 (MISO)','GPIO25'],['GPIO11 (SCLK)','GPIO8 (CE0)'],
  ['GND','GPIO7 (CE1)'],['GPIO0 (ID_SD)','GPIO1 (ID_SC)'],
  ['GPIO5','GND'],['GPIO6','GPIO12'],
  ['GPIO13','GND'],['GPIO19','GPIO16'],
  ['GPIO26','GPIO20'],['GND','GPIO21'],
];

function renderPinout(cfg) {
  const usedPins = new Set();
  const relayPin = cfg.hardware?.relay_pin;
  if (relayPin) usedPins.add(`GPIO${relayPin}`);
  if (cfg.display?.driver === 'waveshare') {
    // Fixed Waveshare HAT pinout (display/waveshare/epdconfig.py) — same for all models
    ['GPIO17', 'GPIO25', 'GPIO8', 'GPIO24'].forEach(p => usedPins.add(p));
  }

  const el = document.getElementById('pinout');
  el.innerHTML = PI_PINS.map((pair, i) => {
    const left = formatPin(pair[0], usedPins, i * 2 + 1);
    const right = formatPin(pair[1], usedPins, i * 2 + 2);
    return `<div>${left} · ${right}</div>`;
  }).join('');
}

function formatPin(label, usedPins, num) {
  const isUsed = [...usedPins].some(p => label.startsWith(p));
  const isPower = label.includes('3.3V') || label.includes('5V');
  const isGnd = label === 'GND';
  const cls = isUsed ? 'pin-used' : isPower ? 'pin-power' : isGnd ? 'pin-gnd' : '';
  return `<span class="${cls}">${num}:${label}</span>`;
}

// ── Tile cache ────────────────────────────────────────────────
async function estimateTiles() {
  const bounds = getMapBounds();
  const zMin = parseInt(getVal('cfg-zoom-min'));
  const zMax = parseInt(getVal('cfg-zoom-max'));
  const res = await api('GET', `/api/map/cache/estimate?north=${bounds.north}&south=${bounds.south}&east=${bounds.east}&west=${bounds.west}&zoom_min=${zMin}&zoom_max=${zMax}`);
  if (res) document.getElementById('tile-estimate').textContent = `~${res.tile_count.toLocaleString()} tiles · ~${res.estimated_mb} MB`;
}

async function startTileCache() {
  const bounds = getMapBounds();
  await api('POST', '/api/map/cache/start', {
    region: bounds,
    zoom_min: parseInt(getVal('cfg-zoom-min')),
    zoom_max: parseInt(getVal('cfg-zoom-max')),
  });
  document.getElementById('tile-progress').classList.remove('hidden');
  document.getElementById('btn-cache-cancel').classList.remove('hidden');
  state.cacheInterval = setInterval(pollCacheStatus, 2000);
}

async function pollCacheStatus() {
  const s = await api('GET', '/api/map/cache/status');
  if (!s) return;
  document.getElementById('tile-bar').style.width = `${s.percent}%`;
  document.getElementById('tile-status').textContent = `Zoom ${s.current_zoom} · ${s.done}/${s.total} tiles (${s.percent}%)`;
  if (!s.active) {
    clearInterval(state.cacheInterval);
    document.getElementById('btn-cache-cancel').classList.add('hidden');
  }
}

function getMapBounds() {
  if (state.map) {
    const b = state.map.getBounds();
    return { north: b.getNorth(), south: b.getSouth(), east: b.getEast(), west: b.getWest() };
  }
  return { north: 0, south: 0, east: 0, west: 0 };
}

// ── Config export / import ────────────────────────────────────
async function exportConfig() {
  const a = document.createElement('a');
  a.href = '/api/config/export';
  a.download = 'config.yaml';
  a.click();
}

async function importConfig(e) {
  const file = e.target.files[0];
  if (!file) return;
  const text = await file.text();
  const res = await fetch('/api/config/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-yaml', ...(state.token ? { 'Authorization': `Bearer ${state.token}` } : {}) },
    body: text,
  });
  if (res.ok) { alert('Config imported. Reload to apply.'); location.reload(); }
}

// ── Setup wizard ──────────────────────────────────────────────
let wizardStep = 1;

function showWizard() {
  document.getElementById('wizard-page').classList.remove('hidden');
  renderWizardStep(1);
}

function renderWizardStep(step) {
  wizardStep = step;
  const title = document.getElementById('wizard-title');
  const subtitle = document.getElementById('wizard-subtitle');
  const body = document.getElementById('wizard-body');
  const back = document.getElementById('wizard-back');
  const next = document.getElementById('wizard-next');

  document.getElementById('ws-1').className = `wizard-step ${step > 1 ? 'done' : 'active'}`;
  document.getElementById('ws-2').className = `wizard-step ${step === 2 ? 'active' : ''}`;

  back.classList.toggle('hidden', step === 1);
  next.textContent = step === 2 ? 'Finish' : 'Next';

  if (step === 1) {
    title.textContent = 'Network Setup';
    subtitle.textContent = 'How should this device connect to the network?';
    body.innerHTML = `
      <div class="field">
        <label>Network Mode</label>
        <select id="wiz-net-mode">
          <option value="hotspot">WiFi Hotspot</option>
          <option value="wifi_client">Connect to WiFi</option>
          <option value="ethernet">Ethernet Only</option>
        </select>
      </div>
      <div id="wiz-hotspot-fields">
        <div class="field-row">
          <div class="field"><label>Hotspot SSID</label><input type="text" id="wiz-hotspot-ssid" value="Digipeater"></div>
          <div class="field"><label>Hotspot Password</label><input type="password" id="wiz-hotspot-pass" value="Digipeater"></div>
        </div>
      </div>
      <div id="wiz-wifi-fields" class="hidden">
        <div class="field">
          <label>SSID</label>
          <div style="display:flex;gap:8px">
            <input type="text" id="wiz-wifi-ssid" list="wiz-wifi-list" placeholder="Scan or type SSID manually" style="flex:1">
            <datalist id="wiz-wifi-list"></datalist>
            <button class="btn btn-secondary btn-sm" id="btn-wiz-wifi-scan">Scan</button>
          </div>
        </div>
        <div class="field"><label>Password</label><input type="password" id="wiz-wifi-pass"></div>
      </div>
      <div id="wiz-net-status" class="mt-8"></div>
    `;
    document.getElementById('wiz-net-mode').addEventListener('change', e => {
      const m = e.target.value;
      document.getElementById('wiz-hotspot-fields').classList.toggle('hidden', m !== 'hotspot');
      document.getElementById('wiz-wifi-fields').classList.toggle('hidden', m !== 'wifi_client');
    });
    document.getElementById('btn-wiz-wifi-scan').addEventListener('click', () => scanWifi('wiz-wifi-list'));
  }

  if (step === 2) {
    title.textContent = 'Station Setup';
    subtitle.textContent = 'Configure your station. You can change this later from the dashboard.';
    // Reuse the main config form fields inline
    body.innerHTML = `<p class="text-muted" style="margin-bottom:16px">Open the full config page after setup to adjust all settings including igate, beacon, and display.</p>
      <div class="field-row">
        <div class="field"><label>Callsign</label><input type="text" id="wiz-callsign" placeholder="NOCALL" style="text-transform:uppercase"></div>
        <div class="field"><label>SSID</label><input type="number" id="wiz-ssid" value="0" min="0" max="15" style="width:70px"></div>
      </div>
      <div class="field">
        <label>Operating Mode</label>
        <select id="wiz-mode">
          <option value="rx_only">Listen Only (RX)</option>
          <option value="igate">Igate</option>
          <option value="digipeater">Digipeater</option>
          <option value="digipeater_igate">Digipeater + Igate</option>
        </select>
      </div>
      <div class="field">
        <label>Direwolf Start Mode</label>
        <select id="wiz-start-mode">
          <option value="manual">Manual</option>
          <option value="auto">Auto (start on boot)</option>
        </select>
      </div>`;
  }

  next.onclick = step === 2 ? finishWizard : async () => {
    if (step === 1) await applyWizardNetwork();
    renderWizardStep(step + 1);
  };
  back.onclick = () => renderWizardStep(step - 1);
}

async function applyWizardNetwork() {
  const mode = document.getElementById('wiz-net-mode').value;
  const body = { mode };
  if (mode === 'hotspot') {
    body.ssid = document.getElementById('wiz-hotspot-ssid').value;
    body.password = document.getElementById('wiz-hotspot-pass').value;
  } else if (mode === 'wifi_client') {
    body.ssid = document.getElementById('wiz-wifi-ssid').value;
    body.password = document.getElementById('wiz-wifi-pass').value;
  }
  document.getElementById('wiz-net-status').textContent = 'Applying network config...';
  const res = await api('POST', '/api/network/apply', body);
  document.getElementById('wiz-net-status').textContent = res?.ok ? '✓ Network configured' : '✗ Failed — check settings';
}

async function finishWizard() {
  const callsign = document.getElementById('wiz-callsign').value.toUpperCase() || 'NOCALL';
  const ssid = parseInt(document.getElementById('wiz-ssid').value) || 0;
  const modeVal = document.getElementById('wiz-mode').value;
  const startMode = document.getElementById('wiz-start-mode').value;

  const passcodeRes = await api('GET', `/api/passcode?callsign=${encodeURIComponent(callsign)}`);

  const cfg = {
    callsign, ssid,
    aprs_passcode: passcodeRes?.passcode || '',
    mode: {
      rx_only: modeVal === 'rx_only',
      igate: modeVal === 'igate' || modeVal === 'digipeater_igate',
      digipeater: modeVal === 'digipeater' || modeVal === 'digipeater_igate',
      beacon: false,
    },
    interface: { type: 'audio', audio_input: 'default', audio_output: 'default' },
    ptt: { method: 'gpio', pin: 17 },
    digipeater: { aliases: ['WIDE1-1', 'WIDE2-1', 'WIDE2-2'] },
    igate: { server: 'rotate.aprs2.net', port: 14580, filter: 'r/0/0/200' },
    rf_beacon: { enabled: false, location: { source: 'gps' } },
    igate_beacon: { enabled: false, location: { source: 'gps' } },
    direwolf: { binary: '/usr/bin/direwolf', config_path: '/etc/direwolf/direwolf.conf', start_mode: startMode, restart_attempts: 3, restart_delays: [10, 30, 60] },
    map: { mode: 'live', tile_server: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', station_aging: 7200, cache: { zoom_min: 8, zoom_max: 14, tile_dir: '/var/digipeater/tiles' } },
    display: { enabled: true, driver: 'waveshare', model: 'epd1in54_v2', pages: [
      { id: 'status', enabled: true, duration: 10 },
      { id: 'config_summary', enabled: true, duration: 10 },
      { id: 'location', enabled: true, duration: 15 },
      { id: 'last_beacon', enabled: true, duration: 10 },
      { id: 'last_heard', enabled: true, duration: 10 },
    ]},
    hardware: { relay_pin: 27, radio_boot_delay: 10, gps: { device: '/dev/ttyAMA0', baud: 9600 } },
    network: { mode: 'hotspot', hotspot: { ssid: 'Digipeater', password: 'Digipeater' }, wifi_client: { ssid: '', password: '' } },
    web: { host: '0.0.0.0', port: 8080, security: { mode: 'none', password: '' } },
    time: { ntp_servers: ['pool.ntp.org', 'time.google.com'] },
  };

  const res = await api('POST', '/api/config', cfg);
  if (res?.ok) {
    state.config = cfg;
    document.getElementById('wizard-page').classList.add('hidden');
    showApp();
  }
}

// ── Utility ───────────────────────────────────────────────────
async function loadConfig() {
  const cfg = await api('GET', '/api/config');
  if (cfg) { state.config = cfg; updateAuthUI(); }
}

// ── Auth ──────────────────────────────────────────────────────
let _loginPromise = null;

function showLogin() {
  if (_loginPromise) return _loginPromise;

  _loginPromise = new Promise(resolve => {
    const overlay = document.getElementById('login-overlay');
    const input   = document.getElementById('login-password');
    const btn     = document.getElementById('login-submit');
    const err     = document.getElementById('login-error');

    overlay.classList.remove('hidden');
    input.value = '';
    err.classList.add('hidden');
    btn.disabled = false;
    btn.textContent = 'Sign In';
    setTimeout(() => input.focus(), 50);

    async function attempt() {
      const pw = input.value;
      if (!pw) { input.focus(); return; }

      btn.disabled = true;
      btn.textContent = 'Signing in...';
      err.classList.add('hidden');

      const res = await _apiFetch('POST', '/api/auth/login', { password: pw });

      if (res.ok) {
        const data = await res.json();
        state.token = data.token;
        localStorage.setItem('token', data.token);
        overlay.classList.add('hidden');
        _loginPromise = null;
        updateAuthUI();
        resolve();
      } else {
        err.textContent = res.status === 401 ? 'Incorrect password.' : 'Login failed — try again.';
        err.classList.remove('hidden');
        btn.disabled = false;
        btn.textContent = 'Sign In';
        input.select();
      }
    }

    btn.onclick = attempt;
    input.onkeydown = e => { if (e.key === 'Enter') attempt(); };
  });

  return _loginPromise;
}

async function logout() {
  if (state.token) {
    await _apiFetch('POST', '/api/auth/logout', null);
    state.token = null;
    localStorage.removeItem('token');
  }
  updateAuthUI();
  await showLogin();
}

function updateAuthUI() {
  const mode = state.config?.web?.security?.mode || 'none';
  const secured = mode !== 'none';
  document.getElementById('auth-badge').classList.toggle('hidden', !secured);
  document.getElementById('btn-logout').classList.toggle('hidden', !secured || !state.token);
}
function setVal(id, v) { const el = document.getElementById(id); if (el) el.value = v; }
function getVal(id) { return document.getElementById(id)?.value || ''; }
function setCheck(id, v) { const el = document.getElementById(id); if (el) el.checked = v; }
function getCheck(id) { return document.getElementById(id)?.checked || false; }
function escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
