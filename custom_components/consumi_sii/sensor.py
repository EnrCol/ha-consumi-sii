"""Sensori per ogni POD (luce) e PDR (gas)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import ConsumiConfigEntry, ConsumiCoordinator
from .models import ELECTRIC, PointSeries, mask_code, statistic_id

PARALLEL_UPDATES = 0

_MONTHS = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)


@dataclass(frozen=True, kw_only=True)
class PointSensorDescription(SensorEntityDescription):
    """Descrive un sensore calcolato dalla serie di un punto."""

    value_fn: Callable[[PointSeries, int], float | None]
    attrs_fn: Callable[[PointSeries, int], dict[str, Any]] | None = None
    month: int | None = None


def _year_attrs(offset: int) -> Callable[[PointSeries, int], dict[str, Any]]:
    def attrs(series: PointSeries, year: int) -> dict[str, Any]:
        months = series.year_months(year - offset)
        return {
            "anno": year - offset,
            "consumi_mensili": months,
            "mesi_mancanti": [m for m, v in months.items() if v is None],
        }

    return attrs


def _latest_value(series: PointSeries, _year: int) -> float | None:
    latest = series.latest_month()
    return latest[1] if latest else None


def _latest_attrs(series: PointSeries, _year: int) -> dict[str, Any]:
    latest = series.latest_month()
    return {"competenza": f"{latest[0][:4]}-{latest[0][4:]}"} if latest else {}


def _month_value(month: int) -> Callable[[PointSeries, int], float | None]:
    def value(series: PointSeries, _year: int) -> float | None:
        latest = series.latest_of_month(month)
        return latest[1] if latest else None

    return value


def _month_attrs(month: int) -> Callable[[PointSeries, int], dict[str, Any]]:
    def attrs(series: PointSeries, _year: int) -> dict[str, Any]:
        latest = series.latest_of_month(month)
        return {"anno": latest[0]} if latest else {}

    return attrs


DESCRIPTIONS: tuple[PointSensorDescription, ...] = (
    PointSensorDescription(
        key="anno_corrente",
        translation_key="anno_corrente",
        value_fn=lambda s, y: s.year_total(y),
        attrs_fn=_year_attrs(0),
    ),
    PointSensorDescription(
        key="anno_precedente",
        translation_key="anno_precedente",
        value_fn=lambda s, y: s.year_total(y - 1),
        attrs_fn=_year_attrs(1),
    ),
    PointSensorDescription(
        key="ultimo_mese",
        translation_key="ultimo_mese",
        value_fn=_latest_value,
        attrs_fn=_latest_attrs,
    ),
    *(
        PointSensorDescription(
            key=f"mese_{month:02d}",
            # Una traduzione per mese: con un'unica chiave e un segnaposto
            # alcuni nomi non venivano risolti e restava solo il dispositivo.
            translation_key=_MONTHS[month - 1],
            value_fn=_month_value(month),
            attrs_fn=_month_attrs(month),
            month=month,
        )
        for month in range(1, 13)
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConsumiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    known: set[tuple[str, str]] = set()

    @callback
    def _add_new_points() -> None:
        new = [key for key in coordinator.data.points if key not in known]
        if not new:
            return
        known.update(new)
        entities: list[SensorEntity] = []
        for commodity, code in new:
            entities.extend(
                PointSensor(coordinator, commodity, code, description)
                for description in DESCRIPTIONS
            )
            entities.append(LastUpdateSensor(coordinator, commodity, code))
        async_add_entities(entities)

    _add_new_points()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_points))


def point_device_info(commodity: str, code: str) -> DeviceInfo:
    electric = commodity == ELECTRIC
    return DeviceInfo(
        identifiers={(DOMAIN, f"{commodity}_{code}")},
        name=f"{'Luce' if electric else 'Gas'} {mask_code(code)}",
        manufacturer="SII - Portale Consumi",
        model="POD energia elettrica" if electric else "PDR gas",
        serial_number=code,
        entry_type=DeviceEntryType.SERVICE,
    )


class PointSensor(CoordinatorEntity[ConsumiCoordinator], SensorEntity):
    """Consumo di un punto di fornitura."""

    _attr_has_entity_name = True
    entity_description: PointSensorDescription

    def __init__(
        self,
        coordinator: ConsumiCoordinator,
        commodity: str,
        code: str,
        description: PointSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._key = (commodity, code)
        electric = commodity == ELECTRIC
        self._attr_unique_id = f"{commodity}_{code}_{description.key}"
        self._attr_device_class = SensorDeviceClass.ENERGY if electric else SensorDeviceClass.GAS
        self._attr_native_unit_of_measurement = (
            UnitOfEnergy.KILO_WATT_HOUR if electric else UnitOfVolume.CUBIC_METERS
        )
        # Nessuno state_class: lo storico a lungo termine sta nelle
        # statistiche esterne mensili, non nei sensori.
        self._attr_suggested_display_precision = 0
        self._attr_device_info = point_device_info(commodity, code)

    @property
    def _series(self) -> PointSeries | None:
        return self.coordinator.data.points.get(self._key)

    @property
    def available(self) -> bool:
        return super().available and self._series is not None

    @property
    def native_value(self) -> float | None:
        series = self._series
        if series is None:
            return None
        return self.entity_description.value_fn(series, dt_util.now().year)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        series = self._series
        if series is None:
            return None
        attrs: dict[str, Any] = {"statistica_energia": statistic_id(DOMAIN, *self._key)}
        if self.entity_description.attrs_fn:
            attrs.update(self.entity_description.attrs_fn(series, dt_util.now().year))
        if series.commodity != ELECTRIC:
            attrs["unita_portale"] = "Smc"
        return attrs


class LastUpdateSensor(CoordinatorEntity[ConsumiCoordinator], SensorEntity):
    """Data e ora dell'ultimo aggiornamento riuscito, sul dispositivo del punto."""

    _attr_has_entity_name = True
    _attr_translation_key = "ultimo_aggiornamento"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ConsumiCoordinator, commodity: str, code: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{commodity}_{code}_ultimo_aggiornamento"
        self._attr_device_info = point_device_info(commodity, code)

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.last_update
