import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak, async_discovered_service_info
from homeassistant.const import CONF_ADDRESS, CONF_NAME

from .const import DOMAIN, SERVICE_UUID

class DometicACConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Dometic AC BLE."""
    
    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow."""
        self._discovered_devices: dict[str, str] = {}

    async def async_step_user(self, user_input=None):
        """Handle a flow initiated by the user."""
        errors = {}
        
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            name = user_input.get(CONF_NAME, "Dometic AC")
            
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            
            return self.async_create_entry(
                title=name,
                data={
                    CONF_ADDRESS: address,
                    CONF_NAME: name,
                }
            )

        # Retrieve discovered BLE devices matching our service UUID
        discovered = async_discovered_service_info(self.hass)
        self._discovered_devices = {}
        for dev in discovered:
            if SERVICE_UUID in dev.advertisement.service_uuids:
                name = dev.name or dev.address
                self._discovered_devices[dev.address] = f"{name} ({dev.address})"

        if self._discovered_devices:
            schema = vol.Schema({
                vol.Required(CONF_ADDRESS): vol.In(self._discovered_devices),
                vol.Optional(CONF_NAME, default="Dometic AC"): str,
            })
        else:
            schema = vol.Schema({
                vol.Required(CONF_ADDRESS): str,
                vol.Optional(CONF_NAME, default="Dometic AC"): str,
            })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak):
        """Handle bluetooth discovery."""
        address = discovery_info.address
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        
        name = discovery_info.name or "Dometic AC"
        self.context["title_placeholders"] = {"name": name, "address": address}
        
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(self, user_input=None):
        """Confirm a bluetooth discovery."""
        if user_input is not None:
            address = self.context["title_placeholders"]["address"]
            name = self.context["title_placeholders"]["name"]
            
            return self.async_create_entry(
                title=name,
                data={
                    CONF_ADDRESS: address,
                    CONF_NAME: name,
                }
            )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders=self.context["title_placeholders"],
        )
