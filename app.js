// APRS Digipeater Monitor JavaScript

// Configuration
const API_BASE = '';
const UPDATE_INTERVAL = 5000; // 5 seconds
const MAP_CENTER = [-37.7870, 175.2793]; // Hamilton, NZ (default)
const MAP_ZOOM = 12;

// State
let map;
let stationPaths = {};
let stationMarkers = {};
let stationDots = {};
let stationVisibility = {};
let stationColors = {};
let colorIndex = 0;
let updateTimer = null;
let latestPacketSymbols = {}; // Store symbols for sidebar consistency

// Initialize map
function initMap() {
    // Configure Leaflet icon paths for offline use
    delete L.Icon.Default.prototype._getIconUrl;
    L.Icon.Default.mergeOptions({
        iconUrl: 'leaflet/images/marker-icon.png',
        iconRetinaUrl: 'leaflet/images/marker-icon-2x.png',
        shadowUrl: 'leaflet/images/marker-shadow.png'
    });
    
    map = L.map('map').setView(MAP_CENTER, MAP_ZOOM);
    
    // Use offline tiles only
    const offlineTileLayer = L.tileLayer('tiles/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors (Offline)',
        maxZoom: 19,
        errorTileUrl: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
    });
    
    // Add offline tile layer to map
    offlineTileLayer.addTo(map);
}

// Get color for a callsign
function getColorForCallsign(callsign) {
    if (!stationColors[callsign]) {
        stationColors[callsign] = `color-${colorIndex % 10}`;
        colorIndex++;
    }
    return stationColors[callsign];
}

// Get RGB color from CSS class
function getRGBColor(cssClass) {
    const colorMap = {
        'color-0': '#007bff',
        'color-1': '#28a745',
        'color-2': '#dc3545',
        'color-3': '#ffc107',
        'color-4': '#17a2b8',
        'color-5': '#6f42c1',
        'color-6': '#e83e8c',
        'color-7': '#fd7e14',
        'color-8': '#20c997',
        'color-9': '#6c757d'
    };
    return colorMap[cssClass] || '#007bff';
}

// Format timestamp
function formatTimestamp(timestamp) {
    const date = new Date(timestamp * 1000);
    return date.toLocaleString();
}

// Get current GPS time from status
let currentGpsTime = null;
let lastGpsTimeUpdate = null; // Track when we last updated GPS time

async function updateGpsTime() {
    try {
        const response = await fetch(`${API_BASE}/api/status`);
        const status = await response.json();
        if (status.gps_time) {
            const now = Date.now() / 1000;
            const serverGpsTime = status.gps_time;
            
            // If we already have a calculated GPS time, use it as the base instead of resetting
            // This prevents the "last seen" time from jumping backwards
            if (currentGpsTime && lastGpsTimeUpdate) {
                // Use our calculated GPS time as the new base, not the server time
                // This ensures continuity
                currentGpsTime = getCurrentGpsTime(); // Use our calculated time
                lastGpsTimeUpdate = now; // Update the timestamp
            } else {
                // First time - use server GPS time
                currentGpsTime = serverGpsTime;
                lastGpsTimeUpdate = now;
            }
        } else {
            // If no GPS time in status, use system time as fallback
            const now = Date.now() / 1000;
            if (!currentGpsTime) {
                currentGpsTime = now;
                lastGpsTimeUpdate = now;
            }
            console.warn('GPS time not available in status, using system time');
        }
    } catch (error) {
        // Fallback to system time if GPS time not available
        const now = Date.now() / 1000;
        if (!currentGpsTime) {
            currentGpsTime = now;
            lastGpsTimeUpdate = now;
        }
        console.error('Error fetching GPS time:', error);
    }
}

// Get current GPS time, accounting for elapsed time since last update
function getCurrentGpsTime() {
    if (!currentGpsTime || !lastGpsTimeUpdate) {
        return Date.now() / 1000; // Fallback to system time
    }
    // Calculate elapsed time since last GPS update and add it to the cached GPS time
    const now = Date.now() / 1000;
    const elapsed = now - lastGpsTimeUpdate;
    return currentGpsTime + elapsed;
}

