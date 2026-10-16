"""Background-thread webcam tracking: AI (MediaPipe Hands) / CLASSIC (HSV blob).

The game loop never blocks: it calls get_state() for the latest result.
All camera/tracking code is wrapped in try/except; on failure the tracker
reports camera_ok=False and the game auto-switches to mouse mode.
Coordinates are NORMALISED (0..1, mirrored) so the game can scale to any window.
"""
import threading
import time

import numpy as np

CAM_W, CAM_H = 640, 360
EMA_ALPHA = 0.5

# Default HSV range for CLASSIC blob mode (tune on calibration screen).
DEFAULT_HSV_LOW = [90, 80, 80]
DEFAULT_HSV_HIGH = [130, 255, 255]


class Tracker:
    def __init__(self, mode="AI"):
        self.mode = mode  # "AI" | "CLASSIC" | "MOUSE"
        self.lock = threading.Lock()
        self.running = False
        self.thread = None
        self.camera_ok = False
        self.message = ""
        # Normalised tips/bases (or None): red = Left hand, blue = Right hand.
        self.red_tip = None
        self.blue_tip = None
        self.red_base = None
        self.blue_base = None
        self.red_found = False
        self.blue_found = False
        self.landmarks = []  # [({"points": [(nx,ny)...], "hand": "Left"/"Right"})]
        self.pip_frame = None  # small BGR frame (mirrored, annotated) for PiP/calibration
        self.mask_frame = None  # small binary mask (CLASSIC mode)
        self.hsv_low = list(DEFAULT_HSV_LOW)
        self.hsv_high = list(DEFAULT_HSV_HIGH)
        # Tracking-loss stats (reset per song by game).
        self.total_frames = 0
        self.lost_frames = 0

    # ---------------- lifecycle ----------------
    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=2.0)
            self.thread = None

    def reset_stats(self):
        with self.lock:
            self.total_frames = 0
            self.lost_frames = 0

    def tracking_loss_pct(self):
        with self.lock:
            if self.total_frames <= 0:
                return 0.0
            return 100.0 * self.lost_frames / self.total_frames

    def get_state(self):
        with self.lock:
            return {
                "mode": self.mode,
                "camera_ok": self.camera_ok,
                "message": self.message,
                "red_tip": self.red_tip,
                "blue_tip": self.blue_tip,
                "red_base": self.red_base,
                "blue_base": self.blue_base,
                "red_found": self.red_found,
                "blue_found": self.blue_found,
                "landmarks": [dict(h) for h in self.landmarks],
                "pip_frame": None if self.pip_frame is None else self.pip_frame.copy(),
                "mask_frame": None if self.mask_frame is None else self.mask_frame.copy(),
                "hsv_low": list(self.hsv_low),
                "hsv_high": list(self.hsv_high),
            }

    # ---------------- internals ----------------
    def _loop(self):
        try:
            import cv2
        except Exception as e:
            with self.lock:
                self.camera_ok = False
                self.message = "OpenCV import failed: %s (press M for mouse)" % e
            return
        cap = None
        try:
            cap = cv2.VideoCapture(0)
            if cap is not None:
                try:
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
                except Exception:
                    pass
            if cap is None or not cap.isOpened():
                with self.lock:
                    self.camera_ok = False
                    self.message = "No camera found — mouse mode (M)"
                return
            with self.lock:
                self.camera_ok = True
                self.message = ""
        except Exception as e:
            with self.lock:
                self.camera_ok = False
                self.message = "Camera error: %s (press M for mouse)" % e
            return

        hands = None
        try:
            if self.mode != "MOUSE":
                hands = self._init_hands()
        except Exception:
            hands = None

        ema = {"red": None, "blue": None}
        while self.running:
            try:
                if self.mode == "MOUSE":
                    time.sleep(0.05)
                    continue
                ok, frame = cap.read()
                if not ok or frame is None:
                    time.sleep(0.02)
                    continue
                try:
                    frame = cv2.resize(frame, (CAM_W, CAM_H))
                except Exception:
                    pass
                frame = cv2.flip(frame, 1)  # mirrored
                if self.mode == "AI":
                    if hands is None:
                        try:
                            hands = self._init_hands()
                        except Exception:
                            hands = None
                    self._process_ai(frame, hands, ema)
                else:
                    self._process_classic(frame, ema)
            except Exception as e:
                with self.lock:
                    self.message = "Tracking error: %s" % e
                time.sleep(0.05)
        try:
            if hands is not None:
                hands.close()
        except Exception:
            pass
        try:
            if cap is not None:
                cap.release()
        except Exception:
            pass

    def _init_hands(self):
        import mediapipe as mp
        return mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            model_complexity=0,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def _smooth(self, ema, key, pt):
        prev = ema.get(key)
        if prev is None or pt is None:
            ema[key] = pt
            return pt
        sm = (EMA_ALPHA * pt[0] + (1 - EMA_ALPHA) * prev[0],
              EMA_ALPHA * pt[1] + (1 - EMA_ALPHA) * prev[1])
        ema[key] = sm
        return sm

    def _store_pip(self, frame, draw_landmarks=True, landmarks_px=None):
        try:
            import cv2
            small = cv2.resize(frame, (213, 120))
            if draw_landmarks and landmarks_px:
                for pts in landmarks_px:
                    for (x, y) in pts:
                        sx = int(x * 213 / CAM_W)
                        sy = int(y * 120 / CAM_H)
                        cv2.circle(small, (sx, sy), 2, (0, 255, 0), -1)
            with self.lock:
                self.pip_frame = small
        except Exception:
            pass

    def _process_ai(self, frame, hands, ema):
        import cv2
        red_tip = blue_tip = red_base = blue_base = None
        red_found = blue_found = False
        lm_draw = []
        try:
            if hands is not None:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                res = hands.process(rgb)
                if res and res.multi_hand_landmarks:
                    handed = []
                    try:
                        handed = [h.classification[0].label for h in res.multi_handedness]
                    except Exception:
                        handed = ["Right"] * len(res.multi_hand_landmarks)
                    for lm, label in zip(res.multi_hand_landmarks, handed):
                        pts = [(p.x * CAM_W, p.y * CAM_H) for p in lm.landmark]
                        lm_draw.append(pts)
                        try:
                            wx, wy = pts[0]
                            tx, ty = pts[8]
                            # Saber: wrist -> fingertip, extended 1.5x beyond fingertip.
                            ex = wx + (tx - wx) * 1.5
                            ey = wy + (ty - wy) * 1.5
                            tip = (ex / CAM_W, ey / CAM_H)
                            base = (wx / CAM_W, wy / CAM_H)
                        except Exception:
                            continue
                        norm = [(x / CAM_W, y / CAM_H) for (x, y) in pts]
                        with self.lock:
                            self.landmarks = self.landmarks  # no-op, replaced below
                        if label == "Left":
                            red_tip = self._smooth(ema, "red", tip)
                            red_base = base
                            red_found = True
                            color = "red"
                        else:
                            blue_tip = self._smooth(ema, "blue", tip)
                            blue_base = base
                            blue_found = True
                            color = "blue"
                        # Draw saber line on frame for PiP.
                        try:
                            cv2.line(frame, (int(wx), int(wy)), (int(ex), int(ey)),
                                     (0, 0, 255) if color == "red" else (255, 0, 0), 3)
                        except Exception:
                            pass
                        self._last_norm = (norm, label) if not hasattr(self, "_last_norm") else getattr(self, "_last_norm", None)
        except Exception:
            pass
        # Rebuild normalised landmark list for calibration screen.
        norm_lms = []
        try:
            for pts in lm_draw:
                norm_lms.append({"points": [(x / CAM_W, y / CAM_H) for (x, y) in pts], "hand": ""})
        except Exception:
            norm_lms = []
        found_any = red_found or blue_found
        with self.lock:
            self.red_tip, self.blue_tip = red_tip, blue_tip
            self.red_base, self.blue_base = red_base, blue_base
            self.red_found, self.blue_found = red_found, blue_found
            self.landmarks = norm_lms
            self.total_frames += 1
            if not found_any:
                self.lost_frames += 1
        self._store_pip(frame, True, lm_draw)

    def _process_classic(self, frame, ema):
        import cv2
        with self.lock:
            low = np.array(self.hsv_low, dtype=np.uint8)
            high = np.array(self.hsv_high, dtype=np.uint8)
        tip = None
        found = False
        try:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, low, high)
            kernel = np.ones((5, 5), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                c = max(contours, key=cv2.contourArea)
                if cv2.contourArea(c) > 300:
                    M = cv2.moments(c)
                    if M["m00"] > 0:
                        cx = M["m10"] / M["m00"]
                        cy = M["m01"] / M["m00"]
                        tip = self._smooth(ema, "blue", (cx / CAM_W, cy / CAM_H))
                        found = True
                        cv2.circle(frame, (int(cx), int(cy)), 8, (255, 0, 0), -1)
                        cv2.drawContours(frame, [c], -1, (0, 255, 0), 2)
            with self.lock:
                self.mask_frame = cv2.resize(mask, (213, 120))
        except Exception:
            pass
        with self.lock:
            # CLASSIC: one saber only -> expose as BLUE saber.
            self.blue_tip = tip
            self.blue_base = None
            self.blue_found = found
            self.red_tip = None
            self.red_base = None
            self.red_found = False
            self.landmarks = []
            self.total_frames += 1
            if not found:
                self.lost_frames += 1
        self._store_pip(frame, False, None)
