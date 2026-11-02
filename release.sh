#!/usr/bin/env bash
#
# Build a development wheel, or a public wheel and sdist selected by the
# conventional-commit release plan. Publish only previously built artifacts.
#
# Usage:
#   ./release.sh build       rebuild locked browser assets, wheel and sdist
#   ./release.sh verify      verify the existing artifact/evidence bytes
#   ./release.sh publish     upload the verified artifacts to GitHub Releases
#
# PYTHON selects the build interpreter. TRAME_VTKJS_RELEASE_VERSION selects a
# public X.Y.Z version; unset it for local +git builds. Public publication also
# requires dist/release-plan.json for HEAD. PyPI uploads run in a separate job
# with trusted publishing, after this exact wheel has passed qualification.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
UMD_REL="src/trame_vtkjs/module/serve/js/trame_vtkjs.umd.js"
# Written by verify_chain.py next to the bundle, so hatch's serve/js/** include
# ships it in the wheel alongside the bundle it describes.
BUILD_INFO_REL="src/trame_vtkjs/module/serve/js/build-info.json"
EVIDENCE_REL="dist/release-evidence.json"
RELEASE_REPOSITORY="PaulHax/trame-vtkjs"

usage() { sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

case "${1:-}" in
  build | verify | publish) COMMAND="$1" ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    echo "release.sh: expected 'build', 'verify' or 'publish' (see --help)" >&2
    exit 2
    ;;
esac
if [ "$#" -ne 1 ]; then
  echo "release.sh: '$COMMAND' takes no further arguments" >&2
  exit 2
fi

die() { echo "release.sh: ERROR: $*" >&2; exit 1; }
step() { echo; echo "==> $*"; }

# --- pinned dependency chain -----------------------------------------------
[ -f "$ROOT/vtkjs-fork.env" ] || die "missing vtkjs-fork.env (the vtk.js pin)"
# shellcheck source=vtkjs-fork.env
. "$ROOT/vtkjs-fork.env"

# --- sha + version ---------------------------------------------------------
git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || die "not a git repo: $ROOT"
FULL_SHA="$(git -C "$ROOT" rev-parse HEAD)"
SHA="$(git -C "$ROOT" rev-parse --short HEAD)"
export TRAME_VTKJS_SHA="$SHA"
BASE="$(sed -n 's/^BASE_VERSION *= *"\(.*\)".*/\1/p' hatch_build.py | head -n1)"
[ -n "$BASE" ] || die "could not read BASE_VERSION from hatch_build.py"
if [ "${TRAME_VTKJS_RELEASE_VERSION+x}" = x ]; then
  PUBLIC_VERSION="$TRAME_VTKJS_RELEASE_VERSION"
  [[ "$PUBLIC_VERSION" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] \
    || die "TRAME_VTKJS_RELEASE_VERSION must be a public X.Y.Z version"
  TAG="trame-vtkjs-v${PUBLIC_VERSION}"
else
  PUBLIC_VERSION=""
  TAG="v${BASE}-git.${SHA}"
fi
echo "commit=${SHA}  base=${BASE}  tag=${TAG}"

require_committed_source() {
  [ -z "$(git status --porcelain --untracked-files=all)" ] \
    || die "source has uncommitted or untracked files; commit the release inputs first"
  [ "$(git rev-parse HEAD)" = "$FULL_SHA" ] \
    || die "HEAD changed during the release command"
}

# The one product wheel in dist/ (build clears older ones first).
dist_wheel() {
  shopt -s nullglob
  local wheels=(dist/trame_vtkjs-*.whl)
  shopt -u nullglob
  [ "${#wheels[@]}" -eq 1 ] || die "expected exactly one wheel in dist/, found ${#wheels[@]}"
  echo "${wheels[0]}"
}

build() {
  require_committed_source
  # Same-version development packages cannot be identified by package metadata
  # or npm's hidden lockfile (which --package-lock-only also rewrites). Install
  # the locked bytes before bundling and restore the verified vtk.js build link.
  step "Installing locked vue-components dependencies"
  local vtkjs_build
  vtkjs_build="$("$PYTHON" - <<'PYTHON_CODE'
import verify_chain as chain
chain.check_vtkjs(chain.read_pin())
print((chain.VUE / "node_modules" / "@kitware" / "vtk.js").resolve())
PYTHON_CODE
)"
  (
    cd vue-components
    npm ci &&
      mkdir -p node_modules/@kitware &&
      ln -s "$vtkjs_build" node_modules/@kitware/vtk.js
  ) || die "locked dependency installation failed"

  # --- build the vue components (produces the UMD bundle) ------------------
  step "Building vue-components (npm run build)"
  ( cd vue-components && npm run build ) || die "vue-components build failed"
  [ -f "$UMD_REL" ] || die "expected UMD not found after build: $UMD_REL"
  local umd_sha
  umd_sha="$(sha256sum "$UMD_REL" | awk '{print $1}')"
  echo "freshly built UMD sha256=${umd_sha}"

  # --- prove the bundle came from the pinned chain -------------------------
  step "Verifying the pinned dependency chain"
  "$PYTHON" verify_chain.py --umd "$UMD_REL" --build-info "$BUILD_INFO_REL" \
    || die "chain verification failed"

  step "Building wheel and source distribution"
  rm -f dist/trame_vtkjs-*.whl dist/trame_vtkjs-*.tar.gz "$EVIDENCE_REL"
  "$PYTHON" -m build --wheel --sdist --outdir dist . || die "distribution build failed"
  local wheel sdist wheel_sha version
  wheel="$(dist_wheel)"
  shopt -s nullglob
  local sources=(dist/trame_vtkjs-*.tar.gz)
  shopt -u nullglob
  [ "${#sources[@]}" -eq 1 ] || die "expected exactly one source distribution"
  sdist="${sources[0]}"
  require_committed_source
  local version_args=()
  [ -z "$PUBLIC_VERSION" ] || version_args=(--version "$PUBLIC_VERSION")
  "$PYTHON" release_artifacts.py record --wheel "$wheel" --sdist "$sdist" \
    --build-info "$BUILD_INFO_REL" --commit "$FULL_SHA" --tag "$TAG" \
    --output "$EVIDENCE_REL" "${version_args[@]}" \
    || die "artifact provenance verification failed"
  wheel_sha="$(sha256sum "$wheel" | awk '{print $1}')"
  version="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["wheel"]["version"])' "$EVIDENCE_REL")"
  local pcl_version
  pcl_version="$("$PYTHON" -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["pointcloudLod"]["version"])' \
    "$BUILD_INFO_REL")"

  step "BUILD + VERIFY OK"
  echo "  version        : ${version}"
  echo "  wheel          : ${wheel}"
  echo "  wheel sha256   : ${wheel_sha}"
  echo "  tag            : ${TAG}"
  echo "  vtk.js         : ${VTKJS_FORK_COMMIT}"
  echo "  pointcloud-lod : ${pcl_version}"
  echo "  evidence       : ${EVIDENCE_REL}"
  echo
  echo "Not published. Run './release.sh publish' to release this wheel."
}

