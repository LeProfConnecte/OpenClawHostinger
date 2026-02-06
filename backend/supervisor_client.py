"""
Supervisor client for managing the clawdbot gateway process.

This module provides a clean interface for starting, stopping, and
checking the status of the gateway process managed by supervisord.

When the backend runs as a non-root user (e.g. CloudPanel site user),
commands are prefixed with `sudo`. The deploy script configures sudoers
to allow passwordless supervisorctl for the site user.
"""

import os
import re
import subprocess
import logging

logger = logging.getLogger(__name__)

# Validate program name to prevent command injection via env var
_SAFE_PROGRAM_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


def _validate_program_name(name: str) -> str:
    """Validate that a supervisor program name is safe."""
    if not name or not _SAFE_PROGRAM_RE.match(name):
        raise ValueError(
            f"Invalid supervisor program name: {name!r}. "
            "Only alphanumeric, dashes, and underscores are allowed."
        )
    if len(name) > 64:
        raise ValueError(f"Program name too long (max 64 chars): {name!r}")
    return name


def _build_cmd(args: list[str]) -> list[str]:
    """
    Build the supervisorctl command, prefixing with sudo if not root.

    On CloudPanel, the backend runs as the site user (e.g. myopenclaw).
    The deploy script creates /etc/sudoers.d/openclaw to allow passwordless
    supervisorctl for the site user.
    """
    if os.geteuid() == 0:
        return args
    return ['sudo', '-n'] + args


class SupervisorClient:
    """Client for interacting with supervisord to manage the gateway process."""

    PROGRAM = _validate_program_name(
        os.environ.get("SUPERVISOR_GATEWAY_PROGRAM", "clawdbot-gateway")
    )

    @classmethod
    def start(cls) -> bool:
        """
        Start the gateway via supervisor.

        Returns:
            True if the start command succeeded, False otherwise.
        """
        try:
            result = subprocess.run(
                _build_cmd(['supervisorctl', 'start', cls.PROGRAM]),
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                logger.info("Started %s via supervisor", cls.PROGRAM)
                return True
            else:
                logger.error("Failed to start %s: %s", cls.PROGRAM, result.stderr)
                return False
        except subprocess.TimeoutExpired:
            logger.error("Timeout starting %s", cls.PROGRAM)
            return False
        except Exception as e:
            logger.error("Error starting %s: %s", cls.PROGRAM, e)
            return False

    @classmethod
    def stop(cls) -> bool:
        """
        Stop the gateway via supervisor.

        Returns:
            True if the stop command succeeded, False otherwise.
        """
        try:
            result = subprocess.run(
                _build_cmd(['supervisorctl', 'stop', cls.PROGRAM]),
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0 or 'NOT RUNNING' in result.stdout:
                logger.info("Stopped %s via supervisor", cls.PROGRAM)
                return True
            else:
                logger.error("Failed to stop %s: %s", cls.PROGRAM, result.stderr)
                return False
        except subprocess.TimeoutExpired:
            logger.error("Timeout stopping %s", cls.PROGRAM)
            return False
        except Exception as e:
            logger.error("Error stopping %s: %s", cls.PROGRAM, e)
            return False

    @classmethod
    def status(cls) -> bool:
        """
        Check if the gateway is running via supervisor.

        Returns:
            True if the process is running (RUNNING state), False otherwise.
        """
        try:
            result = subprocess.run(
                _build_cmd(['supervisorctl', 'status', cls.PROGRAM]),
                capture_output=True,
                text=True,
                timeout=10
            )
            # Check for RUNNING state in output
            # Output format: "clawdbot-gateway            RUNNING   pid 12345, uptime 0:01:23"
            return 'RUNNING' in result.stdout
        except Exception as e:
            logger.error("Error checking %s status: %s", cls.PROGRAM, e)
            return False

    @classmethod
    def get_pid(cls) -> int | None:
        """
        Get the PID of the running gateway process.

        Returns:
            The PID if running, None otherwise.
        """
        try:
            result = subprocess.run(
                _build_cmd(['supervisorctl', 'status', cls.PROGRAM]),
                capture_output=True,
                text=True,
                timeout=10
            )
            # Parse PID from output like: "clawdbot-gateway            RUNNING   pid 12345, uptime 0:01:23"
            if 'RUNNING' in result.stdout and 'pid' in result.stdout:
                # Extract pid number
                parts = result.stdout.split('pid')
                if len(parts) > 1:
                    pid_part = parts[1].strip().split(',')[0].strip()
                    return int(pid_part)
            return None
        except Exception as e:
            logger.error("Error getting %s PID: %s", cls.PROGRAM, e)
            return None

    @classmethod
    def restart(cls) -> bool:
        """
        Restart the gateway via supervisor.

        Returns:
            True if the restart command succeeded, False otherwise.
        """
        try:
            result = subprocess.run(
                _build_cmd(['supervisorctl', 'restart', cls.PROGRAM]),
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                logger.info("Restarted %s via supervisor", cls.PROGRAM)
                return True
            else:
                logger.error("Failed to restart %s: %s", cls.PROGRAM, result.stderr)
                return False
        except subprocess.TimeoutExpired:
            logger.error("Timeout restarting %s", cls.PROGRAM)
            return False
        except Exception as e:
            logger.error("Error restarting %s: %s", cls.PROGRAM, e)
            return False

    @classmethod
    def reload_config(cls) -> bool:
        """
        Reload supervisor configuration.

        Call this after modifying supervisor config files.

        Returns:
            True if reload succeeded, False otherwise.
        """
        try:
            result = subprocess.run(
                _build_cmd(['supervisorctl', 'reread']),
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                logger.error("Failed to reread supervisor config: %s", result.stderr)
                return False

            result = subprocess.run(
                _build_cmd(['supervisorctl', 'update']),
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                logger.error("Failed to update supervisor: %s", result.stderr)
                return False

            logger.info("Supervisor configuration reloaded")
            return True
        except Exception as e:
            logger.error("Error reloading supervisor config: %s", e)
            return False
