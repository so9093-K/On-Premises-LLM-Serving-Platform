#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONSOLE="$ROOT/ui/control-plane"
TOOLS="$ROOT/scripts/quality"

# 제품 UI 의존성은 기존 lock으로 설치한다.
npm --prefix "$CONSOLE" ci

# Runner의 의존성은 분리된 node_modules에 설치하여 제품 번들에 영향을 주지 않는다.
npm --prefix "$TOOLS" install --package-lock=false --ignore-scripts --no-audit --no-fund

# Native Runner만 Console 실행 경로에 투영한다. 제품 의존성은 변경하지 않는다.
mkdir -p "$CONSOLE/node_modules/.bin" "$CONSOLE/node_modules/@playwright"
ln -sfn "$TOOLS/node_modules/vitest" "$CONSOLE/node_modules/vitest"
ln -sfn "$TOOLS/node_modules/@playwright/test" "$CONSOLE/node_modules/@playwright/test"
ln -sfn "$TOOLS/node_modules/.bin/vitest" "$CONSOLE/node_modules/.bin/vitest"
ln -sfn "$TOOLS/node_modules/.bin/playwright" "$CONSOLE/node_modules/.bin/playwright"
