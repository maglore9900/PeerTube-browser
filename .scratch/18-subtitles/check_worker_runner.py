"""Install check for plan 49: the worker's own WhisperRunner (VAD + translate) on CUDA in engine/.pixi."""
import importlib.util
import os
import random
import struct
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("translate_worker", root / "engine/server/db/jobs/translate-worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

random.seed(0)
pcm = struct.pack("<%dh" % (16000 * 5), *(random.randint(-300, 300) for _ in range(16000 * 5)))

runner = worker.WhisperRunner()
print("speech spans:", runner.speech(pcm))
t0 = time.monotonic()
segments, language = runner.transcribe(pcm, None)
print(f"transcribe ok in {time.monotonic() - t0:.1f} s on {worker.MODEL_NAME}/{worker.COMPUTE_TYPE}: language={language} segments={segments}")
import ctranslate2  # noqa: E402

print("ctranslate2", ctranslate2.__version__, "cuda devices", ctranslate2.get_cuda_device_count(), "pid", os.getpid())
runner.unload()
print("unloaded; python", sys.version.split()[0])
