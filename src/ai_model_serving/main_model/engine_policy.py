from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


def _int_flag(command: Sequence[str], flag: str) -> int | None:
    if flag not in command:
        return None
    try:
        return int(command[command.index(flag) + 1])
    except (IndexError, ValueError):
        return None


def _float_flag(command: Sequence[str], flag: str) -> float | None:
    if flag not in command:
        return None
    try:
        return float(command[command.index(flag) + 1])
    except (IndexError, ValueError):
        return None


@dataclass(frozen=True)
class VllmEnginePolicy:
    """Capacity-related vLLM knobs resolved from the final runtime command."""

    max_model_len: int | None
    max_num_seqs: int | None
    max_num_batched_tokens: int | None
    gpu_memory_utilization: float

    @classmethod
    def from_command(cls, command: Sequence[str]) -> "VllmEnginePolicy":
        gpu_memory_utilization = _float_flag(command, "--gpu-memory-utilization")
        return cls(
            max_model_len=_int_flag(command, "--max-model-len"),
            max_num_seqs=_int_flag(command, "--max-num-seqs"),
            max_num_batched_tokens=_int_flag(command, "--max-num-batched-tokens"),
            # vLLM flag가 없거나 해석할 수 없으면 기존 catalog 계약과 같은 0.9다.
            gpu_memory_utilization=(
                0.9 if gpu_memory_utilization is None else gpu_memory_utilization
            ),
        )

    def public_view(self) -> dict[str, Any]:
        return {
            "max_model_len": self.max_model_len,
            "max_num_seqs": self.max_num_seqs,
            "max_num_batched_tokens": self.max_num_batched_tokens,
            "gpu_memory_utilization": self.gpu_memory_utilization,
        }


@dataclass(frozen=True)
class MlxEnginePolicy:
    """Capacity-related MLX knobs projected from the selected static runtime config."""

    max_kv_size: int
    max_generation_tokens: int
    max_num_seqs: int
    vision_cache_size: int

    @classmethod
    def from_runtime_config(cls, runtime: Mapping[str, Any]) -> "MlxEnginePolicy":
        return cls(
            max_kv_size=int(runtime["max_kv_size"]),
            max_generation_tokens=int(runtime["max_generation_tokens"]),
            # Native MLX launcher projects runtime.max_concurrency to --max-num-seqs.
            max_num_seqs=int(runtime["max_concurrency"]),
            vision_cache_size=int(runtime["vision_cache_size"]),
        )

    def public_view(self) -> dict[str, Any]:
        return {
            "max_kv_size": self.max_kv_size,
            "max_generation_tokens": self.max_generation_tokens,
            "max_num_seqs": self.max_num_seqs,
            "vision_cache_size": self.vision_cache_size,
        }
