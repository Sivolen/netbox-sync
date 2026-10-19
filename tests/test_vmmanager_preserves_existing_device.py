from types import SimpleNamespace
from unittest.mock import Mock

from module.sources.vmmanager.connection import VMmanagerHandler
from module.netbox.object_classes import NBDevice


class ExistingDeviceInventory:
    def __init__(self, existing):
        self.existing = existing
        self.update_payload = None

    def get_by_data(self, object_type, data=None):
        assert object_type is NBDevice
        assert data == {"name": "hv01", "site": "DC1"}
        return self.existing

    def add_update_object(self, object_type, data=None, source=None, **kwargs):
        assert object_type is NBDevice
        self.update_payload = dict(data)
        self.existing.data.update(data)
        return self.existing


class TestVMmanagerExistingDevice:
    def test_existing_device_keeps_managed_hardware_fields(self):
        existing = SimpleNamespace(data={
            "name": "hv01",
            "site": "DC1",
            "device_type": "HPE ProLiant DL380 Gen10",
            "serial": "REAL-SERIAL-123",
            "asset_tag": "ASSET-456",
            "platform": "Existing platform",
            "description": "Manually maintained hardware inventory",
        })
        inventory = ExistingDeviceInventory(existing)
        handler = VMmanagerHandler.__new__(VMmanagerHandler)
        handler.inventory = inventory
        handler.log = Mock()

        result = handler._sync_node(
            {"id": 17, "name": "hv01", "state": "running", "cpu_number": 32,
             "ram_mib": 262144},
            site="DC1",
            clusters={},
            device_type="VMmanager Hypervisor",
            device_role="Hypervisor",
            custom_field_names={},
        )

        assert result is existing
        assert existing.data["device_type"] == "HPE ProLiant DL380 Gen10"
        assert existing.data["serial"] == "REAL-SERIAL-123"
        assert existing.data["asset_tag"] == "ASSET-456"
        assert existing.data["platform"] == "Existing platform"
        assert existing.data["description"] == "Manually maintained hardware inventory"
        assert "device_type" not in inventory.update_payload
        assert "serial" not in inventory.update_payload
        assert "asset_tag" not in inventory.update_payload
        assert "platform" not in inventory.update_payload
        assert "description" not in inventory.update_payload
