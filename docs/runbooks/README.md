# Operational runbooks

These runbooks are intentionally conservative. Preserve the privacy boundary
first, then restore capacity. Capture request IDs, status codes, metric names,
and deployment versions—not request bodies or API keys.

- [Redis unavailable or slow](redis.md)
- [Model unavailable or slow](model.md)
- [Jobs and worker failure](jobs.md)
- [Audit or disk failure](audit.md)
- [API key compromise and rotation](security.md)
- [Rollback and disaster recovery](rollback.md)

For all incidents, stop forwarding raw request data into tickets or chat. Use
synthetic probes to verify recovery.
