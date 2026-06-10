"""
SOC tracker for the Mantey site battery bank (13.5 kWh, lead-acid, 10% floor).
SOC is modeled from net power
(generation - load); it is not yet read from physical battery telemetry.
"""
from dataclasses import dataclass


# Mantey site battery bank (13.5 kWh; lead-acid deep-cycle, 10% SOC floor)
VIRTUAL_CAPACITY_KWH = 13.5      # site bank capacity
VIRTUAL_CHARGE_RATE_KW = 5.0
VIRTUAL_DISCHARGE_RATE_KW = 5.0
SOC_MIN = 0.10                  # 10% floor
SOC_MAX = 0.95


@dataclass
class VirtualBattery:
    capacity_kwh: float = VIRTUAL_CAPACITY_KWH
    soc: float = 0.5
    charge_rate_kw: float = VIRTUAL_CHARGE_RATE_KW
    discharge_rate_kw: float = VIRTUAL_DISCHARGE_RATE_KW

    def charge(self, power_kw: float, duration_h: float) -> float:
        energy = min(power_kw, self.charge_rate_kw) * duration_h
        new_soc = self.soc + energy / self.capacity_kwh
        self.soc = min(new_soc, SOC_MAX)
        return energy

    def discharge(self, power_kw: float, duration_h: float) -> float:
        energy = min(power_kw, self.discharge_rate_kw) * duration_h
        new_soc = self.soc - energy / self.capacity_kwh
        self.soc = max(new_soc, SOC_MIN)
        return energy

    def available_kwh(self) -> float:
        return max(0.0, (self.soc - SOC_MIN) * self.capacity_kwh)

    def headroom_kwh(self) -> float:
        return max(0.0, (SOC_MAX - self.soc) * self.capacity_kwh)

    def snapshot(self) -> dict:
        return {
            "soc_pct": round(self.soc * 100, 1),
            "available_kwh": round(self.available_kwh(), 2),
            "headroom_kwh": round(self.headroom_kwh(), 2),
            "capacity_kwh": self.capacity_kwh,
        }


# Module-level virtual battery instance (persists for the process lifetime)
_virtual_battery = VirtualBattery()


def get_virtual_soc() -> dict:
    return _virtual_battery.snapshot()


def update_virtual_soc(load_kw: float, generation_kw: float, duration_h: float = 1 / 60) -> dict:
    net = generation_kw - load_kw
    if net > 0:
        _virtual_battery.charge(net, duration_h)
    elif net < 0:
        _virtual_battery.discharge(-net, duration_h)
    return _virtual_battery.snapshot()


class BatteryModel:
    """
    Public BatteryModel that the IEMS dispatch layer uses.

    Adabi Section 5.5 / eq 5.8 — SOC bounds, round-trip efficiency, and
    charge/discharge limits.
    """

    def __init__(
        self,
        soc: float = 0.5,
        capacity_kwh: float = VIRTUAL_CAPACITY_KWH,
        max_power_kw: float = VIRTUAL_CHARGE_RATE_KW,
        soc_min: float = 0.10,
        soc_max: float = SOC_MAX,
        round_trip_efficiency: float = 0.90,
    ):
        self.capacity_kwh = capacity_kwh
        self.max_power_kw = max_power_kw
        self.soc_min = soc_min
        self.soc_max = soc_max
        self.eta = round_trip_efficiency
        # eta_charge = eta_discharge = sqrt(round-trip) for symmetric losses
        self._eta_one_way = round_trip_efficiency ** 0.5
        self.soc = max(soc_min, min(soc_max, soc))

    def update(self, net_w: float, dt_s: float) -> float:
        """
        Apply net_w (positive=charging, negative=discharging) for dt_s seconds.
        Returns the new SOC fraction in [soc_min, soc_max].
        """
        clipped_w = max(-self.max_power_kw * 1000, min(self.max_power_kw * 1000, net_w))
        energy_kwh = (clipped_w / 1000) * (dt_s / 3600)
        if energy_kwh >= 0:
            energy_kwh *= self._eta_one_way
        else:
            energy_kwh /= self._eta_one_way
        self.soc = max(self.soc_min, min(self.soc_max, self.soc + energy_kwh / self.capacity_kwh))
        return self.soc

    def can_charge(self, w: float) -> bool:
        if self.soc >= self.soc_max:
            return False
        return abs(w) <= self.max_power_kw * 1000

    def can_discharge(self, w: float) -> bool:
        if self.soc <= self.soc_min:
            return False
        return abs(w) <= self.max_power_kw * 1000

    def snapshot(self) -> dict:
        return {
            "soc": round(self.soc, 4),
            "soc_pct": round(self.soc * 100, 1),
            "available_kwh": round(max(0.0, (self.soc - self.soc_min) * self.capacity_kwh), 2),
            "headroom_kwh": round(max(0.0, (self.soc_max - self.soc) * self.capacity_kwh), 2),
            "capacity_kwh": self.capacity_kwh,
            "max_power_kw": self.max_power_kw,
        }
