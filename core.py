"""Pure, headless-testable gameplay math for Beat Shabber AI.

No pygame / cv2 imports here so test_core.py can run anywhere.
Screen coords: x right, y DOWN. All positions in pixels.
"""
import math

# A block is hittable only in its final window before/after its beat.
HIT_WINDOW_BEFORE = 0.35  # seconds before beat
HIT_WINDOW_AFTER = 0.20   # grace seconds after beat
# Minimum saber-tip speed (px/s) for a swipe to count.
SWIPE_MIN_SPEED = 500.0
# Swipe must be within this angle of the block's arrow.
SWIPE_MAX_ANGLE_DEG = 60.0
# Pseudo-3D travel time: spawn at beat_time - TRAVEL_TIME.
TRAVEL_TIME = 1.2

ARROW_DIRS = {
    "up": (0.0, -1.0),
    "down": (0.0, 1.0),
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
}


def _seg_intersect(p1, p2, p3, p4):
    """Return True if segments p1-p2 and p3-p4 intersect (excl. collinear overlap edge cases handled)."""
    def orient(a, b, c):
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(v) < 1e-9:
            return 0
        return 1 if v > 0 else 2

    def on_seg(a, b, c):  # b on segment a-c (collinear assumed)
        return (min(a[0], c[0]) - 1e-9 <= b[0] <= max(a[0], c[0]) + 1e-9 and
                min(a[1], c[1]) - 1e-9 <= b[1] <= max(a[1], c[1]) + 1e-9)

    o1, o2, o3, o4 = orient(p1, p2, p3), orient(p1, p2, p4), orient(p3, p4, p1), orient(p3, p4, p2)
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and on_seg(p1, p3, p2):
        return True
    if o2 == 0 and on_seg(p1, p4, p2):
        return True
    if o3 == 0 and on_seg(p3, p1, p4):
        return True
    if o4 == 0 and on_seg(p3, p2, p4):
        return True
    return False


def point_in_rect(p, rect):
    x, y, w, h = rect
    return x <= p[0] <= x + w and y <= p[1] <= y + h


def seg_intersects_rect(p0, p1, rect):
    """True if movement segment p0->p1 touches rect (x, y, w, h)."""
    if point_in_rect(p0, rect) or point_in_rect(p1, rect):
        return True
    x, y, w, h = rect
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    edges = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    return any(_seg_intersect(p0, p1, a, b) for a, b in edges)


def swipe_angle_deg(swipe_vec, arrow):
    """Angle in degrees between swipe vector and arrow direction. inf if swipe is zero."""
    ax, ay = ARROW_DIRS[arrow]
    sx, sy = swipe_vec
    mag = math.hypot(sx, sy)
    if mag < 1e-9:
        return float("inf")
    dot = (sx * ax + sy * ay) / mag  # arrow dirs are unit length
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(dot))


def swipe_matches(swipe_vec, arrow, max_deg=SWIPE_MAX_ANGLE_DEG):
    return swipe_angle_deg(swipe_vec, arrow) <= max_deg


def classify_cut(p0, p1, speed, saber_color, block_rect, block_color, block_arrow):
    """Classify one saber's swipe against one block.

    Returns one of: "good", "no_hit" (no intersect or too slow),
    "bad_colour", "bad_direction".
    Colour is checked before direction.
    """
    if speed < SWIPE_MIN_SPEED:
        return "no_hit"
    if not seg_intersects_rect(p0, p1, block_rect):
        return "no_hit"
    if saber_color != block_color:
        return "bad_colour"
    swipe_vec = (p1[0] - p0[0], p1[1] - p0[1])
    if not swipe_matches(swipe_vec, block_arrow):
        return "bad_direction"
    return "good"


def multiplier_for_combo(combo):
    if combo >= 16:
        return 8
    if combo >= 8:
        return 4
    if combo >= 4:
        return 2
    return 1


def is_hittable(now, beat_time):
    return (beat_time - HIT_WINDOW_BEFORE) <= now <= (beat_time + HIT_WINDOW_AFTER)


def is_missed(now, beat_time, was_hit):
    return (not was_hit) and now > beat_time + HIT_WINDOW_AFTER
