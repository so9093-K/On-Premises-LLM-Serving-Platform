"""현재 Gateway Runtime 상태에서 smoke inference probe 대상을 결정한다."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from typing import Any


class SmokeRuntimeSelectionError(ValueError):
    """Smoke가 안전하게 probe 대상을 결정할 수 없을 때 발생한다."""


def _indexed_items(
    raw: object,
    *,
    field: str,
    label: str,
) -> dict[str, Mapping[str, Any]]:
    if not isinstance(raw, list):
        raise SmokeRuntimeSelectionError(f"{label} must be an array")
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise SmokeRuntimeSelectionError(f"{label} entries must be objects")
        key = item.get(field)
        if not isinstance(key, str) or not key:
            raise SmokeRuntimeSelectionError(f"{label} entries must define {field}")
        indexed[key] = item
    return indexed


def select_skipped_runtimes(
    document: Mapping[str, Any],
    runtime_keys: Iterable[str],
) -> list[str]:
    """현재 serving 대상이 아닌 Runtime만 반환한다.

    effective topology에서 unavailable이거나 desired state가 stopped인 Runtime은
    의도된 policy state이므로 해당 Runtime 자체를 요구하는 inference probe를 보내지
    않는다. 반대로 active Runtime은 반드시 probe 대상에 남긴다. starting, 누락 또는
    알 수 없는 상태는 readiness 판단을 확정할 수 없으므로 fail-closed한다.
    """

    runtimes = _indexed_items(
        document.get("runtimes"),
        field="service_key",
        label="runtimes",
    )
    topology = _indexed_items(
        document.get("topology", []),
        field="service_key",
        label="topology",
    )

    skipped: list[str] = []
    seen: set[str] = set()
    for runtime_key in runtime_keys:
        if runtime_key in seen:
            continue
        seen.add(runtime_key)

        topology_item = topology.get(runtime_key)
        if topology_item is not None and topology_item.get("available") is False:
            skipped.append(runtime_key)
            continue

        runtime = runtimes.get(runtime_key)
        if runtime is None:
            raise SmokeRuntimeSelectionError(
                f"runtime state missing for available runtime: {runtime_key}"
            )

        state = runtime.get("state")
        if state == "stopped":
            skipped.append(runtime_key)
        elif state == "active":
            continue
        elif state == "starting":
            raise SmokeRuntimeSelectionError(
                f"runtime is still transitioning: {runtime_key}"
            )
        else:
            raise SmokeRuntimeSelectionError(
                f"invalid runtime state for {runtime_key}: {state!r}"
            )

    return skipped


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve Runtime keys that smoke should not inference-probe."
    )
    parser.add_argument(
        "--runtime",
        action="append",
        dest="runtime_keys",
        default=[],
        help="Runtime service_key considered by the smoke test. Repeatable.",
    )
    args = parser.parse_args()

    try:
        document = json.load(sys.stdin)
        if not isinstance(document, Mapping):
            raise SmokeRuntimeSelectionError("runtime status root must be an object")
        skipped = select_skipped_runtimes(document, args.runtime_keys)
    except (json.JSONDecodeError, SmokeRuntimeSelectionError) as exc:
        print(f"[smoke] runtime probe selection failed: {exc}", file=sys.stderr)
        return 2

    print(",".join(skipped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
