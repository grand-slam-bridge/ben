#!/bin/bash
#
# BUILD THE dds3 SOLVER FOR THIS MAC (2026-10-05)
#
# The shipped bin/dds3-darwin/dds3/_dds3.so does not load on macOS 26 / arm64:
#
#   dlopen: Symbol not found: __ZNSt3__113__hash_memoryEPKvm
#
# That is std::__1::__hash_memory, a libc++ ABI symbol. The prebuilt extension was
# linked against a newer libc++ than this machine's /usr/lib/libc++.1.dylib exports.
# It is NOT a Python-version problem - it fails identically under 3.9 and 3.12, and
# the failure is in dlopen before Python looks at the module.
#
# Building from source against the local toolchain fixes it, because the result links
# against the libc++ that is actually here.
#
# The DDS repository builds its Python interface with bazel. Bazel is not needed: the
# interface is pybind11 over two source files, so clang++ compiles it directly. That
# avoids bootstrapping bazel and is what this script does.
#
# FOR THE BENCHMARK ONLY. It writes outside the repository and leaves
# bin/dds3-linux - the build the service actually deploys - completely untouched.
#
#   bash scripts/build-dds3-macos.sh [workdir] [python]
#
#   workdir  where to clone and build (default: a temp dir)
#   python   the interpreter to build for; MUST be the one that will import it
#            (default: python3)
#
# Afterwards, put it on the path ahead of the repo's own:
#
#   PYTHONPATH=<workdir>/dds3pkg python3 -c "import dds3; print(dds3.SolverContext())"
#
set -e

WORK="${1:-$(mktemp -d)}"
PY="${2:-python3}"

echo "workdir: $WORK"
echo "python:  $($PY --version) at $(command -v $PY)"

command -v clang++ >/dev/null || { echo "clang++ missing - run: xcode-select --install"; exit 1; }
$PY -c "import pybind11" 2>/dev/null || $PY -m pip install -q pybind11

mkdir -p "$WORK"
cd "$WORK"
[ -d dds ] || git clone -q --depth 1 https://github.com/dds-bridge/dds.git

# bindings.cpp includes <dds/dds.hpp> while the header lives at library/src/dds.hpp;
# bazel supplies that prefix with include_prefix, so stage it as a symlink instead.
rm -rf inc && mkdir -p inc && ln -s "$WORK/dds/library/src" "$WORK/inc/dds"

INC=$($PY -c "import pybind11;print(pybind11.get_include())")
PYINC=$($PY -c "import sysconfig;print(sysconfig.get_paths()['include'])")
EXT=$($PY -c "import sysconfig;print(sysconfig.get_config_var('EXT_SUFFIX'))")

cd dds
SRC=$(find library/src -name "*.cpp" | grep -vi test)
echo "compiling $(echo "$SRC" | wc -l | tr -d ' ') library sources + 2 binding sources ..."
mkdir -p "$WORK/dds3pkg/dds3"
# shellcheck disable=SC2086
clang++ -std=c++20 -O3 -fPIC -shared -undefined dynamic_lookup \
  -I library/src -I "$WORK/inc" -I "$INC" -I "$PYINC" \
  $SRC python/src/bindings.cpp python/src/converters.cpp \
  -o "$WORK/dds3pkg/dds3/_dds3$EXT"

cp python/dds3/__init__.py "$WORK/dds3pkg/dds3/"
echo "built: $WORK/dds3pkg/dds3/_dds3$EXT"

PYTHONPATH="$WORK/dds3pkg" $PY - <<'PYEOF'
import dds3
PBN = 'N:AKQ.AKQ.AKQ.AKQ T98.T98.T98.T98 765.765.765.765 432.432.432.432'
ctx = dds3.SolverContext()
s = dds3.solve_board_pbn(PBN, trump=4, first=1, current_trick_suit=(0, 0, 0),
                         current_trick_rank=(0, 0, 0), target=-1, solutions=1,
                         mode=1, context=ctx)
assert s['score'][0] == 0, s
par = dds3.calc_all_tables_pbn([PBN], mode=0)['par_results'][0]['par_score']
assert par[0] == 'NS 990', par
print('self-test ok: East takes 0 tricks against AKQ in every suit, par', par[0])
PYEOF

cat <<MSG

Use it (benchmark only - the repo's bin/ is untouched):

  export PYTHONPATH=$WORK/dds3pkg
  export DYLD_LIBRARY_PATH=<ben-repo>/bin/BGA/macos/arm64   # PIMC's own DDS

MSG
