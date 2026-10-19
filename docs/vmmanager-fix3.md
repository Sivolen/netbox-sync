# VMmanager inventory follow-up fixes

- Maps VMmanager `os_name` to a NetBox Platform and links it to the VM.
- Sets the VM aggregate disk capacity from `total_disks_size_mib` while retaining per-disk objects.
- Records OS and storage name in VM comments.
- Assigns an existing IP to the VM interface only if the IP is unassigned or already managed by this source.
- Sets the first successfully linked IPv4/IPv6 address as the VM primary IP.
- Never steals an IP already assigned to another object.

The integration remains read-only toward VMmanager.
