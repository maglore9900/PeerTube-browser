"""Encode search queries into the vector space the ANN index was built in.

The batch job embeds video text once, offline. Search has to embed the user's query at
request time, which means the serving process needs the model too - but a process that is
never searched should not pay for it, and a model nobody has used for a quarter of an
hour should not keep its weights resident.

The split that makes this cheap is measured rather than assumed: importing torch and
sentence_transformers costs about four seconds and cannot be undone, while loading the
model from the HuggingFace cache costs about a tenth of a second. So the import happens
once, on the first query that needs it, and only the model is released when idle.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import numpy as np


class QueryEncoder:
    """One lazily loaded sentence-transformer, released after a period of disuse.

    Safe to call from several request threads at once: the model is created under a lock,
    so concurrent first requests produce one load rather than one model each, and callers
    encode through a strong reference handed out under that lock, so an eviction cannot
    free a model that a request is still using.
    """

    def __init__(
        self,
        model_name: str,
        device: str = "cpu",
        idle_seconds: int = 900,
        enabled: bool = True,
    ) -> None:
        """Configure the encoder without loading anything.

        :param model_name: SentenceTransformer name; must match the index's model.
        :param device: Torch device for encoding.
        :param idle_seconds: Release the model after this long unused; 0 keeps it.
        :param enabled: When false, every encode returns None. Used by the startup
            identity gate to serve lexical-only results rather than wrong ones.
        """
        self.model_name = model_name
        self.device = device
        self.idle_seconds = max(0, int(idle_seconds))
        self.enabled = bool(enabled)
        self.disabled_reason: str | None = None if enabled else "not enabled"
        self._lock = threading.Lock()
        self._model: Any = None
        self._last_used = 0.0
        self._reaper: threading.Thread | None = None
        self._stop = threading.Event()

    def disable(self, reason: str) -> None:
        """Turn the encoder off and record why, for the health endpoint and the log."""
        with self._lock:
            self.enabled = False
            self.disabled_reason = reason
            self._model = None
        logging.warning("[query-encoder] disabled: %s", reason)

    @property
    def loaded(self) -> bool:
        """Whether model weights are currently resident."""
        return self._model is not None

    def _acquire_model(self) -> Any:
        """Return a loaded model, loading it if needed, and stamp the use time.

        The caller keeps the returned reference for the duration of its encode, which is
        what makes concurrent eviction safe.
        """
        with self._lock:
            if self._model is None:
                # Imported here, not at module scope: an Engine that is never searched
                # should not pay the multi-second torch import at startup.
                from sentence_transformers import SentenceTransformer

                started = time.monotonic()
                logging.info(
                    "[query-encoder] loading model=%s device=%s",
                    self.model_name,
                    self.device,
                )
                self._model = SentenceTransformer(self.model_name, device=self.device)
                logging.info(
                    "[query-encoder] loaded model=%s in %.2fs",
                    self.model_name,
                    time.monotonic() - started,
                )
                self._start_reaper_locked()
            self._last_used = time.monotonic()
            return self._model

    def _start_reaper_locked(self) -> None:
        """Start the idle-eviction thread once, with the lock already held."""
        if self.idle_seconds <= 0 or self._reaper is not None:
            return
        self._reaper = threading.Thread(
            target=self._reap_loop,
            name="query-encoder-reaper",
            daemon=True,
        )
        self._reaper.start()

    def _reap_loop(self) -> None:
        """Release the model once it has gone unused for the idle window.

        This runs on its own thread because an idle check on the request path could only
        fire when a request arrives, which is precisely when the encoder is not idle.
        """
        interval = max(1.0, min(60.0, self.idle_seconds / 4))
        while not self._stop.wait(interval):
            with self._lock:
                if self._model is None:
                    continue
                idle_for = time.monotonic() - self._last_used
                if idle_for < self.idle_seconds:
                    continue
                self._model = None
            logging.info(
                "[query-encoder] released model=%s after %.0fs idle",
                self.model_name,
                idle_for,
            )

    def encode(self, text: str) -> np.ndarray | None:
        """Return a normalized query vector, or None when the vector half is off.

        :param text: Sanitized query text. Callers cap its length; the model truncates
            beyond its own sequence limit regardless.
        """
        if not self.enabled or not text:
            return None
        model = self._acquire_model()
        vector = model.encode(
            [text],
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        return np.asarray(vector, dtype=np.float32)

    def shutdown(self) -> None:
        """Stop the idle thread and drop the model. Used by tests and shutdown paths."""
        self._stop.set()
        with self._lock:
            self._model = None
