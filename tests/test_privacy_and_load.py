import numpy as np
import pandas as pd
import pytest

from runlab.models.load import acwr, fitness_fatigue
from runlab.privacy import trim_endpoints


def _track(n=3000):
    return pd.DataFrame({"lat": np.ones(n), "lon": np.ones(n), "distance_m": np.arange(n, dtype=float)})


def test_trim_endpoints_hides_start_and_finish():
    out = trim_endpoints(_track(), 500)
    visible = out.dropna(subset=["lat"])["distance_m"]
    assert visible.min() >= 500 and visible.max() <= 2999 - 500


def test_drop_all_coordinates():
    assert trim_endpoints(_track(), 500, keep_coordinates=False)["lat"].isna().all()


def test_fitness_fatigue_converges_and_form_uses_yesterday():
    load = pd.Series(np.full(400, 50.0))
    ff = fitness_fatigue(load)
    assert ff["ctl"].iloc[-1] == pytest.approx(50, rel=1e-3)
    assert ff["atl"].iloc[-1] == pytest.approx(50, rel=1e-6)
    assert ff["tsb"].iloc[0] == 0.0
    assert ff["tsb"].iloc[1] == pytest.approx(ff["ctl"].iloc[0] - ff["atl"].iloc[0])


def test_acwr_needs_28_days():
    ratio = acwr(pd.Series(np.full(30, 10.0)))
    assert ratio.iloc[:27].isna().all()
    assert ratio.iloc[-1] == pytest.approx(1.0)
