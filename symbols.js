/**
 * APRS Symbol Position Utility
 * Calculates sprite sheet positions for APRS icons
 */

// APRS symbol sprite sheet - using hessu/aprs-symbols
// Default to using a CDN URL, but can be replaced with local file for offline use
const SYMBOL_SHEET_URL = 'aprs-symbols-48-0.png';
const SYMBOL_SIZE = 48; // Each icon is 48x48 pixels
const SYMBOLS_PER_ROW = 16;

function getSymbolPosition(symbolCode, symbolTable = '/') {
    /**
     * Get CSS background position for APRS symbol
     * @param {string} symbolCode - The symbol code (e.g., '>', 'u', 'r', '`')
     * @param {string} symbolTable - The symbol table ('/' or '\')
     * @returns {string} CSS background-position value
     */
    
    if (!symbolCode) {
        // Default symbol (car/mobile) - '>' at position 0,0
        return '0px 0px';
    }
    
    // hessu/aprs-symbols sprite sheet is organized by ASCII character codes
    // Primary table (/) starts at ASCII 33 (!) and goes in order
    // Each row has 16 icons (SYMBOLS_PER_ROW)
    
    let asciiCode = symbolCode.charCodeAt(0);
    
    // For primary symbol table (/), symbols start at ASCII 33 (!)
    // Calculate position based on ASCII code
    if (symbolTable === '/') {
        // Primary table: symbols start at ! (ASCII 33)
        // Position relative to start of table
        const offset = asciiCode - 33;
        
        if (offset < 0) {
            // Invalid, use default
            return '0px 0px';
        }
        
        // Calculate row and column
        const row = Math.floor(offset / SYMBOLS_PER_ROW);
        const col = offset % SYMBOLS_PER_ROW;
        
        return `${col * -SYMBOL_SIZE}px ${row * -SYMBOL_SIZE}px`;
    } else if (symbolTable === '\\') {
        // Alternate symbol table (\) - typically same as primary for most symbols
        // But some symbols may be different, for now use same calculation
        const offset = asciiCode - 33;
        
        if (offset < 0) {
            return '0px 0px';
        }
        
        const row = Math.floor(offset / SYMBOLS_PER_ROW);
        const col = offset % SYMBOLS_PER_ROW;
        
        return `${col * -SYMBOL_SIZE}px ${row * -SYMBOL_SIZE}px`;
    }
    
    // Default fallback
    return '0px 0px';
}

function createAPRSIcon(symbolCode, symbolTable = '/', size = 48) {
    /**
     * Create an HTML div element with APRS icon
     * @param {string} symbolCode - The symbol code
     * @param {string} symbolTable - The symbol table
     * @param {number} size - Icon size in pixels
     * @returns {string} HTML string for the icon
     */
    const position = getSymbolPosition(symbolCode, symbolTable);
    
    return `<div class="aprs-icon" style="width: ${size}px; height: ${size}px; background-image: url('${SYMBOL_SHEET_URL}'); background-repeat: no-repeat; background-position: ${position}; background-size: ${SYMBOLS_PER_ROW * SYMBOL_SIZE}px auto; margin: 0; padding: 0; display: block; box-sizing: border-box;"></div>`;
}

