# BrandFlow Brand Tools MCP

Directory contract:

```text
services/brand-tools-mcp/
├── pyproject.toml
├── Dockerfile
├── src/brand_tools_mcp/  MCP transport, schemas, repository, approval gates
└── tests/                Contract and real-transport integration tests
```

The service is a separate process. It exposes exactly nine versioned tools and never trusts model-supplied approval booleans. High-risk tools verify persisted decisions, immutable hashes, roles, and idempotency in PostgreSQL.
