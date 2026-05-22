from typing import Any
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LOGGER

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Dometic AC light entity."""
    device = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DometicACLight(device, entry)])

class DometicACLight(LightEntity):
    """Representation of a Dometic AC light entity."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, device, entry: ConfigEntry) -> None:
        """Initialize the light entity."""
        self._device = device
        self._entry = entry
        self._attr_name = f"{device.name} Light"
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_light"
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=device.name,
            manufacturer="Dometic",
            model="FreshJet 1700 BLE",
        )

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        self._device.register_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        self._device.unregister_listener(self.async_write_ha_state)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._device._connected

    @property
    def is_on(self) -> bool:
        """Return True if light is on."""
        return self._device.light_power

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        if not self._device.light_power:
            return 0
        # Map Dometic brightness (50 or 100) to 0..255
        if self._device.light_brightness == 50:
            return 127
        elif self._device.light_brightness == 100:
            return 255
        return 255  # Fallback to full brightness

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        LOGGER.info("Turning light ON with brightness: %s", brightness)
        await self._device.set_light_state(True, brightness)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        LOGGER.info("Turning light OFF")
        await self._device.set_light_state(False)
