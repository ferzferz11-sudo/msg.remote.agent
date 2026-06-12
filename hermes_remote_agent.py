#!/usr/bin/env python3
"""
Hermes Remote Agent — подключается к серверу Lavender Messenger
через gRPC Connect и выполняет задачи.

Запуск:
    python3 hermes_remote_agent.py --server 13.140.25.249:50052 --token <jwt>
    
Или через конфиг:
    python3 hermes_remote_agent.py --config /root/.hermes/remote-agent.json
"""

import argparse
import asyncio
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

# ── proto path ──
SCRIPT_DIR = Path(__file__).resolve().parent
# Try multiple paths for proto-generated files
for p in [SCRIPT_DIR, SCRIPT_DIR.parent / "hermes-agent", SCRIPT_DIR.parent]:
    sys.path.insert(0, str(p))

try:
    import grpc
except ImportError:
    print("[FATAL] grpcio not installed. Run: pip3 install grpcio")
    sys.exit(1)

# Import generated proto — try multiple locations
pb = None
pb_grpc = None

for proto_path in [SCRIPT_DIR, SCRIPT_DIR.parent / "hermes-agent"]:
    for suffix in ["", ".py"]:
        try:
            sys.path.insert(0, str(proto_path))
            if (proto_path / "hermes_remote_pb2.py").exists():
                import hermes_remote_pb2 as pb
                import hermes_remote_pb2_grpc as pb_grpc
                break
        except ImportError:
            continue
    if pb:
        break

# If proto not found, generate it
if pb is None:
    print("[INFO] Proto files not found, searching for .proto...")
    proto_file = None
    for search_dir in [SCRIPT_DIR, SCRIPT_DIR.parent, Path("/root/msg")]:
        candidate = search_dir / "hermes_remote.proto"
        if candidate.exists():
            proto_file = candidate
            break
    
    if proto_file is None:
        print("[FATAL] hermes_remote.proto not found!")
        print(f"[FATAL] Searched in: {[str(d) for d in [SCRIPT_DIR, SCRIPT_DIR.parent, Path('/root/msg')]]}")
        sys.exit(1)
    
    print(f"[INFO] Found proto at {proto_file}")
    
    # Generate Python proto files
    try:
        from grpc_tools import protoc
        out_dir = SCRIPT_DIR / "gen"
        out_dir.mkdir(exist_ok=True)
        result = protoc.main([
            "grpc_tools.protoc",
            f"--proto_path={proto_file.parent}",
            f"--python_out={out_dir}",
            f"--grpc_python_out={out_dir}",
            str(proto_file),
        ])
        if result != 0:
            print("[FATAL] protoc failed")
            sys.exit(1)
        sys.path.insert(0, str(out_dir))
        import hermes_remote_pb2 as pb
        import hermes_remote_pb2_grpc as pb_grpc
        print("[INFO] Proto generated successfully")
    except ImportError:
        print("[FATAL] grpcio-tools not installed. Run: pip3 install grpcio-tools")
        sys.exit(1)


# ── retry config ──
CONNECT_RETRY_DELAY = 5       # seconds between connect retries
CONNECT_RETRY_MAX = 60        # max delay between retries
CONNECT_RETRY_FOREVER = True  # keep retrying forever


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def task_status_to_proto(status):
    mapping = {
        "success": pb.TASK_SUCCESS,
        "error": pb.TASK_ERROR,
        "timeout": pb.TASK_TIMEOUT,
        "cancelled": pb.TASK_CANCELLED,
    }
    return mapping.get(status, pb.TASK_STATUS_UNKNOWN)


