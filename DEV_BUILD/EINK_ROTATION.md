# E-Ink Page Rotation

## Pages

### Status
- State: Running (or Standby/Starting/Waiting for GPS fix/Stopping/Error, whatever's true when this page rotates up)
- IP: 192.168.1.50
- Uptime: 2h 14m

### Config summary
- Call: ZL1ABC-9
- Freq: 144.800 MHz
- Mode: Digi+IGate

### Location
- GPS: 8/12 sats
- Lat: -36.8485
- Lon: 174.7633

(manual position instead of live GPS: GPS: Manual, then Lat/Lon as above. No fix yet: GPS: Searching only.)

### Symbol & comment
Icon (drawn from the same sprite sheet as the dashboard's station symbol, see display/rotation.py's _render_symbol_glyph) plus the station comment, wrapped, not label:value rows (see display/templates/default.py's draw_symbol_page):

```
     [icon]
Digipeater test station, Auckland CBD
```

### Last beacon
A table, not label:value rows (see display/templates/default.py's draw_table_page):

```
          Last    Next
    RF:   -       -
 IGate:   Disabled
```

Enabled/disabled is real (same aprs config as Config summary); Last/Next stay "-" until real beacon-transmission history exists.

### Last heard
Icon+callsign, Lat/Lon, then comment, not label:value rows (see display/templates/default.py's draw_station_page):

```
[icon] ZL1ABC-9
  Lat -36.8485  Lon 174.7633
  Mobile /M portable digipeater test
```

Layout is real; every field is a placeholder ("-"/"Not available yet") until real packet history exists, no heard-station data source is tracked anywhere yet.
