#!/usr/bin/env bash
# checks.sh — the verification gate for Python repos.
#
# Runs, in order: format check, lint, type check, tests. Exits non-zero if any
# gate fails, and prints a summary so failures are easy to act on.
#
# Usage (from the repository root):
#   bash checks.sh          # check everything, fix nothing
#   bash checks.sh --fix    # auto-fix lint + formatting first, then run all gates
#
# The script adapts to the repo: it uses `uv run` when a uv project is
# detected (uv.lock or [tool.uv] present), plain tools otherwise, and skips
# gates whose tools are neither installed nor configured — reporting each
# skip so missing tooling is visible rather than silently ignored.

set -u

FIX=0
if [[ "${1:-}" == "--fix" ]]; then
  FIX=1
elif [[ -n "${1:-}" ]]; then
  echo "usage: bash checks.sh [--fix]" >&2
  exit 2
fi

if [[ ! -f "pyproject.toml" && ! -f "setup.py" && ! -f "setup.cfg" ]]; then
  echo "error: no pyproject.toml/setup.py found — run from the repository root." >&2
  exit 2
fi

# Prefer the locked project environment when this is a uv project.
RUNNER=""
if command -v uv >/dev/null 2>&1 && { [[ -f "uv.lock" ]] || grep -q '^\[tool\.uv' pyproject.toml 2>/dev/null; }; then
  RUNNER="uv run"
fi

# have TOOL — is TOOL runnable via the chosen runner?
have() {
  if [[ -n "$RUNNER" ]]; then
    $RUNNER "$1" --version >/dev/null 2>&1
  else
    command -v "$1" >/dev/null 2>&1
  fi
}

PASS=()
FAIL=()
SKIP=()

# gate NAME CMD... — run a gate, record the outcome, stream its output.
gate() {
  local name="$1"; shift
  echo ""
  echo "==> ${name}: $*"
  if "$@"; then
    PASS+=("$name")
  else
    FAIL+=("$name")
  fi
}

skip() {
  SKIP+=("$1 ($2)")
  echo ""
  echo "==> ${1}: skipped — $2"
}

run() { ${RUNNER:+$RUNNER} "$@"; }

# --- 1. Format + lint (ruff) -------------------------------------------------
if have ruff; then
  if [[ $FIX -eq 1 ]]; then
    # Lint fixes first, then format, per ruff's recommended order.
    run ruff check --fix .
    run ruff format .
  fi
  gate "format" run ruff format --check .
  gate "lint" run ruff check .
else
  skip "format/lint" "ruff not installed"
fi

# --- 2. Type check (mypy > pyright > ty, whichever is configured) ------------
TYPE_TARGET="src"
[[ -d "src" ]] || TYPE_TARGET="."
if have mypy && grep -q '^\[tool\.mypy' pyproject.toml 2>/dev/null; then
  gate "types" run mypy "$TYPE_TARGET"
elif have pyright && { [[ -f "pyrightconfig.json" ]] || grep -q '^\[tool\.pyright' pyproject.toml 2>/dev/null; }; then
  gate "types" run pyright
elif have ty; then
  gate "types" run ty check
else
  skip "types" "no configured type checker found (mypy/pyright/ty)"
fi

# --- 3. Tests (pytest) --------------------------------------------------------
if have pytest; then
  echo ""
  echo "==> tests: run pytest"
  run pytest
  rc=$?
  if [[ $rc -eq 0 ]]; then
    PASS+=("tests")
  elif [[ $rc -eq 5 ]]; then
    # pytest exit 5 = no tests collected: surface it, but don't hard-fail a new repo.
    SKIP+=("tests (no tests collected — write some; see references/testing.md)")
  else
    FAIL+=("tests")
  fi
else
  skip "tests" "pytest not installed"
fi

# --- Summary -------------------------------------------------------------------
echo ""
echo "================ checks summary ================"
for g in "${PASS[@]-}";  do [[ -n "$g" ]] && echo "  PASS  $g"; done
for g in "${SKIP[@]-}";  do [[ -n "$g" ]] && echo "  SKIP  $g"; done
for g in "${FAIL[@]-}";  do [[ -n "$g" ]] && echo "  FAIL  $g"; done
echo "================================================"

if [[ ${#FAIL[@]} -gt 0 ]]; then
  echo "Result: FAILED (${#FAIL[@]} gate(s)) — fix the failures above and re-run."
  exit 1
fi
if [[ ${#PASS[@]} -eq 0 ]]; then
  echo "Result: NOTHING RAN — install project tooling (see references/tooling.md)."
  exit 1
fi
echo "Result: OK — all executed gates passed."
