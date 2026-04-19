"""Binary sensor platform for Shopping List with Grocy."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_EXPIRED_PRODUCTS,
    ATTR_EXPIRING_PRODUCTS,
    ATTR_MISSING_PRODUCTS,
    ATTR_OVERDUE_BATTERIES,
    ATTR_OVERDUE_CHORES,
    ATTR_OVERDUE_PRODUCTS,
    ATTR_OVERDUE_TASKS,
    CONF_ENABLE_BATTERIES,
    CONF_ENABLE_CHORES,
    CONF_ENABLE_TASKS,
    DEFAULT_ENABLE_BATTERIES,
    DEFAULT_ENABLE_CHORES,
    DEFAULT_ENABLE_TASKS,
    DOMAIN,
)

LOGGER = logging.getLogger(__name__)


@dataclass
class GrocyAggregateBinarySensorDescription(BinarySensorEntityDescription):
    """Description for Grocy-style binary sensors."""

    attributes_fn: Callable[[list[Any]], Mapping[str, Any] | None]


AGGREGATE_BINARY_SENSORS: tuple[GrocyAggregateBinarySensorDescription, ...] = (
    GrocyAggregateBinarySensorDescription(
        key=ATTR_EXPIRED_PRODUCTS,
        name="Expired products",
        icon="mdi:delete-alert-outline",
        attributes_fn=lambda data: {
            ATTR_EXPIRED_PRODUCTS: data,
            "count": len(data),
        },
    ),
    GrocyAggregateBinarySensorDescription(
        key=ATTR_EXPIRING_PRODUCTS,
        name="Expiring products",
        icon="mdi:clock-fast",
        attributes_fn=lambda data: {
            ATTR_EXPIRING_PRODUCTS: data,
            "count": len(data),
        },
    ),
    GrocyAggregateBinarySensorDescription(
        key=ATTR_OVERDUE_PRODUCTS,
        name="Overdue products",
        icon="mdi:alert-circle-check-outline",
        attributes_fn=lambda data: {
            ATTR_OVERDUE_PRODUCTS: data,
            "count": len(data),
        },
    ),
    GrocyAggregateBinarySensorDescription(
        key=ATTR_MISSING_PRODUCTS,
        name="Missing products",
        icon="mdi:flask-round-bottom-empty-outline",
        attributes_fn=lambda data: {
            ATTR_MISSING_PRODUCTS: data,
            "count": len(data),
        },
    ),
    GrocyAggregateBinarySensorDescription(
        key=ATTR_OVERDUE_CHORES,
        name="Overdue chores",
        icon="mdi:alert-circle-check-outline",
        attributes_fn=lambda data: {
            ATTR_OVERDUE_CHORES: data,
            "count": len(data),
        },
    ),
    GrocyAggregateBinarySensorDescription(
        key=ATTR_OVERDUE_TASKS,
        name="Overdue tasks",
        icon="mdi:alert-circle-check-outline",
        attributes_fn=lambda data: {
            ATTR_OVERDUE_TASKS: data,
            "count": len(data),
        },
    ),
    GrocyAggregateBinarySensorDescription(
        key=ATTR_OVERDUE_BATTERIES,
        name="Overdue batteries",
        icon="mdi:battery-charging-10",
        attributes_fn=lambda data: {
            ATTR_OVERDUE_BATTERIES: data,
            "count": len(data),
        },
    ),
)


def _is_aggregate_binary_sensor_enabled(config: Mapping[str, Any], key: str) -> bool:
    """Return whether an aggregate binary sensor group is enabled."""
    if key == ATTR_OVERDUE_CHORES:
        return config.get(CONF_ENABLE_CHORES, DEFAULT_ENABLE_CHORES)
    if key == ATTR_OVERDUE_TASKS:
        return config.get(CONF_ENABLE_TASKS, DEFAULT_ENABLE_TASKS)
    if key == ATTR_OVERDUE_BATTERIES:
        return config.get(CONF_ENABLE_BATTERIES, DEFAULT_ENABLE_BATTERIES)
    return True


class GrocyDeviceEntity(CoordinatorEntity):
    """Coordinator entity exposing a shared Grocy device."""

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name="Grocy",
            manufacturer="Grocy",
            entry_type=DeviceEntryType.SERVICE,
        )


class GrocyAggregateBinarySensorEntity(GrocyDeviceEntity, BinarySensorEntity):
    """Binary sensor built from the shared polling data."""

    entity_description: GrocyAggregateBinarySensorDescription

    def __init__(self, coordinator, description, config_entry):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{config_entry.entry_id}_{description.key}"
        self._attr_has_entity_name = True
        self._attr_config_entry_id = config_entry.entry_id

    @property
    def is_on(self):
        entity_data = self.coordinator.data.get(self.entity_description.key, [])
        return len(entity_data) > 0 if entity_data else False

    @property
    def extra_state_attributes(self):
        entity_data = self.coordinator.data.get(self.entity_description.key, [])
        return self.entity_description.attributes_fn(entity_data or [])


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    config_data = config_entry.options if config_entry.options else config_entry.data

    update_binary_sensor = ShoppingListWithGrocyBinarySensor(
        coordinator,
        "updating_shopping_list_with_grocy_polling",
        "ShoppingListWithGrocy Update in progress",
    )

    hass.data[DOMAIN]["entities"]["updating_shopping_list_with_grocy_polling"] = (
        update_binary_sensor
    )

    aggregate_binary_sensors = [
        GrocyAggregateBinarySensorEntity(coordinator, description, config_entry)
        for description in AGGREGATE_BINARY_SENSORS
        if _is_aggregate_binary_sensor_enabled(config_data, description.key)
    ]

    async_add_entities([update_binary_sensor, *aggregate_binary_sensors])


class ShoppingListWithGrocyBinarySensor(BinarySensorEntity):
    def __init__(self, coordinator, object_id, name):
        unique_id = "updating_shopping_list_with_grocy_polling"
        entity_id = f"binary_sensor.{unique_id}"
        self.coordinator = coordinator
        self._attr_name = name
        self.entity_id = entity_id
        self._attr_unique_id = unique_id
        self._attr_icon = "mdi:refresh"
        self._attr_is_on = False

    @property
    def is_on(self):
        return self._attr_is_on

    async def update_state(self, state: bool) -> None:
        """Update the sensor state via the proper HA mechanism."""
        self._attr_is_on = state
        # Use async_write_ha_state instead of hass.states.async_set to go
        # through the entity registry properly and avoid state inconsistencies.
        if self.hass:
            self.async_write_ha_state()
