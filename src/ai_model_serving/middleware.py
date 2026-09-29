from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import Response

from .errors import error_response, request_id_from_headers


WRITE_METHODS = {"POST", "PUT", "PATCH"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# 운영자 surface다. 브라우저에서는 같은 origin의 Control Plane Console만 쓰고, 나머지
# 호출자(CLI, Prometheus, Runtime Controller)는 브라우저가 아니다. 공개 API(/v1/*)만
# 다른 origin의 브라우저 client를 받는다.
OPERATOR_PATH_PREFIXES = ("/admin", "/internal", "/metrics", "/ready")


def is_operator_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in OPERATOR_PATH_PREFIXES)


def is_cross_site_browser_request(headers: Mapping[str, str]) -> bool:
    """브라우저가 다른 site의 page에서 보낸 요청인지 판정한다.

    브라우저는 ``Sec-Fetch-Site``를 직접 계산하므로 reverse proxy가 Host를 바꿔도
    판정이 흔들리지 않는다. 그 header가 없는 오래된 브라우저는 ``Origin``과 Host를
    비교한다. 둘 다 없으면 curl·SDK·내부 service 같은 비브라우저 client다.
    """
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None:
        return fetch_site not in {"same-origin", "none"}
    origin = headers.get("origin")
    if origin is None:
        return False
    return urlsplit(origin).netloc.lower() != headers.get("host", "").lower()


async def reject_cross_site_operator_writes(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """다른 site의 page가 운영자 상태를 바꾸는 요청을 body를 읽기 전에 거부한다.

    local_open처럼 Admin 인증이 없는 profile에서는 브라우저가 이 요청을 막는 유일한
    경계다. text/plain POST는 CORS preflight 없이 전송되고 Admin handler는
    Content-Type과 무관하게 JSON body를 읽기 때문에, CORS 설정만으로는 막히지 않는다.
    같은 origin의 Console과 비브라우저 client는 설정 없이 그대로 통과한다.
    """
    if (
        request.method in SAFE_METHODS
        or not is_operator_path(request.url.path)
        or not is_cross_site_browser_request(request.headers)
    ):
        return await call_next(request)
    return error_response(
        "FORBIDDEN",
        "Operator endpoints do not accept state-changing requests from another site. "
        "Use the Control Plane Console served by this Gateway or a non-browser client.",
        request_id_from_headers(request.headers),
    )


def _too_large_response(request: Request, max_body_bytes: int) -> Response:
    return error_response(
        "REQUEST_TOO_LARGE",
        f"Request body exceeds {max_body_bytes} bytes. Limit applies to the full JSON body, including base64 media; reduce media size or split the request.",
        request_id_from_headers(request.headers),
    )


def _content_length_exceeds_limit(request: Request, max_body_bytes: int) -> bool:
    raw_value = request.headers.get("content-length")
    if raw_value is None:
        return False
    try:
        return int(raw_value) > max_body_bytes
    except ValueError:
        # 잘못된 형식의 Content-Length 값은 ASGI 서버/프레임워크가 처리하도록 둔다.
        return False


async def _read_limited_body(request: Request, *, max_body_bytes: int) -> bytes | None:
    """``max_body_bytes``까지 요청 body를 읽는다.

    Returns ``None`` as soon as the limit is exceeded. This avoids buffering an
    arbitrarily large request body in memory before rejecting it, while still
    replaying an already-validated body to downstream FastAPI handlers.
    """
    chunks: list[bytes] = []
    total = 0
    more_body = True

    while more_body:
        message: dict[str, Any] = await request.receive()
        if message.get("type") == "http.disconnect":
            return b""

        chunk = message.get("body", b"")
        if chunk:
            total += len(chunk)
            if total > max_body_bytes:
                return None
            chunks.append(chunk)

        more_body = bool(message.get("more_body", False))

    return b"".join(chunks)



async def enforce_request_body_limit(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    *,
    max_body_bytes: int,
) -> Response:
    """실제 body 크기를 기준으로 너무 큰 write 요청을 거부한다.

    Content-Length is used as a fast rejection path when available. Chunked or
    missing-length bodies are read incrementally and rejected as soon as the
    configured limit is crossed, instead of calling ``request.body()`` and
    buffering the entire oversized payload first.
    """
    if request.method not in WRITE_METHODS:
        return await call_next(request)

    if _content_length_exceeds_limit(request, max_body_bytes):
        return _too_large_response(request, max_body_bytes)

    body = await _read_limited_body(request, max_body_bytes=max_body_bytes)
    if body is None:
        return _too_large_response(request, max_body_bytes)

    # Starlette의 함수형 미들웨어는 request를 캐시된 request 객체로 감싼다.
    # 점진적 읽기가 끝난 후 캐시를 채워서, downstream request 파싱이 원본
    # receive 채널을 다시 건드리지 않고도 동일하게 검증된 body를 사용할 수
    # 있게 한다.
    setattr(request, "_body", body)
    return await call_next(request)
