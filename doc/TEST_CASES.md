# Remote Agent — Тест-кейсы v1.1.3.2

**Дата:** 2026-06-12
**Версия:** v1.1.3.2
**Сервер:** 13.140.25.249:50051 (prod) / localhost:50052 (dev)
**Агент:** Python 3.10+, grpcio

---

## Легенда

- ✅ PASS — работает
- ❌ FAIL — не работает
- ⚠️ PARTIAL — работает частично
- N/A — не применимо

---

## 1. Подключение и регистрация

### CON-01: Успешное подключение с валидным токеном
1. Сгенерировать токен в приложении (Агенты → ⚙ → Сгенерировать токен)
2. Запустить агента: `python3 hermes_remote_agent.py --server localhost:50051 --token <valid_jwt>`
3. **Ожидание:**
   - `[Agent] Connecting to...` — попытка подключения
   - `[Agent] Connected and registered. Caps: shell, git, build, file, docker, ai` — успешная регистрация
   - Агент остаётся запущенным, ожидает задач

### CON-02: Невалидный токен — мгновенная остановка
1. Запустить агента с невалидным токеном: `--token "invalid_token"`
2. **Ожидание:**
   - `[Agent] AUTH FAILED: invalid auth token`
   - `[Agent] Token is invalid or expired. Generate a new token in the app.`
   - Агент завершается (exit code 0), НЕ пытается переподключиться

### CON-03: Недоступный сервер — retry с backoff
1. Остановить сервер
2. Запустить агента: `--server localhost:50051 --token <valid_jwt>`
3. **Ожидание:**
   - `[Agent] Server unavailable: ... Retrying in 5s...`
   - `[Agent] Server unavailable: ... Retrying in 10s...`
   - `[Agent] Server unavailable: ... Retrying in 20s...`
   - Максимальный интервал: 60s

### CON-04: Сервер стал доступен во время retry
1. Запустить агента при остановленном сервере (CON-03)
2. Через 10 секунд запустить сервер
3. **Ожидание:** Агент подключается при следующей попытке, регистрируется

### CON-05: Потеря связи во время работы — auto-reconnect
1. Запустить агента с валидным токеном, дождаться регистрации
2. Убить сервер (kill -9)
3. **Ожидание:**
   - `[Agent] Stream RPC error: StatusCode.UNAVAILABLE: ...`
   - `[Agent] Lost connection. Reconnecting in 5s...`
4. Запустить сервер заново
5. **Ожидание:** Агент переподключается, регистрируется

---

## 2. Выполнение задач

### TASK-01: Shell команда — успешное выполнение
1. Отправить задачу через `DeployAgentTask`:
   - `task_type: "shell"`, `params: { "command": "echo hello" }`
2. **Ожидание:**
   - `success: true`
   - `stdout: "hello\n"`
   - `exit_code: 0`

### TASK-02: Shell команда — ошибка
1. Отправить задачу: `command: "exit 42"`
2. **Ожидание:**
   - `success: false`
   - `exit_code: 42`

### TASK-03: Shell команда — таймаут
1. Отправить задачу: `command: "sleep 300"`, `timeout_sec: 2`
2. **Ожидание:**
   - `success: false`
   - `stderr: "timeout"` (или пусто)
   - `exit_code: 124`

### TASK-04: Git операция
1. Отправить задачу: `task_type: "git"`, `params: { "subcommand": "status" }`
2. **Ожидание:**
   - `success: true`
   - `stdout` содержит вывод `git status`

### TASK-05: File read
1. Создать тестовый файл: `echo "test content" > /tmp/test_agent_read.txt`
2. Отправить задачу: `task_type: "file_read"`, `params: { "path": "/tmp/test_agent_read.txt" }`
3. **Ожидание:**
   - `success: true`
   - `stdout: "test content\n"`

### TASK-06: File write
1. Отправить задачу: `task_type: "file_write"`, `params: { "path": "/tmp/test_agent_write.txt", "content": "hello agent" }`
2. **Ожидание:**
   - `success: true`
   - Файл `/tmp/test_agent_write.txt` создан с содержимым `hello agent`

### TASK-07: Параллельные задачи
1. Отправить 3 задачи одновременно (shell, git, file_read)
2. **Ожидание:** Все 3 задачи выполнены, результаты корректны

---

## 3. Heartbeat

### HB-01: Heartbeat отправляется каждые 30с
1. Запустить агента с валидным токеном
2. Подождать 35 секунд
3. **Ожидание:** Сервер получил хотя бы один `AGENT_HEARTBEAT`

### HB-02: Сервер отмечает heartbeat
1. Запустить агента
2. Через 35с проверить статус агента на сервере
3. **Ожидание:** `last_heartbeat` обновлён, `status: "connected"`

### HB-03: Потеря heartbeat — сервер отключает агента
1. Запустить агента
2. Убить агента (kill -9)
3. Подождать 95 секунд (heartbeat timeout 90s + 5s)
4. **Ожидание:** Сервер отрегистрировал агента (`status: "disconnected"`)

---

## 4. Аутентификация и токены

### AUTH-01: Валидный JWT токен
1. Сгенерировать токен в приложении
2. Запустить агента с этим токеном
3. **Ожидание:** Агент зарегистрирован, `validateToken` возвращает `true`

