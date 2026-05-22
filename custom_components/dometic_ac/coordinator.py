import asyncio
from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection, BleakClientWithServiceCache

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import (
    LOGGER,
    NOTIFY_CHAR_UUID,
    REG_ACTUAL_TEMP,
    REG_FAN_MODE,
    REG_HVAC_MODE,
    REG_LIGHT_BRIGHTNESS,
    REG_LIGHT_POWER,
    REG_POWER,
    REG_SLEEP_MODE,
    REG_TARGET_TEMP,
    WRITE_CHAR_UUID,
)

class DometicACDevice:
    """Connection manager for the Dometic AC BLE device."""

    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        """Initialize the Dometic AC BLE device manager."""
        self.hass = hass
        self.address = address
        self.name = name
        self._client: BleakClient | None = None
        self._connected = False
        self._lock = asyncio.Lock()
        self._listeners = []
        self._loop_task: asyncio.Task | None = None
        self._is_active = True

        # State Cache
        self.power = False
        self.hvac_mode = 3  # Default to Auto
        self.fan_mode = 5  # Default to Auto
        self.target_temp = 21.0
        self.current_temp = 21.0
        self.light_power = False
        self.light_brightness = 100
        self.sleep_mode = False

    def register_listener(self, listener) -> None:
        """Register entity callback."""
        self._listeners.append(listener)

    def unregister_listener(self, listener) -> None:
        """Unregister entity callback."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify_listeners(self) -> None:
        """Notify all registered entities of a state change."""
        for listener in self._listeners:
            listener()

    async def start(self) -> None:
        """Start the background connection loop."""
        self._is_active = True
        self._loop_task = asyncio.create_task(self._connection_loop())

    async def stop(self) -> None:
        """Stop the connection loop and disconnect."""
        self._is_active = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        await self.disconnect()

    async def disconnect(self) -> None:
        """Disconnect the BLE client."""
        async with self._lock:
            if self._client:
                try:
                    await self._client.disconnect()
                except Exception as e:
                    LOGGER.debug("Error disconnecting: %s", e)
                self._client = None
            self._connected = False
            self._notify_listeners()

    def _disconnected_callback(self, client: BleakClient) -> None:
        """Handle unexpected BLE disconnection."""
        LOGGER.info("Dometic AC disconnected unexpectedly")
        self._connected = False
        self._client = None
        self._notify_listeners()

    async def _connection_loop(self) -> None:
        """Main connection and polling loop."""
        retry_delay = 5.0
        while self._is_active:
            if not self._connected:
                LOGGER.debug("Attempting to connect to Dometic AC at %s", self.address)
                ble_device = bluetooth.async_ble_device_from_address(self.hass, self.address)
                if ble_device is None:
                    LOGGER.debug("Device not found by bluetooth scanner, waiting %s seconds", retry_delay)
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 60.0)
                    continue

                try:
                    client = await establish_connection(
                        BleakClientWithServiceCache,
                        ble_device,
                        name=self.name,
                        disconnected_callback=self._disconnected_callback,
                        max_attempts=3
                    )
                    self._client = client
                    self._connected = True
                    retry_delay = 5.0  # Reset retry delay
                    LOGGER.info("Connected to Dometic AC at %s", self.address)
                    
                    # Start notifications
                    await client.start_notify(NOTIFY_CHAR_UUID, self._notification_handler)
                    
                    # Initial state poll
                    await self.poll_all()
                    
                except Exception as e:
                    LOGGER.warning("Failed to connect to Dometic AC at %s: %s", self.address, e)
                    self._connected = False
                    self._client = None
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 60.0)
                    continue

            # If connected, wait 30 seconds then poll to refresh states
            try:
                await asyncio.sleep(30.0)
                if self._connected and self._client:
                    await self.poll_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                LOGGER.error("Error in connection loop: %s", e)

    def _notification_handler(self, char, data: bytearray) -> None:
        """Handle received GATT notifications."""
        LOGGER.debug("Notification received: %s", data.hex())
        if len(data) < 6:
            LOGGER.debug("Notification too short: %d bytes", len(data))
            return

        reg = data[1]
        val_byte = data[5]

        if reg == REG_POWER:
            self.power = (val_byte == 1)
            LOGGER.debug("Power state updated: %s", self.power)
        elif reg == REG_HVAC_MODE:
            self.hvac_mode = val_byte
            LOGGER.debug("HVAC mode updated: %d", self.hvac_mode)
        elif reg == REG_FAN_MODE:
            self.fan_mode = val_byte
            LOGGER.debug("Fan mode updated: %d", self.fan_mode)
        elif reg == REG_TARGET_TEMP:
            if len(data) >= 7:
                temp_raw = int.from_bytes(data[5:7], byteorder="little", signed=True)
                self.target_temp = temp_raw / 1000.0
                LOGGER.debug("Target temperature updated: %f", self.target_temp)
        elif reg == REG_LIGHT_POWER:
            self.light_power = (val_byte == 1)
            LOGGER.debug("Light power updated: %s", self.light_power)
        elif reg == REG_LIGHT_BRIGHTNESS:
            self.light_brightness = val_byte
            LOGGER.debug("Light brightness updated: %d", self.light_brightness)
        elif reg == REG_ACTUAL_TEMP:
            if len(data) >= 7:
                temp_raw = int.from_bytes(data[5:7], byteorder="little", signed=True)
                self.current_temp = temp_raw / 1000.0
                LOGGER.debug("Current temperature updated: %f", self.current_temp)
        elif reg == REG_SLEEP_MODE:
            self.sleep_mode = (val_byte == 1)
            LOGGER.debug("Sleep mode updated: %s", self.sleep_mode)

        self._notify_listeners()

    async def _write_cmd(self, reg: int, val_bytes: list[int]) -> None:
        """Write a command to a device register."""
        payload = bytearray([0x11, reg, 0x00, 0x02, 0x01]) + bytearray(val_bytes)
        if len(payload) < 9:
            payload += bytearray([0x00] * (9 - len(payload)))
        
        async with self._lock:
            if not self._connected or not self._client:
                LOGGER.warning("Cannot write register 0x%02X: Not connected", reg)
                return
            try:
                LOGGER.debug("Writing command: %s", payload.hex())
                await self._client.write_gatt_char(WRITE_CHAR_UUID, payload, response=False)
            except Exception as e:
                LOGGER.error("Failed to write register 0x%02X: %s", reg, e)
                self._connected = False
                self._client = None
                self._notify_listeners()

    async def _write_poll_request(self, reg: int) -> None:
        """Send a register poll request."""
        payload = bytearray([0x12, reg, 0x00, 0x02, 0x01])
        async with self._lock:
            if not self._connected or not self._client:
                return
            try:
                LOGGER.debug("Writing poll request: %s", payload.hex())
                await self._client.write_gatt_char(WRITE_CHAR_UUID, payload, response=False)
            except Exception as e:
                LOGGER.error("Failed to write poll request 0x%02X: %s", reg, e)
                self._connected = False
                self._client = None
                self._notify_listeners()

    async def poll_all(self) -> None:
        """Poll the state of all registers."""
        LOGGER.debug("Polling all registers")
        registers = [
            REG_POWER,
            REG_HVAC_MODE,
            REG_FAN_MODE,
            REG_TARGET_TEMP,
            REG_ACTUAL_TEMP,
            REG_SLEEP_MODE,
            REG_LIGHT_POWER,
            REG_LIGHT_BRIGHTNESS,
        ]
        for reg in registers:
            if not self._connected or not self._client:
                break
            await self._write_poll_request(reg)
            await asyncio.sleep(0.1)

    async def set_power(self, power: bool) -> None:
        """Set the AC power state."""
        val = 1 if power else 0
        await self._write_cmd(REG_POWER, [val, 0x00, 0x00, 0x00])
        self.power = power
        self._notify_listeners()

    async def set_hvac_mode(self, mode: str) -> None:
        """Set the operational/HVAC mode."""
        if mode == "off":
            await self.set_power(False)
            await self.set_sleep_mode(False)
        else:
            if not self.power:
                await self.set_power(True)
                await asyncio.sleep(0.1)

            mode_map = {"cool": 0, "heat": 1, "fan_only": 2, "auto": 3, "dry": 4}
            reg_val = mode_map.get(mode, 3)
            await self._write_cmd(REG_HVAC_MODE, [reg_val, 0x00, 0x00, 0x00])
            self.hvac_mode = reg_val

            if mode not in ["cool", "heat"] and self.sleep_mode:
                await self.set_sleep_mode(False)

            self._notify_listeners()

    async def set_target_temperature(self, temp: float) -> None:
        """Set the target temperature."""
        temp_milli = int(temp * 1000)
        temp_bytes = list(temp_milli.to_bytes(2, byteorder="little", signed=True))
        await self._write_cmd(REG_TARGET_TEMP, temp_bytes + [0x00, 0x00])
        self.target_temp = temp
        self._notify_listeners()

    async def set_fan_mode(self, fan_mode: str) -> None:
        """Set the fan speed mode."""
        fan_map = {"low": 0, "medium": 1, "high": 2, "turbo": 3, "auto": 5}
        reg_val = fan_map.get(fan_mode, 5)
        await self._write_cmd(REG_FAN_MODE, [reg_val, 0x00, 0x00, 0x00])
        self.fan_mode = reg_val
        self._notify_listeners()

    async def set_sleep_mode(self, sleep: bool) -> None:
        """Set the sleep preset mode."""
        val = 1 if sleep else 0
        await self._write_cmd(REG_SLEEP_MODE, [val, 0x00, 0x00, 0x00])
        self.sleep_mode = sleep
        self._notify_listeners()

    async def set_light_state(self, on: bool, brightness: int | None = None) -> None:
        """Set the light state and snap brightness to Dometic-supported values."""
        if not on:
            await self._write_cmd(REG_LIGHT_POWER, [0, 0x00, 0x00, 0x00])
            self.light_power = False
            self._notify_listeners()
        else:
            await self._write_cmd(REG_LIGHT_POWER, [1, 0x00, 0x00, 0x00])
            self.light_power = True
            await asyncio.sleep(0.1)

            if brightness is not None:
                dometic_bright = 50 if brightness < 153 else 100
            else:
                dometic_bright = self.light_brightness if self.light_brightness in [50, 100] else 100

            await self._write_cmd(REG_LIGHT_BRIGHTNESS, [dometic_bright, 0x00, 0x00, 0x00])
            self.light_brightness = dometic_bright
            self._notify_listeners()
