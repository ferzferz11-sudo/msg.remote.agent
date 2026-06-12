# Remote Agent — Тестирование

Документация по тестированию Remote Agent: как запускать, что проверять, как отлаживать.

---

## Быстрый старт

```bash
# Установить зависимости
pip3 install grpcio grpcio-tools

# Запустить агента вручную
python3 hermes_remote_agent.py --server localhost:50051 --token <jwt>

# Запустить с конфигом
python3 hermes_remote_agent.py --config /path/to/config.json

# Проверить что агент работает (через сервер)
grpcurl -plaintext localhost:50051 hermes_agent.HermesAgentService/HealthCheck
```

---

## Структура тестирования

| Тип | Что проверяем | Как |
|-----|--------------|-----|
| Ручное подключение | Connect + Register | Запуск агента, логи |
| Выполнение задач | Shell, git, file, build | `DeployAgentTask` через сервер |
| Heartbeat | Пинг каждые 30с | Логи сервера |
| Reconnect | Потеря и восстановление связи | Kill сервера, перезапуск |
| Auth | Валидация JWT | Разные токены |
| Process management | Start/Stop/Status | gRPC вызовы |

---

## Ручное тестирование

### 1. Подключение

```bash
# Запуск с валидным токеном
python3 hermes_remote_agent.py --server localhost:50051 --token eyJ...

# Ожидаемый вывод:
# [Agent] Connecting to localhost:50051 as 'Hermes Agent' (id=agent-12345)
# [Agent] Connected and registered. Caps: shell, git, build, file, docker, ai
```

**Проверки:**
- Агент выводит "Connected and registered"
- Агент НЕ завершается, остаётся ждать задач
- На сервере в логах: `register: id=... name=... caps=...`

### 2. Невалидный токен

```bash
python3 hermes_remote_agent.py --server localhost:50051 --token "invalid"
```

**Проверки:**
- `[Agent] AUTH FAILED: invalid auth token`
- Агент завершается (НЕ retry)

### 3. Недоступный сервер

```bash
# Сервер остановлен
python3 hermes_remote_agent.py --server localhost:50051 --token eyJ...
```

**Проверки:**
- `[Agent] Server unavailable: ... Retrying in 5s...`
- Экспоненциальный backoff: 5s → 10s → 20s → 40s → 60s

### 4. Выполнение задачи

Отправить задачу через сервер (из другого терминала):

```bash
# Через grpcurl (если есть reflection)
grpcurl -plaintext -d '{"agent_id": "agent-12345", "task_type": "shell", "params": {"command": "echo hello"}}' \
  localhost:50051 messenger.ChatService/DeployAgentTask
```

Или через Android приложение: открыть Remote Agent → отправить сообщение.

**Проверки в логах агента:**
```
[Agent] Task task-xxx: type=TASK_SHELL, params={'command': 'echo hello'}
[Agent] Shell: echo hello
[Agent] Task task-xxx done: success (exit=0, 5ms)
```

### 5. Heartbeat

```bash
# Запустить агента, подождать 35 секунд
# На сервере в логах:
# [HermesAgentService] heartbeat from agent-xxx
```

### 6. Reconnect

```bash
# 1. Запустить агента
python3 hermes_remote_agent.py --server localhost:50051 --token eyJ...

# 2. Убить сервер (в другом терминале)
kill -9 $(pgrep lavender-server)

# 3. Логи агента:
# [Agent] Stream RPC error: StatusCode.UNAVAILABLE
# [Agent] Lost connection. Reconnecting in 5s...

# 4. Запустить сервер заново
/root/LavenderMessenger/run/lavender-server &

# 5. Агент должен переподключиться:
# [Agent] Connecting to...
# [Agent] Connected and registered.
```

---

## Автоматическое тестирование (Python)

### Запуск юнит-тестов

```bash
# Если есть pytest
pip3 install pytest pytest-asyncio
python3 -m pytest tests/ -v

# Без pytest — запуск тестового скрипта
python3 tests/test_agent.py
```

### Пример тестового скрипта

