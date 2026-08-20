"""Per-display-model page templates; models without a dedicated template file get default.py's generic layout."""

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
            logger.warning("Template for model '%s' failed to load: %s, using default", model, e)
    from . import default
    return default
