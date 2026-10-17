"""Main Model 상태 전환과 Catalog 계약 테스트의 공유 Fake Backend.

실제 모델이나 Docker 없이 실행 신원과 Canary 실패를 제어한다.
"""

from __future__ import annotations


_SHARED_IMAGE = "registry.example.com/vllm@sha256:" + "a" * 64
_PROFILE_IMAGE = "registry.example.com/vllm-profile@sha256:" + "b" * 64
_LOCAL_IMAGE = "sha256:" + "c" * 64
_REV_A = "0" * 40
_REV_B = "1" * 40


class FakeBackend:
    def __init__(
        self,
        observed: str | None = None,
        fail_profile: str | None = None,
        fail_drain: bool = False,
        fail_prepare: bool = False,
        started_at: str | None = "boot-0",
    ) -> None:
        self.observed = observed
        self.fail_profile = fail_profile
        self.fail_drain = fail_drain
        self.fail_prepare = fail_prepare
        self.prepared: list[str] = []
        self.replaced: list[str] = []
        self.drain_calls = 0
        self.stopped = 0
        self.started = 0
        # 컨테이너의 관측된 Docker State.StartedAt을 흉내낸다. 테스트가 외부에서
        # main-llm-vllm이 재시작된 상황(Runtime Controller 제어 API를 안 거친 경우)을
        # 시뮬레이션하려면 validate() 호출 사이에 이 값을 바꿔주면 된다.
        self.started_at = started_at
        self.observed_started_at_calls = 0
        self.validate_calls: list[str] = []

    async def observed_profile(self, catalog):
        return self.observed

    async def stop(self, catalog):
        self.stopped += 1

    async def start(self, catalog):
        self.started += 1

    async def prepare(self, catalog, profile):
        self.prepared.append(profile.profile_id)
        if self.fail_prepare:
            raise RuntimeError("cache prepare failed")

    async def replace(self, catalog, profile):
        self.replaced.append(profile.profile_id)
        self.observed = profile.profile_id

    async def wait_for_drain(self, timeout_seconds):
        self.drain_calls += 1
        if self.fail_drain:
            raise RuntimeError("drain timed out")

    async def validate(self, catalog, profile):
        self.validate_calls.append(profile.profile_id)
        if profile.profile_id == self.fail_profile:
            raise RuntimeError("validation failed")

    async def observed_started_at(self, catalog):
        self.observed_started_at_calls += 1
        return self.started_at

