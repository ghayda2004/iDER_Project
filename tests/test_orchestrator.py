import pytest

from backend.models import Battery, EV, HVAC
from backend.orchestrator import dispatch


def ev_branche(id="E01", heures_restantes=10, energie_kwh=10.0):
    ev = EV(id, 60.0, 7.0)
    ev.brancher(0, heures_restantes, heures_restantes % 24, 0.7, energie_kwh)
    ev.debut_heure(0)
    return ev


def test_pas_de_pic_pas_action():
    actions, remaining = dispatch(20.0, [], [], [])
    assert actions == []
    assert remaining == 20.0


def test_batterie_disponible_utilisee_en_priorite():
    batteries = [Battery("B01", 10.0, 0.8, 5.0)]
    evs = [ev_branche()]
    actions, remaining = dispatch(25.0, batteries, evs, [])
    assert actions
    assert actions[0]["device_id"] == "B01"
    assert actions[0]["action_type"] == "DISCHARGE"
    assert remaining > 0


def test_batterie_soc_faible_non_utilisee():
    b = Battery("B03", 10.0, 0.10, 5.0)
    assert b.flexibilite_disponible() == 0


def test_ev_proche_depart_non_retarde_excessivement():
    # 10 kWh à livrer en 2 h à 7 kW : on ne peut reporter que 4 kW sur l'heure courante.
    ev = ev_branche(heures_restantes=2, energie_kwh=10.0)
    assert 0 < ev.flexibilite_disponible() <= 7.0
    assert ev.flexibilite_disponible() == pytest.approx(4.0)
    # Sans marge (7 kWh en 1 h), aucun report possible.
    urgent = ev_branche(heures_restantes=1, energie_kwh=7.0)
    assert urgent.flexibilite_disponible() == 0.0


def test_equite_alterne_les_batteries():
    batteries = [Battery("B01", 10.0, 0.8, 5.0), Battery("B02", 10.0, 0.8, 5.0)]
    actions1, remaining1 = dispatch(5.0, batteries, [], [])
    first = actions1[0]["device_id"]
    first_obj = next(b for b in batteries if b.id == first)
    assert first_obj.stress_score > 0

    for battery in batteries:
        battery.debut_heure()
    actions2, remaining2 = dispatch(5.0, batteries, [], [])
    second = actions2[0]["device_id"]
    second_obj = next(b for b in batteries if b.id == second)
    assert second_obj.stress_score < first_obj.stress_score


def test_plafond_equite_leve_en_coupure():
    def parc():
        batteries = [Battery("B01", 10.0, 0.9, 5.0), Battery("B02", 10.0, 0.9, 5.0)]
        batteries[1].stress_score = 1.0
        return batteries

    normal, _ = dispatch(10.0, parc(), [], [])
    coupure, _ = dispatch(10.0, parc(), [], [], delestage=True)
    assert next(a for a in normal if a["device_id"] == "B01")["power_kw"] == pytest.approx(2.5)
    assert next(a for a in coupure if a["device_id"] == "B01")["power_kw"] == pytest.approx(5.0)


def test_deficit_non_couvert_est_signale():
    batteries = [Battery("B01", 10.0, 0.10, 5.0)]
    evs = [EV("E01", 60.0, 7.0)]                  # non branché
    hvacs = [HVAC("H01", demande_kw=1.0, reduction_max=0.0)]
    actions, remaining = dispatch(50.0, batteries, evs, hvacs)
    assert actions == []
    assert remaining == pytest.approx(50.0, abs=1e-6)
