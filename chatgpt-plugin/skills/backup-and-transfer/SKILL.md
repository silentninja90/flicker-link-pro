---
name: backup-and-transfer
description: Create backups, archives, checksums, and HTTPS uploads or downloads on the laptop.
---

# Backup And Transfer

Use `create_project_backup` before risky operations and verify archives using `checksum_sha256`. For HTTPS downloads or uploads, verify the destination/source and URL; avoid sending secrets or private files to untrusted endpoints. Track long transfers with `interact_with_process`. Use `unzip_to_folder` only after checking archive entries for traversal paths and unexpected overwrites. Report actual transfer completion rather than initiation.
