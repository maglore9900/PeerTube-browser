import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from conftest import client_server  # noqa: E402
from lib import engine_api_client  # noqa: E402


def test_probe():
    print("same", client_server.REQUEST_CONTEXT is engine_api_client.REQUEST_CONTEXT)
    print("outside", engine_api_client.bridge_headers())
    engine_api_client.REQUEST_CONTEXT.request_id = "abc"
    print("inside", engine_api_client.bridge_headers(), engine_api_client.request_id_headers())
    del engine_api_client.REQUEST_CONTEXT.request_id
