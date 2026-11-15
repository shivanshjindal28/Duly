"""Encode the rendered frames + final mix into media/duly-launch-film.mp4 (1080p60 H.264, AAC 256k).

    python tools/film/encode.py
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[2]
FILM = ROOT / "media" / "film"
fps = (FILM / "frames" / "fps.txt").read_text().strip()
out = ROOT / "media" / "duly-launch-film.mp4"
subprocess.run([
    imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
    "-framerate", fps, "-i", str(FILM / "frames" / "%06d.jpg"),
    "-i", str(FILM / "mix.wav"),
    "-vf", "scale=in_range=pc:out_range=tv,format=yuv420p", "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
    "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-profile:v", "high",
    "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", str(out),
], check=True)
print(f"{out} ({out.stat().st_size / 1e6:.1f} MB)")
