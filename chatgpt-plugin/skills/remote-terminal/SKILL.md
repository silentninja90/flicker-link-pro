---
name: remote-terminal
description: Execute, monitor and manage terminal commands and WSL sessions on the authorized Windows laptop.
---

# Remote Terminal

Use `who_am_i` to verify the host before changing anything. Prefer `run_code` for short commands, `start_process` for longer jobs, and `interact_with_process` to retrieve incremental output. Check `list_sessions` before creating duplicate jobs. Use `run_wsl` only for an explicitly requested Linux environment. Never claim a job finished merely because it started. For destructive commands, explain scope and request confirmation. Never print environment secrets or credentials.
