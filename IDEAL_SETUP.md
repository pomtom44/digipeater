# Ideal Setup

[`SUPPORTED_HARDWARE.md`](SUPPORTED_HARDWARE.md) lists everything that's *known to work*. This doc is narrower: it's the one specific build the author actually runs, parts and settings included, kept here so you can copy it exactly instead of picking from a compatibility matrix. If you just want *something* that works, start there instead.

---

## Bill of Materials

| Component | Part / Model |
|---|---|
| Raspberry Pi | Raspberry Pi 3 Model B+ (2017) |
| MicroSD card | Any reliable brand (SanDisk/Samsung), no specific model required |
| External power connector | Any locking 2-pin connector rated for 12V, with strain relief |
| External power source | User's choice — 12V mains PSU, car battery, solar/battery bank, etc. — must stay within the radio's rated voltage range (e.g. raw solar alone can fluctuate too much) |
| Fuse | 15A (match to the radio's rated current draw) |
| Reverse-polarity diode | Any diode rated ≥15A (match or exceed the fuse rating) |
| Low-voltage cutoff | JY-601 |
| 12V-5V step-down converter | XC-4514 (any 12V-5V step-down converter will do) |
| Pi power cable | USB cable (from step-down converter to Pi) |
| Enclosure / case | TBD (specs to come later) |
| 3D printer | For printing mounts |
| Screws / nuts / bolts | Misc, TBD (to be confirmed once fully built) |
| Vero board | |
| Glue / tape | |
| Silicone sealer | |
| Solder & soldering gear | |
| Audio interface | Generic USB sound card / mic-headphone adapter dongle, no specific model |
| Radio | Alinco DR-138T MK2 |
| PTT method | GPIO pin via optocoupler (4N25/4N28) |
| GPS module | Any USB GPS module outputting NMEA 0183 |
| E-ink display | Waveshare 1.54inch e-Paper Module (Rev2.1, 200x200, SSD1681) |
| Radio power relay | Any 12V relay module rated for a 12V load, triggerable from a Pi GPIO pin |
| Antenna feedthrough | UG-492 BNC female-to-female bulkhead feedthrough, 50Ω |
| Feedthrough-to-radio jumper | Short coax cable, BNC male to PL-259 (UHF male), 50Ω |
| Radio audio out → Pi audio in cable | 3.5mm to 3.5mm cable (radio line out to sound card mic in) |
| Pi audio out → Radio mic in cable | 3.5mm to bare wire (sound card headphone out to radio mic in) |
| Radio mic connector plug | 8-pin round Foster-type male plug (mates with radio's mic jack, no need to cut the OEM handset mic) |
| Cables / adapters | Alinco ERW-7 programming cable (radio channel programming) |
| Misc | Power switch, wiring/terminals |

See [`SUPPORTED_HARDWARE.md`](SUPPORTED_HARDWARE.md) for why each of these is the right pick over the alternatives.
