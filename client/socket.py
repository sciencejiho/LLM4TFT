"""Thread-owned Socket.IO connection with GUI-safe status and state signals."""

from __future__ import annotations

import asyncio
import copy
from typing import Any, Optional

import socketio
from PyQt6.QtCore import QThread, pyqtSignal

MAX_CONNECT_ATTEMPTS = 20


class SocketThread(QThread):
    """Keep all socket callbacks in the worker and all widgets in the GUI thread.

    Parameters
    ----------
    parent : QWidget
        Qt object owning this thread.
    loop : asyncio.AbstractEventLoop
        Fresh event loop exclusively owned by the worker after start.
    server_url : str
        Explicit HTTP(S) Socket.IO endpoint.
    """

    update_ui = pyqtSignal(dict)
    connection_status = pyqtSignal(str)
    server_message = pyqtSignal(str)
    game_ended = pyqtSignal()
    session_finished = pyqtSignal(dict)

    def __init__(self, parent: Any, loop: asyncio.AbstractEventLoop, server_url: str):
        super().__init__(parent)
        if loop.is_running() or loop.is_closed():
            raise ValueError("Socket worker requires a fresh event loop")
        if not server_url.startswith(("http://", "https://")):
            raise ValueError("Socket URL must use HTTP or HTTPS")
        self.loop = loop
        self.server_url = server_url
        # Python 3.9 Engine.IO creates an asyncio.Queue immediately. Bind it to
        # the worker loop before the thread starts, rather than a default loop.
        asyncio.set_event_loop(loop)
        self.sio = socketio.AsyncClient(reconnection=False, request_timeout=2)
        self.state: dict[str, Any] = {"user": {}, "home": {}, "lobby": {}, "game": {}}
        self._task: Optional[asyncio.Task[None]] = None
        self._register_events()

    def run(self) -> None:
        """Run connection tasks and release the event loop on thread exit."""
        asyncio.set_event_loop(self.loop)
        self._task = self.loop.create_task(self._connect())
        try:
            self.loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            self.connection_status.emit("Disconnected")
        finally:
            self._task = None
            self.loop.run_until_complete(self._shutdown())
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    async def _shutdown(self) -> None:
        try:
            await asyncio.wait_for(self.sio.shutdown(), timeout=2)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            # Cancelling wait() also cancels Engine.IO's read task. Its normal
            # disconnect awaits that task and propagates cancellation again.
            self.connection_status.emit("Disconnected")
        finally:
            await self.sio.eio.disconnect(abort=True)

    async def _connect(self) -> None:
        for attempt in range(MAX_CONNECT_ATTEMPTS):
            if self.isInterruptionRequested():
                return
            self.connection_status.emit(f"Connecting… ({attempt + 1}/{MAX_CONNECT_ATTEMPTS})")
            try:
                await self.sio.connect(self.server_url, wait_timeout=2)
                await self.sio.wait()
                return
            except (socketio.exceptions.ConnectionError, asyncio.TimeoutError, OSError) as error:
                if attempt == MAX_CONNECT_ATTEMPTS - 1:
                    self.connection_status.emit(f"Connection failed: {error}")
                    return
                await asyncio.sleep(0.2)

    async def send_command(self, action: str, params: Any = None) -> bool:
        """Send a command only while connected and report failures visibly."""
        if not self.sio.connected:
            self.server_message.emit("Not connected to the server")
            return False
        if not isinstance(action, str) or len(action) > 64:
            raise ValueError("Invalid command name")
        await self.sio.emit(action, params)
        return True

    def stop(self) -> bool:
        """Cancel connection work and wait at most five seconds for shutdown."""
        self.requestInterruption()
        if self._task is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._task.cancel)
        return self.wait(5000)

    def _publish(self, section: str, data: dict[str, Any]) -> None:
        self.state[section] = data
        self.update_ui.emit(copy.deepcopy({section: data}))

    def _register_events(self) -> None:
        @self.sio.event
        async def connect() -> None:
            self.connection_status.emit("Connected")

        @self.sio.event
        async def disconnect(reason: Any = None) -> None:
            self.connection_status.emit("Disconnected")

        @self.sio.event
        async def response(data: Any) -> None:
            if isinstance(data, dict):
                message = data.get("message", data)
                self.server_message.emit(str(message)[:300])
            else:
                self.server_message.emit(str(data)[:300])

        @self.sio.event
        async def game_end() -> None:
            self.state["game"] = {}
            self.game_ended.emit()

        @self.sio.event
        async def session_outcome(data: dict[str, Any]) -> None:
            self.session_finished.emit(copy.deepcopy(data))

        @self.sio.event
        async def update_home(data: dict[str, Any]) -> None:
            self._publish("home", data)

        @self.sio.event
        async def update_lobby(data: dict[str, Any]) -> None:
            self._publish("lobby", data)

        @self.sio.event
        async def update_game(data: dict[str, Any]) -> None:
            self._publish("game", data)

        @self.sio.event
        async def update_user(data: dict[str, Any]) -> None:
            self._publish("user", data)
