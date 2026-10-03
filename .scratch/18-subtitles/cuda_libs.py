"""Preload the pip-installed cuBLAS/cuDNN so CTranslate2 finds them without LD_LIBRARY_PATH."""
import ctypes
import glob
import os
import sys


def preload() -> None:
    site = next(p for p in sys.path if p.endswith("site-packages"))
    names = [
        "nvidia/cublas/lib/libcublasLt.so.12",
        "nvidia/cublas/lib/libcublas.so.12",
        "nvidia/cudnn/lib/libcudnn.so.9",
    ]
    # cuDNN 9 dlopens its sub-libraries by soname, so they must be resident too.
    names += [os.path.relpath(p, site) for p in sorted(glob.glob(os.path.join(site, "nvidia/cudnn/lib/libcudnn_*.so.9")))]
    for name in names:
        ctypes.CDLL(os.path.join(site, name), mode=ctypes.RTLD_GLOBAL)
