---
name: audit-and-usage
description: Review tool-call history, inspect results and measure local tool usage.
---

# Audit And Usage

Use `get_usage_stats`, `get_recent_tool_calls`, `list_remote_tool_calls`, `get_tool_result` and `review_device_call` for local agent runtime evidence. Keep result summaries concise and separate attempted actions from verified completions. These local tools report limited runtime/call metadata; they do not report the account's 30-day allowance or Stripe billing. Use the signed-in Flicker Link Pro account page for account usage and subscription status. Do not save passwords, pairing tokens, API keys, or database credentials with `keep_tool_result` or include them in event details.
