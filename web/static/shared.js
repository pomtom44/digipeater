// Shared between config.html and first_run.html: logic identical in both pages, loaded as a
// plain classic <script src> before each page's own inline <script> block. Some functions here
// own their DOM element handles (declared as consts alongside them, right here), since a
// top-level const/let in one <script> tag isn't visible to a separately-loaded one — anything
// that instead reads a *page-specific* render function's local variables has to stay page-local.

const MAIDENHEAD_LETTERS = 'ABCDEFGHIJKLMNOPQR';

function formatDMS(decimal, isLat) {
  const dir = isLat ? (decimal < 0 ? 'S' : 'N') : (decimal < 0 ? 'W' : 'E');
  const abs = Math.abs(decimal);
  const deg = Math.floor(abs);
  const minFull = (abs - deg) * 60;
  const min = Math.floor(minFull);
  const sec = (minFull - min) * 60;
  return `${deg}°${min}'${sec.toFixed(1)}"${dir}`;
}

// Accepts common punctuation variants, leading/trailing N/S/E/W or a bare minus, optional min/sec
function parseDMS(raw) {
  if (!raw) return null;
  let s = raw.trim().toUpperCase();
  let sign = 1;
  const leadingDir = s.match(/^([NSEW])\s*(.*)$/);
  const trailingDir = !leadingDir && s.match(/^(.*?)\s*([NSEW])$/);
  if (leadingDir) {
    sign = (leadingDir[1] === 'S' || leadingDir[1] === 'W') ? -1 : 1;
    s = leadingDir[2].trim();
  } else if (trailingDir) {
    sign = (trailingDir[2] === 'S' || trailingDir[2] === 'W') ? -1 : 1;
    s = trailingDir[1].trim();
  } else if (s.startsWith('-')) {
    sign = -1;
    s = s.slice(1).trim();
  }
  const nums = s.match(/[0-9]+(?:\.[0-9]+)?/g);
  if (!nums || nums.length === 0) return null;
  const deg = parseFloat(nums[0]);
  const min = nums[1] ? parseFloat(nums[1]) : 0;
  const sec = nums[2] ? parseFloat(nums[2]) : 0;
  if (min >= 60 || sec >= 60) return null;
  return sign * (deg + min / 60 + sec / 3600);
}

// Standard Maidenhead algorithm, capped at 6 characters (~4km precision at NZ latitudes)
function formatMaidenhead(lat, lon) {
  let adjLon = lon + 180;
  let adjLat = lat + 90;
  const fieldLon = Math.floor(adjLon / 20);
  const fieldLat = Math.floor(adjLat / 10);
  adjLon -= fieldLon * 20;
  adjLat -= fieldLat * 10;
  const squareLon = Math.floor(adjLon / 2);
  const squareLat = Math.floor(adjLat / 1);
  adjLon -= squareLon * 2;
  adjLat -= squareLat * 1;
  const subLon = Math.floor(adjLon / (2 / 24));
  const subLat = Math.floor(adjLat / (1 / 24));
  // Subsquare letters run a-x (24), wider than MAIDENHEAD_LETTERS (A-R, 18), needs its own arithmetic
  return MAIDENHEAD_LETTERS[fieldLon] + MAIDENHEAD_LETTERS[fieldLat] + squareLon + squareLat
    + String.fromCharCode(97 + subLon) + String.fromCharCode(97 + subLat);
}

function parseMaidenhead(raw) {
  const s = (raw || '').trim();
  if (!/^[A-Ra-r]{2}[0-9]{2}([A-Xa-x]{2})?$/.test(s)) return null;
  const u = s.toUpperCase();
  let lon = MAIDENHEAD_LETTERS.indexOf(u[0]) * 20 - 180;
  let lat = MAIDENHEAD_LETTERS.indexOf(u[1]) * 10 - 90;
  lon += parseInt(u[2], 10) * 2;
  lat += parseInt(u[3], 10) * 1;
  let lonSize = 2, latSize = 1;
  if (u.length >= 6) {
    lon += (u.charCodeAt(4) - 65) * (2 / 24);
    lat += (u.charCodeAt(5) - 65) * (1 / 24);
    lonSize = 2 / 24;
    latSize = 1 / 24;
  }
  // Center of the resolved cell, not its SW corner.
  lon += lonSize / 2;
  lat += latSize / 2;
  return { lat, lon };
}

