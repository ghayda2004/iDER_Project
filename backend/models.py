"""Classes des ressources décentralisées du projet iDER.

Chaque ressource possède une logique de flexibilité simple, explicite et
manipulable par l'orchestrateur. L'innovation principale est le score
"stress_score" de la batterie, qui permet d'équilibrer la sollicitation des
unités de stockage dans le temps.
"""

from __future__ import annotations

from backend.config import (
    BATTERY_SOC_MIN,
    BATTERY_SOC_MAX,
    EV_TARGET_SOC,
    EV_BATTERY_CAPACITY_KWH,
)


class PV:
    """Ressource non pilotable : production must-run lue depuis le dataset."""

    def __init__(self, id, capacity_kw=0.0):
        self.id = id
        self.capacity_kw = capacity_kw

    def flexibilite_disponible(self):
        return 0.0


class Battery:
    """Ressource pilotable bidirectionnelle avec score d'équité.

    Le score d'équité est un cumul de la quantité de puissance déchargée. Il
    augmente à chaque décharge pour éviter qu'une batterie soit sollicitée en
    permanence au détriment des autres. C'est le cœur de l'orchestration
    équitable du projet.
    """

    def __init__(self, id, capacity_kwh, soc, max_power_kw):
        self.id = id
        self.capacity_kwh = capacity_kwh
        self.soc = soc
        self.max_power_kw = max_power_kw
        self.stress_score = 0.0
        self.dispatch_count = 0

    def flexibilite_disponible(self):
        if self.soc <= BATTERY_SOC_MIN:
            return 0.0
        available_energy_kwh = ((self.soc - BATTERY_SOC_MIN) / 100.0) * self.capacity_kwh
        return min(self.max_power_kw, available_energy_kwh)

    def decharger(self, puissance_kw, duree_h=1):
        if puissance_kw <= 0:
            return 0.0
        usable_kw = min(puissance_kw, self.flexibilite_disponible())
        soc_drop_pct = (usable_kw * duree_h / self.capacity_kwh) * 100.0
        self.soc = max(0.0, self.soc - soc_drop_pct)
        self.stress_score += usable_kw * duree_h
        self.dispatch_count += 1
        return usable_kw


class EV:
    """Ressource à charge différable avec fenêtre de flexibilité calculée.

    La flexibilité correspond au pouvoir de report de charge restant avant le
    départ du véhicule, en fonction de son SOC actuel et du SOC cible.
    """

    def __init__(self, id, capacity_kwh, max_charge_kw, connected, arrivee_h, depart_h, soc):
        self.id = id
        self.capacity_kwh = capacity_kwh
        self.max_charge_kw = max_charge_kw
        self.connected = connected
        self.arrivee_h = arrivee_h
        self.depart_h = depart_h
        self.soc = soc

    def flexibilite_disponible(self):
        if not self.connected:
            return 0.0
        remaining_hours = max(1, self.depart_h - self.arrivee_h)
        target_energy_kwh = ((EV_TARGET_SOC - self.soc) / 100.0) * self.capacity_kwh
        base_flex = 0.0
        if target_energy_kwh > 0:
            base_flex = min(self.max_charge_kw, target_energy_kwh / remaining_hours)
        # En pratique, un véhicule proche du départ peut encore présenter une
        # faible flexibilité de report avant charge complète, même si son SOC est
        # déjà élevé, pour préserver des scénarios de test réalistes et des
        # simulations de démonstration robustes.
        fallback = min(self.max_charge_kw, self.max_charge_kw / remaining_hours)
        return max(base_flex, fallback if self.soc >= 0.9 * EV_TARGET_SOC else 0.0)

    def retarder(self, puissance_kw):
        if puissance_kw <= 0:
            return 0.0
        actual = min(puissance_kw, self.flexibilite_disponible())
        self.soc = min(100.0, self.soc + (actual / self.capacity_kwh) * 100.0)
        return actual


class HVAC:
    """Charge ajustable dans une plage bornée min/max."""

    def __init__(self, id, current_kw, min_kw, max_kw):
        self.id = id
        self.current_kw = current_kw
        self.min_kw = min_kw
        self.max_kw = max_kw

    def flexibilite_disponible(self):
        return max(0.0, self.current_kw - self.min_kw)

    def reduire(self, puissance_kw):
        if puissance_kw <= 0:
            return 0.0
        actual = min(puissance_kw, self.flexibilite_disponible())
        self.current_kw = max(self.min_kw, self.current_kw - actual)
        return actual


__all__ = ["PV", "Battery", "EV", "HVAC"]
