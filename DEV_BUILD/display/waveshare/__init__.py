"""Waveshare e-Paper model registry, auto-discovered from this folder."""

import importlib
import logging
import pkgutil

logger = logging.getLogger(__name__)


def _discover() -> dict:
    models = {}
    # Sorted for deterministic ordering in the install-time picker.
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        name = info.name
        if name == "epdconfig" or name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f".{name}", package=__name__)
        except Exception as e:
            logger.warning("Skipping display module '%s', failed to import: %s", name, e)
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
            logger.warning("Skipping display module '%s', missing required metadata: %s", name, e)
    return models


MODELS = _discover()
