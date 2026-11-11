---
name: process-diagnostics
description: Diagnose Windows processes, Docker, resource usage, network and application logs.
---

# Process Diagnostics

Begin with read-only `system_resources`, `process_list`, `list_processes`, `network_info`, `docker_containers`, `read_application_logs`, and `get_config`. Identify process PID, executable and ownership before `process_kill` or `force_terminate`. Do not stop unknown services or processes. For Docker, inspect containers before stop/restart. Distinguish local host status from tunnel or ChatGPT connectivity.
