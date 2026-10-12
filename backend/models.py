"""Ressources décentralisées (DER) pilotées par l'orchestrateur.

Les SoC sont des fractions (0 à 1). Chaque objet est créé une seule fois par
scénario et par mode : son état (SoC, stress_score) se propage d'un jour au
suivant. Une heure de simulation commence par `debut_heure()`.
"""

from __future__ import annotations

from backend.config import (
    BATTERY_CAPACITY_KWH,
    BATTERY_MAX_POWER_KW,
    EV_BATTERY_CAPACITY_KWH,
    EV_MAX_CHARGE_KW,
    HVAC_REDUCTION_MAX,
    ROUND_TRIP_EFFICIENCY,
    SOC_INIT,
    SOC_MAX,
    SOC_MIN,
)

EPS = 1e-9


class Battery:
    """Batterie domestique avec score d'équité.

    `stress_score` cumule l'énergie déchargée (kWh) depuis le début de la
    simulation ; il ne diminue jamais. L'orchestrateur sollicite d'abord les
    batteries les moins stressées.
    """

    def __init__(self, id, capacity_kwh=BATTERY_CAPACITY_KWH, soc=SOC_INIT, max_power_kw=BATTERY_MAX_POWER_KW,
                 house_id=None, efficiency=ROUND_TRIP_EFFICIENCY):
        self.id = id
        self.house_id = house_id
        self.capacity_kwh = capacity_kwh
        self.soc = soc
        self.max_power_kw = max_power_kw
        self.efficiency = efficiency
        self.stress_score = 0.0
        self.dispatch_count = 0
        self.debut_heure()

    def debut_heure(self):
        self.soc_debut = self.soc
        self.puissance_heure_kw = 0.0       # > 0 : charge (côté réseau), < 0 : décharge

    def flexibilite_disponible(self, duree_h=1):
        """Puissance de décharge encore possible sur l'heure (kW), sans passer sous SOC_MIN."""
        if self.puissance_heure_kw > 0:
            return 0.0
        energie = max(0.0, self.soc - SOC_MIN) * self.capacity_kwh
        return max(0.0, min(self.max_power_kw + self.puissance_heure_kw, energie / duree_h))

    def capacite_recharge(self, soc_cible=SOC_MAX, duree_h=1):
        """Puissance de charge acceptable (kW côté réseau) pour atteindre soc_cible sans dépasser SOC_MAX."""
        if self.puissance_heure_kw < 0:
            return 0.0
        cible = min(soc_cible, SOC_MAX)
        energie_stockable = max(0.0, cible - self.soc) * self.capacity_kwh
        return max(0.0, min(self.max_power_kw - self.puissance_heure_kw, energie_stockable / (self.efficiency * duree_h)))

    def decharger(self, puissance_kw, duree_h=1):
        if puissance_kw <= 0:
            return 0.0
        usable_kw = min(puissance_kw, self.flexibilite_disponible(duree_h))
        self.soc = max(SOC_MIN, self.soc - usable_kw * duree_h / self.capacity_kwh)
        self.stress_score += usable_kw * duree_h
        self.dispatch_count += 1
        self.puissance_heure_kw -= usable_kw
        return usable_kw

    def charger(self, puissance_kw, soc_cible=SOC_MAX, duree_h=1):
        """Recharge ; le rendement est appliqué à l'énergie stockée. Retourne la puissance absorbée (kW)."""
        if puissance_kw <= 0:
            return 0.0
        absorbee = min(puissance_kw, self.capacite_recharge(soc_cible, duree_h))
        self.soc = min(SOC_MAX, self.soc + absorbee * self.efficiency * duree_h / self.capacity_kwh)
        self.puissance_heure_kw += absorbee
        return absorbee


