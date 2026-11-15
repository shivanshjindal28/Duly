# Duly launch film

A 78-second, 1080p60 launch film with a Microsoft neural narrator and an original score, rendered from the real app.

```bash
pip install edge-tts imageio-ffmpeg           # dev-only tools (not app requirements)
python tools/film/voice.py                    # voiceover + word timings  -> media/film/vo, timeline.json (sends script.json text to Microsoft TTS)
node tools/film/shots.mjs                     # stage features on a fresh demo DB, capture 2x/3x product shots -> media/film/shots
node tools/film/render.mjs stills 16 36 52    # review chosen moments    -> media/film/stills
node tools/film/render.mjs frames 60          # every frame, deterministic -> media/film/frames
python tools/film/music.py                    # original score, ducked under the voice -> media/film/mix.wav
python tools/film/encode.py                   # -> media/duly-launch-film.mp4
```

- `film.html` is the whole film as `render(t)`: every position, opacity and blur is a function of time, and cues
  are taken from the narrator's word timestamps, so changing the script re-times the visuals automatically.
- Edit the words in `script.json` (voice, pace, pitch, pauses), then re-run the steps above.
- Output in `media/` is git-ignored.
