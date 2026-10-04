"""Run the worker's VAD over a media URL's whole audio: what the job saw, per 30 s window and at lower thresholds."""
import subprocess
import sys

import numpy as np
from faster_whisper.vad import VadOptions, get_speech_timestamps

url = sys.argv[1]
pcm = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", url, "-vn", "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1"], capture_output=True, check=True).stdout
audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
print(f"seconds={len(audio) / 16000:.1f} rms={float(np.sqrt(np.mean(audio ** 2))):.4f}")
for threshold in (0.5, 0.35, 0.2):
    spans = get_speech_timestamps(audio, VadOptions(threshold=threshold, min_silence_duration_ms=500, speech_pad_ms=200))
    speech = sum(s["end"] - s["start"] for s in spans) / 16000
    print(f"threshold={threshold} spans={len(spans)} speech_s={speech:.1f}")
window = 30 * 16000
per_window = [len(get_speech_timestamps(audio[i:i + window], VadOptions(min_silence_duration_ms=500, speech_pad_ms=200))) for i in range(0, len(audio), window)]
print("per_30s_window_spans(default)=", per_window)
