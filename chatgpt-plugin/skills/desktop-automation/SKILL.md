---
name: desktop-automation
description: Operate the authorized Windows desktop through screenshot, window, keyboard and mouse tools.
---

# Desktop Automation

Use `window_list` and `screenshot` to inspect the active desktop. Prefer targeting windows by title over blind coordinates. `focus_and_type`, `keyboard_press`, `keyboard_type`, `mouse_move` and `click` affect the live desktop: verify the target before sending input. Do not interact with password fields, consent screens or payments without explicit user authorization. A headless background service may lack access to an interactive desktop session; report that limitation rather than pretending an action succeeded.
