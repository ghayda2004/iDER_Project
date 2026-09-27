import logging

from backend.config import GRID_LIMIT_KW

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def dispatch(deficit_kw, batteries, evs, hvacs):
    """Orchestre le déficit réseau selon l'ordre de mérite.

    On privilégie d'abord les batteries, puis les VE, puis les HVAC. Les
    batteries sont triées par score d'équité croissant afin de répartir la
    charge entre les ressources de façon plus juste.
    """
    actions = []
    remaining = float(deficit_kw)

    if remaining <= 0:
        return actions, remaining

    batteries_sorted = sorted(batteries, key=lambda b: (b.stress_score, b.dispatch_count))

    for battery in batteries_sorted:
        if remaining <= 0:
            break
        available = float(battery.flexibilite_disponible())
        if available <= 0:
            continue
        power = min(available, remaining, battery.max_power_kw)
        if any(other.stress_score > battery.stress_score for other in batteries_sorted if other.id != battery.id):
            power = min(power, battery.max_power_kw * 0.5)
        if power <= 0:
            continue
        battery.decharger(power, duree_h=1)
        actions.append(
            {
                "device_id": battery.id,
                "device_type": "battery",
                "action_type": "DISCHARGE",
                "power_kw": round(power, 2),
                "justification": (
                    f"Batterie {battery.id} choisie (score équité {battery.stress_score:.1f} kWh cumulés) : -{power:.1f} kW"
                ),
            }
        )
        remaining -= power

    for ev in evs:
        if remaining <= 0:
            break
        available = float(ev.flexibilite_disponible())
        if available <= 0:
            continue
        power = min(available, remaining, ev.max_charge_kw)
        if power <= 0:
            continue
        ev.retarder(power)
        actions.append(
            {
                "device_id": ev.id,
                "device_type": "ev",
                "action_type": "DELAY",
                "power_kw": round(power, 2),
                "justification": (
                    f"Véhicule {ev.id} reporté : +{power:.1f} kW différé avant départ prévu à {ev.depart_h}h"
                ),
            }
        )
        remaining -= power

    for hvac in hvacs:
        if remaining <= 0:
            break
        available = float(hvac.flexibilite_disponible())
        if available <= 0:
            continue
        power = min(available, remaining)
        if power <= 0:
            continue
        hvac.reduire(power)
        actions.append(
            {
                "device_id": hvac.id,
                "device_type": "hvac",
                "action_type": "REDUCE",
                "power_kw": round(power, 2),
                "justification": (
                    f"Chauffage {hvac.id} réduit : -{power:.1f} kW dans la plage de confort autorisée"
                ),
            }
        )
        remaining -= power

    if remaining > 0:
        logging.warning("Déficit réseau non couvert : %.2f kW après orchestration", remaining)

    return actions, remaining
