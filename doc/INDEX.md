# Remote Agent — Documentation Index

Index of documents for the Remote Agent repository.

---

## Quick Start

1. **doc/README.ru.md** — project overview, architecture, quick start (read first)
2. **CHANGELOG.md** (in root) — version history

---

## Documentation Files

| File | Purpose | When to Read |
|------|---------|-------------|
| `doc/README.ru.md` | Project overview, architecture, protocol, quick start | First thing |
| `doc/INDEX.md` | This file — navigation | For navigation |

---

## Protocol

The protocol is defined in `hermes_remote.proto` (shared with the server).

Key RPC: `HermesAgentService.Connect` — bidirectional stream.

Message flow:
1. Agent connects → sends `AGENT_REGISTER`
2. Server validates JWT token
3. Server sends `ORCHESTRATOR_TASK`
4. Agent executes → sends `AGENT_TASK_RESULT`
5. Agent sends `AGENT_HEARTBEAT` every 30s

---

## Repository Structure

```
msg.remote.agent/
  hermes_remote_agent.py       # Main agent (Python)
  hermes_remote_pb2.py         # Generated protobuf classes
  hermes_remote_pb2_grpc.py    # Generated gRPC stubs
  hermes_remote.proto          # Protocol definition
  doc/
    INDEX.md                   # This file
    README.ru.md               # Project documentation
  scripts/                     # Deployment scripts (future)
```

---

## Related Repositories

| Repository | Purpose |
|------------|---------|
| `msg` | Lavender Messenger server (Go) |
| `msg.client.android` | Android client (Kotlin) |
| `msg.client.web` | Web client (TypeScript) |
| `msg.remote.agent` | This repository — Remote Agent (Python) |
