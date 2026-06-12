# Lavender Messenger — Remote Agent

Remote Agent for Lavender Messenger. Connects to the server via bidirectional
gRPC stream, registers with JWT token, and executes tasks (shell, git, build,
file, docker, AI).

## Quick Start

```bash
pip3 install grpcio
python3 hermes_remote_agent.py --server 13.140.25.249:50051 --token <jwt>
```

Generate a token in the Lavender app: Агенты → ⚙ → Сгенерировать токен.

## Documentation

- [doc/README.ru.md](doc/README.ru.md) — project overview, architecture, protocol
- [CHANGELOG.md](CHANGELOG.md) — version history

## Protocol

See `hermes_remote.proto` — shared with the server repository (`msg/`).

## License

Private — Lavender Messenger project.
