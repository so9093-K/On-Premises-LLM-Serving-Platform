"""반복 수집 오류 중에도 모델 연결 실패의 원인을 확인할 수 있다."""
import json

from scripts.ops import platform_logs


def test_repeated_scrapes_do_not_hide_gateway_readiness(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(platform_logs, "REQUEST_EVENTS", tmp_path)
    gateway = {"service": "gateway", "route": "/ready", "status_code": 503,
               "readiness_summary": "main_llm_vllm: MODEL_UNAVAILABLE"}
    scrape = {"service": "risk-signal-service", "route": "/metrics", "status_code": 401,
              "error_code": "UNAUTHORIZED"}
    (tmp_path / "gateway.jsonl").write_text(json.dumps(gateway) + "\n")
    (tmp_path / "risk.jsonl").write_text("\n".join(json.dumps(scrape) for _ in range(10)) + "\n")
    assert platform_logs._structured_events(3) == 2
    output = capsys.readouterr().out
    assert "main_llm_vllm: MODEL_UNAVAILABLE" in output
    assert "repeated=10" in output
    assert output.count("UNAUTHORIZED") == 1
    assert platform_logs._structured_events(3, all_events=True) == 3
    output = capsys.readouterr().out
    assert output.count("UNAUTHORIZED") == 3
    assert "repeated=" not in output
