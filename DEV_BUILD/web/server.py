import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from display.base import DisplayDriver

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(display_driver: DisplayDriver, first_boot: bool) -> FastAPI:
    app = FastAPI(title="APRS Digipeater")

    @app.get("/")
    async def root():
        page = "first_run.html" if first_boot else "test.html"
        return FileResponse(STATIC_DIR / page)

    @app.get("/test")
    async def test_page():
        return FileResponse(STATIC_DIR / "test.html")

    @app.get("/api/status")
    async def status():
        return {"ok": True, "first_boot": first_boot}

    @app.get("/api/display/status")
    async def display_status():
        return {
            "driver": type(display_driver).__name__,
            "width": display_driver.width,
            "height": display_driver.height,
        }

    @app.post("/api/display/clear")
    async def display_clear():
        try:
            display_driver.clear()
        except Exception as e:
            logger.error("Display clear failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True}

    @app.post("/api/display/test")
    async def display_test():
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            raise HTTPException(status_code=500, detail="Pillow not installed")
        try:
            w, h = display_driver.width, display_driver.height
            image = Image.new("1", (w, h), 255)
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, w - 1, h - 1), outline=0)
            margin = display_driver.margin
            line_height = display_driver.line_height
            lines = [
                "APRS Digipeater",
                "E-Ink test pattern",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                f"{w} x {h}",
            ]
            y = margin
            for line in lines:
                draw.text((margin, y), line, fill=0)
                y += line_height
            display_driver.show(image)
        except Exception as e:
            logger.error("Display test render failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True}

    @app.post("/api/display/sleep")
    async def display_sleep():
        try:
            display_driver.sleep()
        except Exception as e:
            logger.error("Display sleep failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True}

    return app
