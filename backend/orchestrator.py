import logging

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

ORDRE_MERITE = ("battery", "ev", "hvac")
# En coupure STEG, la priorité de délestage est HVAC -> VE -> charge de base (énergie non desservie).
ORDRE_DELESTAGE = ("battery", "hvac", "ev")


def fmt(valeur, decimales=1):
    """Nombre au format français (virgule décimale) pour les justifications."""
    return f"{valeur:.{decimales}f}".replace(".", ",")


def dispatch(deficit_kw, batteries, evs, hvacs, ordre=ORDRE_MERITE, delestage=False):
    """Couvre le déficit STEG (kW) avec les DER selon l'ordre de mérite.

    Ordre par défaut : batteries, puis report de recharge des VE, puis
    réduction HVAC. Les batteries sont triées par `stress_score` croissant
    (puis nombre de sollicitations) pour répartir l'usure. Retourne
    `(actions, deficit_restant_kw)` ; les puissances ne sont pas arrondies afin
    que le bilan énergétique soit exact. Les objets sont modifiés (SoC, score).
    """
    actions = []
    remaining = float(deficit_kw)

    if remaining <= 0:
        return actions, remaining

    def couvrir_batteries():
        nonlocal remaining
        batteries_sorted = sorted(batteries, key=lambda b: (b.stress_score, b.dispatch_count))
        for battery in batteries_sorted:
            if remaining <= 0:
                break
            available = float(battery.flexibilite_disponible())
            if available <= 0:
                continue
            power = min(available, remaining, battery.max_power_kw)
            # Règle d'équité : si une autre batterie est moins sollicitée que celle-ci, on
            # plafonne cette dernière à 50 % de sa puissance pour étaler l'usure. Cette règle
            # peut s'écarter de l'optimum de coût du LP (qui ne connaît pas l'usure) : elle
            # mobilise parfois une ressource plus chère (VE, HVAC) alors qu'une batterie
            # disposait encore de puissance. En coupure STEG (délestage), la continuité
            # d'alimentation prime sur l'usure : le plafond n'est pas appliqué.
            if not delestage and any(other.stress_score > battery.stress_score for other in batteries_sorted if other.id != battery.id):
                power = min(power, battery.max_power_kw * 0.5)
            if power <= 0:
                continue
            power = battery.decharger(power, duree_h=1)
            actions.append(
                {
                    "device_id": battery.id,
                    "device_type": "battery",
                    "action_type": "DISCHARGE",
                    "power_kw": power,
                    "justification": (
                        f"Batterie {battery.id} choisie (score équité {fmt(battery.stress_score)} kWh cumulés, "
                        f"SoC {fmt(battery.soc * 100, 0)} %) : -{fmt(power, 2)} kW"
                    ),
                }
            )
            remaining -= power

    def couvrir_ve():
        nonlocal remaining
        for ev in evs:
            if remaining <= 0:
                break
            available = float(ev.flexibilite_disponible(delestage))
            if available <= 0:
                continue
            power = ev.retarder(min(available, remaining), delestage)
            if power <= 0:
                continue
            raison = "délesté (coupure STEG)" if delestage else f"reporté, départ prévu à {ev.depart_h} h"
            actions.append(
                {
                    "device_id": ev.id,
                    "device_type": "ev",
                    "action_type": "DELAY",
                    "power_kw": power,
                    "justification": f"Véhicule {ev.id} {raison} : {fmt(power, 2)} kW de recharge différés",
                }
            )
            remaining -= power

    def couvrir_hvac():
        nonlocal remaining
        for hvac in hvacs:
            if remaining <= 0:
                break
            available = float(hvac.flexibilite_disponible(delestage))
            if available <= 0:
                continue
            power = hvac.reduire(min(available, remaining), delestage)
            if power <= 0:
                continue
            raison = "délesté (coupure STEG)" if delestage else "réduit dans la plage de confort autorisée"
            actions.append(
                {
                    "device_id": hvac.id,
                    "device_type": "hvac",
                    "action_type": "REDUCE",
                    "power_kw": power,
                    "justification": f"Climatisation {hvac.id} {raison} : -{fmt(power, 2)} kW",
                }
            )
            remaining -= power

    etapes = {"battery": couvrir_batteries, "ev": couvrir_ve, "hvac": couvrir_hvac}
    for categorie in ordre:
        etapes[categorie]()

    if remaining > 1e-9:
        logging.debug("Déficit non couvert : %.2f kW après orchestration", remaining)

    return actions, max(0.0, remaining)
