---
status: accepted
---

# Use transactional task intents and fenced execution ownership

Crash-Cap will commit each durable task intent in the same PostgreSQL transaction as the domain state that requires it, then publish it to Redis through an independent relay with at-least-once delivery. A Worker must acquire a short-lived execution ownership lease whose generation increases on every reclaim; every terminal result, projection, and follow-up intent is accepted only from the current generation, while long Core, RustFS, and Symbolicator work runs without a database lock. This closes the database-to-Redis loss window without pretending to provide exactly-once delivery, and it means rollbacks after schema activation must use an image that still understands pending intents and fencing.