class EV:
    """Véhicule électrique dont la recharge peut être reportée tant que le départ le permet.

    Sans pilotage, il recharge à pleine puissance dès l'arrivée. Une session
    (arrivée, départ, énergie) est ouverte par `brancher` ; `debut_heure(t)`
    indique l'heure courante de la chronologie continue.
    """

    def __init__(self, id, capacity_kwh=EV_BATTERY_CAPACITY_KWH, max_charge_kw=EV_MAX_CHARGE_KW, house_id=None):
        self.id = id
        self.house_id = house_id
        self.capacity_kwh = capacity_kwh
        self.max_charge_kw = max_charge_kw
        self.connected = False
        self.t = 0
        self.t_depart = 0
        self.depart_h = None
        self.soc = None
        self.energie_restante_kwh = 0.0
        self.a_charge_heure_precedente = False
        self.reporte_kw = 0.0

    def brancher(self, t_arrivee, t_depart, depart_h, soc_arrivee, energie_kwh):
        self.connected = True
        self.t = t_arrivee
        self.t_depart = t_depart
        self.depart_h = depart_h
        self.soc = soc_arrivee
        self.energie_restante_kwh = energie_kwh
        self.a_charge_heure_precedente = False

    def debrancher(self):
        """Départ du véhicule ; retourne l'énergie qui n'a pas pu être livrée (kWh)."""
        non_livre = self.energie_restante_kwh if self.connected else 0.0
        self.connected = False
        self.energie_restante_kwh = 0.0
        self.a_charge_heure_precedente = False
        return non_livre

    def debut_heure(self, t):
        self.t = t
        self.reporte_kw = 0.0

    def demande_kw(self):
        """Recharge qu'il effectuerait cette heure sans pilotage."""
        if not self.connected or self.energie_restante_kwh <= EPS:
            return 0.0
        return min(self.max_charge_kw, self.energie_restante_kwh)

    def heures_restantes(self):
        return max(0, self.t_depart - self.t)

    def flexibilite_disponible(self, delestage=False):
        """Puissance reportable cette heure en garantissant la recharge complète avant le départ.

        Reporter x kW laisse E - (d - x) kWh pour les H - 1 heures suivantes ;
        il faut donc x <= P (H - 1) - E + d. En délestage (coupure STEG), tout
        est reportable.
        """
        demande = self.demande_kw() - self.reporte_kw
        if demande <= EPS:
            return 0.0
        if delestage:
            return demande
        marge = self.max_charge_kw * (self.heures_restantes() - 1) - self.energie_restante_kwh + self.demande_kw()
        return max(0.0, min(demande, marge - self.reporte_kw))

    def retarder(self, puissance_kw, delestage=False):
        if puissance_kw <= 0:
            return 0.0
        actual = min(puissance_kw, self.flexibilite_disponible(delestage))
        self.reporte_kw += actual
        return actual

    def fin_heure(self):
        """Effectue la recharge non reportée ; retourne la puissance consommée (kW)."""
        puissance = max(0.0, self.demande_kw() - self.reporte_kw)
        self.energie_restante_kwh = max(0.0, self.energie_restante_kwh - puissance)
        if self.soc is not None:
            self.soc = min(1.0, self.soc + puissance / self.capacity_kwh)
        self.a_charge_heure_precedente = puissance > EPS
        return puissance


class HVAC:
    """Climatisation/chauffage dont la demande horaire peut être réduite dans la plage de confort."""

    def __init__(self, id, demande_kw=0.0, reduction_max=HVAC_REDUCTION_MAX, house_id=None):
        self.id = id
        self.house_id = house_id
        self.demande_kw = demande_kw
        self.reduction_max = reduction_max
        self.reduit_kw = 0.0

    def debut_heure(self, demande_kw):
        self.demande_kw = demande_kw
        self.reduit_kw = 0.0

    def flexibilite_disponible(self, delestage=False):
        plafond = self.demande_kw if delestage else self.demande_kw * self.reduction_max
        return max(0.0, plafond - self.reduit_kw)

    def reduire(self, puissance_kw, delestage=False):
        if puissance_kw <= 0:
            return 0.0
        actual = min(puissance_kw, self.flexibilite_disponible(delestage))
        self.reduit_kw += actual
        return actual


__all__ = ["Battery", "EV", "HVAC"]