// Format relative time using GPS time
function formatRelativeTime(timestamp) {
    if (!timestamp || timestamp === 0) {
        return 'Never';
    }
    
    // Use continuously updating GPS time
    const now = getCurrentGpsTime();
    const diff = now - timestamp;
    
    // Debug logging (can be removed later)
    if (!currentGpsTime) {
        console.warn('formatRelativeTime: currentGpsTime is null, using system time');
    }
    
    // Handle negative differences (timestamp in future - shouldn't happen but handle gracefully)
    if (diff < 0) {
        console.warn(`formatRelativeTime: negative diff (${diff.toFixed(1)}s), timestamp: ${new Date(timestamp * 1000).toISOString()}, now: ${new Date(now * 1000).toISOString()}`);
        return 'Just now';
    }
    
    if (diff < 1) {
        return 'Just now';
    } else if (diff < 60) {
        return `${Math.floor(diff)}s ago`;
    } else if (diff < 3600) {
        return `${Math.floor(diff / 60)}m ago`;
    } else if (diff < 86400) {
        return `${Math.floor(diff / 3600)}h ago`;
    } else {
        return `${Math.floor(diff / 86400)}d ago`;
    }
}

// Load status
async function loadStatus() {
    try {
        const response = await fetch(`${API_BASE}/api/status`);
        const status = await response.json();
        
        // Update GPS time - ensure it's set
        if (status.gps_time) {
            currentGpsTime = status.gps_time;
        } else {
            // If no GPS time in status, use system time as fallback
            currentGpsTime = Date.now() / 1000;
        }
        
        // Update status panel
        document.getElementById('status-version').textContent = status.version || 'Unknown';
        
        const gpsEl = document.getElementById('status-gps');
        gpsEl.textContent = status.gps_status || 'Unknown';
        gpsEl.className = 'status-value ' + (status.gps_status === '3D Fix' ? 'online' : 'offline');
        
        const audioEl = document.getElementById('status-audio');
        if (status.audio_error) {
            audioEl.textContent = 'Error';
            audioEl.className = 'status-value offline';
        } else {
            audioEl.textContent = status.audio_device || 'Unknown';
            audioEl.className = 'status-value ' + (status.audio_device ? 'online' : 'offline');
        }
        
        const agwEl = document.getElementById('status-agw');
        agwEl.textContent = status.agw_ready ? 'Ready' : 'Not Ready';
        agwEl.className = 'status-value ' + (status.agw_ready ? 'online' : 'offline');
        
        const kissEl = document.getElementById('status-kiss');
        kissEl.textContent = status.kiss_ready ? 'Ready' : 'Not Ready';
        kissEl.className = 'status-value ' + (status.kiss_ready ? 'online' : 'offline');
    } catch (error) {
        console.error('Error loading status:', error);
        // Fallback to system time on error
        currentGpsTime = Date.now() / 1000;
    }
}

