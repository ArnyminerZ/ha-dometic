from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_BLUETOOTH_SOURCE, DOMAIN, SOURCE_AUTO
from .coordinator import DometicACDevice

PLATFORMS = [Platform.CLIMATE, Platform.LIGHT]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dometic AC from a config entry."""
    address = entry.data[CONF_ADDRESS]
    name = entry.data.get(CONF_NAME, "Dometic AC")
    source = entry.options.get(
        CONF_BLUETOOTH_SOURCE,
        entry.data.get(CONF_BLUETOOTH_SOURCE, SOURCE_AUTO),
    )
    selected_source = None if source == SOURCE_AUTO else source
    
    device = DometicACDevice(hass, address, name, selected_source)
    
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = device
    
    # Start the connection and polling loop
    await device.start()
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        device = hass.data[DOMAIN].pop(entry.entry_id)
        await device.stop()
        
    return unload_ok
