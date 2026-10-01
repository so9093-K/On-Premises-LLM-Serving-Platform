from __future__ import annotations

from typing import Any

from ai_model_serving.risk_input import detector_prompt_char_budget
from .common import (
    ROOT,
    read_yaml,
    service_default_host_ports,
)


def validate_deployment_targets() -> None:
    from ai_model_serving.deployment_target import load_deployment_target
    from ai_model_serving.serving_profile import load_main_serving_catalog

    document = read_yaml('configs/deployment_targets.yaml')
    targets = document.get('targets')
    default_target = str(document.get('default_target', ''))
    if not isinstance(targets, dict) or default_target not in targets:
        raise SystemExit('deployment_targets.yaml must declare an existing default_target')
    for target_id, raw_target in targets.items():
        target = load_deployment_target(ROOT / 'configs/deployment_targets.yaml', str(target_id))
        if target.implementation_status == 'planned' and target_id == default_target:
            raise SystemExit('a planned deployment target cannot be the default')
        load_main_serving_catalog(ROOT / target.main_profile_catalog)
        # Console은 runs_monitoring_stack으로 Grafana 링크를 보인다. compose와 어긋나면
        # 없는 Grafana를 가리키거나 있는 것을 숨긴다. dynamic target은 full-stack compose를 쓴다.
        compose_files = raw_target.get('compose_files') or ['ops/compose/full-stack.private-network.yaml']
        runs_prometheus = False
        for path in compose_files:
            if not (ROOT / path).exists():
                continue
            compose_services = read_yaml(path).get('services')
            if isinstance(compose_services, dict) and 'prometheus' in compose_services:
                runs_prometheus = True
                break
        if target.runs_monitoring_stack != runs_prometheus:
            raise SystemExit(
                f'deployment target {target_id!r} declares runs_monitoring_stack='
                f'{target.runs_monitoring_stack} but its compose files '
                f"{'include' if runs_prometheus else 'do not include'} prometheus"
            )


def validate_deploy_profiles() -> None:
    from ai_model_serving.runtime_topology import load_runtime_topology

    try:
        topology = load_runtime_topology(ROOT)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    document = read_yaml('configs/deploy_profiles.yaml')
    profiles = document.get('profiles')
    default_profile = document.get('default_profile')
    if not isinstance(profiles, dict) or default_profile not in profiles:
        raise SystemExit('deploy_profiles.yaml must declare an existing default_profile')
    controllable_runtimes = topology.controllable_keys
    for profile_id, profile in profiles.items():
        deferred = profile.get('deferred_runtimes') if isinstance(profile, dict) else None
        if not isinstance(deferred, list) or not all(isinstance(item, str) for item in deferred):
            raise SystemExit(
                f'deploy profile {profile_id!r} must define deferred_runtimes as a string list'
            )
        unknown_runtimes = set(deferred) - controllable_runtimes
        if unknown_runtimes:
            raise SystemExit(
                f'deploy profile {profile_id!r} references non-controllable runtimes: '
                f'{", ".join(sorted(unknown_runtimes))}'
            )


def validate_ports() -> None:
    """실제 host endpoint port 정책만 service registry 기준으로 검증한다.

    Compose 내부 runtime port 일치는 load_runtime_topology()가 소유한다. 여기서는
    host-published service와 app-only host_process가 선언한 default_host_port만 본다.
    """
    services = read_yaml('configs/services.yaml')['services']
    host_ports = service_default_host_ports()
    owners_by_port: dict[int, str] = {}

    for service_id, host_port in host_ports.items():
        previous = owners_by_port.get(host_port)
        if previous is not None:
            raise SystemExit(
                f'duplicate default_host_port {host_port}: {previous} and {service_id}'
            )
        owners_by_port[host_port] = service_id

        service = services[service_id]
        categories = set(service.get('categories', []))
        if (
            {'public_entrypoint', 'host_process'} & categories
            and not 9400 <= host_port <= 9409
        ):
            raise SystemExit(
                f'{service_id} application host port must be in 9400..9409, got {host_port}'
            )
        if 'visualization' in categories and not 9410 <= host_port <= 9419:
            raise SystemExit(
                f'{service_id} visualization host port must be in 9410..9419, got {host_port}'
            )

    if host_ports.get('gateway') != 9400:
        raise SystemExit(
            f'gateway default_host_port must remain 9400, got {host_ports.get("gateway")}'
        )

    metal_port = int(read_yaml('configs/macos_mlx_runtime.yaml')['runtime']['port'])
    main_runtime_port = int(services['main_llm_vllm']['container_port'])
    if metal_port != main_runtime_port:
        raise SystemExit(
            'macos_mlx_runtime runtime.port must match '
            f'services.main_llm_vllm.container_port {main_runtime_port}, got {metal_port}'
        )


