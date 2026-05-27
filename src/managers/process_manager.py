import os
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from src.models.portforward_config import ForwardEntry

if TYPE_CHECKING:
    from src.managers.logging_manager import LoggingManager

# Prevent console windows from popping up for each kubectl process on Windows.
_CREATE_NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Working directory for kubectl subprocesses.
# Using the user home dir ensures relative certificate paths in kubeconfig resolve
# correctly and credential helpers (kubelogin, aws-iam-authenticator, …) find
# their config files – exactly as they would in an interactive shell.
_KUBECTL_CWD: Path = Path.home()

# After this many consecutive failures the forward is put into ERROR state and
# auto-restart is disabled until the user manually unchecks and re-checks the entry.
MAX_AUTO_RESTARTS = 5

# Seconds to wait after spawning before we confirm the process is actually running.
# kubectl port-forward may exit within milliseconds on errors – this catches that.
STARTUP_CONFIRM_DELAY = 2.0

# Seconds between automatic restart attempts.
RESTART_DELAY = 3

# Seconds between health checks for RUNNING services that have health_check_path set.
# Use a conservative default to avoid stressing services that are sensitive to
# frequent TLS handshakes.
HEALTH_CHECK_INTERVAL = 30

# After this many consecutive health-check failures the forward is restarted.
HEALTH_CHECK_MAX_FAILS = 3

# Timeout in seconds for health check HTTP requests (includes SSL handshake).
HEALTH_CHECK_TIMEOUT = 30


class ForwardStatus(Enum):
    STOPPED = "Stopped"
    STARTING = "Starting..."
    RUNNING = "Running"
    RESTARTING = "Restarting"
    ERROR = "Error"


class ForwardState:
    def __init__(self, entry: ForwardEntry) -> None:
        self.entry = entry
        self.desired_running: bool = False
        self.process: Optional[subprocess.Popen] = None
        self.status: ForwardStatus = ForwardStatus.STOPPED
        self.restart_count: int = 0
        # Resets to 0 whenever a process survives past STARTUP_CONFIRM_DELAY or
        # when the user manually re-enables the forward.
        self.consecutive_failures: int = 0
        self.last_event: str = "-"
        self.error_message: str = ""
        # Health check state
        self.health_status: str = "-"
        self.health_check_fail_count: int = 0
        self.last_health_check_at: float = 0.0  # Timestamp when the last health check was performed
        # True while a health-check thread for this forward is active.
        self.health_check_in_progress: bool = False
        # Internal guard: prevents two threads racing to start the same forward.
        self._starting: bool = False


