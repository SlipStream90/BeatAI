"""Headless tests for Beat Shabber AI (no camera, no window, no network).

1. Beat detection on the generated 60 s / 120 BPM click track -> ~120 beats (+-10%).
2. Segment-rect intersection + swipe-direction + colour: 4 hand-written cases
   (hit, miss, wrong direction, wrong colour).
Run:  python test_core.py
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core
import beats

TMP_WAV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "songs", "_test_click.wav")
RECT = (100, 100, 80, 80)  # x, y, w, h -> covers (100..180, 100..180)


def test_beat_detection():
    beats.generate_click_track(TMP_WAV, bpm=120.0, seconds=60.0)
    times, tempo = beats.get_beat_times(TMP_WAV)
    n = len(times)
    print("beats found: %d (tempo %.1f)" % (n, tempo))
    assert 108 <= n <= 132, "expected ~120 beats in 60 s @120BPM, got %d" % n
    # Beats should be roughly evenly spaced at 0.5 s.
    gaps = [b - a for a, b in zip(times, times[1:])]
    avg = sum(gaps) / len(gaps)
    assert 0.4 <= avg <= 0.6, "mean beat gap %.3f s, expected ~0.5" % avg
    # Clean up wav + cache.
    for p in (TMP_WAV, TMP_WAV + beats.CACHE_SUFFIX):
        try:
            os.remove(p)
        except OSError:
            pass
    print("PASS beat detection (~120 beats, 0.5 s spacing)")


def swipe(p0, p1, speed, color, arrow):
    return core.classify_cut(p0, p1, speed, color, RECT, "blue", arrow)


def test_hit():
    # Fast blue swipe straight down through the rect; arrow = down -> good.
    r = swipe((140, 40), (140, 200), 1500.0, "blue", "down")
    assert r == "good", "hit case -> %s" % r
    print("PASS hit (good cut)")


def test_miss():
    # Swipe far away from the rect -> no_hit even though fast + correct colour/dir.
    r = swipe((300, 300), (400, 400), 2000.0, "blue", "right")
    assert r == "no_hit", "miss case -> %s" % r
    # Too-slow swipe through the rect also must not count.
    r2 = core.classify_cut((140, 40), (140, 200), 50.0, "blue", RECT, "blue", "down")
    assert r2 == "no_hit", "slow swipe case -> %s" % r2
    print("PASS miss (no intersection / too slow)")


def test_wrong_direction():
    # Blue swipe through rect but horizontal while arrow demands down -> bad_direction.
    r = swipe((40, 140), (220, 140), 1500.0, "blue", "down")
    assert r == "bad_direction", "wrong-direction case -> %s" % r
    print("PASS wrong direction (bad cut)")


def test_wrong_colour():
    # Red swipe through a blue block with correct direction -> bad_colour.
    r = swipe((140, 40), (140, 200), 1500.0, "red", "down")
    assert r == "bad_colour", "wrong-colour case -> %s" % r
    print("PASS wrong colour (bad cut)")


def test_scoring_helpers():
    assert core.multiplier_for_combo(0) == 1
    assert core.multiplier_for_combo(4) == 2
    assert core.multiplier_for_combo(8) == 4
    assert core.multiplier_for_combo(16) == 8
    assert core.is_hittable(9.80, 10.0) and not core.is_hittable(9.0, 10.0)
    assert core.is_missed(10.3, 10.0, False) and not core.is_missed(10.1, 10.0, False)
    assert not core.is_missed(11.0, 10.0, True)
    print("PASS scoring helpers (multiplier / windows)")


if __name__ == "__main__":
    test_beat_detection()
    test_hit()
    test_miss()
    test_wrong_direction()
    test_wrong_colour()
    test_scoring_helpers()
    print("ALL TESTS PASSED")
