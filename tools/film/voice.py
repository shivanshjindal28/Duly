"""Voice the launch-film script line by line (Microsoft neural TTS via edge-tts), then measure each line.

Writes media/film/vo/<id>.mp3 and media/film/timeline.json: start / end of every line on the film's clock
(lead-in + each line + its pause). The visuals and the music are cut to this timeline.

    python tools/film/voice.py
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import edge_tts
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "media" / "film"
LEAD_IN = 1.2  # seconds of picture and music before the first word


def duration(path: Path) -> float:
    """Length of an audio file in seconds (decoded by ffmpeg, so it is exact)."""
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out = subprocess.run([ff, "-i", str(path), "-f", "null", "-"], capture_output=True, text=True).stderr
    t = [l for l in out.splitlines() if "time=" in l][-1].split("time=")[1].split()[0]
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


async def main() -> None:
    script = json.loads((ROOT / "tools" / "film" / "script.json").read_text(encoding="utf-8"))
    (OUT / "vo").mkdir(parents=True, exist_ok=True)
    t = LEAD_IN
    timeline = []
    for line in script["lines"]:
        mp3 = OUT / "vo" / f"{line['id']}.mp3"
        com = edge_tts.Communicate(line["text"], script["voice"], rate=script["rate"], pitch=script["pitch"],
                                   boundary="WordBoundary")
        words, audio = [], bytearray()
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
            elif chunk["type"] == "WordBoundary":  # offsets in 100 ns units
                words.append({"w": chunk["text"], "t": round(t + chunk["offset"] / 1e7, 3)})
        mp3.write_bytes(bytes(audio))
        d = duration(mp3)
        timeline.append({"id": line["id"], "text": line["text"], "start": round(t, 3), "end": round(t + d, 3), "words": words})
        print(f"{line['id']:10s} {t:6.2f} -> {t + d:6.2f}  ({d:.2f}s)")
        t += d + line["gap_after"]
    (OUT / "timeline.json").write_text(json.dumps({"total": round(t, 3), "lines": timeline}, indent=2), encoding="utf-8")
    print(f"total {t:.1f}s")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
