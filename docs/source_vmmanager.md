# VMmanager 6 inventory source

`netbox-sync` imports virtual machines from VMmanager 6 into NetBox. This is a read-only integration: it does not create, modify, start, stop, or delete VMs in VMmanager.

## Configuration

Add a source section to `settings.ini`:

```ini
[source/production-vmmanager]
enabled = True
type = vmmanager
api_url = https://vmmanager.example.org
email = netbox-sync@example.org
password = change-me
site_name = VMmanager
cluster_name = VMmanager: production
cluster_type_name = VMmanager
sync_clusters = True
sync_nodes = True
exclude_dummy_clusters = False
hypervisor_device_type = VMmanager Hypervisor
hypervisor_device_role = Hypervisor
; Optional regex-based mapping to NetBox tenant and tags
;vm_tenant_relation = .* = mz
;vm_tag_relation = .* = mz
verify_ssl = True
timeout = 30
```

Use a dedicated VMmanager account with the minimum permissions required to read VM inventory. Keep TLS verification enabled in production.

## Data synchronized

The source creates/updates a NetBox site and imports VMmanager clusters, VMs, and hypervisor nodes. Set `sync_clusters = False` or `sync_nodes = False` to disable either part. `exclude_dummy_clusters = True` skips clusters whose `virtualization_type` is `dummy` and skips their VMs/nodes. Hypervisors are represented as NetBox Devices using the configured device type and role; their management IP is assigned to a `mgmt0` interface and set as the device's primary IP. VMmanager IDs are stored in the VM/device `serial` field to preserve identity when names change.

Hypervisor CPU and RAM values are written to existing NetBox Device custom fields when a compatible field is configured for Devices. CPU field aliases: `cpu`, `cpu_count`, `cpu_cores`, `cores`, `vcpus`; RAM aliases: `ram`, `ram_mib`, `memory`, `memory_mib`, `ram_mb`. RAM values are stored in MiB. If no compatible field exists, the sync logs a warning at the end naming the recommended custom fields to create: `cpu` (Integer) and `ram_mib` (Integer), both assigned to Devices. CPU/RAM and kernel version are also summarized in the device description. `vm_tenant_relation` maps VM names to NetBox tenants and `vm_tag_relation` maps VM names to tags using regex expressions; the syntax matches other sources, for example `.* = mz`.

The client uses `POST /auth/v4/public/token` for authentication and paginated `GET /vm/v3/host?limit=offset,count`, `/vm/v3/cluster?limit=offset,count`, and `/vm/v3/node?limit=offset,count` requests. Every enabled inventory endpoint is fetched and validated before the source is marked safe for pruning. Validate optional disk/network fields against Swagger for the exact installed edition/version before production rollout.

## Removal and failure safety

The project's standard source tags and orphan/pruning policy apply, including its configured pruning delay. The source fetches and validates every enabled inventory snapshot (VMs and, when enabled, clusters and hypervisor nodes) before changing the in-memory inventory or marking the source safe for pruning. Authentication errors, HTTP failures, invalid JSON, unknown response shapes, or objects without IDs raise an error and stop the run before NetBox update/pruning can execute. API failure is never treated as an empty inventory. A valid empty list is treated as a real empty snapshot and source-owned objects are orphaned/deleted according to global pruning settings.

The source is read-only against VMmanager. It only sends a token-creation POST request and inventory GET requests. Memory/disk units must be confirmed against the target installation's Swagger response before production rollout.

### Existing physical hypervisor devices

When importing VMmanager nodes, the source matches an existing NetBox device by
name and site. For matched devices, VMmanager updates the cluster relationship,
status, management interface/IP, and configured CPU/RAM custom fields, but preserves
the administrator-managed device type (manufacturer/model), serial number, asset
tag, platform, and description. VMmanager node IDs are not hardware serial numbers
and are not written to NetBox's `serial` field. Unmatched nodes are created using
the configured generic hypervisor device type and role.