### AUTH-02: Отозванный токен
1. Сгенерировать токен
2. Отозвать токен в приложении (Агенты → ⚙ → Отозвать)
3. Запустить агента с отозванным токеном
4. **Ожидание:** `AUTH FAILED: token revoked`

### AUTH-03: Просроченный токен
1. Сгенерировать токен с TTL 1 час
2. Подождать истечения TTL (или подменить в БД)
3. Запустить агента
4. **Ожидание:** `AUTH FAILED: token expired`

### AUTH-04: Токен с другим agent_id
1. Сгенерировать токен для `agent_A`
2. Запустить агента с `--agent-id agent_B` и токеном от `agent_A`
3. **Ожидание:** `AUTH FAILED: token agent_id mismatch`

---

## 5. Управление процессом (server-side launch)

### PROC-01: StartAgent — успешный запуск
1. Вызвать `StartAgent` через gRPC с валидным токеном
2. **Ожидание:**
   - `success: true`
   - `pid > 0`
   - Процесс агента запущен (`ps aux | grep hermes_remote_agent`)

### PROC-02: StartAgent — скрипт не найден
1. Переименовать/удалить скрипт
2. Вызвать `StartAgent`
3. **Ожидание:**
   - `success: false`
   - `error: "agent script not found: ..."`

### PROC-03: StopAgent — остановка
1. Запустить агента через `StartAgent`
2. Вызвать `StopAgent`
3. **Ожидание:**
   - `success: true`
   - Процесс агента остановлен

### PROC-04: GetAgentProcessStatus
1. Запустить агента через `StartAgent`
2. Вызвать `GetAgentProcessStatus`
3. **Ожидание:**
   - `running: true`
   - `pid > 0`
   - `started_at` заполнен

### PROC-05: Агент завершился сам — статус обновлён
1. Запустить агента через `StartAgent`
2. Убить процесс агента (kill -9)
3. Подождать 5 секунд
4. Вызвать `GetAgentProcessStatus`
5. **Ожидание:** `running: false`

---

## 6. Маршрутизация через оркестратор

### ORCH-01: Задача через оркестратор → агент
1. Запустить агента с валидным токеном
2. Отправить сообщение в Hermes чат, которое маршрутизируется к агенту
3. **Ожидание:**
   - Оркестратор отправляет `ORCHESTRATOR_TASK` агенту
   - Агент выполняет задачу, возвращает `AGENT_TASK_RESULT`
   - Результат отображается в чате

### ORCH-02: Агент не подключён — ошибка
1. НЕ запускать агента
2. Отправить сообщение в Hermes чат
3. **Ожидание:** Ошибка "agent not connected" или аналогичная

---

## 7. Персистентность и настройки

### CONF-01: Конфиг из файла
1. Создать `/tmp/agent_config.json`:
   ```json
   {
     "server_addr": "localhost:50051",
     "agent_id": "test-agent",
     "agent_name": "Test Agent",
     "auth_token": "<valid_jwt>",
     "capabilities": ["shell", "git"]
   }
   ```
2. Запустить: `python3 hermes_remote_agent.py --config /tmp/agent_config.json`
3. **Ожидание:** Агент зарегистрирован с `agent_id: "test-agent"`, caps: `shell, git`

### CONF-02: Переменные окружения AGENT_SCRIPT_PATH
1. `export AGENT_SCRIPT_PATH=/wrong/path.py`
2. Вызвать `StartAgent` на сервере
3. **Ожидание:** `error: "agent script not found: /wrong/path.py"`

### CONF-03: Переменные окружения AGENT_VENV_PYTHON
1. `export AGENT_VENV_PYTHON=/usr/bin/python3`
2. Вызвать `StartAgent`
3. **Ожидание:** Агент запущен с указанным Python

---

## 8. Graceful shutdown

### SHUTDOWN-01: SIGTERM
1. Запустить агента
2. Отправить SIGTERM: `kill <pid>`
3. **Ожидание:** Агент завершается, сервер получает `AGENT_DISCONNECT`

### SHUTDOWN-02: SIGINT (Ctrl+C)
1. Запустить агента в foreground
2. Нажать Ctrl+C
3. **Ожидание:** Агент завершается корректно

### SHUTDOWN-03: Сервер инициирует отключение
1. Запустить агента
2. Сервер отправляет `ORCHESTRATOR_DISCONNECT`
3. **Ожидание:** Агент завершается

---

## Результаты тестирования

| ID | Статус | Комментарий |
|----|--------|-------------|
| CON-01 | | |
| CON-02 | | |
| CON-03 | | |
| CON-04 | | |
| CON-05 | | |
| TASK-01 | | |
| TASK-02 | | |
| TASK-03 | | |
| TASK-04 | | |
| TASK-05 | | |
| TASK-06 | | |
| TASK-07 | | |
| HB-01 | | |
| HB-02 | | |
| HB-03 | | |
| AUTH-01 | | |
| AUTH-02 | | |
| AUTH-03 | | |
| AUTH-04 | | |
| PROC-01 | | |
| PROC-02 | | |
| PROC-03 | | |
| PROC-04 | | |
| PROC-05 | | |
| ORCH-01 | | |
| ORCH-02 | | |
| CONF-01 | | |
| CONF-02 | | |
| CONF-03 | | |
| SHUTDOWN-01 | | |
| SHUTDOWN-02 | | |
| SHUTDOWN-03 | | |
