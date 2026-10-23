#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Test runner dependencies remain outside the production frontend lock.
# Explicit tool versions are the single source for this optional development environment.
npm --prefix "$ROOT/ui/control-plane" ci
npm --prefix "$ROOT/ui/control-plane" install \
  --no-save --package-lock=false --ignore-scripts --no-audit --no-fund \
  'vitest@5.0.5' '@playwright/test@1.64.1'
