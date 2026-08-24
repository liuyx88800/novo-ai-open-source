# Open-source boundary

This repository publishes the Novo AI landing application, the VOZEB PRO Agent and short-drama Studio integration, and the reviewed FastAPI compatibility adapter from the initial 2026-08-22 integration snapshot.

The following are intentionally excluded:

- Novo AI proprietary canvas runtimes and source files
- Classic Canvas, Smart Canvas, Canvas V2, and Workbench implementations
- Canvas build artifacts, source maps, screenshots, backups, release archives, and deployment bundles
- Proprietary canvas Agent orchestration and server-side canvas execution logic
- Account databases, billing records, provider configuration, prompts containing private business logic, uploaded media, task history, and logs
- `.env` files, API keys, access tokens, SMTP credentials, payment credentials, SSH keys, certificates, and server addresses

`integrations/fastapi/vz_routes.py` is an integration adapter rather than a standalone server. Its host imports document the API surface expected from an embedding backend. Implementations of those host services are outside this repository.

Please report any file that appears to cross this boundary through a private security channel before opening a public issue.