```python
#!/usr/bin/env python3
"""Basic integration test for Remote Agent."""

import asyncio
import subprocess
import sys
import time
import os

SERVER = os.getenv("TEST_SERVER", "localhost:50051")
TOKEN = os.getenv("TEST_TOKEN", "")

def test_agent_help():
    """Test that agent starts and shows help."""
    result = subprocess.run(
        [sys.executable, "hermes_remote_agent.py", "--help"],
        capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0
    assert "--server" in result.stdout
    assert "--token" in result.stdout
    print("✓ test_agent_help PASSED")

def test_agent_no_token():
    """Test that agent exits without token."""
    result = subprocess.run(
        [sys.executable, "hermes_remote_agent.py", "--server", "localhost:50051"],
        capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 1
    assert "No auth token" in result.stdout
    print("✓ test_agent_no_token PASSED")

def test_agent_invalid_server():
    """Test retry on unavailable server."""
    proc = subprocess.Popen(
        [sys.executable, "hermes_remote_agent.py",
         "--server", "localhost:19999", "--token", "test"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    time.sleep(8)  # Wait for first retry
    proc.terminate()
    proc.wait(timeout=5)
    output = proc.stdout.read()
    assert "Server unavailable" in output or "Retrying" in output
    print("✓ test_agent_invalid_server PASSED")

if __name__ == "__main__":
    test_agent_help()
    test_agent_no_token()
    test_agent_invalid_server()
    print("\nAll tests passed!")
```

---

## Отладка

### Включить DEBUG на сервере

```bash
DEBUG=1 /root/LavenderMessenger/run/lavender-server
```

Покажет:
- Все gRPC вызовы
- Валидацию токенов
- Запуск/остановку процессов агентов

### Логи агента

Агент пишет в stdout/stderr:
- `[Agent] Connecting...` — подключение
- `[Agent] Connected and registered` — успех
- `[Agent] Task ...` — получена задача
- `[Agent] Task ... done` — результат
- `[Agent] Stream RPC error` — ошибка связи
- `[Agent] Lost connection. Reconnecting...` — переподключение

### Проверка состояния агента на сервере

```bash
# Список подключённых агентов
grpcurl -plaintext localhost:50051 messenger.ChatService/ListRemoteAgents

# Статус конкретного агента
grpcurl -plaintext -d '{"agent_id": "agent-12345"}' \
  localhost:50051 messenger.ChatService/GetRemoteAgentStatus
```

### Проверка процесса

```bash
# Найти процесс агента
ps aux | grep hermes_remote_agent

# Проверить что процесс слушает
lsof -p <pid> | grep -E "REG|txt"
```

---

## Типичные проблемы

### "agent script not found"

**Причина:** Сервер не может найти `hermes_remote_agent.py`.

**Решение:**
```bash
# Проверить путь
ls -la /root/msg.remote.agent/hermes_remote_agent.py

# Если файла нет — клонировать репозиторий
cd /root && git clone https://github.com/ferzferz11-sudo/msg.remote.agent.git

# Или задать путь через env
export AGENT_SCRIPT_PATH=/path/to/hermes_remote_agent.py
```

### "UNAUTHENTICATED: invalid auth token"

**Причина:** Токен невалидный, отозван или просрочен.

**Решение:**
1. Сгенерировать новый токен в приложении
2. Проверить что токен не отозван в БД
3. Проверить TTL токена

### "UNAVAILABLE: failed to connect"

**Причера:** Сервер не запущен или порт недоступен.

**Решение:**
```bash
# Проверить что сервер слушает
ss -tlnp | grep 50051

# Проверить firewall
iptables -L INPUT -n | grep 50051
```

### Агент завершается сразу после запуска

**Причины:**
1. Невалидный токен — проверить логи
2. Сервер недоступен — проверить подключение
3. Нет зависимостей — `pip3 install grpcio`

---

## Покрытие кода

| Модуль | Что покрыто | Статус |
|--------|-------------|--------|
| `connect()` | Подключение, retry, auth | Ручное |
| `run()` | Приём задач, heartbeat | Ручное |
| `_handle_task()` | Все типы задач | Ручное |
| `_exec_shell()` | Shell команды | Ручное |
| `_exec_git()` | Git операции | Ручное |
| `_exec_build()` | Сборка | Ручное |
| `_read_file()` / `_write_file()` | Файловые операции | Ручное |
| Token validation | JWT проверка | Через сервер |
| Process management | Start/Stop/Status | Ручное |

Автоматические тесты отсутствуют — проект тестируется вручную через интеграцию с сервером.
