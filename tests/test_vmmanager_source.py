# -*- coding: utf-8 -*-
"""Unit tests for the VMmanager 6 source and API client."""
from urllib.parse import parse_qs, urlparse

import pytest

from module.common.logging import get_logger
from module.netbox.inventory import (
    NBCluster, NBDevice, NBDeviceRole, NBDeviceType, NBManufacturer,
    NBVM, NBSite, NBClusterType,
)
from module.sources.vmmanager.client import VMmanagerAPIError, VMmanagerClient
from module.sources.vmmanager.connection import VMmanagerHandler


class FakeResponse:
    def __init__(self, payload, status_code=200, invalid_json=False):
        self.payload = payload
        self.status_code = status_code
        self.invalid_json = invalid_json

    def json(self):
        if self.invalid_json:
            raise ValueError("not JSON")
        return self.payload


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        parsed = urlparse(url)
        key = (method, parsed.path, parse_qs(parsed.query).get("limit", [None])[0])
        route = self.routes.get(key)
        if route is None:
            raise AssertionError(f"Unexpected request: {key}")
        if isinstance(route, list):
            route = route.pop(0)
        return route

    def close(self):
        self.closed = True


def test_client_authenticates_and_reads_all_pages():
    session = FakeSession({
        ("POST", "/auth/v4/public/token", None): FakeResponse({"token": "test-token"}),
        ("GET", "/vm/v3/host", "0,2"): FakeResponse({"size": 3, "list": [{"id": 1}, {"id": 2}]}),
        ("GET", "/vm/v3/host", "2,2"): FakeResponse({"size": 3, "list": [{"id": 3}]}),
    })
    client = VMmanagerClient("https://vmm.example/", "reader@example.org", "secret", session=session)

    assert client.get_hosts(page_size=2) == [{"id": 1}, {"id": 2}, {"id": 3}]
    get_calls = [call for call in session.calls if call[0] == "GET"]
    assert len(get_calls) == 2
    assert all(call[2]["headers"]["x-xsrf-token"] == "test-token" for call in get_calls)
    assert session.calls[0][2]["json"] == {"email": "reader@example.org", "password": "secret"}


def test_client_rejects_duplicate_ids_across_pages():
    session = FakeSession({
        ("POST", "/auth/v4/public/token", None): FakeResponse({"token": "token"}),
        ("GET", "/vm/v3/disk", "0,1"): FakeResponse({"size": 2, "list": [{"id": 7}]}),
        ("GET", "/vm/v3/disk", "1,1"): FakeResponse({"size": 2, "list": [{"id": 7}]}),
    })
    client = VMmanagerClient("https://vmm.example", "reader", "secret", session=session)

    with pytest.raises(VMmanagerAPIError, match="duplicate disk IDs"):
        client.get_disks(page_size=1)


def test_client_rejects_item_without_id():
    session = FakeSession({
        ("POST", "/auth/v4/public/token", None): FakeResponse({"token": "token"}),
        ("GET", "/vm/v3/node", "0,50"): FakeResponse({"size": 1, "list": [{"name": "node-1"}]}),
    })
    client = VMmanagerClient("https://vmm.example", "reader", "secret", session=session)

    with pytest.raises(VMmanagerAPIError, match="without an ID"):
        client.get_nodes()


def test_client_reports_api_http_errors():
    session = FakeSession({
        ("POST", "/auth/v4/public/token", None): FakeResponse({"token": "token"}),
        ("GET", "/vm/v3/cluster", "0,50"): FakeResponse({"error": {"msg": "forbidden"}}, status_code=403),
    })
    client = VMmanagerClient("https://vmm.example", "reader", "secret", session=session)

    with pytest.raises(VMmanagerAPIError, match="HTTP 403"):
        client.get_clusters()


def _handler(inventory):
    handler = object.__new__(VMmanagerHandler)
    handler.inventory = inventory
    handler.name = "vmmanager-test"
    handler.source_tag = "Source: vmmanager-test"
    handler.log = get_logger()
    return handler


