"""
Waveshare e-Paper model registry — auto-discovered from this folder.

To add support for a new screen: drop a driver module here (a class named
EPD with init/getbuffer/display/Clear/sleep — copy an existing file as a
template) exposing the metadata constants DESC, LANDSCAPE_WIDTH,
LANDSCAPE_HEIGHT (LINE_HEIGHT/MARGIN optional, default 16/4). It will show
up in the config-page model dropdown and be loadable by name automatically.
Nothing else in the app needs to change — the config-page dropdown, the
GPIO pinout note, and driver_waveshare.py all read this registry rather
than naming models individually. See epd2in9b_v3.py for the constants
this scan reads.
"""

import importlib
import logging
import pkgutil

logger = logging.getLogger(__name__)


def _discover() -> dict:
    models = {}
    for info in pkgutil.iter_modules(__path__):
        name = info.name
        if name == "epdconfig" or name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f".{name}", package=__name__)
        except Exception as e:
            logger.warning("Skipping display module '%s' — failed to import: %s", name, e)
            continue
        if not hasattr(mod, "EPD"):
            continue
        try:
            models[name] = {
                "module": name,
                "desc": mod.DESC,
                "w": mod.LANDSCAPE_WIDTH,
                "h": mod.LANDSCAPE_HEIGHT,
                "line_height": getattr(mod, "LINE_HEIGHT", 16),
                "margin": getattr(mod, "MARGIN", 4),
            }
        except AttributeError as e:
            logger.warning("Skipping display module '%s' — missing required metadata: %s", name, e)
    return models


MODELS = _discover()
