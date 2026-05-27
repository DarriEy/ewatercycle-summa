"""Unit tests for the SUMMA eWaterCycle model plugin.

These tests verify the plugin's configuration logic without requiring
a running Docker container or the SUMMA BMI binary.
"""

import textwrap

import pytest

from ewatercycle_summa.utils import (
    parse_file_manager,
    parse_summa_time,
    write_file_manager,
)

# ---------------------------------------------------------------------------
# fileManager.txt parsing / writing
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_file_manager(tmp_path):
    """Create a minimal fileManager.txt for testing."""
    fm = tmp_path / "fileManager.txt"
    fm.write_text(textwrap.dedent("""\
        controlVersion       'SUMMA_FILE_MANAGER_V3.0.0'
        simStartTime         '2017-10-01 00:00'
        simEndTime           '2018-09-30 00:00'
        tmZoneInfo           'utcTime'
        outFilePrefix        'test_run'
        settingsPath         'settings/SUMMA/'
        forcingPath          'forcing/SUMMA_input/'
        outputPath           'output/'
        decisionsFile        'modelDecisions.txt'
        ! This is a comment
        initConditionFile    'coldState.nc'
        attributeFile        'attributes.nc'
    """))
    return fm


def test_parse_file_manager(sample_file_manager):
    config = parse_file_manager(sample_file_manager)
    assert config["controlVersion"] == "SUMMA_FILE_MANAGER_V3.0.0"
    assert config["simStartTime"] == "2017-10-01 00:00"
    assert config["simEndTime"] == "2018-09-30 00:00"
    assert config["settingsPath"] == "settings/SUMMA/"
    assert config["forcingPath"] == "forcing/SUMMA_input/"
    assert config["decisionsFile"] == "modelDecisions.txt"
    assert "comment" not in " ".join(config.keys()).lower()


def test_parse_file_manager_skips_comments(sample_file_manager):
    config = parse_file_manager(sample_file_manager)
    assert len(config) == 11


def test_write_file_manager_roundtrip(tmp_path, sample_file_manager):
    original = parse_file_manager(sample_file_manager)
    out_path = tmp_path / "output_fm.txt"
    write_file_manager(original, out_path)
    roundtripped = parse_file_manager(out_path)
    assert roundtripped == original


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------


def testparse_summa_time_standard():
    dt = parse_summa_time("2017-10-01 00:00")
    assert dt.year == 2017
    assert dt.month == 10
    assert dt.day == 1


def testparse_summa_time_with_seconds():
    dt = parse_summa_time("2017-10-01 00:00:00")
    assert dt.year == 2017


def testparse_summa_time_iso():
    dt = parse_summa_time("2017-10-01T00:00:00")
    assert dt.year == 2017


def testparse_summa_time_invalid():
    with pytest.raises(ValueError, match="Cannot parse"):
        parse_summa_time("not-a-date")


# ---------------------------------------------------------------------------
# Plugin discovery
# ---------------------------------------------------------------------------


def test_plugin_entry_point():
    """Verify that the plugin is discoverable via ewatercycle entry points."""
    try:
        from ewatercycle.models import sources
        assert "SUMMA" in sources
    except ImportError:
        pytest.skip("ewatercycle not installed")


def test_forcing_entry_point():
    """Verify that the forcing class is discoverable."""
    try:
        from ewatercycle.forcings import sources
        assert "SUMMAForcing" in sources
    except ImportError:
        pytest.skip("ewatercycle not installed")


# ---------------------------------------------------------------------------
# CMIP6 dataset helper
# ---------------------------------------------------------------------------


def test_cmip6_dataset_defaults():
    ewatercycle = pytest.importorskip("ewatercycle")  # noqa: F841
    from ewatercycle_summa.forcing import cmip6_dataset

    ds = cmip6_dataset("MRI-ESM2-0")
    assert ds.dataset == "MRI-ESM2-0"
    assert ds.project == "CMIP6"
    assert ds.exp == "historical"
    assert ds.ensemble == "r1i1p1f1"
    assert ds.grid == "gn"


def test_cmip6_dataset_ssp():
    ewatercycle = pytest.importorskip("ewatercycle")  # noqa: F841
    from ewatercycle_summa.forcing import cmip6_dataset

    ds = cmip6_dataset("EC-Earth3", exp="ssp585", ensemble="r1i1p1f2")
    assert ds.dataset == "EC-Earth3"
    assert ds.exp == "ssp585"
    assert ds.ensemble == "r1i1p1f2"


def test_cmip6_dataset_in_recipe_builder():
    ewatercycle = pytest.importorskip("ewatercycle")  # noqa: F841
    from ewatercycle.esmvaltool.builder import RecipeBuilder

    from ewatercycle_summa.forcing import cmip6_dataset

    ds = cmip6_dataset("IPSL-CM6A-LR")
    recipe = (
        RecipeBuilder()
        .title("test")
        .dataset(ds)
        .start(2000)
        .end(2001)
        .add_variable("tas")
        .build()
    )
    assert recipe.datasets is not None
    assert len(recipe.datasets) == 1
    assert recipe.datasets[0].project == "CMIP6"