def test_disk_sizes_are_imported_and_vm_total_updated_only_when_totals_match(inventory):
    handler = _handler(inventory)
    site = inventory.add_update_object(NBSite, data={"name": "site-a"}, source=handler)
    cluster_type = inventory.add_update_object(NBClusterType, data={"name": "VMmanager"}, source=handler)
    cluster = inventory.add_update_object(NBCluster, data={"name": "cluster-a", "type": cluster_type,
        "scope_type": "dcim.site", "scope_id": site}, source=handler)
    vm = inventory.add_update_object(NBVM, data={"name": "vm-a", "cluster": cluster, "disk": 123}, source=handler)
    host = {"id": 42, "total_disks_size_mib": 1000,
            "disks": [{"id": 1}, {"id": 2}]}
    source_disks = [
        {"id": 1, "host": {"id": 42}, "target_dev": "vda", "size_mib": 600},
        {"id": 2, "host": {"id": 42}, "target_dev": "vdb", "size_mib": 400},
        # A disk belonging to another VM must not be assigned to this VM.
        {"id": 3, "host": {"id": 99}, "target_dev": "vdc", "size_mib": 900},
    ]

    handler._sync_disks(vm, host, source_disks=source_disks)

    disks = vm.get_virtual_disks()
    assert {disk.data["name"]: disk.data["size"] for disk in disks} == {"vm-a-vda": 600, "vm-a-vdb": 400}
    assert vm.data["disk"] == 1000


def test_inconsistent_disk_snapshot_does_not_overwrite_vm_total(inventory):
    handler = _handler(inventory)
    vm = inventory.add_update_object(NBVM, data={"name": "vm-b", "disk": 777}, source=handler)
    host = {"id": 50, "total_disks_size_mib": 1000, "disks": [{"id": 10}]}
    source_disks = [{"id": 10, "host": {"id": 50}, "target_dev": "vda", "size_mib": 900}]

    handler._sync_disks(vm, host, source_disks=source_disks)

    assert vm.data["disk"] == 777


def test_existing_hypervisor_hardware_identity_is_preserved(inventory):
    handler = _handler(inventory)
    site = inventory.add_update_object(NBSite, data={"name": "site-hw"}, source=handler)
    manufacturer = inventory.add_update_object(NBManufacturer,
        data={"name": "Dell", "slug": "dell"}, source=handler)
    device_type = inventory.add_update_object(NBDeviceType,
        data={"model": "PowerEdge R750", "slug": "poweredge-r750", "manufacturer": manufacturer}, source=handler)
    role = inventory.add_update_object(NBDeviceRole,
        data={"name": "Hypervisor", "slug": "hypervisor", "color": "607d8b", "vm_role": False}, source=handler)
    device = inventory.add_update_object(NBDevice, data={
        "name": "hv-01", "site": site, "device_type": device_type, "device_role": role,
        "serial": "REAL-SERIAL-123", "asset_tag": "ASSET-456", "description": "Curated inventory record",
    }, source=handler)

    handler._sync_node({"id": 901, "name": "hv-01", "state": "active"}, site, {},
                       device_type, role, {})

    assert device.data["device_type"] is device_type
    assert device.data["device_type"].data["manufacturer"] is manufacturer
    assert device.data["serial"] == "REAL-SERIAL-123"
    assert device.data["asset_tag"] == "ASSET-456"
    assert device.data["description"] == "Curated inventory record"


def test_vm_resources_status_and_platform_are_synchronized(inventory):
    handler = _handler(inventory)
    site = inventory.add_update_object(NBSite, data={"name": "site-vm"}, source=handler)
    cluster_type = inventory.add_update_object(NBClusterType, data={"name": "VMmanager"}, source=handler)
    cluster = inventory.add_update_object(NBCluster, data={"name": "cluster-vm", "type": cluster_type,
        "scope_type": "dcim.site", "scope_id": site}, source=handler)

    vm = handler._sync_vm({
        "id": 123, "name": "app-01", "cpu_number": 4, "ram_mib": 8192,
        "status": "stopped", "os_name": "Ubuntu 24.04", "total_disks_size_mib": 0,
        "disks": [],
    }, cluster, site, source_disks=[])

    assert vm.data["name"] == "app-01"
    assert vm.data["vcpus"] == 4.0
    assert vm.data["memory"] == 8192
    assert vm.data["status"] == "offline"
    assert vm.data["platform"].data["name"] == "Ubuntu 24.04"
    assert vm.data["cluster"] is cluster
    assert vm.data["site"] is site


def test_vm_name_relations_support_tenant_and_multiple_tags(inventory):
    import re
    handler = _handler(inventory)
    handler.settings = type("Settings", (), {
        "vm_tenant_relation": [{"object_regex": re.compile(r"^prod-"), "assigned_name": "Production"}],
        "vm_tag_relation": [
            {"object_regex": re.compile(r"^prod-"), "assigned_name": "critical"},
            {"object_regex": re.compile(r"^prod-"), "assigned_name": "managed"},
        ],
    })()

    assert handler._resolve_relation("prod-api-01", "vm_tenant_relation") == "Production"
    assert handler._resolve_relation("prod-api-01", "vm_tag_relation", multiple=True) == ["critical", "managed"]
    assert handler._resolve_relation("dev-api-01", "vm_tenant_relation") is None
