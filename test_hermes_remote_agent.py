#!/usr/bin/env python3
"""
Unit tests for hermes_remote_agent.py

Run: cd /root/msg.remote.agent && python3 -m pytest test_hermes_remote_agent.py -v
"""

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# Add script dir to path
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# Import proto-generated classes
from hermes_remote_pb2 import (
    AGENT_REGISTER, AGENT_HEARTBEAT, AGENT_TASK_RESULT, AGENT_DISCONNECT,
    ORCHESTRATOR_TASK, ORCHESTRATOR_PING, ORCHESTRATOR_DISCONNECT,
    TASK_SUCCESS, TASK_ERROR, TASK_TIMEOUT, TASK_CANCELLED, TASK_STATUS_UNKNOWN,
    TASK_SHELL, TASK_GIT, TASK_BUILD, TASK_FILE_READ, TASK_FILE_WRITE, TASK_DOCKER, TASK_CUSTOM,
    Task, TaskResult, RegistrationInfo, AgentMessage, OrchestratorMessage,
)

# Import agent module
from hermes_remote_agent import (
    RemoteAgent, get_local_ip, task_status_to_proto,
    CONNECT_RETRY_DELAY, CONNECT_RETRY_MAX,
)


# ── Fixtures ──

@pytest.fixture
def agent():
    """Create a test agent instance."""
    return RemoteAgent(
        server_addr="localhost:50052",
        agent_id="test-agent-1",
        agent_name="Test Agent",
        auth_token="test-token-123",
        caps=["shell", "git", "file"],
    )


@pytest.fixture
def mock_channel():
    """Create a mock gRPC channel."""
    channel = MagicMock()
    channel.get_state.return_value = MagicMock()  # READY state
    channel.close = AsyncMock()
    return channel


@pytest.fixture
def mock_stream():
    """Create a mock bidirectional stream."""
    stream = AsyncMock()
    stream.write = AsyncMock()
    # Empty async iterator by default (no messages from server)
    stream.__aiter__ = AsyncMock(return_value=iter([]))
    return stream


# ── Test: get_local_ip ──

class TestGetLocalIp:
    def test_returns_string(self):
        """get_local_ip should return a non-empty string."""
        ip = get_local_ip()
        assert isinstance(ip, str)
        assert len(ip) > 0

    def test_returns_ip_format(self):
        """get_local_ip should return something that looks like an IP."""
        ip = get_local_ip()
        # Either dotted decimal or localhost
        assert ip == "127.0.0.1" or "." in ip

    @patch("hermes_remote_agent.socket.socket")
    def test_fallback_on_error(self, mock_socket_cls):
        """get_local_ip should return 127.0.0.1 on error."""
        mock_socket_cls.side_effect = Exception("no network")
        ip = get_local_ip()
        assert ip == "127.0.0.1"


# ── Test: task_status_to_proto ──

class TestTaskStatusToProto:
    def test_success(self):
        assert task_status_to_proto("success") == TASK_SUCCESS

    def test_error(self):
        assert task_status_to_proto("error") == TASK_ERROR

    def test_timeout(self):
        assert task_status_to_proto("timeout") == TASK_TIMEOUT

    def test_cancelled(self):
        assert task_status_to_proto("cancelled") == TASK_CANCELLED

    def test_unknown(self):
        assert task_status_to_proto("unknown") == TASK_STATUS_UNKNOWN

    def test_empty_string(self):
        assert task_status_to_proto("") == TASK_STATUS_UNKNOWN


# ── Test: RemoteAgent initialization ──

class TestRemoteAgentInit:
    def test_basic_init(self, agent):
        assert agent.server_addr == "localhost:50052"
        assert agent.agent_id == "test-agent-1"
        assert agent.agent_name == "Test Agent"
        assert agent.auth_token == "test-token-123"
        assert agent.caps == ["shell", "git", "file"]
        assert agent.running is True

    def test_default_caps(self):
        agent = RemoteAgent("localhost:50052", "id", "name", "token")
        assert agent.caps == ["shell", "git", "build", "file", "docker", "ai"]

    def test_custom_caps(self):
        agent = RemoteAgent("localhost:50052", "id", "name", "token", caps=["shell"])
        assert agent.caps == ["shell"]


# ── Test: Task handling ──

