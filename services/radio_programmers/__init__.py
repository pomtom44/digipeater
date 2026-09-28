"""Registry of radio-programming drivers; add a new radio by adding one entry here."""

from services.radio_programmers import alinco_dr138_mkii

DRIVERS = {
    alinco_dr138_mkii.MODEL: alinco_dr138_mkii,
}
