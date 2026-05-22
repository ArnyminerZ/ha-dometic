import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak, async_discovered_service_info
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.helpers import selector

from .const import (
    CONF_BLUETOOTH_SOURCE,
    DOMAIN,
    MANUFACTURER_DATA_PREFIX,
    MANUFACTURER_ID,
    SERVICE_UUID,
    SOURCE_AUTO,
)


def _matches_service_uuid(service_info: BluetoothServiceInfoBleak) -> bool:
    """Return True if advertisement includes the Dometic service UUID."""
    advertised = {
        uuid.lower() for uuid in (service_info.advertisement.service_uuids or [])
    }
    return SERVICE_UUID.lower() in advertised


def _matches_manufacturer_data(service_info: BluetoothServiceInfoBleak) -> bool:
    """Return True if advertisement includes known Dometic manufacturer signature."""
    manufacturer_data = service_info.advertisement.manufacturer_data or {}
    payload = manufacturer_data.get(MANUFACTURER_ID)
    if payload is None:
        return False
    return payload.startswith(MANUFACTURER_DATA_PREFIX)


def _is_supported_advertisement(service_info: BluetoothServiceInfoBleak) -> bool:
    """Return True when advertisement matches known Dometic signatures."""
    return _matches_service_uuid(service_info) or _matches_manufacturer_data(service_info)


def _source_options_from_service_infos(
    service_infos: list[BluetoothServiceInfoBleak],
) -> dict[str, str]:
    """Build source options for a list of service infos."""
    options: dict[str, str] = {SOURCE_AUTO: "Automatic (best available proxy)"}
    for service_info in service_infos:
        source = service_info.source
        if source and source not in options:
            options[source] = source
    return options


def _discover_matching_service_infos(
    hass,
) -> list[BluetoothServiceInfoBleak]:
    """Return matching discoveries from both connectable and non-connectable caches."""
    best_by_address: dict[str, BluetoothServiceInfoBleak] = {}
    for connectable in (True, False):
        for service_info in async_discovered_service_info(hass, connectable=connectable):
            if not _is_supported_advertisement(service_info):
                continue
            current = best_by_address.get(service_info.address)
            if current is None:
                best_by_address[service_info.address] = service_info
                continue
            current_rssi = current.rssi if current.rssi is not None else -999
            new_rssi = service_info.rssi if service_info.rssi is not None else -999
            if new_rssi > current_rssi:
                best_by_address[service_info.address] = service_info
    return list(best_by_address.values())

class DometicACConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Dometic AC BLE."""
    
    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow."""
        self._discovered_devices: dict[str, str] = {}

    async def async_step_user(self, user_input=None):
        """Handle a flow initiated by the user."""
        errors = {}
        discovered = _discover_matching_service_infos(self.hass)
        self._discovered_devices = {}

        for dev in discovered:
            name = dev.name or dev.address
            self._discovered_devices[dev.address] = f"{name} ({dev.address})"
        
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            name = user_input.get(CONF_NAME, "Dometic AC")
            source = user_input.get(CONF_BLUETOOTH_SOURCE, SOURCE_AUTO)
            
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            
            return self.async_create_entry(
                title=name,
                data={
                    CONF_ADDRESS: address,
                    CONF_NAME: name,
                    CONF_BLUETOOTH_SOURCE: source,
                }
            )

        if self._discovered_devices:
            source_options = _source_options_from_service_infos(discovered)
            address_options = [
                selector.SelectOptionDict(value=address, label=label)
                for address, label in sorted(self._discovered_devices.items(), key=lambda item: item[1])
            ]
            schema = vol.Schema({
                vol.Required(CONF_ADDRESS): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=address_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        custom_value=False,
                    )
                ),
                vol.Optional(CONF_NAME, default="Dometic AC"): str,
                vol.Optional(CONF_BLUETOOTH_SOURCE, default=SOURCE_AUTO): vol.In(source_options),
            })
        else:
            schema = vol.Schema({
                vol.Required(CONF_ADDRESS): str,
                vol.Optional(CONF_NAME, default="Dometic AC"): str,
                vol.Optional(CONF_BLUETOOTH_SOURCE, default=SOURCE_AUTO): vol.In(
                    {SOURCE_AUTO: "Automatic (best available proxy)"}
                ),
            })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak):
        """Handle bluetooth discovery."""
        if not _is_supported_advertisement(discovery_info):
            return self.async_abort(reason="not_supported")

        address = discovery_info.address
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        
        name = discovery_info.name or "Dometic AC"
        self.context["title_placeholders"] = {"name": name, "address": address}
        self.context["discovery"] = {
            CONF_ADDRESS: address,
            CONF_NAME: name,
            CONF_BLUETOOTH_SOURCE: discovery_info.source or SOURCE_AUTO,
        }
        
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(self, user_input=None):
        """Confirm a bluetooth discovery."""
        if user_input is not None:
            discovery = self.context["discovery"]
            source = user_input.get(CONF_BLUETOOTH_SOURCE, SOURCE_AUTO)
            
            return self.async_create_entry(
                title=discovery[CONF_NAME],
                data={
                    CONF_ADDRESS: discovery[CONF_ADDRESS],
                    CONF_NAME: discovery[CONF_NAME],
                    CONF_BLUETOOTH_SOURCE: source,
                }
            )

        discovery = self.context["discovery"]
        source_options = {
            SOURCE_AUTO: "Automatic (best available proxy)",
        }
        if discovery[CONF_BLUETOOTH_SOURCE] != SOURCE_AUTO:
            source_options[discovery[CONF_BLUETOOTH_SOURCE]] = discovery[
                CONF_BLUETOOTH_SOURCE
            ]

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_BLUETOOTH_SOURCE,
                        default=discovery[CONF_BLUETOOTH_SOURCE],
                    ): vol.In(source_options)
                }
            ),
            description_placeholders=self.context["title_placeholders"],
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Create the options flow."""
        return DometicACOptionsFlow(config_entry)


class DometicACOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Dometic AC BLE."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        address = self._config_entry.data[CONF_ADDRESS]
        current_source = self._config_entry.options.get(
            CONF_BLUETOOTH_SOURCE,
            self._config_entry.data.get(CONF_BLUETOOTH_SOURCE, SOURCE_AUTO),
        )
        if not current_source:
            current_source = SOURCE_AUTO

        service_infos = [
            dev
            for dev in _discover_matching_service_infos(self.hass)
            if dev.address == address and _is_supported_advertisement(dev)
        ]

        source_options = _source_options_from_service_infos(service_infos)
        if current_source not in source_options:
            source_options[current_source] = current_source

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_BLUETOOTH_SOURCE, default=current_source): vol.In(
                        source_options
                    )
                }
            ),
        )
