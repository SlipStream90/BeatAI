"""Song handling: beat detection (librosa, cached to JSON) + demo click-track fallback."""
import json
import os

import numpy as np

SONGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "songs")
CACHE_SUFFIX = ".beats.json"
SUPPORTED_EXTS = (".mp3", ".wav", ".ogg", ".flac")


def list_songs():
    try:
        files = sorted(f for f in os.listdir(SONGS_DIR)
                       if f.lower().endswith(SUPPORTED_EXTS))
    except OSError:
        files = []
    return [os.path.join(SONGS_DIR, f) for f in files]


def generate_click_track(path, bpm=120.0, seconds=60.0, sr=22050):
    """Generate a click track (sharp attacks librosa can beat-track) and save as wav."""
    n = int(sr * seconds)
    audio = np.zeros(n, dtype=np.float32)
    beat_every = int(sr * 60.0 / bpm)
    click_len = int(sr * 0.05)  # 50 ms click
    t = np.arange(click_len, dtype=np.float32) / sr
    # 1 kHz sine burst with exponential decay = sharp onset.
    click = (0.9 * np.sin(2 * np.pi * 1000.0 * t) * np.exp(-t * 90.0)).astype(np.float32)
    for start in range(0, n, beat_every):
        end = min(start + click_len, n)
        audio[start:end] += click[:end - start]
    # Normalise to avoid clipping.
    peak = float(np.max(np.abs(audio)))
    if peak > 0:
        audio = (audio / peak * 0.9).astype(np.float32)
    try:
        import soundfile as sf
        sf.write(path, audio, sr)
    except Exception:
        # Fallback: PCM wav via stdlib.
        import wave
        pcm = (audio * 32767).astype(np.int16)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
    return path


def ensure_song():
    """Return a playable song path; generate demo click track if songs/ is empty."""
    os.makedirs(SONGS_DIR, exist_ok=True)
    songs = list_songs()
    if songs:
        return songs
    demo = os.path.join(SONGS_DIR, "demo.wav")
    if not os.path.exists(demo):
        generate_click_track(demo)
    return [demo]


def get_beat_times(song_path):
    """Beat times in seconds, cached to <song>.beats.json next to the song."""
    cache = song_path + CACHE_SUFFIX
    if os.path.exists(cache):
        try:
            with open(cache, "r") as f:
                data = json.load(f)
            times = [float(t) for t in data.get("beats", [])]
            if times:
                return times, float(data.get("tempo", 120.0))
        except Exception:
            pass
    import librosa
    y, sr = librosa.load(song_path, sr=22050, mono=True)
    try:
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="frames")
        tempo = float(tempo.item() if hasattr(tempo, "item") else tempo)
        times = librosa.frames_to_time(beats, sr=sr).tolist()
    except Exception:
        # Total fallback: assume 120 BPM from 0.
        dur = len(y) / float(sr)
        tempo = 120.0
        times = [i * 0.5 for i in range(int(dur / 0.5))]
    times = [float(t) for t in times]
    try:
        with open(cache, "w") as f:
            json.dump({"tempo": tempo, "beats": times}, f)
    except Exception:
        pass
    return times, tempo


def audio_duration(song_path):
    try:
        import librosa
        return float(librosa.get_duration(path=song_path))
    except Exception:
        return 60.0
