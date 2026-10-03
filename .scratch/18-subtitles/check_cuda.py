"""Smoke check: CTranslate2 sees the GPU and a tiny Whisper model runs translate on it."""
import cuda_libs

cuda_libs.preload()

import ctranslate2  # noqa: E402
import numpy as np  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402

print("ctranslate2", ctranslate2.__version__, "cuda devices", ctranslate2.get_cuda_device_count())
print("cuda compute types", sorted(ctranslate2.get_supported_compute_types("cuda")))
model = WhisperModel("tiny", device="cuda", compute_type="int8_float16")
audio = (np.random.randn(16000 * 5) * 0.01).astype(np.float32)
segments, info = model.transcribe(audio, task="translate")
print("ran on cuda; detected", info.language, [s.text for s in segments])