class TestTaskHandling:
    @pytest.mark.asyncio
    async def test_exec_shell_success(self, agent):
        """Shell command should return stdout, stderr, exit_code."""
        stdout, stderr, exit_code = await agent._exec_shell({"command": "echo hello"})
        assert "hello" in stdout
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_exec_shell_error(self, agent):
        """Shell command with non-zero exit should return exit_code."""
        stdout, stderr, exit_code = await agent._exec_shell({"command": "exit 42"})
        assert exit_code == 42

    @pytest.mark.asyncio
    async def test_exec_shell_empty_command(self, agent):
        """Empty command should return error."""
        stdout, stderr, exit_code = await agent._exec_shell({"command": ""})
        assert exit_code == 1
        assert "no command" in stderr

    @pytest.mark.asyncio
    async def test_exec_shell_timeout(self, agent):
        """Long-running command should timeout."""
        stdout, stderr, exit_code = await agent._exec_shell({"command": "sleep 300"})
        assert exit_code == 124
        assert "timeout" in stderr

    @pytest.mark.asyncio
    async def test_exec_git_status(self, agent):
        """Git status should work in a git repo."""
        # This test repo is a git repo
        stdout, stderr, exit_code = await agent._exec_git({"subcommand": "status"})
        # Should succeed (exit 0) even if dirty
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_exec_git_no_subcommand(self, agent):
        """Git with no subcommand should return error."""
        stdout, stderr, exit_code = await agent._exec_git({})
        assert exit_code == 1
        assert "no git subcommand" in stderr

    @pytest.mark.asyncio
    async def test_read_file_success(self, agent):
        """Reading an existing file should return content."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test content")
            f.flush()
            path = f.name

        try:
            stdout, stderr, exit_code = await agent._read_file({"path": path})
            assert "test content" in stdout
            assert exit_code == 0
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, agent):
        """Reading a non-existent file should return error."""
        stdout, stderr, exit_code = await agent._read_file({"path": "/tmp/nonexistent_12345.txt"})
        assert exit_code == 1
        assert len(stderr) > 0

    @pytest.mark.asyncio
    async def test_read_file_no_path(self, agent):
        """File read with no path should return error."""
        stdout, stderr, exit_code = await agent._read_file({})
        assert exit_code == 1
        assert "no path" in stderr

    @pytest.mark.asyncio
    async def test_write_file_success(self, agent):
        """Writing a file should create it with content."""
        path = f"/tmp/test_agent_write_{os.getpid()}.txt"
        try:
            stdout, stderr, exit_code = await agent._write_file({
                "path": path,
                "content": "hello agent",
            })
            assert exit_code == 0
            assert Path(path).read_text() == "hello agent"
        finally:
            if Path(path).exists():
                os.unlink(path)

    @pytest.mark.asyncio
    async def test_write_file_no_path(self, agent):
        """File write with no path should return error."""
        stdout, stderr, exit_code = await agent._write_file({"content": "data"})
        assert exit_code == 1
        assert "no path" in stderr

    @pytest.mark.asyncio
    async def test_exec_build(self, agent):
        """Build command should execute in specified directory."""
        stdout, stderr, exit_code = await agent._exec_build(
            {"command": "echo build ok"},
            working_dir="/tmp",
        )
        assert "build ok" in stdout
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_exec_docker_no_command(self, agent):
        """Docker with no command should return error."""
        stdout, stderr, exit_code = await agent._exec_docker({"command": ""})
        assert exit_code == 1
        assert "no docker command" in stderr


# ── Test: Task result construction ──

class TestTaskResult:
    def test_task_result_proto_fields(self):
        """TaskResult proto should have all required fields."""
        result = TaskResult(
            task_id="task-1",
            status=TASK_SUCCESS,
            stdout="output",
            stderr="",
            exit_code=0,
            duration_ms=100,
        )
        assert result.task_id == "task-1"
        assert result.status == TASK_SUCCESS
        assert result.stdout == "output"
        assert result.exit_code == 0
        assert result.duration_ms == 100

    def test_task_result_serialization(self):
        """TaskResult should serialize and deserialize."""
        result = TaskResult(
            task_id="task-2",
            status=TASK_ERROR,
            stdout="out",
            stderr="err",
            exit_code=1,
            duration_ms=200,
        )
        data = result.SerializeToString()
        restored = TaskResult()
        restored.ParseFromString(data)
        assert restored.task_id == "task-2"
        assert restored.status == TASK_ERROR
        assert restored.exit_code == 1


# ── Test: Registration proto ──

class TestRegistrationProto:
    def test_registration_info_fields(self):
        """RegistrationInfo should have all required fields."""
        reg = RegistrationInfo(
            agent_id="agent-1",
            agent_name="Test",
            version="1.0.0",
            host="localhost",
            ip_address="127.0.0.1",
            os="linux",
            capabilities=["shell", "git"],
            auth_token="token123",
        )
        assert reg.agent_id == "agent-1"
        assert reg.capabilities == ["shell", "git"]
        assert reg.auth_token == "token123"

    def test_agent_message_with_registration(self):
        """AgentMessage should wrap RegistrationInfo."""
        reg = RegistrationInfo(
            agent_id="agent-1",
            agent_name="Test",
            auth_token="token",
        )
        msg = AgentMessage(
            agent_id="agent-1",
            type=AGENT_REGISTER,
            payload=reg.SerializeToString(),
            timestamp_ms=1234567890,
        )
        assert msg.type == AGENT_REGISTER
        assert msg.agent_id == "agent-1"

        # Deserialize payload
        restored_reg = RegistrationInfo()
        restored_reg.ParseFromString(msg.payload)
        assert restored_reg.agent_id == "agent-1"


# ── Test: Heartbeat message ──

class TestHeartbeat:
    def test_heartbeat_message_type(self):
        """Heartbeat should use AGENT_HEARTBEAT type."""
        msg = AgentMessage(
            agent_id="agent-1",
            type=AGENT_HEARTBEAT,
            timestamp_ms=int(time.time() * 1000),
        )
        assert msg.type == AGENT_HEARTBEAT


# ── Test: Config loading ──

class TestConfig:
    def test_config_from_json(self):
        """Config should load from JSON file."""
        config_data = {
            "server_addr": "localhost:50052",
            "agent_id": "config-agent",
            "agent_name": "Config Agent",
            "auth_token": "config-token",
            "capabilities": ["shell", "git"],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            f.flush()
            path = f.name

        try:
            with open(path) as f:
                loaded = json.load(f)
            assert loaded["server_addr"] == "localhost:50052"
            assert loaded["agent_id"] == "config-agent"
            assert loaded["capabilities"] == ["shell", "git"]
        finally:
            os.unlink(path)

    def test_config_defaults(self):
        """Config with minimal fields should use defaults."""
        config_data = {"auth_token": "token"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            f.flush()
            path = f.name

        try:
            with open(path) as f:
                loaded = json.load(f)
            assert loaded.get("server_addr", "localhost:50052") == "localhost:50052"
        finally:
            os.unlink(path)


# ── Test: Retry config ──

class TestRetryConfig:
    def test_retry_constants(self):
        """Retry constants should be reasonable."""
        assert CONNECT_RETRY_DELAY == 5
        assert CONNECT_RETRY_MAX == 60


# ── Test: Proto message types ──

class TestProtoMessageTypes:
    def test_agent_message_types_exist(self):
        """All agent message types should be defined."""
        assert AGENT_REGISTER is not None
        assert AGENT_HEARTBEAT is not None
        assert AGENT_TASK_RESULT is not None
        assert AGENT_DISCONNECT is not None

    def test_orchestrator_message_types_exist(self):
        """All orchestrator message types should be defined."""
        assert ORCHESTRATOR_TASK is not None
        assert ORCHESTRATOR_PING is not None
        assert ORCHESTRATOR_DISCONNECT is not None

    def test_task_types_exist(self):
        """All task types should be defined."""
        assert TASK_SHELL is not None
        assert TASK_GIT is not None
        assert TASK_BUILD is not None
        assert TASK_FILE_READ is not None
        assert TASK_FILE_WRITE is not None
        assert TASK_DOCKER is not None
        assert TASK_CUSTOM is not None

    def test_task_statuses_exist(self):
        """All task statuses should be defined."""
        assert TASK_SUCCESS is not None
        assert TASK_ERROR is not None
        assert TASK_TIMEOUT is not None
        assert TASK_CANCELLED is not None


# ── Test: _handle_task integration ──

class TestHandleTask:
    @pytest.mark.asyncio
    async def test_handle_shell_task(self, agent, mock_stream):
        """_handle_task should process shell task and send result."""
        agent.stream = mock_stream

        task = Task(
            task_id="task-1",
            task_type=TASK_SHELL,
            params={"command": "echo test"},
            working_dir="",
        )

        await agent._handle_task(task)

        # Should have written a result message
        assert mock_stream.write.called
        call_args = mock_stream.write.call_args
        msg = call_args[0][0]
        assert msg.type == AGENT_TASK_RESULT
        assert msg.agent_id == "test-agent-1"

        # Deserialize and check result
        result = TaskResult()
        result.ParseFromString(msg.payload)
        assert result.task_id == "task-1"
        assert result.status == TASK_SUCCESS
        assert "test" in result.stdout
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_handle_task_error(self, agent, mock_stream):
        """_handle_task should return error status for failing command."""
        agent.stream = mock_stream

        task = Task(
            task_id="task-err",
            task_type=TASK_SHELL,
            params={"command": "exit 42"},
            working_dir="",
        )

        await agent._handle_task(task)

        call_args = mock_stream.write.call_args
        msg = call_args[0][0]
        result = TaskResult()
        result.ParseFromString(msg.payload)
        assert result.status == TASK_ERROR
        assert result.exit_code == 42

    @pytest.mark.asyncio
    async def test_handle_unsupported_task(self, agent, mock_stream):
        """_handle_task should return error for unsupported task type."""
        agent.stream = mock_stream

        task = Task(
            task_id="task-bad",
            task_type=999,  # unknown type
            params={},
            working_dir="",
        )

        await agent._handle_task(task)

        call_args = mock_stream.write.call_args
        msg = call_args[0][0]
        result = TaskResult()
        result.ParseFromString(msg.payload)
        assert result.exit_code == 1
        assert "Unsupported" in result.stderr


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
