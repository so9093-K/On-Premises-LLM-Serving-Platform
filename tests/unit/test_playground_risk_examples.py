"""Control Plane Risk Playground의 합성 예제가 실제 로컬 검출기 결과와 일치하는지 검증한다.

예제는 운영자가 PII·Secret 탐지를 실제 데이터 없이 확인하는 수단이다. 검출기 규칙이
바뀌어 예제가 더 이상 기대 신호를 만들지 않으면, 화면은 "탐지 없음"을 정상 동작처럼
보여 주게 된다. Prompt 예제는 모델 Runtime이 판정하므로 결정론적 검증 대상이 아니다.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ai_model_serving.detectors.pii import PIIProtectionDetector
from ai_model_serving.detectors.secret import SecretExposureDetector

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = json.loads(
    (ROOT / "ui/control-plane/src/playgroundRiskExamples.json").read_text(encoding="utf-8")
)
LOCAL_DETECTORS = {
    "pii": (PIIProtectionDetector(),),
    "secret": (SecretExposureDetector(),),
    # Core의 통합 평가는 로컬 PII·Secret 검출기만 실행한다.
    "assessment": (PIIProtectionDetector(), SecretExposureDetector()),
}


@pytest.mark.parametrize(
    "example",
    [item for item in EXAMPLES if item["check"] in LOCAL_DETECTORS],
    ids=lambda item: item["id"],
)
def test_local_risk_example_produces_its_expected_signals(example) -> None:
    async def detected_codes() -> set[str]:
        codes: set[str] = set()
        for detector in LOCAL_DETECTORS[example["check"]]:
            result = await detector.assess(example["prompt"])
            assert result["status"] == "completed"
            codes.update(item["code"] for item in result["categories"] if item["detected"])
            # 응답은 원문 값을 돌려주지 않는다. 화면도 이 응답만 표시한다.
            assert example["prompt"] not in json.dumps(result, ensure_ascii=False)
        return codes

    assert asyncio.run(detected_codes()) == set(example["expected_codes"])


def test_examples_cover_local_detectors_and_a_clean_baseline() -> None:
    checks = {item["check"] for item in EXAMPLES}
    assert {"pii", "secret", "assessment"} <= checks
    assert any(item["check"] == "assessment" and not item["expected_codes"] for item in EXAMPLES)
