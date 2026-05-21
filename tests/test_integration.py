"""Integration tests for the SUMMA eWaterCycle plugin.

These tests require:
  1. Docker running with the summa-grpc4bmi image built
  2. The Provo test parameter set (run scripts/setup_test_domain.sh first)

Run with:
    pytest tests/test_integration.py -v --run-integration

Skip without the flag:
    pytest tests/  (skips these tests by default)
"""

from pathlib import Path

import pytest

PARAM_SET_DIR = Path(__file__).parent.parent / "test_parameter_set"


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires Docker and test data")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-integration", default=False):
        skip = pytest.mark.skip(reason="needs --run-integration flag")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require Docker",
    )


@pytest.fixture()
def parameter_set():
    """Load the Provo test parameter set."""
    if not PARAM_SET_DIR.exists():
        pytest.skip(
            "Test parameter set not found. "
            "Run: ./scripts/setup_test_domain.sh"
        )
    try:
        from ewatercycle.base.parameter_set import ParameterSet
    except ImportError:
        pytest.skip("ewatercycle not installed")

    return ParameterSet(
        name="summa_provo",
        directory=PARAM_SET_DIR,
        config="settings/SUMMA/fileManager.txt",
        target_model="SUMMA",
    )


@pytest.fixture()
def forcing():
    """Load forcing from the test parameter set."""
    forcing_dir = PARAM_SET_DIR / "forcing" / "SUMMA_input"
    if not forcing_dir.exists() or not list(forcing_dir.glob("*.nc")):
        pytest.skip("No forcing files found in test parameter set")

    try:
        from ewatercycle_summa.forcing import SUMMAForcing
    except ImportError:
        pytest.skip("ewatercycle not installed")

    return SUMMAForcing(
        directory=str(forcing_dir),
        forcing_file="forcing.nc",
        start_time="2017-10-01T00:00:00Z",
        end_time="2018-09-30T00:00:00Z",
    )


@pytest.mark.integration
class TestSUMMASetup:
    """Test model setup (config file generation) without running the BMI."""

    def test_make_cfg_file(self, parameter_set, tmp_path):
        """Verify that _make_cfg_file writes a valid fileManager.txt."""
        from ewatercycle_summa.model import SUMMAMethods, _parse_file_manager

        # We can't instantiate SUMMAMethods directly (it's abstract via
        # eWaterCycleModel), so we test the config generation helpers
        # through the SUMMA class with a mock BMI image.
        from ewatercycle_summa.model import SUMMA

        model = SUMMA(parameter_set=parameter_set)
        cfg_file, cfg_dir = model.setup(cfg_dir=str(tmp_path / "run"))

        assert Path(cfg_file).exists()
        config = _parse_file_manager(Path(cfg_file))
        assert config["controlVersion"] == "SUMMA_FILE_MANAGER_V3.0.0"
        assert "settings" in config.get("settingsPath", "")

    def test_setup_with_time_override(self, parameter_set, tmp_path):
        """Verify that start/end time overrides are applied."""
        from ewatercycle_summa.model import SUMMA, _parse_file_manager

        model = SUMMA(parameter_set=parameter_set)
        cfg_file, cfg_dir = model.setup(
            cfg_dir=str(tmp_path / "run"),
            start_time="2018-01-01 00:00",
            end_time="2018-06-01 00:00",
        )

        config = _parse_file_manager(Path(cfg_file))
        assert config["simStartTime"] == "2018-01-01 00:00"
        assert config["simEndTime"] == "2018-06-01 00:00"


@pytest.mark.integration
class TestSUMMAFullRun:
    """Full BMI lifecycle test — requires Docker container running."""

    def test_initialize_update_finalize(self, parameter_set, forcing, tmp_path):
        """Run the full BMI lifecycle: setup -> init -> update -> finalize."""
        from ewatercycle_summa.model import SUMMA

        model = SUMMA(
            parameter_set=parameter_set,
            forcing=forcing,
        )

        cfg_file, cfg_dir = model.setup(cfg_dir=str(tmp_path / "run"))
        model.initialize(cfg_file)

        # Run a few time steps
        for _ in range(3):
            model.update()

        assert model.time > model.start_time

        model.finalize()
