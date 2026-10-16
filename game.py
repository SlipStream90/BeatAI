"""Pygame front-end: menu / calibration / play / end screens + hit detection FX."""
import csv
import json
import math
import os
import random
import time

import pygame

import beats
import core
from core import TRAVEL_TIME
from tracking import Tracker

W, H = 960, 540
VP = (W // 2, int(H * 0.36))  # vanishing point
LANE_X = [int(W * 0.30), int(W * 0.43), int(W * 0.57), int(W * 0.70)]
LANE_Y = int(H * 0.78)

RED = (255, 70, 70)
BLUE = (90, 170, 255)
BG = (12, 12, 22)
WHITE = (235, 235, 245)
DIM = (150, 150, 170)

ARROWS = ["up", "down", "left", "right"]
COLORS = ["red", "blue"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HIGHSCORE_PATH = os.path.join(BASE_DIR, "highscores.json")
RESULTS_PATH = os.path.join(BASE_DIR, "results.csv")


def _text(font, s, color=WHITE):
    return font.render(s, True, color)


def draw_arrow(surf, arrow, cx, cy, size, color):
    s = size // 2
    if arrow == "up":
        pts = [(cx, cy - s), (cx - s, cy + s), (cx + s, cy + s)]
    elif arrow == "down":
        pts = [(cx, cy + s), (cx - s, cy - s), (cx + s, cy - s)]
    elif arrow == "left":
        pts = [(cx - s, cy), (cx + s, cy - s), (cx + s, cy + s)]
    else:
        pts = [(cx + s, cy), (cx - s, cy - s), (cx - s, cy + s)]
    pygame.draw.polygon(surf, (15, 15, 25), pts)
    pygame.draw.polygon(surf, color, pts, 3)


def block_rect_at(progress, lane):
    """Pseudo-3D: lerp vanishing point -> lane target, growing with progress."""
    p = max(0.0, min(1.15, progress))
    tx, ty = LANE_X[lane], LANE_Y
    cx = VP[0] + (tx - VP[0]) * p
    cy = VP[1] + (ty - VP[1]) * p
    size = 16 + p * 70
    size = max(8.0, size)
    return (cx - size / 2, cy - size / 2, size, size), (cx, cy), size


class Game:
    def __init__(self):
        pygame.init()
        try:
            pygame.mixer.init()
            self.audio_ok = True
        except Exception:
            self.audio_ok = False
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("Beat Shabber AI")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont(None, 30)
        self.big = pygame.font.SysFont(None, 64)
        self.small = pygame.font.SysFont(None, 22)
        self.state = "menu"
        self.tracker = Tracker("AI")
        self.tracker.start()
        self.mode = "AI"  # AI | CLASSIC | MOUSE
        self.songs = beats.ensure_song()
        self.song_idx = 0
        self.banner = ""
        self.banner_until = 0.0
        self.debug = False
        self.hsv_sel = 0
        # per-song
        self.beat_times = []
        self.tempo = 120.0
        self.duration = 60.0
        self.chart = []
        self.spawn_idx = 0
        self.active = []
        self.debris = []
        self.particles = []
        self.score = 0
        self.combo = 0
        self.max_combo = 0
        self.good = 0
        self.bad = 0
        self.miss = 0
        self.song_t0 = 0.0
        self.music_started = False
        self.sabers = {}
        self.fps = 0.0

    # ---------------- helpers ----------------
    def say(self, msg, secs=4.0):
        self.banner = msg
        self.banner_until = time.time() + secs

    def song_time(self):
        if self.audio_ok and self.music_started:
            try:
                pos = pygame.mixer.music.get_pos()
                if pos is not None and pos >= 0:
                    return pos / 1000.0
            except Exception:
                pass
        return time.time() - self.song_t0

    def accuracy(self):
        total = self.good + self.bad + self.miss
        return 100.0 * self.good / total if total else 100.0

    # ---------------- song flow ----------------
    def start_song(self):
        path = self.songs[self.song_idx]
        self.say("Analysing beats...")
        self.beat_times, self.tempo = beats.get_beat_times(path)
        # Skip beats in the first second (audio fade-in / music start latency).
        self.beat_times = [b for b in self.beat_times if b >= 1.0]
        if not self.beat_times:
            self.beat_times = [i * 0.5 for i in range(2, 122)]
            self.tempo = 120.0
        self.duration = beats.audio_duration(path)
        # Build chart: random colour/arrow/lane; every 4th beat spawns two blocks.
        self.chart = []
        lanes = list(range(4))
        for i, bt in enumerate(self.beat_times):
            lane = random.choice(lanes)
            self.chart.append({"beat": bt, "lane": lane,
                               "color": random.choice(COLORS),
                               "arrow": random.choice(ARROWS)})
            if i % 4 == 3:
                lane2 = random.choice([l for l in lanes if l != lane])
                other = "blue" if self.chart[-1]["color"] == "red" else "red"
                self.chart.append({"beat": bt, "lane": lane2, "color": other,
                                   "arrow": random.choice(ARROWS)})
        self.chart.sort(key=lambda b: b["beat"])
        self.spawn_idx = 0
        self.active = []
        self.debris = []
        self.particles = []
        self.score = self.combo = self.max_combo = 0
        self.good = self.bad = self.miss = 0
        self.sabers = {"red": {"prev": None, "tip": None, "speed": 0.0, "found": False},
                       "blue": {"prev": None, "tip": None, "speed": 0.0, "found": False}}
        self.tracker.reset_stats()
        try:
            if self.audio_ok:
                pygame.mixer.music.load(path)
                pygame.mixer.music.play()
                self.music_started = True
            else:
                self.music_started = False
        except Exception:
            self.music_started = False
        self.song_t0 = time.time()
        self.state = "play"

    def end_song(self, reason="finished"):
        try:
            if self.audio_ok:
                pygame.mixer.music.stop()
        except Exception:
            pass
        self.music_started = False
        loss = self.tracker.tracking_loss_pct()
        acc = self.accuracy()
        # High scores.
        entry = {"song": os.path.basename(self.songs[self.song_idx]),
                 "mode": self.mode, "score": self.score,
                 "accuracy": round(acc, 1), "max_combo": self.max_combo,
                 "tracking_loss_pct": round(loss, 1)}
        try:
            hs = []
            if os.path.exists(HIGHSCORE_PATH):
                with open(HIGHSCORE_PATH) as f:
                    hs = json.load(f)
            hs.append(entry)
            hs = sorted(hs, key=lambda e: e.get("score", 0), reverse=True)[:20]
            with open(HIGHSCORE_PATH, "w") as f:
                json.dump(hs, f, indent=1)
        except Exception:
            pass
        # P5: per-song comparison log (AI vs CLASSIC).
        try:
            new = not os.path.exists(RESULTS_PATH)
            with open(RESULTS_PATH, "a", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["mode", "accuracy", "tracking_loss_pct"])
                w.writerow([self.mode, round(acc, 1), round(loss, 1)])
        except Exception:
            pass
        self.state = "end"

    # ---------------- per-frame ----------------
    def update_sabers(self, st, dt):
        dt = max(dt, 1e-4)
        for color in ("red", "blue"):
            s = self.sabers[color]
            s["prev"] = s["tip"]
        if self.mode == "MOUSE":
            mx, my = pygame.mouse.get_pos()
            s = self.sabers["blue"]
            s["tip"] = (float(mx), float(my))
            s["found"] = True
            self.sabers["red"]["tip"] = None
            self.sabers["red"]["found"] = False
        else:
            for color, key in (("red", "red_tip"), ("blue", "blue_tip")):
                nt = st.get(key)
                s = self.sabers[color]
                if st.get("camera_ok") and nt is not None and s is not None:
                    tip = (nt[0] * W, nt[1] * H)
                    s["tip"] = tip
                    s["found"] = True
                else:
                    s["tip"] = None
                    s["found"] = False
        for color in ("red", "blue"):
            s = self.sabers[color]
            if s["tip"] is not None and s["prev"] is not None:
                d = math.hypot(s["tip"][0] - s["prev"][0], s["tip"][1] - s["prev"][1])
                s["speed"] = d / dt
            else:
                s["speed"] = 0.0

    def judge_block(self, block, rect):
        """Judge one hittable block against both sabers. Returns True if consumed."""
        results = {}
        for color in ("red", "blue"):
            s = self.sabers[color]
            if s["found"] and s["tip"] is not None and s["prev"] is not None:
                results[color] = core.classify_cut(
                    s["prev"], s["tip"], s["speed"], color,
                    rect, block["color"], block["arrow"])
        if not results:
            return False
        if "good" in results.values():
            self.on_cut(block, rect, good=True)
            return True
        # Matching-colour swipe with wrong direction takes priority over wrong colour.
        ms = results.get(block["color"])
        if ms == "bad_direction":
            self.on_cut(block, rect, good=False)
            return True
        if "bad_colour" in results.values():
            self.on_cut(block, rect, good=False)
            return True
        return False

    def on_cut(self, block, rect, good):
        cx = rect[0] + rect[2] / 2
        cy = rect[1] + rect[3] / 2
        if good:
            self.combo += 1
            self.max_combo = max(self.max_combo, self.combo)
            self.score += 100 * core.multiplier_for_combo(self.combo)
            self.good += 1
        else:
            self.combo = 0
            self.bad += 1
        # Split halves fly apart along the cut (arrow) direction + particles.
        dx, dy = core.ARROW_DIRS[block["arrow"]]
        col = RED if block["color"] == "red" else BLUE
        for sign in (-1, 1):
            self.debris.append({"x": cx, "y": cy,
                                "vx": dx * sign * 320 + random.uniform(-60, 60),
                                "vy": dy * sign * 320 - 120,
                                "size": rect[2] / 2, "angle": 0.0,
                                "va": random.uniform(-540, 540),
                                "life": 0.6, "color": col})
        for _ in range(14):
            a = random.uniform(0, math.tau)
            sp = random.uniform(80, 420)
            self.particles.append({"x": cx, "y": cy,
                                   "vx": math.cos(a) * sp, "vy": math.sin(a) * sp - 100,
                                   "life": random.uniform(0.25, 0.6),
                                   "max": 0.6,
                                   "color": col if good else (200, 200, 200)})

    def update_play(self, dt, st):
        now = self.song_time()
        # Spawn blocks whose travel window has opened.
        while (self.spawn_idx < len(self.chart) and
               self.chart[self.spawn_idx]["beat"] - TRAVEL_TIME <= now):
            b = dict(self.chart[self.spawn_idx])
            b.update({"hit": False, "counted_miss": False})
            self.active.append(b)
            self.spawn_idx += 1
        # Judge + expire.
        for b in self.active:
            if b["hit"] or b["counted_miss"]:
                continue
            prog = 1.0 - (b["beat"] - now) / TRAVEL_TIME
            rect, _, _ = block_rect_at(prog, b["lane"])
            if core.is_hittable(now, b["beat"]):
                if self.judge_block(b, rect):
                    b["hit"] = True
            if core.is_missed(now, b["beat"], b["hit"]):
                b["counted_miss"] = True
                self.miss += 1
                self.combo = 0
        self.active = [b for b in self.active
                       if not (b["hit"] or b["counted_miss"])]
        # FX.
        for d in self.debris:
            d["life"] -= dt
            d["x"] += d["vx"] * dt
            d["y"] += d["vy"] * dt
            d["vy"] += 900 * dt
            d["angle"] += d["va"] * dt
        self.debris = [d for d in self.debris if d["life"] > 0]
        for p in self.particles:
            p["life"] -= dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vy"] += 700 * dt
        self.particles = [p for p in self.particles if p["life"] > 0]
        # Song over?
        last = self.chart[-1]["beat"] if self.chart else 0
        if now > max(last + 2.5, self.duration + 1.0):
            self.end_song()

    # ---------------- drawing ----------------
    def draw_sabers(self):
        for color, col in (("red", RED), ("blue", BLUE)):
            s = self.sabers[color]
            if not s["found"] or s["tip"] is None:
                continue
            tip = (int(s["tip"][0]), int(s["tip"][1]))
            if self.mode == "AI":
                st = self._last_state or {}
                base_n = st.get("red_base" if color == "red" else "blue_base")
                if base_n is not None:
                    base = (int(base_n[0] * W), int(base_n[1] * H))
                    pygame.draw.line(self.screen, col, base, tip, 7)
                    pygame.draw.line(self.screen, WHITE, base, tip, 2)
                else:
                    pygame.draw.circle(self.screen, col, tip, 12)
            else:
                if s["prev"] is not None:
                    prev = (int(s["prev"][0]), int(s["prev"][1]))
                    pygame.draw.line(self.screen, col, prev, tip, 8)
                pygame.draw.circle(self.screen, col, tip, 12)
                pygame.draw.circle(self.screen, WHITE, tip, 12, 2)

    def draw_play(self, now):
        self.screen.fill(BG)
        # Lane guides.
        for lx in LANE_X:
            pygame.draw.line(self.screen, (40, 40, 60), VP, (lx, LANE_Y), 1)
        pygame.draw.circle(self.screen, (50, 50, 70), VP, 6)
        # Blocks far -> near.
        items = []
        for b in self.active:
            prog = 1.0 - (b["beat"] - now) / TRAVEL_TIME
            rect, center, size = block_rect_at(prog, b["lane"])
            items.append((prog, b, rect, center, size))
        items.sort(key=lambda t: t[0])
        for _, b, rect, center, size in items:
            col = RED if b["color"] == "red" else BLUE
            hot = core.is_hittable(now, b["beat"])
            pygame.draw.rect(self.screen, col,
                             (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])), 0)
            pygame.draw.rect(self.screen, WHITE,
                             (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])),
                             4 if hot else 2)
            draw_arrow(self.screen, b["arrow"], int(center[0]), int(center[1]),
                       int(size * 0.7), WHITE)
        # Debris halves.
        for d in self.debris:
            s = max(2, int(d["size"] * (d["life"] / 0.6)))
            pts = [(-s // 2, -s // 2), (s // 2, -s // 2), (0, s // 2)]
            a = math.radians(d["angle"])
            ca, sa = math.cos(a), math.sin(a)
            rp = [(d["x"] + x * ca - y * sa, d["y"] + x * sa + y * ca) for x, y in pts]
            pygame.draw.polygon(self.screen, d["color"], rp)
        for p in self.particles:
            r = max(1, int(4 * p["life"] / p["max"]))
            pygame.draw.circle(self.screen, p["color"], (int(p["x"]), int(p["y"])), r)
        self.draw_sabers()
        # HUD.
        mult = core.multiplier_for_combo(self.combo)
        hud = self.font.render(
            "Score %d   Combo %d   x%d   Acc %.1f%%" % (
                self.score, self.combo, mult, self.accuracy()), True, WHITE)
        self.screen.blit(hud, (16, 10))
        song = _text(self.small, os.path.basename(self.songs[self.song_idx]) +
                     "  [M]ouse [C]lassic/AI [D]ebug [Q]uit", DIM)
        self.screen.blit(song, (16, H - 30))

    def draw_menu(self):
        self.screen.fill(BG)
        self.screen.blit(_text(self.big, "BEAT SHABBER AI", (120, 220, 255)), (W // 2 - 250, 60))
        self.screen.blit(_text(self.font, "Webcam Beat Saber — CV demo  |  Mode: %s" % self.mode, WHITE),
                         (W // 2 - 270, 130))
        y = 190
        for i, p in enumerate(self.songs):
            name = os.path.basename(p)
            col = (255, 255, 120) if i == self.song_idx else WHITE
            prefix = "> " if i == self.song_idx else "  "
            self.screen.blit(_text(self.font, prefix + name, col), (W // 2 - 250, y))
            y += 36
        self.screen.blit(_text(self.font, "[ENTER] Start   [K] Calibrate   [C] AI/CLASSIC   [M] Mouse   [ESC] Quit", DIM),
                         (W // 2 - 330, H - 90))
        self.screen.blit(_text(self.small, "Sabers: Left hand = RED, Right hand = BLUE. Swipe along the arrow.", DIM),
                         (W // 2 - 300, H - 55))

    def draw_calibration(self, st):
        self.screen.fill(BG)
        self.screen.blit(_text(self.font, "CALIBRATION — %s mode (C switch, M mouse, ENTER back)" % self.mode, WHITE), (20, 12))
        frame = st.get("mask_frame") if (self.mode == "CLASSIC") else st.get("pip_frame")
        if frame is not None:
            try:
                import cv2
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if len(frame.shape) == 3 else frame
                if len(frame.shape) == 2:
                    import numpy as np
                    rgb = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                surf = pygame.surfarray.make_surface(np.transpose(rgb, (1, 0, 2)))
                surf = pygame.transform.scale(surf, (640, 360))
                self.screen.blit(surf, (20, 50))
            except Exception:
                pass
        else:
            self.screen.blit(_text(self.font, "No camera frame yet...", DIM), (20, 60))
        y = 50
        if self.mode == "CLASSIC":
            names = ["H low", "H high", "S low", "S high", "V low", "V high"]
            vals = st.get("hsv_low", [0, 0, 0]) + st.get("hsv_high", [0, 0, 0])
            order = [0, 3, 1, 4, 2, 5]
            for i, idx in enumerate(order):
                mark = "> " if i == self.hsv_sel else "  "
                self.screen.blit(_text(self.font, "%s%s: %d" % (mark, names[i], vals[idx]),
                                       (255, 255, 120) if i == self.hsv_sel else WHITE), (680, y))
                y += 34
            self.screen.blit(_text(self.small, "[W/S] select  [LEFT/RIGHT] -/+", DIM), (680, y + 10))
        else:
            with self.tracker.lock:
                n = len(self.tracker.landmarks)
            self.screen.blit(_text(self.font, "Hands with landmarks: %d" % n, WHITE), (680, y))
            self.screen.blit(_text(self.small, "Show palms to the camera.", DIM), (680, y + 40))
        if not st.get("camera_ok") and self.mode != "MOUSE":
            self.screen.blit(_text(self.font, st.get("message") or "Camera unavailable", (255, 120, 120)), (20, H - 40))

    def draw_end(self):
        self.screen.fill(BG)
        self.screen.blit(_text(self.big, "RESULTS", (120, 220, 255)), (W // 2 - 130, 70))
        loss = self.tracker.tracking_loss_pct()
        lines = ["Song: %s" % os.path.basename(self.songs[self.song_idx]),
                 "Mode: %s" % self.mode,
                 "Score: %d" % self.score,
                 "Accuracy: %.1f%%  (%d good / %d bad / %d miss)" % (
                     self.accuracy(), self.good, self.bad, self.miss),
                 "Max combo: %d" % self.max_combo,
                 "TRACKING-LOSS: %.1f%%" % loss]
        y = 170
        for ln in lines:
            self.screen.blit(_text(self.font, ln, WHITE), (W // 2 - 260, y))
            y += 40
        self.screen.blit(_text(self.font, "[ENTER] Menu   [ESC] Quit", DIM), (W // 2 - 160, H - 80))

    def draw_debug(self, st):
        if not self.debug:
            return
        fps = _text(self.small, "FPS %.0f" % self.fps, (120, 255, 120))
        self.screen.blit(fps, (W - 90, 10))
        frame = st.get("pip_frame")
        if frame is not None and self.state != "calib":
            try:
                import cv2
                import numpy as np
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                surf = pygame.surfarray.make_surface(np.transpose(rgb, (1, 0, 2)))
                self.screen.blit(surf, (W - 213 - 8, 34))
                pygame.draw.rect(self.screen, (120, 255, 120), (W - 213 - 8, 34, 213, 120), 1)
            except Exception:
                pass

    def draw_banner(self):
        if self.banner and time.time() < self.banner_until:
            t = _text(self.font, self.banner, (255, 220, 120))
            self.screen.blit(t, (W // 2 - t.get_width() // 2, H - 70))

    # ---------------- main loop ----------------
    def set_mode(self, mode):
        self.mode = mode
        self.tracker.mode = mode
        self.say("Mode: %s" % mode)

    def run(self):
        self._last_state = {}
        running = True
        while running:
            dt = self.clock.tick(60) / 1000.0
            self.fps = self.clock.get_fps()
            st = self.tracker.get_state()
            self._last_state = st
            # Auto-fallback if camera dies mid-demo.
            if self.mode != "MOUSE" and not st.get("camera_ok") and st.get("message"):
                if self.tracker.thread is not None and not self.tracker.thread.is_alive():
                    pass  # thread ended; message already explains
                if "No camera" in st["message"] or "Camera error" in st["message"] or "failed" in st["message"]:
                    if not getattr(self, "_fb_done", False):
                        self._fb_done = True
                        self.set_mode("MOUSE")
                        self.say("Camera failed — mouse mode (M). " + st["message"][:60])
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    k = ev.key
                    if k == pygame.K_ESCAPE:
                        running = False
                    elif k == pygame.K_d:
                        self.debug = not self.debug
                    elif k == pygame.K_m:
                        self.set_mode("MOUSE")
                    elif k == pygame.K_c:
                        self.set_mode("CLASSIC" if self.mode == "AI" else "AI")
                    elif self.state == "menu":
                        if k == pygame.K_UP:
                            self.song_idx = (self.song_idx - 1) % len(self.songs)
                        elif k == pygame.K_DOWN:
                            self.song_idx = (self.song_idx + 1) % len(self.songs)
                        elif k == pygame.K_k:
                            self.state = "calib"
                        elif k in (pygame.K_RETURN, pygame.K_SPACE):
                            self.start_song()
                    elif self.state == "calib":
                        if k in (pygame.K_RETURN, pygame.K_BACKSPACE, pygame.K_k):
                            self.state = "menu"
                        elif k == pygame.K_w:
                            self.hsv_sel = (self.hsv_sel - 1) % 6
                        elif k == pygame.K_s:
                            self.hsv_sel = (self.hsv_sel + 1) % 6
                        elif k in (pygame.K_LEFT, pygame.K_RIGHT):
                            d = -1 if k == pygame.K_LEFT else 1
                            # sel 0..5 -> (low/high list, channel, min, max)
                            idx_map = [(0, 0, 0, 179), (1, 0, 0, 179), (0, 1, 0, 255),
                                       (1, 1, 0, 255), (0, 2, 0, 255), (1, 2, 0, 255)]
                            ai, ch, lo, hi = idx_map[self.hsv_sel]
                            with self.tracker.lock:
                                lst = self.tracker.hsv_low if ai == 0 else self.tracker.hsv_high
                                lst[ch] = max(lo, min(hi, lst[ch] + d))
                    elif self.state == "play":
                        if k == pygame.K_q:
                            try:
                                if self.audio_ok:
                                    pygame.mixer.music.stop()
                            except Exception:
                                pass
                            self.music_started = False
                            self.state = "menu"
                    elif self.state == "end":
                        if k in (pygame.K_RETURN, pygame.K_SPACE):
                            self.state = "menu"
            if self.state == "menu":
                if not self.songs:
                    self.songs = beats.ensure_song()
                self.draw_menu()
            elif self.state == "calib":
                self.draw_calibration(st)
            elif self.state == "play":
                self.update_sabers(st, dt)
                self.update_play(dt, st)
                if self.state == "play":  # may have ended mid-update
                    self.draw_play(self.song_time())
            elif self.state == "end":
                self.draw_end()
            self.draw_debug(st)
            self.draw_banner()
            pygame.display.flip()
        self.tracker.stop()
        try:
            if self.audio_ok:
                pygame.mixer.music.stop()
                pygame.mixer.quit()
        except Exception:
            pass
        pygame.quit()


def run():
    Game().run()
