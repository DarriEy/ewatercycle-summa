# ewatercycle-summa

SUMMA (Structure for Unifying Multiple Modeling Alternatives) plugin for [eWaterCycle](https://ewatercycle.readthedocs.io/).

Uses the SUMMA Fortran BMI from [CH-Earth/summa](https://github.com/CH-Earth/summa/tree/develop_sundials) served via [grpc4bmi](https://github.com/eWaterCycle/grpc4bmi) in a Docker container.

## Installation

```bash
pip install ewatercycle-summa
```

## Usage

```python
from ewatercycle.models import SUMMA
from ewatercycle.parameter_sets import ParameterSet

from ewatercycle_summa.forcing import SUMMAForcing

# Point to pre-prepared SUMMA forcing
forcing = SUMMAForcing(
    directory="/path/to/forcing",
    forcing_file="forcing.nc",
    start_time="2000-01-01T00:00:00Z",
    end_time="2001-01-01T00:00:00Z",
)

# Point to SUMMA parameter set (settings, attributes, cold state, etc.)
parameter_set = ParameterSet(
    name="summa_test",
    directory="/path/to/parameter_set",
    config="settings/SUMMA/fileManager.txt",
    target_model="SUMMA",
)

# Create and run the model
model = SUMMA(forcing=forcing, parameter_set=parameter_set)
cfg_file, cfg_dir = model.setup()
model.initialize(cfg_file)

while model.time < model.end_time:
    model.update()

model.finalize()
```

## Parameter Set Structure

A SUMMA parameter set for eWaterCycle should contain:

```
parameter_set_dir/
  settings/SUMMA/
    fileManager.txt        # SUMMA file manager (paths are remapped at runtime)
    modelDecisions.txt     # Process-model decisions
    outputControl.txt      # Output variable selection
    basinParamInfo.txt     # GRU-level parameter metadata
    localParamInfo.txt     # HRU-level parameter metadata
    TBL_GENPARM.TBL        # General parameter lookup table
    TBL_MPTABLE.TBL        # Noah-MP parameter table
    TBL_SOILPARM.TBL       # Soil parameter table
    TBL_VEGPARM.TBL        # Vegetation parameter table
    coldState.nc           # Initial conditions
    attributes.nc          # Spatial attributes (HRU/GRU)
    trialParams.nc         # Calibration parameters
  forcing/SUMMA_input/     # (optional) default forcing if not provided separately
    *.nc
```

Default template files for the settings are included in this package and can be
used as a starting point.

## Container

The Docker image builds SUMMA from the `develop_sundials` branch with Fortran
BMI support and exposes it via grpc4bmi:

```bash
cd container
docker build -t ghcr.io/ewatercycle/summa-grpc4bmi:v0.1.0 .
```

## SUMMA BMI Variables

### Inputs (7 forcing variables)
| CSDMS Standard Name | SUMMA Name | Units |
|---|---|---|
| `atmosphere_water__precipitation_mass_flux` | pptrate | mm s-1 |
| `land_surface_air__temperature` | airtemp | K |
| `atmosphere_air_water~vapor__relative_saturation` | spechum | kg kg-1 |
| `land_surface_wind__speed` | windspd | m s-1 |
| `land_surface_radiation~incoming~shortwave__energy_flux` | SWRadAtm | W m-2 |
| `land_surface_radiation~incoming~longwave__energy_flux` | LWRadAtm | W m-2 |
| `land_surface_air__pressure` | airpres | Pa |

### Outputs (16 variables)
Includes runoff, evaporation, transpiration, sublimation, baseflow, SWE, soil
water, vegetation water, and energy balance fluxes. See `summa_bmi.f90` for the
full list.

## License

Apache-2.0
