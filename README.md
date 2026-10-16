# Beat Shabber AI

A webcam **Beat Saber clone** in Python, built for a university Computer Vision demo.
Slice beat-synced blocks with light sabers driven by your hands — no headset, no GPU, no training. CPU only.

## How it plays

Blocks fly from the screen's vanishing point toward 4 lanes and land exactly on the beat.
Swing the matching-colour saber **along the arrow** while the block is in its hit window:

- **Left hand → RED saber, Right hand → BLUE saber** (MediaPipe handedness)
- Good cut: +100 × combo multiplier (×1 → ×2 @4 → ×4 @8 → ×8 @16)
- Wrong colour or wrong swipe direction = bad cut · unhit block = miss (resets combo)

## Stack

Python 3.11 · pygame · opencv-python · numpy · librosa · mediapipe 0.10.14 · soundfile · scipy

## Setup

```bash
pip install -r requirements.txt
```

Drop any `.mp3` / `.wav` into `songs/` (optional — a 60 s 120 BPM click track is auto-generated if the folder is empty).

## Run

```bash
python main.py        # single entry point
python test_core.py   # headless tests (no camera/window needed)
```

## Controls

| Key | Action |
|---|---|
| ENTER / SPACE | Start song · back to menu |
| ↑ / ↓ | Select song |
| C | Toggle AI tracking ↔ CLASSIC colour-blob |
| M | Mouse fallback (blue saber) — always playable, camera or not |
| K | Calibration screen (live landmarks / blob mask, HSV tuning) |
| W/S + ←/→ | Select / adjust HSV thresholds (CLASSIC calibration) |
| D | Debug overlay: FPS + camera picture-in-picture |
| Q | Abort song to menu |
| ESC | Quit (camera released, pygame exits cleanly) |

## Tracking modes

- **AI** (default): MediaPipe Hands, 2 hands, `model_complexity=0`. Saber = wrist (landmark 0) → index fingertip (landmark 8), extended 1.5×, EMA-smoothed (α=0.5). Capture + tracking run in a background thread; the render loop never blocks.
- **CLASSIC**: HSV colour-blob tracking (largest contour centroid = saber tip, one saber). Tune the range on the calibration screen.
- **MOUSE**: mouse drives the blue saber. Auto-engaged with an on-screen message if the camera fails.

## Beat sync

`librosa.beat.beat_track` extracts beat times before play (cached to `songs/<file>.beats.json`).
Audio plays via `pygame.mixer.music`; the game clock syncs to `get_pos()`.
Blocks spawn at `beat_time − 1.2 s` and arrive on the beat; every 4th beat spawns a red+blue pair.

## Results & report data

- End screen: score, accuracy, max combo, **TRACKING-LOSS %** (frames with no hand/blob ÷ total).
- `highscores.json` — top-20 scores.
- `results.csv` — `{mode, accuracy, tracking_loss_pct}` appended per song, for the AI-vs-CLASSIC report comparison.

## Project layout

```
main.py        entry point
game.py        pygame loop: menu / calibration / play / end, hit judging, FX
tracking.py    threaded webcam tracking (AI / CLASSIC), normalised coords
beats.py       beat detection + click-track fallback + JSON cache
core.py        pure gameplay math (segment∩rect, swipe angle, scoring) — headless-testable
test_core.py   beat-count (~120 ±10%) + 4 hand-written hit cases
songs/         drop .mp3/.wav here
```

## Robustness

Camera/tracking wrapped in try/except with mouse auto-fallback · no network calls at runtime · clean shutdown on ESC.
