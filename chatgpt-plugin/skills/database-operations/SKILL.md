---
name: database-operations
description: Inspect and execute PostgreSQL operations on the authorized laptop with database safeguards.
---

# Database Operations

Use `db_execute` only with a user-authorized PostgreSQL connection string supplied through a secure channel. Prefer SELECT and schema inspection before modifications. Back up before migrations. Never echo connection credentials. Do not drop or truncate tables or reset databases unless explicitly requested. Record verification queries and results.
