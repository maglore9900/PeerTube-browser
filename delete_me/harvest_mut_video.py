PROD = "engine/server/api/handlers/video.py"
TEST = "tests/active/test_video.py"

MUTATIONS = [
    ("V1-around-the-adapter", '        raw = fetch_bounded(host, path, headers={"accept": "application/json"})',
     '        raw = __import__("data.source_fetch", fromlist=["build_opener"]).build_opener().open(__import__("urllib.request", fromlist=["Request"]).Request(f"https://{host}{path}", headers={"accept": "application/json"}), timeout=4).read()',
     "fetch_instance_json_answers_none"),
    ("V2-cap-lifted", '        raw = fetch_bounded(host, path, headers={"accept": "application/json"})', '        raw = fetch_bounded(host, path, headers={"accept": "application/json"}, max_bytes=10**9)',
     "fetch_instance_json_answers_none"),
]
