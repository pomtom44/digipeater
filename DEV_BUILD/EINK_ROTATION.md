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
A table, not label:value rows (see display/templates/default.py's draw_table_page). Real, backed by services/packet_log.py tailing Direwolf's journal for beacon-transmission log lines:

```
          Last    Next
    RF:   2m      28m
 IGate:   Disabled
```

Both fields are "None" (not a bare "-") when a beacon type is enabled but nothing's actually been seen yet this run (just started, or none due).

### Last heard
Icon+callsign, Lat/Lon, then comment, not label:value rows (see display/templates/default.py's draw_station_page). Real, same source as Last Beacon, aprslib-decoded from the journal tail:

```
[icon] ZL1ABC-9
  Lat -36.8485  Lon 174.7633
  Mobile /M portable digipeater test
```

Every field is "None" until something's actually been heard this run.
