"""Screen capture and cropping of calibrated regions."""

from __future__ import annotations

import platform

from PIL import Image, ImageGrab

_dpi_set = False


def make_dpi_aware() -> None:
    """
    On Windows with display scaling (125%, 150%...), make screenshots and window
    coordinates use real pixels so calibration matches capture exactly.
    """
    global _dpi_set
    if _dpi_set or platform.system() != "Windows":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
    _dpi_set = True


def screenshot() -> Image.Image:
    """Full screenshot of the main monitor, RGB."""
    make_dpi_aware()
    return ImageGrab.grab().convert("RGB")


def crop(frame: Image.Image, region: dict) -> Image.Image:
    return frame.crop((region["x1"], region["y1"], region["x2"], region["y2"]))


class ScreenChanged(RuntimeError):
    pass


def check_screen_matches(frame: Image.Image, calibration: dict) -> None:
    """Fail loudly if the screen size changed since calibration (regions would be wrong)."""
    expected = calibration.get("screen_size")
    if expected and list(frame.size) != list(expected):
        raise ScreenChanged(
            f"Screen size is {frame.width}×{frame.height} but calibration was done at "
            f"{expected[0]}×{expected[1]}.\nResolution or display scaling changed — "
            "please run Calibrate again."
        )
