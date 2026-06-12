# Changelog

All notable changes to the Remote Agent project.

---

## [1.1.3.2] — 2026-06-12

### Fixed

- **Reconnect**: Agent now automatically reconnects on stream failure with
  exponential backoff (5s → 10s → 20s → 40s → 60s max)
- **Auth error handling**: `UNAUTHENTICATED` — immediate stop with clear message
  (no retry). `UNAVAILABLE` — retry with backoff.
- **Stream stability**: `run()` loop now survives stream errors and reconnects
  instead of crashing
- **Channel cleanup**: Proper channel/stream cleanup on errors via `_cleanup_channel()`
- **Heartbeat resilience**: Heartbeat task is properly cancelled on reconnect

### Changed

- `connect()` now has retry loop with exponential backoff
- `run()` is now an outer loop that reconnects after stream failures
- Registration message built before `stream.write()` for clarity

---

## [1.1.3.1] — 2026-06-12

### Added

- Initial Remote Agent implementation
- Bidirectional gRPC stream (`Connect`)
- JWT token authentication
- Task execution: shell, git, build, file_read, file_write, docker, AI
- Heartbeat every 30s
- Token management RPCs: `GenerateAgentToken`, `RevokeAgentToken`, `ListAgentTokens`
- Agent process management: `StartAgent`, `StopAgent`, `GetAgentProcessStatus`

---

## [1.1.3.0] — 2026-06-11

### Added

- First version of Remote Agent protocol (`hermes_remote.proto`)
- Server-side implementation of `HermesAgentService`
- `RemoteAgentManager` for orchestrator
- Agent token persistence in PostgreSQL (`agent_tokens` table)
