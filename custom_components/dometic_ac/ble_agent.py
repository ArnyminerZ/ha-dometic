"""BlueZ NoInputNoOutput agent for automatic Just Works BLE pairing on Linux."""

import asyncio
import sys

from .const import LOGGER

_DBUS_AVAILABLE = False
_AGENT_PATH = "/com/homeassistant/dometic_ac_BleAgent"
_agent_lock: asyncio.Lock | None = None
_agent_bus = None  # D-Bus connection kept alive to hold the exported agent object

try:
    if sys.platform.startswith("linux"):
        from dbus_fast.aio import MessageBus
        from dbus_fast.constants import BusType
        from dbus_fast.service import ServiceInterface, method
        from dbus_fast import DBusError
        _DBUS_AVAILABLE = True
except Exception:
    pass


if _DBUS_AVAILABLE:
    class _JustWorksAgent(ServiceInterface):
        """BlueZ Agent1 that auto-accepts Just Works pairing with no user interaction."""

        def __init__(self) -> None:
            super().__init__("org.bluez.Agent1")

        @method()
        def Release(self) -> None:
            pass

        @method()
        def RequestPinCode(self, device: "o") -> "s":
            raise DBusError("org.bluez.Error.Rejected", "PIN not supported")

        @method()
        def DisplayPinCode(self, device: "o", pincode: "s") -> None:
            pass

        @method()
        def RequestPasskey(self, device: "o") -> "u":
            raise DBusError("org.bluez.Error.Rejected", "Passkey not supported")

        @method()
        def DisplayPasskey(self, device: "o", passkey: "u", entered: "q") -> None:
            pass

        @method()
        def RequestConfirmation(self, device: "o", passkey: "u") -> None:
            pass  # auto-confirm for Just Works

        @method()
        def RequestAuthorization(self, device: "o") -> None:
            pass

        @method()
        def AuthorizeService(self, device: "o", uuid: "s") -> None:
            pass

        @method()
        def Cancel(self) -> None:
            pass


def _get_lock() -> asyncio.Lock:
    global _agent_lock
    if _agent_lock is None:
        _agent_lock = asyncio.Lock()
    return _agent_lock


async def ensure_bluez_agent() -> None:
    """Register a NoInputNoOutput BlueZ agent for Just Works BLE pairing.

    Safe to call multiple times — the agent is registered only once per process.
    Does nothing on non-Linux platforms or when dbus_fast is unavailable.
    """
    global _agent_bus
    if not _DBUS_AVAILABLE:
        return

    async with _get_lock():
        if _agent_bus is not None:
            return
        try:
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            agent = _JustWorksAgent()
            bus.export(_AGENT_PATH, agent)

            introspection = await bus.introspect("org.bluez", "/org/bluez")
            proxy = bus.get_proxy_object("org.bluez", "/org/bluez", introspection)
            mgr = proxy.get_interface("org.bluez.AgentManager1")

            await mgr.call_register_agent(_AGENT_PATH, "NoInputNoOutput")
            await mgr.call_request_default_agent(_AGENT_PATH)

            _agent_bus = bus
            LOGGER.debug("Registered NoInputNoOutput BlueZ pairing agent")
        except Exception as err:
            LOGGER.debug("BlueZ agent registration skipped: %s", err)
