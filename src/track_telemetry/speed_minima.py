"""Measured local speed troughs for synchronized report markers."""
import numpy as np


def speed_minima_indices(values, *, reversal_kmh=3.):
    """Require a fall and recovery of 3 km/h; return original sample indices.

    Hysteresis suppresses small speed noise without smoothing measured values.
    An uncompleted boundary trough is not a confirmed local minimum. If there
    are no completed troughs, retain the window minimum as a boundary candidate.
    These are speed troughs, not automatically identified physical corners.
    """
    speed = np.asarray(values, dtype=float)
    if not len(speed) or not np.all(np.isfinite(speed)):
        return []
    peak, trough, falling = 0, 0, False
    result = []
    for i in range(1, len(speed)):
        if not falling:
            if speed[i] >= speed[peak]:
                peak = i
            elif speed[peak]-speed[i] >= reversal_kmh:
                falling, trough = True, i
        elif speed[i] < speed[trough]:
            trough = i
        elif speed[i]-speed[trough] >= reversal_kmh:
            result.append(trough)
            peak, falling = i, False
    return result or [int(np.argmin(speed))]


def place_label(x, y, text, occupied, *, font=15., bounds=(0., 0., 600., 600.)):
    """Place an SVG label without intersecting previously reserved text boxes."""
    left, top, right, bottom = bounds
    width = sum(1. if ord(c) > 127 else .62 for c in text)*font + 6
    height = font*1.4
    x = max(left+3, min(x, right-width-3))
    preferred = max(top+height, min(y, bottom-4))
    choices = [preferred]
    for step in range(1, 100):
        choices.extend((preferred-step*height, preferred+step*height))
    for baseline in choices:
        box = (x, baseline-font, x+width, baseline+font*.4)
        if box[1] < top or box[3] > bottom:
            continue
        if all(box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3]
               for b in occupied):
            occupied.append(box)
            return x, baseline
    occupied.append((x, preferred-font, x+width, preferred+font*.4))
    return x, preferred
