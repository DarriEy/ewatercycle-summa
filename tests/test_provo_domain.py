"""Tests using the downloaded Provo test domain.

Run scripts/setup_test_domain.sh first to populate the test data.
"""

from pathlib import Path

import pytest

from ewatercycle_summa.utils import parse_file_manager, parse_summa_time

PARAM_SET_DIR = Path(__file__).parent.parent / "test_parameter_set"
FM_PATH = PARAM_SET_DIR / "settings" / "SUMMA" / "fileManager.txt"


@pytest.fixture()
def provo_config():
    if not FM_PATH.exists():
        pytest.skip("Test parameter set not found — run scripts/setup_test_domain.sh")
    return parse_file_manager(FM_PATH)


def test_provo_file_manager_parses(provo_config):
    assert provo_config["controlVersion"] == "SUMMA_FILE_MANAGER_V3.0.0"
    assert provo_config["simStartTime"] == "2017-10-01 00:00"
    assert provo_config["simEndTime"] == "2018-09-30 00:00"


def test_provo_file_manager_has_all_required_keys(provo_config):
    required = [
        "controlVersion",
        "simStartTime",
        "simEndTime",
        "settingsPath",
        "forcingPath",
        "outputPath",
        "decisionsFile",
        "outputControlFile",
        "initConditionFile",
        "attributeFile",
        "trialParamFile",
        "forcingListFile",
        "vegTableFile",
        "soilTableFile",
        "generalTableFile",
        "noahmpTableFile",
    ]
    missing = [k for k in required if k not in provo_config]
    assert not missing, f"Missing keys in fileManager.txt: {missing}"


def test_provo_settings_files_exist(provo_config):
    settings_dir = PARAM_SET_DIR / provo_config["settingsPath"].rstrip("/")
    if not settings_dir.exists():
        pytest.skip("Settings directory not found")

    expected_files = [
        provo_config.get("decisionsFile", "modelDecisions.txt"),
        provo_config.get("outputControlFile", "outputControl.txt"),
        provo_config.get("initConditionFile", "coldState.nc"),
        provo_config.get("attributeFile", "attributes.nc"),
        provo_config.get("trialParamFile", "trialParams.nc"),
        provo_config.get("vegTableFile", "TBL_VEGPARM.TBL"),
        provo_config.get("soilTableFile", "TBL_SOILPARM.TBL"),
        provo_config.get("generalTableFile", "TBL_GENPARM.TBL"),
        provo_config.get("noahmpTableFile", "TBL_MPTABLE.TBL"),
    ]

    for fname in expected_files:
        fpath = settings_dir / fname
        assert fpath.exists(), f"Missing settings file: {fpath}"


def test_provo_times_parse(provo_config):
    start = parse_summa_time(provo_config["simStartTime"])
    end = parse_summa_time(provo_config["simEndTime"])
    assert start.year == 2017
    assert end.year == 2018
    assert end > start