verify() {
  require_committed_source
  "$PYTHON" release_artifacts.py verify --evidence "$EVIDENCE_REL" \
    --artifacts dist --commit "$FULL_SHA"
}

publish() {
  verify
  if [ -n "$PUBLIC_VERSION" ]; then
    "$PYTHON" release_plan.py check --plan dist/release-plan.json \
      || die "public release plan no longer matches HEAD"
  fi
  local wheel wheel_sha fields
  wheel="$(dist_wheel)"
  wheel_sha="$(sha256sum "$wheel" | awk '{print $1}')"
  fields="$("$PYTHON" - "$EVIDENCE_REL" "$TAG" <<'PYCODE'
import json, sys
evidence = json.load(open(sys.argv[1]))
if evidence["wheel"]["tag"] != sys.argv[2]:
    sys.exit("release tag does not match the built artifact")
print(evidence["wheel"]["version"])
print(evidence["pointcloudLod"]["version"])
print(evidence["bundle"]["sha256"])
PYCODE
)" || die "release identity does not match the built artifact"
  local version pcl_version umd_sha
  { read -r version; read -r pcl_version; read -r umd_sha; } <<<"$fields"
  echo "  wheel          : ${wheel}"
  echo "  wheel sha256   : ${wheel_sha}"
  echo "  version        : ${version}"

  step "Publishing verified GitHub release ${TAG}"
  command -v gh >/dev/null 2>&1 || die "gh CLI not found"
  # In CI, GH_TOKEN/GITHUB_TOKEN authenticates gh non-interactively; only fall
  # back to the interactive-login check when no token is present.
  if [ -z "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]; then
    gh auth status >/dev/null 2>&1 || die "gh not authenticated (run: gh auth login, or set GH_TOKEN)"
  fi

  local notes
  notes="$(cat <<EOF
trame-vtkjs at ${SHA} (version ${version}).

Embedded chain (see the attached release-evidence.json):

- vtk.js ${VTKJS_FORK_REPO} @ \`${VTKJS_FORK_COMMIT}\`
- pointcloud-lod ${pcl_version}
- UMD sha256 \`${umd_sha}\`
- wheel sha256 \`${wheel_sha}\`
EOF
)"

  local notes_file uploaded dl_url
  local stable_args=()
  [ -z "$PUBLIC_VERSION" ] || stable_args=(--stable)
  notes_file="$(mktemp)"
  printf '%s\n' "$notes" > "$notes_file"
  uploaded="$("$PYTHON" release_assets.py --repository "$RELEASE_REPOSITORY" \
    --tag "$TAG" --commit "$FULL_SHA" --notes "$notes_file" \
    "$wheel" dist/trame_vtkjs-*.tar.gz "$EVIDENCE_REL" "${stable_args[@]}")" || {
      rm -f "$notes_file"
      die "immutable release publication failed"
    }
  rm -f "$notes_file"
  dl_url="$("$PYTHON" -c \
    'import json,sys; from pathlib import Path; print(json.loads(sys.argv[1])[Path(sys.argv[2]).name])' \
    "$uploaded" "$wheel")"
  [ -n "$dl_url" ] || die "could not read uploaded asset URL from release ${TAG}"

  step "PUBLISHED: paste into the app's pyproject.toml"
  echo
  echo "trame-vtkjs = { url = \"${dl_url}\" }"
  echo
  echo "# sha256 = ${wheel_sha}"
}

"$COMMAND"
