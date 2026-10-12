import pytest

from backend import config, database

N_DAYS_TEST = 20


@pytest.fixture(scope="session")
def pipeline(tmp_path_factory):
    """Pipeline complet (20 jours) dans une base et un dossier de modèles temporaires."""
    from backend.forecasting_ml import train_models
    from backend.generate_dataset import generate_dataset
    from backend.simulation import run_simulation

    dossier = tmp_path_factory.mktemp("ider")
    patch = pytest.MonkeyPatch()
    patch.setattr(database, "DB_PATH", dossier / "test.db")
    patch.setattr(config, "MODEL_DIR", dossier / "models")
    measurements, sessions = generate_dataset(n_days=N_DAYS_TEST)
    ml = train_models(grille=[{"max_depth": 10, "min_samples_leaf": 2}], n_estimators=40)
    simulation = run_simulation()
    yield {"measurements": measurements, "sessions": sessions, "ml": ml, **simulation}
    patch.undo()