class ProcessManager:
    """
    Manages kubectl port-forward subprocesses.

    Each registered forward can be started or stopped via set_desired().
    A background monitor thread polls every MONITOR_INTERVAL seconds and
    automatically restarts processes that have died while desired_running=True.
    Auto-restart is limited to MAX_AUTO_RESTARTS consecutive failures; after that
    the forward moves to ERROR status and must be manually re-enabled.
    """

    MONITOR_INTERVAL: int = 5  # seconds

    def __init__(
        self,
        on_status_change: Callable[[str], None],
        logger: Optional["LoggingManager"] = None,
    ) -> None:
        self._states: Dict[str, ForwardState] = {}
        self._on_status_change = on_status_change
        self._logger = logger
        self._lock = threading.Lock()
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="portforward-monitor",
            daemon=True,
        )
        self._monitor_thread.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, entry: ForwardEntry) -> None:
        """Register a forward entry without starting it.
        Safe to call multiple times; subsequent calls update the entry definition."""
        with self._lock:
            if entry.name not in self._states:
                self._states[entry.name] = ForwardState(entry)
            else:
                self._states[entry.name].entry = entry

    def set_logger(self, logger: Optional["LoggingManager"]) -> None:
        """Update the logger instance."""
        with self._lock:
            self._logger = logger

    def set_desired(self, entry: ForwardEntry, running: bool) -> None:
        """Set whether a forward should be running and act on it immediately."""
        with self._lock:
            if entry.name not in self._states:
                self._states[entry.name] = ForwardState(entry)
            state = self._states[entry.name]
            state.desired_running = running
            if running:
                # Manual (re-)enable: reset failure counter so auto-restart works again.
                state.consecutive_failures = 0
                state.error_message = ""
                state.health_status = "-"
                state.health_check_fail_count = 0
                state.last_health_check_at = 0.0
                state.health_check_in_progress = False

        if running:
            self._do_start(entry.name)
        else:
            self._do_stop(entry.name)

    def get_state(self, name: str) -> Optional[ForwardState]:
        with self._lock:
            return self._states.get(name)

    def reset_restart_counts(self) -> None:
        """Reset restart_count to 0 for all forwards."""
        with self._lock:
            for state in self._states.values():
                state.restart_count = 0

    def shutdown(self) -> None:
        """Stop all running processes and terminate the monitor thread."""
        self._running = False
        with self._lock:
            names = list(self._states.keys())
        for name in names:
            self._do_stop(name)
        if self._logger:
            self._logger.shutdown()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _do_start(self, name: str) -> None:
        """Start the kubectl process for *name*. No-op if already running."""
        with self._lock:
            state = self._states.get(name)
            if not state:
                return
            # Guard against concurrent start attempts.
            if state._starting:
                return
            if state.process is not None and state.process.poll() is None:
                return  # Process is still alive.
            if not state.desired_running:
                return
            state._starting = True
            state.status = ForwardStatus.STARTING
            # Clear previous error only when a fresh start is explicitly requested.
            entry = state.entry
            cmd = self._build_cmd(entry)

        self._notify(name)

        process: Optional[subprocess.Popen] = None
        error_msg: str = ""

        try:
            # Inherit the full environment so credential helpers (kubelogin,
            # aws-iam-authenticator, gke-gcloud-auth-plugin, …) work exactly
            # as in an interactive shell.
            env = os.environ.copy()
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,   # capture stdout – some kubectl versions
                stderr=subprocess.STDOUT, # write errors there; merge both pipes
                cwd=str(_KUBECTL_CWD),
                env=env,
                creationflags=_CREATE_NO_WINDOW,
            )
        except FileNotFoundError:
            error_msg = "kubectl not found – is it installed and in PATH?"
        except PermissionError:
            error_msg = f"Permission denied binding to port {entry.local_port}."
        except Exception as exc:
            error_msg = str(exc)

        with self._lock:
            state = self._states.get(name)
            if state:
                state._starting = False
                if process is not None:
                    state.process = process
                    # Stay in STARTING until _confirm_running verifies the process
                    # is still alive after STARTUP_CONFIRM_DELAY seconds.
                    state.last_event = _now()
                else:
                    state.consecutive_failures += 1
                    state.status = ForwardStatus.ERROR
                    state.error_message = error_msg
                    if self._logger:
                        self._logger.log_forward_error(name, error_msg)

        self._notify(name)

        if process is not None:
            # Confirm the process survived the startup grace period.
            # stderr is read synchronously inside _confirm_running once the
            # process has exited, so no separate drain thread is needed.
            threading.Thread(
                target=self._confirm_running,
                args=(name, process),
                daemon=True,
                name=f"confirm-{name}",
            ).start()

    def _confirm_running(self, name: str, process: subprocess.Popen) -> None:
        """
        Wait STARTUP_CONFIRM_DELAY seconds, then:
        - Process still alive → mark RUNNING, reset failure counter.
        - Process already dead → read its stderr, update failure state,
          trigger restart or switch to ERROR.
        """
        time.sleep(STARTUP_CONFIRM_DELAY)

        alive = process.poll() is None

        # Read combined stdout/stderr OUTSIDE the lock.
        # When the process has exited, read() returns immediately.
        error_msg = ""
        if not alive:
            error_msg = _read_output(process)

        should_restart = False

        with self._lock:
            state = self._states.get(name)
            if state is None or state.process is not process:
                return  # Stopped or replaced in the meantime.

            if alive:
                state.status = ForwardStatus.RUNNING
                state.consecutive_failures = 0
                state.error_message = ""
                # Log successful start
                if self._logger:
                    entry = state.entry
                    self._logger.log_forward_started(
                        name,
                        entry.resource,
                        entry.port_mapping,
                    )
            else:
                # Process died during the startup grace period.
                state.process = None
                state.restart_count += 1
                state.consecutive_failures += 1
                state.last_event = _now()
                if error_msg:
                    state.error_message = error_msg
                    if self._logger:
                        self._logger.log_forward_error(name, error_msg)

                if not state.desired_running:
                    state.status = ForwardStatus.STOPPED
                elif state.consecutive_failures >= MAX_AUTO_RESTARTS:
                    state.status = ForwardStatus.ERROR
                    if not state.error_message:
                        state.error_message = (
                            f"Stopped after {MAX_AUTO_RESTARTS} consecutive failures. "
                            "Uncheck and re-check to retry."
                        )
                else:
                    state.status = ForwardStatus.RESTARTING
                    should_restart = True

        self._notify(name)

        if should_restart:
            time.sleep(RESTART_DELAY)
            self._do_start(name)

    def _do_stop(self, name: str) -> None:
        process_to_kill: Optional[subprocess.Popen] = None
        was_running = False

        with self._lock:
            state = self._states.get(name)
            if not state:
                return
            was_running = state.status == ForwardStatus.RUNNING
            process_to_kill = state.process
            state.process = None
            state.status = ForwardStatus.STOPPED
            state.last_event = _now()
            state.health_status = "-"
            state.health_check_in_progress = False

        self._notify(name)

        if process_to_kill is not None:
            try:
                process_to_kill.terminate()
                process_to_kill.wait(timeout=3)
            except Exception:
                try:
                    process_to_kill.kill()
                except Exception:
                    pass

        # Log the stop
        if self._logger and was_running:
            self._logger.log_forward_stopped(name)

    def _monitor_loop(self) -> None:
        while self._running:
            time.sleep(self.MONITOR_INTERVAL)
            self._check_processes()
            self._schedule_health_checks()

    def _check_processes(self) -> None:
        # Collect (name, dead_process) pairs while holding the lock, then
        # read stderr and decide what to do outside the lock.
        dead: List[tuple] = []

        with self._lock:
            for name, state in self._states.items():
                if not state.desired_running or state._starting:
                    continue
                if state.process is None:
                    continue
                if state.process.poll() is not None:
                    # Runtime death: process was RUNNING and then exited.
                    proc = state.process
                    state.process = None
                    state.restart_count += 1
                    state.consecutive_failures += 1
                    state.last_event = _now()
                    dead.append((name, proc))

        for name, proc in dead:
            # Read combined stdout/stderr outside the lock.
            error_msg = _read_output(proc)

            should_restart = False

            with self._lock:
                state = self._states.get(name)
                if state is None:
                    continue
                if error_msg:
                    state.error_message = error_msg
                    if self._logger:
                        self._logger.log_forward_error(name, error_msg)
                if not state.desired_running:
                    state.status = ForwardStatus.STOPPED
                elif state.consecutive_failures >= MAX_AUTO_RESTARTS:
                    state.status = ForwardStatus.ERROR
                    if not state.error_message:
                        state.error_message = (
                            f"Stopped after {MAX_AUTO_RESTARTS} consecutive failures. "
                            "Uncheck and re-check to retry."
                        )
                else:
                    state.status = ForwardStatus.RESTARTING
                    should_restart = True

            self._notify(name)

            if should_restart:
                time.sleep(RESTART_DELAY)
                self._do_start(name)

    def _schedule_health_checks(self) -> None:
        """Spawn a daemon thread for each RUNNING service whose health check is due."""
        now = time.monotonic()
        tasks: List[tuple] = []
        with self._lock:
            for name, state in self._states.items():
                if state.status != ForwardStatus.RUNNING:
                    continue
                # Check if either HTTP or gRPC health check is configured
                has_http_check = state.entry.health_check_path
                has_grpc_check = state.entry.health_check_grpc
                if not (has_http_check or has_grpc_check):
                    continue
                if state.health_check_in_progress:
                    continue
                if now - state.last_health_check_at >= HEALTH_CHECK_INTERVAL:
                    state.last_health_check_at = now
                    state.health_check_in_progress = True
                    tasks.append((
                        name,
                        state.entry.local_port,
                        state.entry.health_check_path,
                        state.entry.health_check_tls,
                        state.entry.health_check_grpc,
                    ))

        for name, port, path, tls, is_grpc in tasks:
            if is_grpc:
                threading.Thread(
                    target=self._do_grpc_health_check,
                    args=(name, port, tls),
                    daemon=True,
                    name=f"health-grpc-{name}",
                ).start()
            else:
                threading.Thread(
                    target=self._do_health_check,
                    args=(name, port, path, tls),
                    daemon=True,
                    name=f"health-{name}",
                ).start()

    def _do_health_check(self, name: str, port: int, path: str, tls: bool) -> None:
        """Perform a single HTTP/HTTPS health check and update the state accordingly."""
        scheme = "https" if tls else "http"
        url = f"{scheme}://127.0.0.1:{port}{path}"
        ok = False
        error_detail = ""
        try:
            if tls:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(url, timeout=HEALTH_CHECK_TIMEOUT, context=ctx):  # noqa: S310
                    ok = True
            else:
                with urllib.request.urlopen(url, timeout=HEALTH_CHECK_TIMEOUT):  # noqa: S310
                    ok = True
        except urllib.error.HTTPError as exc:
            # Treat any HTTP response (even 4xx/5xx) as reachable – the tunnel works.
            ok = exc.code < 500
            if not ok:
                error_detail = f"HTTP {exc.code}"
        except urllib.error.URLError as exc:
            ok = False
            error_detail = str(exc.reason)
        except Exception as exc:
            ok = False
            error_detail = str(exc)

        should_restart = False
        with self._lock:
            state = self._states.get(name)
            if state is None:
                return
            # Mark check as completed regardless of service state.
            state.health_check_in_progress = False
            # Use completion timestamp so next check is spaced from end of request.
            state.last_health_check_at = time.monotonic()
            if state.status != ForwardStatus.RUNNING:
                return
            if ok:
                state.health_status = "OK"
                state.health_check_fail_count = 0
            else:
                state.health_check_fail_count += 1
                state.health_status = f"FAIL ({state.health_check_fail_count})"
                # Log health check failure
                if self._logger:
                    self._logger.log_health_check_failure(
                        name, port, path, state.health_check_fail_count, error_detail, tls
                    )
                if (
                    state.health_check_fail_count >= HEALTH_CHECK_MAX_FAILS
                    and state.desired_running
                ):
                    # Too many consecutive failures – restart the port-forward.
                    state.health_check_fail_count = 0
                    state.consecutive_failures = 0
                    state.restart_count += 1
                    should_restart = True
                    if self._logger:
                        self._logger.log_forward_restarting(
                            name, f"Health check failures (max {HEALTH_CHECK_MAX_FAILS} reached)"
                        )

        self._notify(name)

        if should_restart:
            self._do_stop(name)
            time.sleep(RESTART_DELAY)
            self._do_start(name)

    def _do_grpc_health_check(self, name: str, port: int, tls: bool) -> None:
        """Perform a single gRPC health check (grpc.health.v1.Health/Check) and update the state accordingly."""
        ok = False
        error_detail = ""
        
        try:
            import grpc
            from grpc_health.v1 import health_pb2, health_pb2_grpc
        except ImportError as exc:
            error_detail = f"grpcio packages not installed: {exc}. Install with: pip install grpcio grpcio-health-checking"
            ok = False
        else:
            try:
                # Create channel with or without TLS
                target = f"127.0.0.1:{port}"
                
                if tls:
                    # Create a secure channel with certificate verification disabled
                    credentials = grpc.ssl_channel_credentials()
                    channel = grpc.secure_channel(target, credentials)
                else:
                    # Create an insecure channel
                    channel = grpc.insecure_channel(target)
                
                try:
                    # Create a stub and call the health check
                    stub = health_pb2_grpc.HealthStub(channel)
                    request = health_pb2.HealthCheckRequest(service="")
                    response = stub.Check(request, timeout=HEALTH_CHECK_TIMEOUT)
                    
                    # Check the response status
                    if response.status == health_pb2.HealthCheckResponse.SERVING:
                        ok = True
                    else:
                        status_name = health_pb2.HealthCheckResponse.ServingStatus.Name(response.status)
                        error_detail = f"Status: {status_name}"
                finally:
                    # Close the channel
                    channel.close()
                    
            except grpc.RpcError as rpc_err:
                error_detail = f"gRPC error: {rpc_err.details() if hasattr(rpc_err, 'details') else str(rpc_err)}"
                ok = False
            except Exception as exc:
                error_detail = str(exc)
                ok = False

        should_restart = False
        with self._lock:
            state = self._states.get(name)
            if state is None:
                return
            # Mark check as completed regardless of service state.
            state.health_check_in_progress = False
            # Use completion timestamp so next check is spaced from end of request.
            state.last_health_check_at = time.monotonic()
            if state.status != ForwardStatus.RUNNING:
                return
            if ok:
                state.health_status = "OK"
                state.health_check_fail_count = 0
            else:
                state.health_check_fail_count += 1
                state.health_status = f"FAIL ({state.health_check_fail_count})"
                # Log health check failure
                if self._logger:
                    self._logger.log_health_check_failure(
                        name, port, None, state.health_check_fail_count, error_detail, tls
                    )
                if (
                    state.health_check_fail_count >= HEALTH_CHECK_MAX_FAILS
                    and state.desired_running
                ):
                    # Too many consecutive failures – restart the port-forward.
                    state.health_check_fail_count = 0
                    state.consecutive_failures = 0
                    state.restart_count += 1
                    should_restart = True
                    if self._logger:
                        self._logger.log_forward_restarting(
                            name, f"gRPC health check failures (max {HEALTH_CHECK_MAX_FAILS} reached)"
                        )

        self._notify(name)

        if should_restart:
            self._do_stop(name)
            time.sleep(RESTART_DELAY)
            self._do_start(name)

    @staticmethod
    def _build_cmd(entry: ForwardEntry) -> List[str]:
        cmd = [
            "kubectl",
            "port-forward",
            entry.resource,
            f"{entry.local_port}:{entry.remote_port}",
        ]
        if entry.context:
            cmd.extend(["--context", entry.context])
        return cmd

    def _notify(self, name: str) -> None:
        try:
            self._on_status_change(name)
        except Exception:
            pass


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _read_output(process: subprocess.Popen) -> str:
    """Read all available output from a terminated process (stdout+stderr merged).

    Returns the last non-empty line, or '' if nothing was captured.
    Stdout and stderr are merged into a single pipe via stderr=STDOUT, so we
    only need to read from stdout here.
    """
    pipe = process.stdout or process.stderr
    if pipe is None:
        return ""
    try:
        raw = pipe.read()
        if not raw:
            return ""
        lines = [ln.strip() for ln in raw.decode(errors="replace").splitlines() if ln.strip()]
        return lines[-1] if lines else ""
    except Exception:
        return ""
