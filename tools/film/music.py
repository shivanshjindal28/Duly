"""Original score and final mix for the launch film (pure numpy synthesis, no samples, no licences).

Reads media/film/timeline.json and the voiceover clips, writes media/film/mix.wav (48 kHz stereo):
music cut to the narration, ducked under the voice, with transition whooshes and a logo impact.

    python tools/film/music.py
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
FILM = ROOT / "media" / "film"
SR = 48_000
rng = np.random.default_rng(7)

TL = json.loads((FILM / "timeline.json").read_text(encoding="utf-8"))
LINES = {l["id"]: l for l in TL["lines"]}
TOTAL = TL["total"]
N = int(TOTAL * SR) + SR


def word(lid: str, w: str, nth: int = 0) -> float:
    ws = [x["t"] for x in LINES[lid]["words"] if x["w"].lower().strip(".,") == w]
    return ws[min(nth, len(ws) - 1)]


def note(name: str) -> float:
    names = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4, "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1, "B": 2}
    n, octv = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((names[n] + (octv - 4) * 12) / 12)


def env_adsr(n: int, a: float, r: float) -> np.ndarray:
    t = np.arange(n) / SR
    e = np.minimum(1, t / max(a, 1e-4))
    rel = np.clip((t[-1] - t) / max(r, 1e-4), 0, 1)
    return e * rel


def fft_lowpass(x: np.ndarray, cutoff: float, slope: float = 4.0) -> np.ndarray:
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / np.sqrt(1 + (f / cutoff) ** (2 * slope))
    return np.fft.irfft(X, len(x))


def fft_highpass(x: np.ndarray, cutoff: float, slope: float = 3.0) -> np.ndarray:
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR) + 1e-6
    X *= 1 / np.sqrt(1 + (cutoff / f) ** (2 * slope))
    return np.fft.irfft(X, len(x))


def add(buf: np.ndarray, sig: np.ndarray, at: float, gain: float = 1.0, pan: float = 0.0) -> None:
    i = int(at * SR)
    if i >= buf.shape[1]:
        return
    sig = sig[: buf.shape[1] - i]
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[0, i:i + len(sig)] += sig * gain * l * 1.414
    buf[1, i:i + len(sig)] += sig * gain * r * 1.414


# ------------------------------------------------------------------ instruments
def pad(freqs: list[float], dur: float, attack: float = 1.6, release: float = 2.2, bright: float = 1400) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for f in freqs:
        for det in (-0.12, 0.0, 0.11):  # detuned saw stack, softened
            ff = f * 2 ** (det / 12)
            ph = (t * ff + rng.random()) % 1.0
            saw = 2 * ph - 1
            out += saw * 0.35 + np.sin(2 * np.pi * ff * t) * 0.65
    out = fft_lowpass(out, bright, 3)
    return out / max(1, len(freqs) * 3) * env_adsr(n, attack, release)


def pluck(f: float, dur: float = 0.9) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    e = np.exp(-t * 5.5)
    s = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 9) + 0.12 * np.sin(2 * np.pi * 3 * f * t) * np.exp(-t * 14))
    return s * e * np.minimum(1, t / 0.004)


def kick(dur: float = 0.5) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 46 + 90 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t * 7.5) * np.minimum(1, t / 0.002)


def shaker(dur: float = 0.08) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    return fft_highpass(rng.standard_normal(n), 6500) * np.exp(-t * 60)


def tick() -> np.ndarray:
    n = int(0.05 * SR)
    t = np.arange(n) / SR
    return fft_highpass(rng.standard_normal(n), 3000) * np.exp(-t * 140) * 0.6


def boom(dur: float = 3.5) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 32 + 40 * np.exp(-t * 6)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 1.4)
    crack = fft_lowpass(rng.standard_normal(n), 900) * np.exp(-t * 9) * 0.5
    return (body + crack) * np.minimum(1, t / 0.003)


def whoosh(dur: float = 1.1, up: bool = True) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    shape = np.sin(np.pi * t / dur) ** 2
    lo = fft_lowpass(noise, 2500, 2) * (t / dur if up else 1 - t / dur)
    return fft_highpass(lo, 300) * shape


def riser(dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    noise = fft_highpass(rng.standard_normal(n), 800) * (t / dur) ** 2.5
    f = 180 * 2 ** (3 * t / dur)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * (t / dur) ** 3 * 0.25
    return noise * 0.5 + tone


def reverb(x: np.ndarray, seconds: float = 2.8, mix: float = 0.35) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.empty_like(x)
    for ch in range(2):
        ir = rng.standard_normal(n) * np.exp(-t * 6.9 / seconds)
        ir = fft_lowpass(ir, 6000, 1.5)
        ir /= np.sqrt(np.sum(ir ** 2))
        size = 1 << int(np.ceil(np.log2(len(x[ch]) + n)))
        wet = np.fft.irfft(np.fft.rfft(x[ch], size) * np.fft.rfft(ir, size), size)[: len(x[ch])]
        out[ch] = x[ch] * (1 - mix) + wet * mix * 1.6
    return out


# ------------------------------------------------------------------ the score
music = np.zeros((2, N))
fx = np.zeros((2, N))
DULY = word("intro", "duly")
GROOVE = LINES["reads"]["start"] - 0.4
END_HIT = word("close", "duly")
BEAT = 60 / 96

# 1. tension: drone + ticking pulse + heartbeat, riser into the logo
drone = pad([note("D2"), note("A2"), note("D3")], DULY + 0.4, attack=2.5, release=0.6, bright=520)
add(music, drone, 0.0, 0.9)
for k in range(int((DULY - 1.0) / BEAT)):
    add(music, tick(), 0.4 + k * BEAT, 0.16 + 0.10 * (k % 2 == 0), pan=0.3 if k % 2 else -0.3)
for k in range(int((DULY - 6.0) / (2 * BEAT))):
    add(music, kick(0.45), 6.0 + k * 2 * BEAT, 0.28)
add(fx, riser(3.6), DULY - 3.6, 0.55)

# 2. logo impact + shimmer chord
add(fx, boom(), DULY - 0.02, 1.35)
shimmer = pad([note("D4"), note("F#4"), note("A4"), note("E5"), note("A5")], 6.5, attack=0.05, release=4.5, bright=5200)
add(music, shimmer, DULY - 0.02, 0.85)

# 3. groove: chord progression every 2 bars, plucked arpeggios, kick + shaker that build
prog = [["D3", "F#3", "A3", "C#4", "E4"], ["B2", "D3", "F#3", "A3", "D4"], ["G2", "B2", "D3", "F#3", "A3"], ["A2", "C#3", "E3", "G3", "B3"]]
bar2 = 8 * BEAT
t = GROOVE
i = 0
while t < END_HIT - 0.3:
    chord = prog[i % 4]
    dur = min(bar2 + 1.5, END_HIT - t + 1.0)
    add(music, pad([note(c) for c in chord], dur, attack=1.2, release=1.6, bright=1600), t, 0.55)
    add(music, pad([note(chord[0][:-1] + str(int(chord[0][-1]) - 1))], dur, attack=0.6, release=1.0, bright=300), t, 0.5)
    arp = [chord[1], chord[2], chord[3], chord[4], chord[3], chord[2], chord[4], chord[3]]
    for k in range(16):
        tt = t + k * BEAT / 2
        if tt >= END_HIT - 0.4:
            break
        nn = arp[k % 8]
        add(music, pluck(note(nn[:-1] + str(int(nn[-1]) + 1))), tt, 0.13 + 0.05 * (k % 4 == 0), pan=-0.35 if k % 2 else 0.35)
    i += 1
    t += bar2
KICK_FROM = LINES["decides"]["start"] - 0.2
SHAKE_FROM = LINES["fraud"]["start"] - 0.2
b = GROOVE
k = 0
while b < END_HIT - 0.5:
    if b >= KICK_FROM and k % 2 == 0:
        add(music, kick(), b, 0.42)
    if b >= SHAKE_FROM:
        for s in range(4):
            add(music, shaker(), b + s * BEAT / 4, 0.05 + 0.03 * (s == 2), pan=0.2)
    b += BEAT
    k += 1

# transitions
for lid in ["reads", "decides", "rules", "fraud", "pays", "suppliers", "audit"]:
    add(fx, whoosh(1.0), LINES[lid]["start"] - 0.75, 0.22, pan=-0.2)

# 4. resolve: final chord + soft boom on the closing "Duly"
add(fx, boom(4.5), END_HIT - 0.02, 0.6)
final = pad([note("D3"), note("A3"), note("D4"), note("F#4"), note("A4"), note("E5")], TOTAL - END_HIT + 0.5, attack=0.08, release=4.0, bright=4200)
add(music, final, END_HIT - 0.02, 1.25)

music = reverb(music, 3.2, 0.38)
fx = reverb(fx, 2.2, 0.25)
bed = music + fx * 0.9
bed /= np.max(np.abs(bed)) + 1e-9

# ------------------------------------------------------------------ voice: decode, place, duck the music under it
ff = imageio_ffmpeg.get_ffmpeg_exe()
voice = np.zeros(N)
for l in TL["lines"]:
    raw = subprocess.run([ff, "-v", "error", "-i", str(FILM / "vo" / f"{l['id']}.mp3"), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    v = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    i0 = int(l["start"] * SR)
    voice[i0:i0 + len(v)] += v[: N - i0]
voice = fft_highpass(voice, 80, 2)
voice /= np.max(np.abs(voice)) + 1e-9

win = int(0.05 * SR)
rms = np.sqrt(np.convolve(voice ** 2, np.ones(win) / win, mode="same"))
active = (rms > 0.02).astype(float)
# smooth: fast attack, slow release
duck = np.zeros(N)
acc = 0.0
att, rel = 1 - np.exp(-1 / (0.04 * SR / 64)), 1 - np.exp(-1 / (0.45 * SR / 64))
for j in range(0, N, 64):
    target = active[j]
    acc += (target - acc) * (att if target > acc else rel)
    duck[j:j + 64] = acc
gain = 10 ** (-13 * duck / 20)  # up to -13 dB under the voice

mix = np.stack([bed[0] * 0.85 * gain + voice * 0.80, bed[1] * 0.85 * gain + voice * 0.80])
# fades + soft limiter
fade_in = np.minimum(1, np.arange(N) / (0.6 * SR))
fade_out = np.clip((TOTAL * SR - np.arange(N)) / (1.6 * SR), 0, 1)
mix *= fade_in * fade_out
mix = np.tanh(mix * 1.15) / np.tanh(1.15)
mix /= np.max(np.abs(mix)) / 0.95
mix = mix[:, : int(TOTAL * SR)]

out = FILM / "mix.wav"
pcm = (np.clip(mix.T, -1, 1) * 32767).astype("<i2")
import wave

with wave.open(str(out), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print(f"mix: {out} ({TOTAL:.1f}s)")