class RemoteAgent:
    def __init__(self, server_addr, agent_id, agent_name, auth_token, caps=None):
        self.server_addr = server_addr
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.auth_token = auth_token
        self.caps = caps or ["shell", "git", "build", "file", "docker", "ai"]
        self.channel = None
        self.stream = None
        self.running = True

    async def connect(self):
        """Connect to the server with retry. Returns after successful registration."""
        retry_delay = CONNECT_RETRY_DELAY

        while self.running:
            try:
                print(f"[Agent] Connecting to {self.server_addr} as '{self.agent_name}' (id={self.agent_id})")

                self.channel = grpc.aio.insecure_channel(self.server_addr)
                stub = pb_grpc.HermesAgentServiceStub(self.channel)

                # Bidirectional stream with auth metadata
                metadata = (("authorization", f"Bearer {self.auth_token}"),)
                self.stream = stub.Connect(metadata=metadata)

                # Wait a moment to see if server rejects the token immediately
                # The server validates on first message, so we check channel state
                await asyncio.sleep(0.5)
                state = self.channel.get_state(try_to_connect=False)
                if state in (grpc.ChannelConnectivity.TRANSIENT_FAILURE, grpc.ChannelConnectivity.SHUTDOWN):
                    print(f"[Agent] Channel not ready (state={state}), retrying in {retry_delay}s...")
                    await self._cleanup_channel()
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, CONNECT_RETRY_MAX)
                    continue

                # Send registration
                reg = pb.RegistrationInfo(
                    agent_id=self.agent_id,
                    agent_name=self.agent_name,
                    version="1.0.0",
                    host=platform.node(),
                    ip_address=get_local_ip(),
                    os=platform.system().lower(),
                    capabilities=self.caps,
                    auth_token=self.auth_token,
                )
                reg_msg = pb.AgentMessage(
                    agent_id=self.agent_id,
                    type=pb.AGENT_REGISTER,
                    payload=reg.SerializeToString(),
                    timestamp_ms=int(time.time() * 1000),
                )
                await self.stream.write(reg_msg)
                print(f"[Agent] Connected and registered. Caps: {', '.join(self.caps)}")
                return  # success

            except grpc.aio.AioRpcError as e:
                code = e.code()
                details = e.details() or "unknown"
                if code == grpc.StatusCode.UNAUTHENTICATED:
                    print(f"[Agent] AUTH FAILED: {details}")
                    print("[Agent] Token is invalid or expired. Generate a new token in the app.")
                    # Don retry on auth failure — it won't fix itself
                    self.running = False
                    await self._cleanup_channel()
                    return
                elif code == grpc.StatusCode.UNAVAILABLE:
                    print(f"[Agent] Server unavailable: {details}. Retrying in {retry_delay}s...")
                else:
                    print(f"[Agent] RPC error: {code}: {details}. Retrying in {retry_delay}s...")
                await self._cleanup_channel()
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, CONNECT_RETRY_MAX)

            except Exception as e:
                print(f"[Agent] Connect error: {e}. Retrying in {retry_delay}s...")
                await self._cleanup_channel()
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, CONNECT_RETRY_MAX)

    async def _cleanup_channel(self):
        if self.channel:
            try:
                await self.channel.close()
            except Exception:
                pass
            self.channel = None
        self.stream = None

    async def run(self):
        """Main loop: receive and process messages. Auto-reconnect on failure."""
        while self.running:
            if self.stream is None:
                await self.connect()
                if self.stream is None:
                    # Connect failed permanently
                    break

            # Heartbeat
            heartbeat_task = asyncio.create_task(self._heartbeat())

            try:
                async for msg in self.stream:
                    if not self.running:
                        break

                    if msg.type == pb.ORCHESTRATOR_TASK:
                        task = pb.Task()
                        task.ParseFromString(msg.payload)
                        asyncio.create_task(self._handle_task(task))

                    elif msg.type == pb.ORCHESTRATOR_PING:
                        pass

                    elif msg.type == pb.ORCHESTRATOR_DISCONNECT:
                        print("[Agent] Disconnect requested by server")
                        self.running = False
                        break

            except grpc.aio.AioRpcError as e:
                print(f"[Agent] Stream RPC error: {e.code()}: {e.details()}")
                if e.code() == grpc.StatusCode.UNAUTHENTICATED:
                    print("[Agent] Token rejected. Stopping.")
                    self.running = False
                    break
            except Exception as e:
                print(f"[Agent] Stream error: {e}")
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except (asyncio.CancelledError, Exception):
                    pass

            if not self.running:
                break

            print(f"[Agent] Lost connection. Reconnecting in {CONNECT_RETRY_DELAY}s...")
            self.stream = None
            await asyncio.sleep(CONNECT_RETRY_DELAY)

    async def _handle_task(self, task):
        try:
            type_name = pb.TaskType.Name(task.task_type)
        except ValueError:
            type_name = f"UNKNOWN({task.task_type})"
        print(f"[Agent] Task {task.task_id}: type={type_name}, params={dict(task.params)}")
        start = time.time()

        stdout, stderr, exit_code = "", "", 0
        status = "success"

        try:
            if task.task_type in (pb.TASK_SHELL, pb.TASK_AI):
                stdout, stderr, exit_code = await self._exec_shell(task.params)
            elif task.task_type == pb.TASK_GIT:
                stdout, stderr, exit_code = await self._exec_git(task.params)
            elif task.task_type == pb.TASK_BUILD:
                stdout, stderr, exit_code = await self._exec_build(task.params, task.working_dir)
            elif task.task_type == pb.TASK_FILE_READ:
                stdout, stderr, exit_code = await self._read_file(task.params)
            elif task.task_type == pb.TASK_FILE_WRITE:
                stdout, stderr, exit_code = await self._write_file(task.params)
            elif task.task_type == pb.TASK_DOCKER:
                stdout, stderr, exit_code = await self._exec_docker(task.params)
            elif task.task_type == pb.TASK_CUSTOM:
                stdout, stderr, exit_code = await self._exec_shell(task.params)
            else:
                stderr = f"Unsupported: {type_name}"
                exit_code = 1
        except Exception as e:
            stderr = str(e)
            exit_code = 1

        if exit_code != 0:
            status = "error"

        duration_ms = int((time.time() - start) * 1000)

        result = pb.TaskResult(
            task_id=task.task_id,
            status=task_status_to_proto(status),
            stdout=stdout[:10000],
            stderr=stderr[:5000],
            exit_code=exit_code,
            duration_ms=duration_ms,
        )

        try:
            await self.stream.write(pb.AgentMessage(
                agent_id=self.agent_id,
                type=pb.AGENT_TASK_RESULT,
                payload=result.SerializeToString(),
                timestamp_ms=int(time.time() * 1000),
            ))
            print(f"[Agent] Task {task.task_id} done: {status} (exit={exit_code}, {duration_ms}ms)")
            if stdout:
                print(f"[Agent] stdout: {stdout[:200]}")
        except Exception as e:
            print(f"[Agent] Failed to send result: {e}")

    async def _exec_shell(self, params):
        cmd = params.get("command", "")
        if not cmd:
            return "", "no command specified", 1
        print(f"[Agent] Shell: {cmd}")
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            return stdout.decode(errors="replace"), stderr.decode(errors="replace"), proc.returncode or 0
        except asyncio.TimeoutError:
            proc.kill()
            return "", "timeout", 124

    async def _exec_git(self, params):
        args = []
        for key in ["subcommand", "args", "message", "branch", "remote", "path"]:
            if key in params:
                args.append(params[key])
        if not args:
            return "", "no git subcommand", 1
        print(f"[Agent] git {' '.join(args)}")
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            return stdout.decode(errors="replace"), stderr.decode(errors="replace"), proc.returncode or 0
        except asyncio.TimeoutError:
            proc.kill()
            return "", "timeout", 124

    async def _exec_build(self, params, working_dir):
        cmd = params.get("command", "go build ./...")
        print(f"[Agent] Build: {cmd} (dir={working_dir})")
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir or None,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            return stdout.decode(errors="replace"), stderr.decode(errors="replace"), proc.returncode or 0
        except asyncio.TimeoutError:
            proc.kill()
            return "", "timeout", 124

    async def _read_file(self, params):
        path = params.get("path", "")
        if not path:
            return "", "no path", 1
        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, lambda: Path(path).read_text(errors="replace"))
            return data, "", 0
        except Exception as e:
            return "", str(e), 1

    async def _write_file(self, params):
        path = params.get("path", "")
        content = params.get("content", "")
        if not path:
            return "", "no path", 1
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: Path(path).write_text(content))
            return "written", "", 0
        except Exception as e:
            return "", str(e), 1

    async def _exec_docker(self, params):
        cmd = params.get("command", "")
        if not cmd:
            return "", "no docker command", 1
        print(f"[Agent] Docker: {cmd}")
        try:
            proc = await asyncio.create_subprocess_shell(
                f"docker {cmd}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            return stdout.decode(errors="replace"), stderr.decode(errors="replace"), proc.returncode or 0
        except asyncio.TimeoutError:
            proc.kill()
            return "", "timeout", 124

    async def _heartbeat(self):
        while self.running:
            await asyncio.sleep(30)
            try:
                await self.stream.write(pb.AgentMessage(
                    agent_id=self.agent_id,
                    type=pb.AGENT_HEARTBEAT,
                    timestamp_ms=int(time.time() * 1000),
                ))
            except Exception:
                break


async def main():
    parser = argparse.ArgumentParser(description="Hermes Remote Agent for Lavender Messenger")
    parser.add_argument("--config", default="", help="Config JSON file")
    parser.add_argument("--server", default="localhost:50052", help="Server gRPC address")
    parser.add_argument("--agent-id", default="", help="Agent ID")
    parser.add_argument("--agent-name", default="Hermes Agent", help="Agent name")
    parser.add_argument("--token", default="", help="JWT auth token")
    parser.add_argument("--caps", default="shell,git,build,file,docker,ai", help="Capabilities (comma-separated)")
    args = parser.parse_args()

    # Load config file if provided
    config = {}
    if args.config and Path(args.config).exists():
        with open(args.config) as f:
            config = json.load(f)

    server = args.server or config.get("server_addr", "localhost:50052")
    agent_id = args.agent_id or config.get("agent_id", f"agent-{os.getpid()}")
    agent_name = args.agent_name or config.get("agent_name", "Hermes Agent")
    token = args.token or config.get("auth_token", "")
    caps = args.caps.split(",") if args.caps else config.get("capabilities", ["shell", "git", "build", "file", "docker", "ai"])

    if not token:
        print("[FATAL] No auth token! Use --token or config file with 'auth_token'")
        print("\nTo generate a token:")
        print("  1. Open Lavender app → Агенты → ⚙ → Сгенерировать токен")
        print("  2. Copy the token")
        print("  3. Run: python3 hermes_remote_agent.py --token <your-token>")
        sys.exit(1)

    agent = RemoteAgent(server, agent_id, agent_name, token, caps)

    def shutdown(sig, frame):
        print(f"\n[Agent] Signal {sig}, shutting down...")
        agent.running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    await agent.connect()
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
