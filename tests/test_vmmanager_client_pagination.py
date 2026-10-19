import importlib.util
from pathlib import Path


CLIENT_PATH = Path(__file__).parents[1] / "module/sources/vmmanager/client.py"
spec = importlib.util.spec_from_file_location("vmmanager_client_test_module", CLIENT_PATH)
client_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client_module)


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, collections):
        self.collections = collections
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append(url)
        if "auth/v4/public/token" in url:
            return FakeResponse({"token": "test-token"})
        path = url.split("/vm/v3/", 1)[1].split("?", 1)[0]
        offset, count = map(int, url.split("limit=", 1)[1].split("&", 1)[0].split(","))
        items = self.collections[path]
        return FakeResponse({"list": items[offset:offset + count], "size": len(items)})


def test_all_inventory_endpoints_are_paginated_and_complete():
    session = FakeSession({
        "host": [{"id": 1}, {"id": 2}, {"id": 3}],
        "cluster": [{"id": 10}, {"id": 11}],
        "node": [{"id": 20}],
    })
    client = client_module.VMmanagerClient("https://vmmanager.test", "user", "pass", session=session)
    assert [x["id"] for x in client.get_hosts(page_size=2)] == [1, 2, 3]
    assert [x["id"] for x in client.get_clusters(page_size=1)] == [10, 11]
    assert [x["id"] for x in client.get_nodes(page_size=1)] == [20]


def test_incomplete_snapshot_is_rejected():
    class BadSession(FakeSession):
        def request(self, method, url, **kwargs):
            if "auth/v4/public/token" in url:
                return FakeResponse({"token": "test-token"})
            offset = int(url.split("limit=", 1)[1].split(",", 1)[0])
            return FakeResponse({"list": [{"id": 1}] if offset == 0 else [], "size": 2})

    client = client_module.VMmanagerClient("https://vmmanager.test", "user", "pass", session=BadSession({}))
    try:
        client.get_nodes(page_size=10)
    except client_module.VMmanagerAPIError as exc:
        assert "incomplete" in str(exc)
    else:
        raise AssertionError("incomplete snapshot should be rejected")
