"""Reverse telemetry from onboard-video overlays (needle dials, digital readouts, map dots).

All heavy third-party imports (cv2, pytesseract) are function-local so that
importing this package never affects the report workflow when video extras
are not installed.
"""

from .clean import clean_speed_series, interp_gaps, reject_outliers
from .jobs import AnchoredJob, OcrJob
from .verify import FourChecks, four_checks

__all__ = [
    "AnchoredJob",
    "OcrJob",
    "FourChecks",
    "clean_speed_series",
    "four_checks",
    "interp_gaps",
    "reject_outliers",
]