def validate_risk_detector_generation_budget() -> None:
    serving = read_yaml('configs/model_serving.yaml')['models']
    catalog = read_yaml('configs/model_catalog.yaml')['models']
    detector_specs = read_yaml('configs/model_serving.yaml')['risk_signal_service'].get('detectors', {})
    for detector in detector_specs.values():
        if detector.get('type', 'vllm') == 'local':
            continue
        logical_id = detector['source_model']
        service_key = detector['service_key']
        catalog_tokens = catalog[logical_id]['runtime']['max_output_tokens']
        runtime_tokens = serving[service_key]['max_output_tokens']
        fixed_tokens = detector.get('fixed_parameters', {}).get('max_tokens')
        if not (catalog_tokens == runtime_tokens == fixed_tokens == 1):
            raise SystemExit(
                f'{logical_id} max_output_tokens must align at 1 across model catalog, runtime, and detector policy'
            )
    risk_signal_service_cfg = read_yaml('configs/model_serving.yaml')['risk_signal_service']
    input_policy = risk_signal_service_cfg.get('input_policy', {})
    max_prompt_chars = int(input_policy.get('max_prompt_chars', 0))
    enabled_detector_keys = [
        detector['service_key']
        for detector in detector_specs.values()
        if detector.get('enabled', True) is True and detector.get('type', 'vllm') != 'local'
    ]
    if not enabled_detector_keys:
        # enabled vLLM detector가 없으면 이 상한을 유도할 detector context가 없다.
        # 그때 max_prompt_chars는 local detector에만 적용되는 자체 guard이므로 양수인지만
        # 본다. settings.py의 runtime 유도도 같은 분기를 갖는다.
        if max_prompt_chars <= 0:
            raise SystemExit(
                'configs/model_serving.yaml risk_signal_service.input_policy.max_prompt_chars '
                'must be > 0'
            )
        return
    min_detector_window = min(int(serving[key]['max_model_len']) for key in enabled_detector_keys)
    expected_upper_bound = detector_prompt_char_budget(min_detector_window)
    if max_prompt_chars <= 0 or max_prompt_chars > expected_upper_bound:
        raise SystemExit(
            f'configs/model_serving.yaml risk_signal_service.input_policy.max_prompt_chars={max_prompt_chars} '
            f'must be > 0 and <= {expected_upper_bound} '
            f'(risk_input.detector_prompt_char_budget(min detector max_model_len {min_detector_window}))'
        )

def gpu_budget_status(registry: Any, gpu_budgets: dict[str, Any]) -> dict[str, Any]:
    """설정된 GPU 총 사용률을 gpu_budgets.yaml의 avoid_above 정책과 비교한다."""
    total = round(
        sum(float(service.config.get("gpu_memory_utilization", 0)) for service in registry.iter_runtime_services()),
        6,
    )
    policy = gpu_budgets["gpu"]["total_gpu_memory_utilization"]
    avoid_above = float(policy.get("avoid_above", 1.0))
    return {
        "total_gpu_memory_utilization": total,
        "avoid_above": avoid_above,
        "over_avoid_threshold": total >= avoid_above,
    }


def validate_model_resource_control_policy() -> None:
    from ai_model_serving.domain import ModelRegistry

    serving = read_yaml('configs/model_serving.yaml')
    catalog_document = read_yaml('configs/model_catalog.yaml')
    for key, cfg in serving['models'].items():
        if cfg.get('enabled', True) is not True:
            continue
        control = cfg.get('resource_control')
        if not isinstance(control, dict):
            raise SystemExit(f'{key} missing resource_control')
        required_fields = ['isolation', 'admission_control']
        if key != 'main_llm':
            required_fields.append('request_limits')
        for field in required_fields:
            if field not in control:
                raise SystemExit(f'{key} resource_control missing {field}')
        admission = control['admission_control']
        if key != 'main_llm' and admission.get('max_concurrency') != int(cfg.get('max_num_seqs', admission.get('max_concurrency'))):
            raise SystemExit(f'{key} resource control concurrency should track max_num_seqs')
        if float(cfg.get('gpu_memory_utilization', 0)) <= 0 or float(cfg.get('gpu_memory_utilization', 0)) >= 1:
            raise SystemExit(f'{key} gpu_memory_utilization must be between 0 and 1')
    registry = ModelRegistry(catalog_document, serving)
    budget = gpu_budget_status(registry, read_yaml('configs/gpu_budgets.yaml'))
    if budget['over_avoid_threshold']:
        raise SystemExit(
            f'total configured gpu_memory_utilization {budget["total_gpu_memory_utilization"]} '
            f'must stay below avoid_above {budget["avoid_above"]}'
        )
    # 이 검증은 profile 정책 구조만 본다. image pin의 실제 해석은 .env를 읽는
    # boot/admin 경로에서 수행하므로 여기서 runtime image env를 요구하지 않는다.
    main_profiles = read_yaml('configs/main_model_profiles.yaml')['profiles']
    for profile_id, profile in main_profiles.items():
        policy = profile.get('gateway_policy', {})
        if not policy:
            raise SystemExit(f'{profile_id} must declare gateway_policy')
        limits = policy['request_limits']
        capabilities = profile.get('capabilities', {})
        if 'image' in capabilities.get('deployed_input', []):
            if int(limits.get('max_image_inputs', 0)) != 1 or limits.get('allowed_image_url_schemes') != ['data']:
                raise SystemExit(f'{profile_id} image input policy must allow exactly one data:image input')
            if int(limits.get('max_image_bytes', 0)) <= 0 or int(limits.get('max_image_pixels', 0)) <= 0:
                raise SystemExit(f'{profile_id} image input policy must define decoded byte and pixel limits')
            if not limits.get('allowed_image_mime_types'):
                raise SystemExit(f'{profile_id} image input policy must define allowed image MIME types')