// Flat-earth approximation used client-side only to seed the initial box size
function boundsFromRadius(lat, lon, radiusKm) {
  const latDelta = radiusKm / 111.0;
  const lonDelta = radiusKm / (111.0 * Math.max(Math.cos(lat * Math.PI / 180), 0.01));
  return { north: lat + latDelta, south: lat - latDelta, east: lon + lonDelta, west: lon - lonDelta };
}

function formatBytes(bytes) {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function formatDuration(totalSeconds) {
  const s = Math.max(0, Math.round(totalSeconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

// Base symbol set (overlay is a separate free-form character typed into the code field), from hessu/aprs-symbol-index
const APRS_SYMBOLS = [
  { table: '/', symbol: '!', label: 'Police station' },
  { table: '/', symbol: '#', label: 'Digipeater' },
  { table: '/', symbol: '$', label: 'Telephone' },
  { table: '/', symbol: '%', label: 'DX cluster' },
  { table: '/', symbol: '&', label: 'HF gateway' },
  { table: '/', symbol: '\'', label: 'Small aircraft' },
  { table: '/', symbol: '(', label: 'Mobile satellite station' },
  { table: '/', symbol: ')', label: 'Wheelchair, handicapped' },
  { table: '/', symbol: '*', label: 'Snowmobile' },
  { table: '/', symbol: '+', label: 'Red Cross' },
  { table: '/', symbol: ',', label: 'Boy Scouts' },
  { table: '/', symbol: '-', label: 'House' },
  { table: '/', symbol: '.', label: 'Red X' },
  { table: '/', symbol: '/', label: 'Red dot' },
  { table: '/', symbol: '0', label: 'Numbered circle: 0' },
  { table: '/', symbol: '1', label: 'Numbered circle: 1' },
  { table: '/', symbol: '2', label: 'Numbered circle: 2' },
  { table: '/', symbol: '3', label: 'Numbered circle: 3' },
  { table: '/', symbol: '4', label: 'Numbered circle: 4' },
  { table: '/', symbol: '5', label: 'Numbered circle: 5' },
  { table: '/', symbol: '6', label: 'Numbered circle: 6' },
  { table: '/', symbol: '7', label: 'Numbered circle: 7' },
  { table: '/', symbol: '8', label: 'Numbered circle: 8' },
  { table: '/', symbol: '9', label: 'Numbered circle: 9' },
  { table: '/', symbol: ':', label: 'Fire' },
  { table: '/', symbol: ';', label: 'Campground, tent' },
  { table: '/', symbol: '<', label: 'Motorcycle' },
  { table: '/', symbol: '=', label: 'Railroad engine' },
  { table: '/', symbol: '>', label: 'Car' },
  { table: '/', symbol: '?', label: 'File server' },
  { table: '/', symbol: '@', label: 'Hurricane predicted path' },
  { table: '/', symbol: 'A', label: 'Aid station' },
  { table: '/', symbol: 'B', label: 'BBS' },
  { table: '/', symbol: 'C', label: 'Canoe' },
  { table: '/', symbol: 'E', label: 'Eyeball' },
  { table: '/', symbol: 'F', label: 'Farm vehicle, tractor' },
  { table: '/', symbol: 'G', label: 'Grid square, 3 by 3' },
  { table: '/', symbol: 'H', label: 'Hotel' },
  { table: '/', symbol: 'I', label: 'TCP/IP network station' },
  { table: '/', symbol: 'K', label: 'School' },
  { table: '/', symbol: 'L', label: 'PC user' },
  { table: '/', symbol: 'M', label: 'Mac apple' },
  { table: '/', symbol: 'N', label: 'NTS station' },
  { table: '/', symbol: 'O', label: 'Balloon' },
  { table: '/', symbol: 'P', label: 'Police car' },
  { table: '/', symbol: 'R', label: 'Recreational vehicle' },
  { table: '/', symbol: 'S', label: 'Space Shuttle' },
  { table: '/', symbol: 'T', label: 'SSTV' },
  { table: '/', symbol: 'U', label: 'Bus' },
  { table: '/', symbol: 'V', label: 'ATV, Amateur Television' },
  { table: '/', symbol: 'W', label: 'Weather service site' },
  { table: '/', symbol: 'X', label: 'Helicopter' },
  { table: '/', symbol: 'Y', label: 'Sailboat' },
  { table: '/', symbol: 'Z', label: 'Windows flag' },
  { table: '/', symbol: '[', label: 'Human' },
  { table: '/', symbol: '\\', label: 'DF triangle' },
  { table: '/', symbol: ']', label: 'Mailbox, post office' },
  { table: '/', symbol: '^', label: 'Large aircraft' },
  { table: '/', symbol: '_', label: 'Weather station' },
  { table: '/', symbol: '`', label: 'Satellite dish antenna' },
  { table: '/', symbol: 'a', label: 'Ambulance' },
  { table: '/', symbol: 'b', label: 'Bicycle' },
  { table: '/', symbol: 'c', label: 'Incident command post' },
  { table: '/', symbol: 'd', label: 'Fire station' },
  { table: '/', symbol: 'e', label: 'Horse, equestrian' },
  { table: '/', symbol: 'f', label: 'Fire truck' },
  { table: '/', symbol: 'g', label: 'Glider' },
  { table: '/', symbol: 'h', label: 'Hospital' },
  { table: '/', symbol: 'i', label: 'IOTA, islands on the air' },
  { table: '/', symbol: 'j', label: 'Jeep' },
  { table: '/', symbol: 'k', label: 'Truck' },
  { table: '/', symbol: 'l', label: 'Laptop' },
  { table: '/', symbol: 'm', label: 'Mic-E repeater' },
  { table: '/', symbol: 'n', label: 'Node, black bulls-eye' },
  { table: '/', symbol: 'o', label: 'Emergency operations center' },
  { table: '/', symbol: 'p', label: 'Dog' },
  { table: '/', symbol: 'q', label: 'Grid square, 2 by 2' },
  { table: '/', symbol: 'r', label: 'Repeater tower' },
  { table: '/', symbol: 's', label: 'Ship, power boat' },
  { table: '/', symbol: 't', label: 'Truck stop' },
  { table: '/', symbol: 'u', label: 'Semi-trailer truck, 18-wheeler' },
  { table: '/', symbol: 'v', label: 'Van' },
  { table: '/', symbol: 'w', label: 'Water station' },
  { table: '/', symbol: 'x', label: 'X / Unix' },
  { table: '/', symbol: 'y', label: 'House, yagi antenna' },
  { table: '/', symbol: 'z', label: 'Shelter' },
  { table: '\\', symbol: '!', label: 'Emergency' },
  { table: '\\', symbol: '#', label: 'Digipeater, green star' },
  { table: '\\', symbol: '$', label: 'Bank or ATM' },
  { table: '\\', symbol: '&', label: 'Gateway station' },
  { table: '\\', symbol: '\'', label: 'Crash / incident site' },
  { table: '\\', symbol: '(', label: 'Cloudy' },
  { table: '\\', symbol: ')', label: 'Firenet MEO, MODIS Earth Observation' },
  { table: '\\', symbol: '*', label: 'Snow' },
  { table: '\\', symbol: '+', label: 'Church' },
  { table: '\\', symbol: ',', label: 'Girl Scouts' },
  { table: '\\', symbol: '-', label: 'House, HF antenna' },
  { table: '\\', symbol: '.', label: 'Ambiguous, question mark inside circle' },
  { table: '\\', symbol: '/', label: 'Waypoint destination' },
  { table: '\\', symbol: '0', label: 'Circle, IRLP / Echolink/WIRES' },
  { table: '\\', symbol: '8', label: '802.11 WiFi or other network node' },
  { table: '\\', symbol: '9', label: 'Gas station' },
  { table: '\\', symbol: ':', label: 'Hail' },
  { table: '\\', symbol: ';', label: 'Park, picnic area' },
  { table: '\\', symbol: '<', label: 'Advisory, single red flag' },
  { table: '\\', symbol: '>', label: 'Red car' },
  { table: '\\', symbol: '?', label: 'Info kiosk' },
  { table: '\\', symbol: '@', label: 'Hurricane, Tropical storm' },
  { table: '\\', symbol: 'A', label: 'White box' },
  { table: '\\', symbol: 'B', label: 'Blowing snow' },
  { table: '\\', symbol: 'C', label: 'Coast Guard' },
  { table: '\\', symbol: 'D', label: 'Drizzling rain' },
  { table: '\\', symbol: 'E', label: 'Smoke, Chimney' },
  { table: '\\', symbol: 'F', label: 'Freezing rain' },
  { table: '\\', symbol: 'G', label: 'Snow shower' },
  { table: '\\', symbol: 'H', label: 'Haze' },
  { table: '\\', symbol: 'I', label: 'Rain shower' },
  { table: '\\', symbol: 'J', label: 'Lightning' },
  { table: '\\', symbol: 'K', label: 'Kenwood HT' },
  { table: '\\', symbol: 'L', label: 'Lighthouse' },
  { table: '\\', symbol: 'N', label: 'Navigation buoy' },
  { table: '\\', symbol: 'O', label: 'Rocket' },
  { table: '\\', symbol: 'P', label: 'Parking' },
  { table: '\\', symbol: 'Q', label: 'Earthquake' },
  { table: '\\', symbol: 'R', label: 'Restaurant' },
  { table: '\\', symbol: 'S', label: 'Satellite' },
  { table: '\\', symbol: 'T', label: 'Thunderstorm' },
  { table: '\\', symbol: 'U', label: 'Sunny' },
  { table: '\\', symbol: 'V', label: 'VORTAC, Navigational aid' },
  { table: '\\', symbol: 'W', label: 'NWS site' },
  { table: '\\', symbol: 'X', label: 'Pharmacy' },
  { table: '\\', symbol: '[', label: 'Wall Cloud' },
  { table: '\\', symbol: '^', label: 'Aircraft' },
  { table: '\\', symbol: '_', label: 'Weather site' },
  { table: '\\', symbol: '`', label: 'Rain' },
  { table: '\\', symbol: 'a', label: 'Red diamond' },
  { table: '\\', symbol: 'b', label: 'Blowing dust, sand' },
  { table: '\\', symbol: 'c', label: 'CD triangle, RACES, CERTS, SATERN' },
  { table: '\\', symbol: 'd', label: 'DX spot' },
  { table: '\\', symbol: 'e', label: 'Sleet' },
  { table: '\\', symbol: 'f', label: 'Funnel cloud' },
  { table: '\\', symbol: 'g', label: 'Gale, two red flags' },
  { table: '\\', symbol: 'h', label: 'Store' },
  { table: '\\', symbol: 'i', label: 'Black box, point of interest' },
  { table: '\\', symbol: 'j', label: 'Work zone, excavating machine' },
  { table: '\\', symbol: 'k', label: 'SUV, ATV' },
  { table: '\\', symbol: 'm', label: 'Value sign, 3 digit display' },
  { table: '\\', symbol: 'n', label: 'Red triangle' },
  { table: '\\', symbol: 'o', label: 'Small circle' },
  { table: '\\', symbol: 'p', label: 'Partly cloudy' },
  { table: '\\', symbol: 'r', label: 'Restrooms' },
  { table: '\\', symbol: 's', label: 'Ship, boat' },
  { table: '\\', symbol: 't', label: 'Tornado' },
  { table: '\\', symbol: 'u', label: 'Truck' },
  { table: '\\', symbol: 'v', label: 'Van' },
  { table: '\\', symbol: 'w', label: 'Flooding' },
  { table: '\\', symbol: 'y', label: 'Skywarn' },
  { table: '\\', symbol: 'z', label: 'Shelter' },
  { table: '\\', symbol: '{', label: 'Fog' },
];

// Sprite sheets from hessu/aprs-symbols (CC BY-SA 4.0, see aprs-symbols/COPYRIGHT.md); grid is 16x6 cells of 64x64, sequential ASCII from '!'
const SPRITE_CELL_W = 64;
const SPRITE_CELL_H = 64;
const SPRITE_SHEET_W = 1024;
const SPRITE_SHEET_H = 384;
const SPRITE_BASE = '/static/aprs-symbols/';

function spriteCellFor(sym) {
  const sheet = sym.table === '\\' ? 'sheet1.png' : 'sheet0.png';
  const code = sym.symbol.charCodeAt(0) - 0x21;
  return { sheet, col: code % 16, row: Math.floor(code / 16) };
}

// Needs display:inline-block or width/height on the span are ignored
function symbolGlyphHTML(sym, displayW) {
  const { sheet, col, row } = spriteCellFor(sym);
  const scale = displayW / SPRITE_CELL_W;
  const displayH = Math.round(SPRITE_CELL_H * scale);
  const bgW = Math.round(SPRITE_SHEET_W * scale);
  const bgH = Math.round(SPRITE_SHEET_H * scale);
  const bgX = -Math.round(col * SPRITE_CELL_W * scale);
  const bgY = -Math.round(row * SPRITE_CELL_H * scale);
  const style = `display:inline-block;flex-shrink:0;width:${displayW}px;height:${displayH}px;background-image:url('${SPRITE_BASE}${sheet}');background-repeat:no-repeat;background-size:${bgW}px ${bgH}px;background-position:${bgX}px ${bgY}px;`;
  return `<span class="symbol-glyph" style="${style}"></span>`;
}

function findSymbol(table, symbol) {
  return APRS_SYMBOLS.find(s => s.table === table && s.symbol === symbol) || { table, symbol, overlay: '' };
}

// Code is the raw APRS symbol reference (table + symbol + optional overlay char, e.g. "/#" or "\&T")
function symbolCodeFromSymbol(sym) {
  return sym.table === '\\' ? `\\${sym.symbol}${sym.overlay || ''}` : `${sym.table}${sym.symbol}`;
}

function parseSymbolCode(code) {
  code = (code || '').trim();
  if (!code) return null;
  if (code.length === 1) return { table: '/', symbol: code[0], overlay: '' };
  const table = code[0] === '\\' ? '\\' : '/';
  const symbol = code[1];
  const overlay = table === '\\' ? (code[2] || '') : '';
  return { table, symbol, overlay };
}

function symbolPickerHTML(pickerId, initialSym) {
  const code = symbolCodeFromSymbol(initialSym);
  const primaryOptions = APRS_SYMBOLS.filter(s => s.table === '/')
    .map(s => `<option value="${s.table}${s.symbol}">${s.table}${s.symbol}: ${s.label}</option>`).join('');
  const altOptions = APRS_SYMBOLS.filter(s => s.table === '\\')
    .map(s => `<option value="${s.table}${s.symbol}">\\${s.symbol}: ${s.label}</option>`).join('');
  return `
    <div class="symbol-picker" id="${pickerId}">
      <div class="symbol-input-row">
        ${symbolGlyphHTML(initialSym, 48)}
        <input type="text" class="symbol-code-input" maxlength="3" value="${code}" placeholder="/#">
        <span class="symbol-badge-inline${initialSym.overlay ? '' : ' hidden'}">${initialSym.overlay || ''}</span>
        <select class="symbol-select">
          <option value="">(pick from list)</option>
          <optgroup label="Primary table (/)">${primaryOptions}</optgroup>
          <optgroup label="Alternate table (\\)">${altOptions}</optgroup>
        </select>
      </div>
    </div>
  `;
}

function wireSymbolPicker(pickerId) {
  const picker = document.getElementById(pickerId);
  const input = picker.querySelector('.symbol-code-input');
  const select = picker.querySelector('.symbol-select');

  function updatePreview() {
    const sym = parseSymbolCode(input.value) || { table: '/', symbol: '#', overlay: '' };
    const row = picker.querySelector('.symbol-input-row');
    row.querySelector('.symbol-glyph').outerHTML = symbolGlyphHTML(sym, 48);
    row.querySelector('.symbol-badge-inline').textContent = sym.overlay || '';
    row.querySelector('.symbol-badge-inline').classList.toggle('hidden', !sym.overlay);
  }

  function syncSelectFromInput() {
    const sym = parseSymbolCode(input.value);
    const baseCode = sym ? sym.table + sym.symbol : '';
    const hasOption = [...select.options].some(o => o.value === baseCode);
    select.value = hasOption ? baseCode : '';
  }

  input.addEventListener('input', () => {
    updatePreview();
    syncSelectFromInput();
  });

  select.addEventListener('change', () => {
    if (!select.value) return;
    input.value = select.value;
    updatePreview();
  });

  syncSelectFromInput();
}

function getSymbolPickerValue(pickerId) {
  const input = document.getElementById(pickerId).querySelector('.symbol-code-input');
  return parseSymbolCode(input.value) || { table: '/', symbol: '#', overlay: '' };
}

function addOption(select, value, label) {
  const opt = document.createElement('option');
  opt.value = value;
  opt.textContent = label;
  select.appendChild(opt);
  return opt;
}

// Escape quotes/ampersands so the attribute doesn't break
// Returns a "?" button carrying its help text in a data attribute
function helpIcon(text) {
  const escaped = text.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
  return `<button type="button" class="help-icon" data-help="${escaped}" aria-label="Help">?</button>`;
}

// Shows the serial PTT line field only when Serial is the selected PTT method
function updatePttSerialLineVisibility() {
  const isSerial = document.getElementById('radio-ptt').value.startsWith('serial:');
  document.getElementById('radio-ptt-serial-line-wrap').classList.toggle('hidden', !isSerial);
}

const THEME_LABELS = { null: 'Theme: System', light: 'Theme: Light', dark: 'Theme: Dark' };

function applyUiTheme(theme) {
  if (theme === 'light' || theme === 'dark') {
    document.documentElement.setAttribute('data-theme', theme);
  } else {
    document.documentElement.removeAttribute('data-theme');
  }
  document.getElementById('theme-toggle').textContent = THEME_LABELS[theme];
}

const helpOverlay = document.getElementById('help-overlay');
const helpBoxText = document.getElementById('help-box-text');

function hideHelp() {
  helpOverlay.classList.add('hidden');
}

// innerHTML, not textContent: help text is static wizard copy, some of it lists
function showHelp(text) {
  helpBoxText.innerHTML = text;
  helpOverlay.classList.remove('hidden');
}

const confirmOverlay = document.getElementById('confirm-overlay');
const confirmBoxText = document.getElementById('confirm-box-text');
const confirmBoxYes = document.getElementById('confirm-box-yes');
const confirmBoxNo = document.getElementById('confirm-box-no');

function confirmModal(text, yesLabel, noLabel) {
  return new Promise((resolve) => {
    confirmBoxText.textContent = text;
    confirmBoxYes.textContent = yesLabel;
    confirmBoxNo.textContent = noLabel;
    confirmOverlay.classList.remove('hidden');
    function cleanup(result) {
      confirmOverlay.classList.add('hidden');
      confirmBoxYes.removeEventListener('click', onYes);
      confirmBoxNo.removeEventListener('click', onNo);
      resolve(result);
    }
    function onYes() { cleanup(true); }
    function onNo() { cleanup(false); }
    confirmBoxYes.addEventListener('click', onYes);
    confirmBoxNo.addEventListener('click', onNo);
  });
}

// Module-level so saveGpsStep() can call it after renderGpsStep()'s closure has exited
function getManualLatLon(format) {
  format = format || document.getElementById('gps-loc-format').value;
  let lat, lon;
  if (format === 'dms') {
    lat = parseDMS(document.getElementById('gps-lat-dms').value);
    lon = parseDMS(document.getElementById('gps-lon-dms').value);
    if (lat === null || lon === null) return null;
  } else if (format === 'maidenhead') {
    const parsed = parseMaidenhead(document.getElementById('gps-grid').value);
    if (!parsed) return null;
    lat = parsed.lat;
    lon = parsed.lon;
  } else {
    lat = parseFloat(document.getElementById('gps-lat').value);
    lon = parseFloat(document.getElementById('gps-lon').value);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  }
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return { lat, lon };
}

// Kept short (unlike APRS_DEFAULT_TXVIA) since this is the station's own beacon path
const APRS_DEFAULT_RF_BEACON_PATH = 'WIDE1-1';

// Shared markup for RF/IGate beacon sections, identical apart from Path (RF-only)
function beaconFieldsHTML(prefix, { includePath }) {
  return `
    ${includePath ? `
    <div class="field">
      <label for="${prefix}-path">Path ${helpIcon("Kept short for a fixed station's own beacon: WIDE1-1 (one hop) is standard practice rather than a wide-area path.")}</label>
      <input type="text" id="${prefix}-path" value="${APRS_DEFAULT_RF_BEACON_PATH}">
    </div>
    <div class="field-row">
      <div class="field">
        <label for="${prefix}-phg-power">Power ${helpIcon('Optional. Antenna power/height/gain, encoded into the beacon so other stations can estimate your range. Leave blank to omit.')}</label>
        <div class="field-suffix"><input type="number" id="${prefix}-phg-power" min="0" placeholder="e.g. 5"><span>W</span></div>
      </div>
      <div class="field">
        <label for="${prefix}-phg-height">Height</label>
        <div class="field-suffix"><input type="number" id="${prefix}-phg-height" min="0" placeholder="e.g. 20"><span>ft AAT</span></div>
      </div>
      <div class="field">
        <label for="${prefix}-phg-gain">Gain</label>
        <div class="field-suffix"><input type="number" id="${prefix}-phg-gain" min="0" placeholder="e.g. 3"><span>dB</span></div>
      </div>
    </div>` : ''}
    <div class="field-row">
      <div class="field">
        <label for="${prefix}-delay">Initial delay</label>
        <div class="field-suffix"><input type="number" id="${prefix}-delay" min="0" value="1"><span>min</span></div>
      </div>
      <div class="field">
        <label for="${prefix}-interval">Interval</label>
        <div class="field-suffix"><input type="number" id="${prefix}-interval" min="1" value="30"><span>min</span></div>
      </div>
    </div>
  `;
}

function collectBeaconFields(prefix, { includePath }) {
  const beacon = {
    enabled: true,
    delay: document.getElementById(`${prefix}-delay`).value,
    interval: document.getElementById(`${prefix}-interval`).value,
  };
  if (includePath) {
    beacon.path = document.getElementById(`${prefix}-path`).value;
    const power = document.getElementById(`${prefix}-phg-power`).value;
    const height = document.getElementById(`${prefix}-phg-height`).value;
    const gain = document.getElementById(`${prefix}-phg-gain`).value;
    if (power || height || gain) beacon.phg = { power, height, gain };
  }
  return beacon;
}

function restoreBeaconFields(prefix, saved) {
  if (!saved) return;
  const pathEl = document.getElementById(`${prefix}-path`);
  if (pathEl && saved.path !== undefined) pathEl.value = saved.path;
  document.getElementById(`${prefix}-delay`).value = saved.delay ?? 1;
  document.getElementById(`${prefix}-interval`).value = saved.interval ?? 30;
  const powerEl = document.getElementById(`${prefix}-phg-power`);
  if (powerEl) {
    powerEl.value = saved.phg?.power ?? '';
    document.getElementById(`${prefix}-phg-height`).value = saved.phg?.height ?? '';
    document.getElementById(`${prefix}-phg-gain`).value = saved.phg?.gain ?? '';
  }
}

// var, not let: renderEinkTab() in each page's own script reassigns this directly
// (`einkPages = ...`), and only var/function declarations are visible as true globals
// across separate <script> tags — a top-level let here wouldn't be reachable from there.
var einkPages = [];

function renderEinkPageLists() {
  const enabledList = document.getElementById('eink-enabled-list');
  const disabledList = document.getElementById('eink-disabled-list');
  const enabled = einkPages.filter(p => p.enabled);
  const disabled = einkPages.filter(p => !p.enabled);

  enabledList.innerHTML = enabled.map((p, i) => `
    <div class="eink-page-row">
      <div class="eink-page-info"><strong>${p.label}</strong></div>
      <div class="field-suffix" style="flex: 0 0 100px;">
        <input type="number" min="1" class="eink-duration" data-id="${p.id}" value="${p.duration}">
        <span>sec</span>
      </div>
      <div class="eink-page-actions">
        <button type="button" class="eink-move-up" data-id="${p.id}" ${i === 0 ? 'disabled' : ''} title="Move up">&uarr;</button>
        <button type="button" class="eink-move-down" data-id="${p.id}" ${i === enabled.length - 1 ? 'disabled' : ''} title="Move down">&darr;</button>
        <button type="button" class="eink-disable" data-id="${p.id}">Disable</button>
      </div>
    </div>
  `).join('') || '<p class="hint">Nothing enabled: every screen is disabled below.</p>';

  disabledList.innerHTML = disabled.map(p => `
    <div class="eink-page-row disabled">
      <div class="eink-page-info"><strong>${p.label}</strong></div>
      <div class="eink-page-actions">
        <button type="button" class="eink-enable" data-id="${p.id}">Enable</button>
      </div>
    </div>
  `).join('') || '<p class="hint">Nothing disabled.</p>';

  enabledList.querySelectorAll('.eink-move-up').forEach(btn =>
    btn.addEventListener('click', () => moveEinkPage(btn.dataset.id, -1)));
  enabledList.querySelectorAll('.eink-move-down').forEach(btn =>
    btn.addEventListener('click', () => moveEinkPage(btn.dataset.id, 1)));
  enabledList.querySelectorAll('.eink-disable').forEach(btn =>
    btn.addEventListener('click', () => setEinkPageEnabled(btn.dataset.id, false)));
  disabledList.querySelectorAll('.eink-enable').forEach(btn =>
    btn.addEventListener('click', () => setEinkPageEnabled(btn.dataset.id, true)));
  enabledList.querySelectorAll('.eink-duration').forEach(input =>
    input.addEventListener('input', () => {
      const page = einkPages.find(p => p.id === input.dataset.id);
      if (page) page.duration = input.value;
    }));
}

function moveEinkPage(id, delta) {
  const enabledIds = einkPages.filter(p => p.enabled).map(p => p.id);
  const from = enabledIds.indexOf(id);
  const to = from + delta;
  if (from === -1 || to < 0 || to >= enabledIds.length) return;
  const fromIdx = einkPages.findIndex(p => p.id === id);
  const toIdx = einkPages.findIndex(p => p.id === enabledIds[to]);
  [einkPages[fromIdx], einkPages[toIdx]] = [einkPages[toIdx], einkPages[fromIdx]];
  renderEinkPageLists();
}

// Re-enabling always appends to the end of the rotation rather than restoring its old position
function setEinkPageEnabled(id, enabled) {
  const idx = einkPages.findIndex(p => p.id === id);
  if (idx === -1) return;
  const [page] = einkPages.splice(idx, 1);
  page.enabled = enabled;
  einkPages.push(page);
  renderEinkPageLists();
}
