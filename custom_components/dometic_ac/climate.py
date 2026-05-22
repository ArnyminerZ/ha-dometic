from typing import Any
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import (
    PRESET_NONE,
    PRESET_SLEEP,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LOGGER

# Fan modes
FAN_TURBO = "turbo"

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Dometic AC climate entity."""
    device = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DometicACClimate(device, entry)])

class DometicACClimate(ClimateEntity):
    """Representation of a Dometic AC climate entity."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.FAN_ONLY,
        HVACMode.AUTO,
        HVACMode.DRY,
    ]
    _attr_fan_modes = ["low", "medium", "high", FAN_TURBO, "auto"]
    _attr_preset_modes = [PRESET_NONE, PRESET_SLEEP]
    _attr_min_temp = 16.0
    _attr_max_temp = 30.0
    _attr_target_temperature_step = 0.5
    _enable_legacy_easy_mode_setup = False

    def __init__(self, device, entry: ConfigEntry) -> None:
        """Initialize the climate entity."""
        self._device = device
        self._entry = entry
        self._attr_name = device.name
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_climate"
        
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
    def hvac_mode(self) -> HVACMode:
        """Return current operation ie. heat, cool, idle."""
        if not self._device.power:
            return HVACMode.OFF
        
        mode_map = {
            0: HVACMode.COOL,
            1: HVACMode.HEAT,
            2: HVACMode.FAN_ONLY,
            3: HVACMode.AUTO,
            4: HVACMode.DRY,
        }
        return mode_map.get(self._device.hvac_mode, HVACMode.AUTO)

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._device.current_temp

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self._device.target_temp

    @property
    def fan_mode(self) -> str | None:
        """Return the fan setting."""
        fan_map = {
            0: "low",
            1: "medium",
            2: "high",
            3: FAN_TURBO,
            5: "auto",
        }
        return fan_map.get(self._device.fan_mode, "auto")

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        return PRESET_SLEEP if self._device.sleep_mode else PRESET_NONE

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        LOGGER.info("Setting HVAC mode to: %s", hvac_mode)
        await self._device.set_hvac_mode(hvac_mode)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            LOGGER.info("Setting temperature to: %s", temp)
            await self._device.set_target_temperature(temp)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        LOGGER.info("Setting fan mode to: %s", fan_mode)
        await self._device.set_fan_mode(fan_mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        LOGGER.info("Setting preset mode to: %s", preset_mode)
        if preset_mode == PRESET_SLEEP:
            current_hvac = self.hvac_mode
            if current_hvac not in [HVACMode.COOL, HVACMode.HEAT]:
                LOGGER.warning("Sleep mode is only valid in Cool or Heat mode")
                return
            await self._device.set_sleep_mode(True)
        else:
            await self._device.set_sleep_mode(False)

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        await self._device.set_power(True)

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        await self._device.set_power(False)
