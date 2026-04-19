"""Button platform for Shopping List with Grocy."""

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class GrocyDeviceEntity(CoordinatorEntity):
    """Coordinator entity exposing the shared Grocy device."""

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name="Grocy",
            manufacturer="Grocy",
            entry_type=DeviceEntryType.SERVICE,
        )


class GrocyForceRefreshButton(GrocyDeviceEntity, ButtonEntity):
    """Manual refresh button for the Grocy integration."""

    def __init__(self, coordinator, config_entry) -> None:
        super().__init__(coordinator)
        self._attr_name = "Force Refresh"
        self._attr_unique_id = f"{config_entry.entry_id}_force_refresh"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:refresh"
        self._attr_config_entry_id = config_entry.entry_id

    async def async_press(self) -> None:
        """Trigger an immediate refresh."""
        await self.coordinator.request_update()


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the button platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([GrocyForceRefreshButton(coordinator, config_entry)])
