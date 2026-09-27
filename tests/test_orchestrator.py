import pytest

from backend.models import Battery, EV, HVAC
from backend.orchestrator import dispatch


@pytest.fixture
def battery_parc():
    return [Battery("B01", 10.0, 80, 5.0), Battery("B02", 10.0, 75, 5.0)]


def test_pas_de_pic_pas_action():
    actions, remaining = dispatch(20.0, [], [], [])
    assert actions == []
    assert remaining == 20.0


def test_batterie_disponible_utilisee_en_priorite():
    batteries = [Battery("B01", 10.0, 80, 5.0)]
    actions, remaining = dispatch(25.0, batteries, [], [])
    assert actions
    assert actions[0]["device_id"] == "B01"
    assert actions[0]["action_type"] == "DISCHARGE"
    assert remaining > 0


def test_batterie_soc_faible_non_utilisee():
    b = Battery("B03", 10.0, 10, 5.0)
    assert b.flexibilite_disponible() == 0


def test_ev_proche_depart_non_retarde_excessivement():
    ev = EV("E01", 50.0, 7.0, True, 18, 19, 90.0)
    assert 0 < ev.flexibilite_disponible() <= 7.0


def test_equite_alterne_les_batteries():
    batteries = [Battery("B01", 10.0, 80, 5.0), Battery("B02", 10.0, 80, 5.0)]
    actions1, remaining1 = dispatch(5.0, batteries, [], [])
    first = actions1[0]["device_id"]
    first_obj = next(b for b in batteries if b.id == first)
    assert first_obj.stress_score > 0

    actions2, remaining2 = dispatch(5.0, batteries, [], [])
    second = actions2[0]["device_id"]
    second_obj = next(b for b in batteries if b.id == second)
    assert second_obj.stress_score < first_obj.stress_score


def test_deficit_non_couvert_est_signale():
    batteries = [Battery("B01", 10.0, 10, 5.0)]
    evs = [EV("E01", 15.0, 7.0, False, 18, 19, 90.0)]
    hvacs = [HVAC("H01", 1.0, 1.0, 0.7)]
    actions, remaining = dispatch(50.0, batteries, evs, hvacs)
    assert remaining > 0
    assert remaining == pytest.approx(50.0, abs=1e-6)
