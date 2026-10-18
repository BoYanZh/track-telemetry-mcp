"""Digital speed OCR. Proven on RaceRender/custom/Catalyst families.
psm8 beats psm7 decisively on clean digits (6/10 vs 2/10 exact)."""

from __future__ import annotations


def _ocr_thresh(thresh, psm, valid_range):
    """Shared tesseract tail: border + digit whitelist + range gate."""
    import cv2
    import pytesseract

    bordered = cv2.copyMakeBorder(thresh, 20, 20, 20, 20,
                                  cv2.BORDER_CONSTANT, value=0)
    txt = pytesseract.image_to_string(
        bordered, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789")
    digits = "".join(c for c in txt if c.isdigit())
    if not digits:
        return None
    value = int(digits)
    lo, hi = valid_range
    return value if lo <= value <= hi else None


def read_digits(frame, roi, psm=8, valid_range=(15, 140)):
    """OCR an integer speed from a full-frame ROI. Returns int or None."""
    import cv2

    x, y, w, h = roi
    crop = frame[y:y + h, x:x + w]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    big = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return _ocr_thresh(thresh, psm, valid_range)


def read_blue_digits(frame, roi, psm=8, valid_range=(15, 140)):
    """OCR blue-channel digital speed (dark overlay, blue digits).

    Proven on Gua9O96-pTE (5/5 exact incl. 3-digit 103): isolates digits via
    blue-dominance (B - max(G, R)) + OTSU, which drops the white "MPH" label
    and red/white arc bar that share the ROI. Upscale is 4x (digits are
    ~25px tall vs ~45px for white-digit families).
    """
    import cv2

    x, y, w, h = roi
    crop = frame[y:y + h, x:x + w]
    b, g, r = cv2.split(crop)
    dom = cv2.subtract(b, cv2.max(g, r))
    big = cv2.resize(dom, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return _ocr_thresh(thresh, psm, valid_range)


# Documented OCR confusion pairs (frame-verified): reject-or-verify on sight.
CONFUSION_PAIRS = ("7->2", "8->6", "6/9->5", "6x->8x", "9x->7x")
