"""Own a loopback game server without requiring a second terminal."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import IO, Optional, final

ROOT = Path(__file__).resolve().parent
MAX_STARTUP_POLLS = 150
POLL_SECONDS = 0.1


@final
class LocalServer:
    """Start and stop only the child server owned by this launcher.

    Parameters
    ----------
    project_dir : Path, optional
        Repository containing server.py; defaults to this module's directory.
    data_dir : Path, optional
        Runtime database, logs and replay directory; defaults to the repository.
    seed : int, default 0
        Seed shared by the session's game RNGs.
    ruleset : {'research', 'legacy'}, default 'research'
        Versioned progression profile.
    timed : bool, default False
        Automatically end preparation when its timer expires.
    fast : bool, default False
        Simulate combat without wall-clock delays for headless data generation.
    """

    def __init__(
        self,
        project_dir: Optional[Path] = None,
        data_dir: Optional[Path] = None,
        seed: int = 0,
        ruleset: str = "research",
        timed: bool = False,
        fast: bool = False,
    ) -> None:
        if ruleset not in ("research", "legacy"):
            raise ValueError("Unknown ruleset")
        if not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
            raise ValueError("Seed must be an integer between 0 and 2**32-1")
        self.project_dir = Path(project_dir or ROOT).resolve()
        self.data_dir = Path(data_dir or self.project_dir).resolve()
        self.seed, self.ruleset, self.timed = seed, ruleset, timed
        self.fast = fast
        self.url = ""
        self.process: Optional[subprocess.Popen[bytes]] = None
        self._log: Optional[IO[bytes]] = None
        self._ready_dir: Optional[tempfile.TemporaryDirectory[str]] = None

    def start(self) -> str:
        """Return a verified server URL or reap the failed child and raise."""
        if self.process is not None:
            raise RuntimeError("This launcher has already started a server")
        if not (self.project_dir / "server.py").is_file():
            raise FileNotFoundError(f"No server.py in {self.project_dir}")
        log_dir = self.data_dir / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log = (log_dir / "local-server.log").open("wb")
        self._ready_dir = tempfile.TemporaryDirectory(prefix="llm4tft-")
        ready_path = Path(self._ready_dir.name) / "ready.json"
        token = uuid.uuid4().hex
        command = [
            sys.executable,
            "-u",
            str(self.project_dir / "server.py"),
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--seed",
            str(self.seed),
            "--ruleset",
            self.ruleset,
            "--data-dir",
            str(self.data_dir),
            "--ready-file",
            str(ready_path),
            "--token",
            token,
        ]
        if self.timed:
            command.append("--timed")
        if self.fast:
            command.append("--fast")
        try:
            self.process = subprocess.Popen(
                command, cwd=self.project_dir, stdout=self._log, stderr=subprocess.STDOUT
            )
            self.url = self._wait_ready(ready_path, token)
        except (OSError, RuntimeError, TimeoutError):
            self.stop()
            details = (log_dir / "local-server.log").read_text(errors="replace")[-4000:]
            raise RuntimeError(
                f"Local server failed. See {log_dir / 'local-server.log'}\n{details}"
            ) from None
        return self.url

    def _wait_ready(self, ready_path: Path, token: str) -> str:
        for _ in range(MAX_STARTUP_POLLS):
            if self.process is None or self.process.poll() is not None:
                raise RuntimeError("Server exited before becoming ready")
            if ready_path.is_file():
                info = json.loads(ready_path.read_text())
                url = info["url"]
                with urllib.request.urlopen(url + "/health", timeout=1) as response:
                    health = json.load(response)
                if health.get("application") != "LLM4TFT" or health.get("token") != token:
                    raise RuntimeError("Unexpected process answered the readiness check")
                return str(url)
            time.sleep(POLL_SECONDS)
        raise TimeoutError("Local server startup exceeded 15 seconds")

    def stop(self) -> None:
        """Reap the owned process; repeated calls are harmless."""
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        if self._log is not None:
            self._log.close()
            self._log = None
        if self._ready_dir is not None:
            self._ready_dir.cleanup()
            self._ready_dir = None

    def __enter__(self) -> LocalServer:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()
