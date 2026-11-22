"""Sensori annuali e mensili del Portale Consumi."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, KEY_LAST_UPDATE
from .coordinator import KEY_CALENDAR_ELECTRIC, KEY_CALENDAR_GAS

_MONTHS = (
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
)


def _device_info(coordinator) -> DeviceInfo:
    """Raggruppa le entità nel dispositivo dell'integrazione."""
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.entry.entry_id)},
        name="Portale Consumi SII",
    )


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        ActivePointCountSensor(coordinator, "elettriche"),
        ActivePointCountSensor(coordinator, "gas"),
        LastUpdateSensor(coordinator),
        CalendarConsumptionSensor(coordinator, "electric", None),
        CalendarConsumptionSensor(coordinator, "gas", None),
    ]

    for month in range(1, 13):
        entities.append(CalendarConsumptionSensor(coordinator, "electric", month))
        entities.append(CalendarConsumptionSensor(coordinator, "gas", month))

    async_add_entities(entities)


class ActivePointCountSensor(CoordinatorEntity, SensorEntity):
    """Numero di POD o PDR che hanno una fornitura attiva."""

    _attr_has_entity_name = False

    def __init__(self, coordinator, commodity: str) -> None:
        super().__init__(coordinator)
        self._commodity = commodity
        self._attr_device_info = _device_info(coordinator)
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_active_points_{commodity}"
        )
        self._attr_name = (
            "PortaleConsumi - Forniture elettriche attive"
            if commodity == "elettriche"
            else "PortaleConsumi - Forniture gas attive"
        )

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        key = (
            "active_electric_points"
            if self._commodity == "elettriche"
            else "active_gas_points"
        )
        return data.get(key, 0)


class LastUpdateSensor(CoordinatorEntity, SensorEntity):
    """Data e ora dell'ultimo aggiornamento riuscito."""

    _attr_has_entity_name = False
    _attr_name = "PortaleConsumi - Ultimo aggiornamento"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = _device_info(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_ultimo_aggiornamento"

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(KEY_LAST_UPDATE)


class CalendarConsumptionSensor(CoordinatorEntity, SensorEntity):
    """Totale dell'anno o valore di uno specifico mese."""

    _attr_has_entity_name = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, commodity: str, month: int | None) -> None:
        super().__init__(coordinator)
        self._commodity = commodity
        self._month = month
        self._attr_device_info = _device_info(coordinator)

        if commodity == "electric":
            self._data_key = KEY_CALENDAR_ELECTRIC
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
            label = "elettrico"
        else:
            self._data_key = KEY_CALENDAR_GAS
            self._attr_device_class = SensorDeviceClass.GAS
            self._attr_native_unit_of_measurement = "m³"
            label = "gas"

        suffix = "anno" if month is None else f"mese_{month:02d}"
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{commodity}_{suffix}"
        )
        self._attr_name = (
            f"PortaleConsumi - Consumo {label} anno solare"
            if month is None
            else f"PortaleConsumi - Consumo {label} {_MONTHS[month - 1]}"
        )

    @property
    def native_value(self):
        calendar = (self.coordinator.data or {}).get(self._data_key) or {}
        if self._month is None:
            return calendar.get("total")
        return calendar.get("months", {}).get(f"{self._month:02d}")

    @property
    def extra_state_attributes(self):
        calendar = (self.coordinator.data or {}).get(self._data_key) or {}
        attributes = {
            "anno": calendar.get("year"),
            "mesi_con_dato": calendar.get("months_available", 0),
            "mesi_mancanti": calendar.get("months_missing", []),
        }

        if self._month is None:
            attributes["consumi_mensili"] = calendar.get("months", {})
        else:
            attributes["mese"] = f"{self._month:02d}"

        if self._commodity == "gas":
            attributes["unita_portale"] = "Smc"

        return attributes