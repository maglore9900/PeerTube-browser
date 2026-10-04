"""Install check for plan 49: the Engine's query encoder still loads and encodes in engine/.pixi after faster-whisper."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / "engine/server"), str(root / "engine/server/api")]

from data.query_encoder import QueryEncoder  # noqa: E402
from server_config import QUERY_ENCODER_DEVICE, QUERY_ENCODER_MODEL  # noqa: E402

import huggingface_hub, numpy, tokenizers, torch, transformers  # noqa: E401,E402

encoder = QueryEncoder(QUERY_ENCODER_MODEL, QUERY_ENCODER_DEVICE, idle_seconds=0)
vector = encoder.encode("vidéos de cuisine en français")
print("encoder", QUERY_ENCODER_MODEL, QUERY_ENCODER_DEVICE, "-> dim", None if vector is None else vector.shape)
print("versions: transformers", transformers.__version__, "hub", huggingface_hub.__version__,
      "tokenizers", tokenizers.__version__, "numpy", numpy.__version__, "torch", torch.__version__)
