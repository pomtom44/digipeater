"""
Per-display-model page templates.

To give a display model its own layout: add a module here named exactly
after its driver (e.g. epd1in54_v2.py matches display/waveshare/epd1in54_v2.py),
exposing:

    draw_loading_page(driver) -> PIL.Image
    draw_status_page(driver, title: str, rows: list[tuple[str, str]]) -> PIL.Image

Adding a new screen's template never touches an existing one — each model's
layout lives in its own file. Models without a dedicated template file get
default.py's layout, which sizes itself from the driver's actual dimensions
and is reasonable on any screen shape, but won't look as considered as a
template designed for that exact aspect ratio.
"""

import importlib
import logging

logger = logging.getLogger(__name__)


def get_template(model: str):
    if model:
        try:
            return importlib.import_module(f".{model}", package=__name__)
        except ModuleNotFoundError:
            pass
        except Exception as e:
            logger.warning("Template for model '%s' failed to load: %s — using default", model, e)
    from . import default
    return default
