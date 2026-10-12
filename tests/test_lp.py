import pytest

from backend.models import Battery, EV, HVAC
from backend.optimizer_lp import comparer_lp_regles, optimize_deficit


def ressources():
    batteries = [Battery("B01", 10.0, 0.9, 5.0), Battery("B02", 10.0, 0.9, 5.0)]
    batteries[1].stress_score = 3.0           # B01 sera plafonnée à 50 % par la règle d'équité
    ev = EV("E01", 60.0, 7.0)
    ev.brancher(0, 12, 7, 0.6, 18.0)
    ev.debut_heure(0)
    hvacs = [HVAC("C01", demande_kw=2.0)]
    return batteries, [ev], hvacs


def test_lp_ne_coute_jamais_plus_que_les_regles():
    batteries, evs, hvacs = ressources()
    comparaison = comparer_lp_regles(9.0, batteries, evs, hvacs)
    assert comparaison["cout_lp"] <= comparaison["cout_regles"] + 1e-6
    assert comparaison["cout_lp"] < comparaison["cout_regles"]        # écart dû au plafond d'équité
    assert batteries[0].soc == pytest.approx(0.9)                     # objets d'origine intacts


def test_lp_couvre_le_deficit_avec_les_batteries_d_abord():
    batteries, evs, hvacs = ressources()
    allocations, residuel = optimize_deficit(9.0, batteries, evs, hvacs)
    assert residuel == pytest.approx(0.0, abs=1e-6)
    assert sum(a["power_kw"] for a in allocations) == pytest.approx(9.0)
    assert {a["device_type"] for a in allocations} == {"battery"}
