"""Probe for plan 53 phase 1: str() of the errors the checkpoint raises at open, and of a write to a closed pipe."""
import io
import ssl
import urllib.error


def test_probe():
    for exc in (urllib.error.URLError(ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")), TimeoutError("timed out"), ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number")):
        print(type(exc).__name__, isinstance(exc, OSError), repr(str(exc)))
    closed = io.BytesIO()
    closed.close()
    try:
        closed.write(b"x")
    except ValueError as exc:
        print("closed write:", repr(f"media download failed: {exc}"))
    assert False, "probe"
