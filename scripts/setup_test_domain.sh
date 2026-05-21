#!/usr/bin/env bash
# Download the Provo test domain from CH-Earth/summa and structure it as an
# eWaterCycle ParameterSet.
#
# Usage:
#   ./scripts/setup_test_domain.sh [target_dir]
#
# Default target: ./test_parameter_set/

set -euo pipefail

TARGET="${1:-$(dirname "$0")/../test_parameter_set}"
TARGET=$(cd "$(dirname "$TARGET")" && pwd)/$(basename "$TARGET")

REPO_URL="https://github.com/CH-Earth/summa.git"
BRANCH="develop_sundials"
SPARSE_PATH="test_ngen/domain_provo"

echo "==> Setting up SUMMA Provo test domain at: $TARGET"

# Clone just the test domain (sparse checkout to avoid pulling the full repo)
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "==> Sparse-cloning $SPARSE_PATH from $BRANCH ..."
cd "$TMPDIR"
git init -q summa
cd summa
git remote add origin "$REPO_URL"
git config core.sparseCheckout true
echo "$SPARSE_PATH" > .git/info/sparse-checkout
git fetch --depth 1 origin "$BRANCH" -q
git checkout -q FETCH_HEAD

DOMAIN="$TMPDIR/summa/$SPARSE_PATH"

# Structure as eWaterCycle ParameterSet
# The parameter set needs:
#   settings/SUMMA/  -> all config files
#   forcing/SUMMA_input/ -> forcing NetCDFs
mkdir -p "$TARGET/settings/SUMMA"
mkdir -p "$TARGET/forcing/SUMMA_input"

echo "==> Copying settings files ..."
cp "$DOMAIN/settings/SUMMA/"* "$TARGET/settings/SUMMA/"

echo "==> Copying forcing files ..."
if [ -d "$DOMAIN/forcing/SUMMA_input" ]; then
    # Copy any files that exist (may be empty in sparse checkout)
    find "$DOMAIN/forcing/SUMMA_input" -type f -exec cp {} "$TARGET/forcing/SUMMA_input/" \;
fi

# Rewrite fileManager.txt with relative paths suitable for eWaterCycle.
# The plugin's _make_cfg_file() will remap these at runtime, but we make them
# sensible defaults here.
FM="$TARGET/settings/SUMMA/fileManager.txt"
if [ -f "$FM" ]; then
    echo "==> Rewriting fileManager.txt with portable paths ..."
    cat > "$FM" << 'FILEMANAGER'
controlVersion       'SUMMA_FILE_MANAGER_V3.0.0'
simStartTime         '2017-10-01 00:00'
simEndTime           '2018-09-30 00:00'
tmZoneInfo           'utcTime'
outFilePrefix        'summa_provo'
settingsPath         'settings/SUMMA/'
forcingPath          'forcing/SUMMA_input/'
outputPath           'output/'
decisionsFile        'modelDecisions.txt'
outputControlFile    'outputControl.txt'
globalHruParamFile   'localParamInfo.txt'
globalGruParamFile   'basinParamInfo.txt'
initConditionFile    'coldState.nc'
attributeFile        'attributes.nc'
trialParamFile       'trialParams.nc'
forcingListFile      'forcingFileList.txt'
vegTableFile         'TBL_VEGPARM.TBL'
soilTableFile        'TBL_SOILPARM.TBL'
generalTableFile     'TBL_GENPARM.TBL'
noahmpTableFile      'TBL_MPTABLE.TBL'
FILEMANAGER
fi

echo ""
echo "==> Test parameter set ready at: $TARGET"
echo ""
echo "Contents:"
find "$TARGET" -type f | sort | sed "s|$TARGET/|  |"
echo ""
echo "Use with eWaterCycle:"
echo "  from ewatercycle.base.parameter_set import ParameterSet"
echo "  ps = ParameterSet("
echo "      name='summa_provo',"
echo "      directory='$TARGET',"
echo "      config='settings/SUMMA/fileManager.txt',"
echo "      target_model='SUMMA',"
echo "  )"
