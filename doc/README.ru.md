# Lavender Messenger — Remote Agent

Удалённый агент для Lavender Messenger. Подключается к серверу через
bidirectional gRPC stream (`Connect`), регистрируется, и выполняет задачи
(shell, git, build, file, docker, AI).

**Автор:** OWL (автоматическая генерация на основе протокола)
**Версия:** совместима с сервером v1.1.3.x
**Язык:** Python 3.10+

---

## Архитектура

```
┌─────────────┐    gRPC Connect      ┌──────────────────┐
│  Remote      │ ◄══════════════════► │  Lavender Server  │
│  Agent       │   bidir stream       │  :50051 / :50052  │
│  (Python)    │                      │                    │
└─────────────┘                      └──────────────────┘
       │                                      │
       │ 1. Connect + Register                 │
       │ 2. Receive Task (ORCHESTRATOR_TASK)   │
       │ 3. Execute (shell, git, build, ...)   │
       │ 4. Send Result (AGENT_TASK_RESULT)    │
       │ 5. Heartbeat every 30s                │
```

### Протокол

Базовый протокол — `hermes_remote.proto` (общий с сервером).

Ключевые сообщения:

- `AgentMessage` — от агента к серверу (`AGENT_REGISTER`, `AGENT_HEARTBEAT`,
  `AGENT_TASK_RESULT`, `AGENT_LOG`, `AGENT_DISCONNECT`, `AGENT_ERROR`)
- `OrchestratorMessage` — от сервера к агенту (`ORCHESTRATOR_TASK`,
  `ORCHESTRATOR_PING`, `ORCHESTRATOR_DISCONNECT`)
- `Task` — задача для выполнения (тип + параметры)
- `TaskResult` — результат (stdout, stderr, exit_code, duration_ms)

### Типы задач

| Тип | Описание |
|-----|----------|
| `TASK_SHELL` | Выполнение shell-команды |
| `TASK_GIT` | Git операции (clone, pull, commit, push) |
| `TASK_BUILD` | Сборка проекта (go build, gradle, etc.) |
| `TASK_FILE_READ` | Чтение файла |
| `TASK_FILE_WRITE` | Запись файла |
| `TABK_DOCKER` | Docker операции |
| `TASK_AI` | AI-ответ (агент сам решает как ответить) |
| `TASK_CUSTOM` | Произвольный скрипт |

---

## Быстрый старт

### 1. Сгенерировать токен

В приложении Lavender:
1. Откройте «Агенты» → ⚙ → «Сгенерировать токен»
2. Скопируйте токен (JWT, показывается только один раз!)

### 2. Установить зависимости

```bash
pip3 install grpcio grpcio-tools
```

### 3. Запустить агента

```bash
python3 hermes_remote_agent.py \
  --server 13.140.25.249:50051 \
  --token <your-jwt-token>
```

Или через конфиг:

```bash
python3 hermes_remote_agent.py --config /path/to/config.json
```

### Конфигурационный файл

```json
{
  "server_addr": "13.140.25.249:50051",
  "agent_id": "my-agent-1",
  "agent_name": "Build Agent",
  "auth_token": "eyJ...",
  "capabilities": ["shell", "git", "build", "file"]
}
```

---

## Параметры запуска

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `--server` | `localhost:50052` | Адрес gRPC сервера |
| `--agent-id` | `agent-<pid>` | Уникальный ID агента |
| `--agent-name` | `Hermes Agent` | Имя агента |
| `--token` | *(required)* | JWT токен аутентификации |
| `--caps` | `shell,git,build,file,docker,ai` | Возможности (capabilities) |
| `--config` | — | JSON файл с настройками |

---

## Поведение

### Подключение
- Агент подключается к серверу и отправляет `AGENT_REGISTER`
- Сервер валидирует JWT токен
- При невалидном токене — немедленная остановка (без retry)
- При недоступности сервера — retry с экспоненциальным backoff (5s → 60s)

### Выполнение задач
- Агент получает `ORCHESTRATOR_TASK` через stream
- Задача выполняется асинхронно (параллельно с другими)
- Результат отправляется как `AGENT_TASK_RESULT`
- Таймаут по умолчанию: 120s (shell), 60s (git), 300s (build)

### Heartbeat
- Каждые 30 секунд отправляется `AGENT_HEARTBEAT`
- Сервер отслеживает последний heartbeat (таймаут 90s)

### Reconnect
- При потере stream — автоматический reconnect
- Экспоненциальный backoff: 5s → 10s → 20s → 40s → 60s (max)
- `UNAUTHENTICATED` — мгновенная остановка (не retry)

---

## Отладка

Включить DEBUG-логи сервера:

```bash
DEBUG=1 ./lavender-server
```

Логи агента выводятся в stdout:
- `[Agent] Connecting...` — попытка подключения
- `[Agent] Connected and registered` — успешная регистрация
- `[Agent] Task ...` — получена задача
- `[Agent] Task ... done` — задача выполнена
- `[Agent] Lost connection. Reconnecting...` — переподключение

---

## Связанные репозитории

| Репозиторий | Назначение |
|-------------|------------|
| `msg` | Сервер Lavender Messenger (Go) |
| `msg.client.android` | Android клиент (Kotlin) |
| `msg.client.web` | Web клиент (TypeScript) |
| `msg.remote.agent` | Этот репозиторий — Remote Agent (Python) |

### Серверные компоненты (в репозитории `msg`)

Файлы, связанные с Remote Agent в серверном репозитории:
- `hermes_agent_service.go` — gRPC сервис `HermesAgentService` (Connect, HealthCheck)
- `hermes_remote_manager.go` — менеджер удалённых агентов (регистрация, задачи, результаты)
- `db_hermes.go` — методы БД для токенов агентов
- `server_ai.go` — `DeployAgentTask` (отправка задачи агенту, ожидание результата)

### Клиентские компоненты (в репозитории `msg.client.android`)

- `data/grpc/HermesGrpc.kt` — hand-written gRPC клиент для Android
- `data/proto/MessengerProto.kt` — proto-классы (DeployAgentTask, etc.)
- `ui/remote/RemoteAgentViewModel.kt` — ViewModel для Remote Agent UI
- `ui/remote/RemoteAgentActivity.kt` — экран чата с агентом
- `ui/remote/RemoteAgentSettingsActivity.kt` — настройки (токены, запуск/остановка)
