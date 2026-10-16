from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse


CONSOLE_PREFIX = "/admin/console"
CONSOLE_ASSET_PREFIX = f"{CONSOLE_PREFIX}/assets/"
_CONSOLE_ROOT = Path(__file__).resolve().parent / "static" / "control-plane"

_CSP = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    )
)
_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
_INDEX_HEADERS = {**_SECURITY_HEADERS, "Cache-Control": "no-cache"}
_ASSET_HEADERS = {
    **_SECURITY_HEADERS,
    "Cache-Control": "public, max-age=31536000, immutable",
}


def _manifest_asset_files(manifest_path: Path, assets_root: Path) -> dict[str, Path]:
    """생성된 Manifest에서 신뢰할 수 있는 URL·파일 허용 목록을 만든다.

    요청 경로를 파일시스템 경로 생성에 직접 사용해서는 안 된다. 체크인된
    Vite Manifest를 앱 구성 시 한 번 검증하고, 서버가 제공할 수 있는
    불변 정적 파일의 정확한 집합은 해당 Manifest가 소유한다.
    """
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Admin Console asset manifest is unreadable or invalid") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("Admin Console asset manifest must be a JSON object")

    references: set[str] = set()
    for entry in manifest.values():
        if not isinstance(entry, dict):
            raise RuntimeError("Admin Console asset manifest entries must be objects")
        file_name = entry.get("file")
        if file_name is not None:
            if not isinstance(file_name, str):
                raise RuntimeError("Admin Console manifest file must be a string")
            references.add(file_name)
        for field in ("css", "assets"):
            values = entry.get(field, [])
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise RuntimeError(f"Admin Console manifest {field} must be a string array")
            references.update(values)

    files: dict[str, Path] = {}
    for reference in sorted(references):
        logical = PurePosixPath(reference)
        if (
            logical.is_absolute()
            or len(logical.parts) < 2
            or logical.parts[0] != "assets"
            or ".." in logical.parts
        ):
            raise RuntimeError(f"Admin Console manifest contains invalid asset path: {reference}")
        relative = PurePosixPath(*logical.parts[1:])
        candidate = (assets_root / Path(*relative.parts)).resolve()
        if not candidate.is_relative_to(assets_root) or not candidate.is_file():
            raise RuntimeError(f"Admin Console generated asset is missing or unsafe: {reference}")
        files[relative.as_posix()] = candidate

    if not files:
        raise RuntimeError("Admin Console asset manifest does not declare any generated assets")
    return files


def register_admin_console(app: FastAPI, *, root: Path | None = None) -> None:
    """API 문서와 독립적으로 자체 호스팅 Control Plane Console을 등록한다.

    생성된 Frontend는 설치되는 Python 패키지의 구성요소다. 필수 빌드
    산출물이 없다면 Runtime의 빈 브라우저 화면으로 넘어가지 않고
    패키징 오류로 앱 구성 자체를 실패시킨다.
    """
    console_root = (root or _CONSOLE_ROOT).resolve()
    index_path = console_root / "index.html"
    manifest_path = console_root / "asset-manifest.json"
    assets_root = (console_root / "assets").resolve()
    for required in (index_path, manifest_path):
        if not required.is_file():
            raise RuntimeError(f"Admin Console generated artifact is missing: {required}")
    asset_files = _manifest_asset_files(manifest_path, assets_root)

    @app.get(CONSOLE_PREFIX, include_in_schema=False)
    async def admin_console_redirect() -> RedirectResponse:
        return RedirectResponse(f"{CONSOLE_PREFIX}/", status_code=307)

    @app.get(f"{CONSOLE_PREFIX}/", include_in_schema=False)
    async def admin_console_index() -> FileResponse:
        return FileResponse(index_path, headers=_INDEX_HEADERS)

    @app.get(f"{CONSOLE_PREFIX}/assets/{{asset_path:path}}", include_in_schema=False)
    async def admin_console_asset(asset_path: str) -> FileResponse:
        candidate = asset_files.get(asset_path)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Admin Console asset not found.")
        return FileResponse(candidate, headers=_ASSET_HEADERS)

    @app.get(f"{CONSOLE_PREFIX}/{{client_path:path}}", include_in_schema=False)
    async def admin_console_client_route(client_path: str) -> FileResponse:
        # 클라이언트 경로는 BrowserRouter가 소유한다. 서버는 동일한 불변 진입
        # 문서만 제공하며 API·정적 파일 Prefix는 상위에서 더 구체적인 라우트로 처리한다.
        return FileResponse(index_path, headers=_INDEX_HEADERS)