// Load callsigns
async function loadCallsigns() {
    try {
        const [callsignsResponse, packetsResponse] = await Promise.all([
            fetch(`${API_BASE}/api/callsigns`),
            fetch(`${API_BASE}/api/packets`)
        ]);
        
        const callsigns = await callsignsResponse.json();
        const allPackets = await packetsResponse.json();
        
        // Group packets by callsign+SSID to get latest symbol (handle multiple SSIDs)
        const packetsByCallsign = {};
        allPackets.forEach(packet => {
            const cs = packet.callsign;
            const ssid = packet.ssid;
            // Use callsign-SSID as key to separate different SSIDs
            const callsignKey = ssid ? `${cs}-${ssid}` : cs;
            if (!packetsByCallsign[callsignKey]) {
                packetsByCallsign[callsignKey] = [];
            }
            packetsByCallsign[callsignKey].push(packet);
        });
        
        // Sort packets by timestamp for each callsign to ensure we get the latest
        Object.keys(packetsByCallsign).forEach(cs => {
            packetsByCallsign[cs].sort((a, b) => a.timestamp - b.timestamp);
        });
        
        // Cache packets data for continuous "last seen" updates
        cachedPacketsByCallsign = packetsByCallsign;
        
        const listEl = document.getElementById('callsign-list');
        
        if (callsigns.length === 0) {
            listEl.innerHTML = '<div class="empty-state">No stations seen yet</div>';
            return;
        }
        
        listEl.innerHTML = callsigns.map(callsign => {
            // Create display name with SSID if present
            const displayName = callsign.ssid ? `${callsign.callsign}-${callsign.ssid}` : callsign.callsign;
            // Use callsign-SSID as key to handle multiple SSIDs for same callsign
            const callsignKey = callsign.ssid ? `${callsign.callsign}-${callsign.ssid}` : callsign.callsign;
            
            const colorClass = getColorForCallsign(callsignKey);
            const isVisible = stationVisibility[callsignKey] !== false;
            
            // Get symbol from stored symbols (updated by updateMap) or latest packet, or use default
            // Always use latest packet first, then stored symbol, then default
            const packets = packetsByCallsign[callsignKey] || [];
            const latestPacket = packets.length > 0 ? packets[packets.length - 1] : null;
            const storedSymbol = latestPacketSymbols[callsignKey];
            
            // Priority: latest packet > stored symbol > default
            const symbolCode = latestPacket?.symbol_code || storedSymbol?.symbol_code || '>';
            const symbolTable = latestPacket?.symbol_table || storedSymbol?.symbol_table || '/';
            const iconHtml = createAPRSIcon(symbolCode, symbolTable, 48);
            
            return `
                <div class="callsign-item ${isVisible ? '' : 'hidden'}" data-callsign="${callsignKey}">
                    <input type="checkbox" class="callsign-toggle" ${isVisible ? 'checked' : ''} 
                           onchange="toggleCallsign('${callsignKey}', this.checked)">
                    <div class="callsign-icon">${iconHtml}</div>
                    <div class="callsign-color ${colorClass}"></div>
                    <div class="callsign-info">
                        <div class="callsign-name">${displayName}</div>
                        <div class="callsign-meta">
                            <span>${formatRelativeTime(callsign.last_seen)}</span>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    } catch (error) {
        console.error('Error loading callsigns:', error);
    }
}

// Toggle callsign visibility
function toggleCallsign(callsign, visible) {
    stationVisibility[callsign] = visible;
    
    // Update UI
    const itemEl = document.querySelector(`[data-callsign="${callsign}"]`);
    if (itemEl) {
        if (visible) {
            itemEl.classList.remove('hidden');
        } else {
            itemEl.classList.add('hidden');
        }
    }
    
    // Update map
    updateMapVisibility();
}

// Update map visibility based on toggles
function updateMapVisibility() {
    Object.keys(stationPaths).forEach(callsign => {
        const isVisible = stationVisibility[callsign] !== false;
        
        if (stationPaths[callsign]) {
            if (isVisible) {
                map.addLayer(stationPaths[callsign]);
            } else {
                map.removeLayer(stationPaths[callsign]);
            }
        }
        
        if (stationDots[callsign]) {
            stationDots[callsign].forEach(dot => {
                if (isVisible) {
                    map.addLayer(dot);
                } else {
                    map.removeLayer(dot);
                }
            });
        }
        
        if (stationMarkers[callsign]) {
            if (isVisible) {
                map.addLayer(stationMarkers[callsign]);
            } else {
                map.removeLayer(stationMarkers[callsign]);
            }
        }
    });
}

// Update sidebar "Last seen" times without full reload
function updateSidebarLastSeen(packetsByCallsign) {
    const callsignCount = Object.keys(packetsByCallsign).length;
    if (callsignCount === 0) {
        return;
    }
    
    Object.keys(packetsByCallsign).forEach(callsign => {
        const packets = packetsByCallsign[callsign];
        if (packets.length === 0) return;
        
        // Get latest packet timestamp
        const latestPacket = packets[packets.length - 1];
        const lastSeen = latestPacket.timestamp;
        
        // Find the sidebar item for this callsign
        const itemEl = document.querySelector(`[data-callsign="${callsign}"]`);
        if (itemEl) {
            const metaEl = itemEl.querySelector('.callsign-meta span');
            if (metaEl) {
                const newText = formatRelativeTime(lastSeen);
                if (metaEl.textContent !== newText) {
                    metaEl.textContent = newText;
                }
            }
        }
    });
}

// Load and update map data
async function updateMap() {
    try {
        const response = await fetch(`${API_BASE}/api/packets`);
        const allPackets = await response.json();
        
        // Group packets by callsign+SSID (to handle multiple SSIDs for same callsign)
        const packetsByCallsign = {};
        allPackets.forEach(packet => {
            const callsign = packet.callsign;
            const ssid = packet.ssid;
            // Use callsign-SSID as key to separate different SSIDs
            const callsignKey = ssid ? `${callsign}-${ssid}` : callsign;
            if (!packetsByCallsign[callsignKey]) {
                packetsByCallsign[callsignKey] = [];
            }
            packetsByCallsign[callsignKey].push(packet);
        });
        
        // Sort packets by timestamp for each callsign
        Object.keys(packetsByCallsign).forEach(callsign => {
            packetsByCallsign[callsign].sort((a, b) => a.timestamp - b.timestamp);
        });
        
        // Remove old paths/markers for callsigns not in current data
        Object.keys(stationPaths).forEach(callsign => {
            if (!packetsByCallsign[callsign]) {
                if (stationPaths[callsign]) {
                    map.removeLayer(stationPaths[callsign]);
                    delete stationPaths[callsign];
                }
                if (stationMarkers[callsign]) {
                    map.removeLayer(stationMarkers[callsign]);
                    delete stationMarkers[callsign];
                }
                if (stationDots[callsign]) {
                    stationDots[callsign].forEach(dot => map.removeLayer(dot));
                    delete stationDots[callsign];
                }
            }
        });
        
        // Update or create paths for each callsign
        Object.keys(packetsByCallsign).forEach(callsign => {
            const packets = packetsByCallsign[callsign];
            const coordinates = packets.map(p => [p.latitude, p.longitude]);
            
            if (coordinates.length === 0) return;
            
            // Get latest packet and store symbol info
            const latestPacket = packets[packets.length - 1];
            const symbolCode = latestPacket.symbol_code || '>';
            const symbolTable = latestPacket.symbol_table || '/';
            
            // Store symbol for sidebar consistency
            latestPacketSymbols[callsign] = {
                symbol_code: symbolCode,
                symbol_table: symbolTable
            };
            
            const colorClass = getColorForCallsign(callsign);
            const color = getRGBColor(colorClass);
            
            // Remove old path if exists
            if (stationPaths[callsign]) {
                map.removeLayer(stationPaths[callsign]);
            }
            
            // Create new path
            stationPaths[callsign] = L.polyline(coordinates, {
                color: color,
                weight: 3,
                opacity: 0.7
            });
            
            // Add path to map if visible
            if (stationVisibility[callsign] !== false) {
                stationPaths[callsign].addTo(map);
            }
            
            // Remove old dots if exist
            if (stationDots[callsign]) {
                stationDots[callsign].forEach(dot => map.removeLayer(dot));
            }
            
            // Create dots for each point
            stationDots[callsign] = [];
            packets.forEach((packet, index) => {
                const dot = L.circleMarker([packet.latitude, packet.longitude], {
                    radius: 4,
                    fillColor: color,
                    color: color,
                    weight: 2,
                    opacity: 0.8,
                    fillOpacity: 0.6
                });
                
                const timestamp = formatTimestamp(packet.timestamp);
                const comment = packet.comment || '';
                dot.bindPopup(`
                    <div style="text-align: center;">
                        <strong>${callsign}</strong><br>
                        <small>${timestamp}</small><br>
                        ${comment ? `<em>${comment}</em>` : ''}
                    </div>
                `);
                
                stationDots[callsign].push(dot);
            });
            
            // Remove old marker if exists
            if (stationMarkers[callsign]) {
                map.removeLayer(stationMarkers[callsign]);
            }
            
            // Create marker for latest position with APRS icon
            // Use the symbol info stored above
            const markerSymbolCode = latestPacketSymbols[callsign].symbol_code;
            const markerSymbolTable = latestPacketSymbols[callsign].symbol_table;
            
            // Create display name - callsign already includes SSID if present (from the key)
            const displayName = callsign;
            
            const iconHtml = createAPRSIcon(markerSymbolCode, markerSymbolTable, 48);
            // Create icon with label below - bigger with shaded background
            const markerHtml = `
                <div style="
                    text-align: center;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    width: 100%;
                ">
                    <div style="flex-shrink: 0;">${iconHtml}</div>
                    <div style="
                        margin-top: 3px;
                        font-size: 12px;
                        font-weight: bold;
                        color: #fff;
                        background-color: rgba(0, 0, 0, 0.7);
                        padding: 2px 8px;
                        border-radius: 4px;
                        white-space: nowrap;
                        line-height: 1.3;
                        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.5);
                        text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.8);
                        display: inline-block;
                        max-width: 200px;
                        overflow: hidden;
                        text-overflow: ellipsis;
                    ">${displayName}</div>
                </div>
            `;
            
            stationMarkers[callsign] = L.marker([latestPacket.latitude, latestPacket.longitude], {
                icon: L.divIcon({
                    html: markerHtml,
                    className: 'aprs-marker-icon',
                    iconSize: [200, 70], // Width increased to accommodate label, height for label
                    iconAnchor: [100, 24] // Anchor at center horizontally, center of icon vertically
                })
            });
            
            const timestamp = formatTimestamp(latestPacket.timestamp);
            const comment = latestPacket.comment || '';
            stationMarkers[callsign].bindPopup(`
                <div style="text-align: center;">
                    <strong>${displayName}</strong><br>
                    <small>Last seen: ${timestamp}</small><br>
                    ${comment ? `<em>${comment}</em>` : ''}
                </div>
            `);
            
            // Add marker to map if visible
            if (stationVisibility[callsign] !== false) {
                stationMarkers[callsign].addTo(map);
            }
        });
        
        // Add all new layers to map first, then update visibility
        // This ensures markers are added before visibility check
        Object.keys(packetsByCallsign).forEach(callsign => {
            if (stationPaths[callsign] && stationVisibility[callsign] !== false) {
                if (!map.hasLayer(stationPaths[callsign])) {
                    stationPaths[callsign].addTo(map);
                }
            }
            
            if (stationDots[callsign]) {
                stationDots[callsign].forEach(dot => {
                    if (stationVisibility[callsign] !== false && !map.hasLayer(dot)) {
                        dot.addTo(map);
                    }
                });
            }
            
            if (stationMarkers[callsign] && stationVisibility[callsign] !== false) {
                if (!map.hasLayer(stationMarkers[callsign])) {
                    stationMarkers[callsign].addTo(map);
                }
            }
        });
        
        // Update visibility (will handle hiding/showing)
        updateMapVisibility();
        
        // Cache packets data for continuous "last seen" updates
        cachedPacketsByCallsign = packetsByCallsign;
        
        // Update sidebar "Last seen" times
        updateSidebarLastSeen(packetsByCallsign);
        
        // Note: Auto-zoom removed - map will maintain user's zoom level
        
    } catch (error) {
        console.error('Error updating map:', error);
    }
}

// Reset database
async function resetDatabase() {
    if (!confirm('Are you sure you want to reset the database? This will delete all packet data and cannot be undone.')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/reset`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            // Clear all map data
            Object.keys(stationPaths).forEach(callsign => {
                if (stationPaths[callsign]) {
                    map.removeLayer(stationPaths[callsign]);
                }
                if (stationMarkers[callsign]) {
                    map.removeLayer(stationMarkers[callsign]);
                }
                if (stationDots[callsign]) {
                    stationDots[callsign].forEach(dot => map.removeLayer(dot));
                }
            });
            
            stationPaths = {};
            stationMarkers = {};
            stationDots = {};
            latestPacketSymbols = {};
            
            // Reload callsigns and map
            await loadCallsigns();
            await updateMap();
            
            alert('Database reset successfully!');
        } else {
            const error = await response.json();
            alert(`Error resetting database: ${error.error || 'Unknown error'}`);
        }
    } catch (error) {
        console.error('Error resetting database:', error);
        alert('Error resetting database. Please check the console for details.');
    }
}

// Store packets data for continuous "last seen" updates
let cachedPacketsByCallsign = {};

// Update "last seen" times continuously (every second)
let lastSeenUpdateInterval = null;
function startLastSeenUpdates() {
    // Clear any existing interval
    if (lastSeenUpdateInterval) {
        clearInterval(lastSeenUpdateInterval);
    }
    // Start new interval
    lastSeenUpdateInterval = setInterval(() => {
        const cacheSize = Object.keys(cachedPacketsByCallsign).length;
        if (cacheSize > 0) {
            updateSidebarLastSeen(cachedPacketsByCallsign);
        }
    }, 1000); // Update every second
}

// Periodic update
async function startUpdates() {
    await updateGpsTime(); // Update GPS time first and wait for it
    loadCallsigns();
    await updateMap();
    
    // Start continuous "last seen" updates
    startLastSeenUpdates();
    
    updateTimer = setInterval(async () => {
        await updateGpsTime(); // Update GPS time on each interval and wait for it
        loadCallsigns();
        await updateMap();
    }, UPDATE_INTERVAL);
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
    initMap();
    // Initialize GPS time before starting updates
    await updateGpsTime();
    await startUpdates();
});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (updateTimer) {
        clearInterval(updateTimer);
    }
});

