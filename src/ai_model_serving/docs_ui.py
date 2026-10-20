from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# 표의 식별자는 줄바꿈 없이 가로 스크롤로 읽는다. 데스크톱의 태그 설명은
# 엔드포인트 카드 폭을 제한해 본문 공간을 확보한다. Scalar 버전 변경 시 선택자를 확인한다.
DOCS_CUSTOM_CSS = (
    ".scalar-app .markdown table code{white-space:nowrap;word-break:normal;}"
    ".scalar-app .markdown table{display:block;width:100%;overflow-x:auto;}"
    ".scalar-toaster{max-width:calc(100vw - 32px);}"
    "@media (min-width:1000px){"
    ".section-column:has(> [class*=endpoints-]),"
    ".section-column:has(> .sticky-cards){flex:0 0 300px;}"
    "}"
)

# 문서 화면의 JS 번들은 저장소에 vendoring 한다. 온프레미스 배포는 외부 egress가
# 없어도 /docs가 떠야 하고, CDN 참조는 air-gap 망에서 빈 화면이 된다.
# 버전과 SRI 해시는 이 표가 단독으로 소유하며, scripts/build/fetch_docs_assets.py가
# 같은 값으로 내려받아 검증한다. 브라우저는 same-origin 응답에도 integrity를 그대로
# 검증하므로 vendoring 파일이 손상되면 실행하지 않는다.
_STATIC_DIR = Path(__file__).resolve().parent / "static"


@dataclass(frozen=True)
class VendoredAsset:
    """문서 화면이 쓰는 self-host JS 번들 하나."""

    filename: str
    source_url: str
    integrity: str

    @property
    def route(self) -> str:
        return f"/static/{self.filename}"

    @property
    def path(self) -> Path:
        return _STATIC_DIR / self.filename


SCALAR_BUNDLE = VendoredAsset(
    filename="scalar-api-reference-1.69.0.js",
    source_url=(
        "https://cdn.jsdelivr.net/npm/@scalar/api-reference@1.69.0/"
        "dist/browser/standalone.js"
    ),
    integrity="sha384-UL+pt9bcR3hCuzEybA1bAyu6yv9qkzJuYCP5N+HZPOo9ZkUXcMflxqBjC1vfDzfe",
)
VENDORED_ASSETS = (SCALAR_BUNDLE,)

# 브라우저는 HTML 문서를 열 때마다 /favicon.ico를 요청한다. 라우트가 없으면
# /docs를 열 때마다 운영 로그에 404가 쌓인다. 외부 URL을 가리킬 수는
# 없으므로(air-gap) 작은 SVG를 인라인으로 들고 직접 서빙한다.
FAVICON_ROUTE = "/favicon.ico"
FAVICON_MEDIA_TYPE = "image/svg+xml"
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="7" fill="#1f2933"/>'
    '<circle cx="16" cy="16" r="4.5" fill="#7dd3fc"/>'
    '<circle cx="7" cy="9" r="2.5" fill="#94a3b8"/>'
    '<circle cx="7" cy="23" r="2.5" fill="#94a3b8"/>'
    '<circle cx="25" cy="16" r="2.5" fill="#94a3b8"/>'
    '<g stroke="#94a3b8" stroke-width="1.6">'
    '<line x1="9.2" y1="10.2" x2="13" y2="13.6"/>'
    '<line x1="9.2" y1="21.8" x2="13" y2="18.4"/>'
    '<line x1="20.5" y1="16" x2="22.5" y2="16"/>'
    "</g></svg>"
).encode("utf-8")


# Scalar는 vendored JS만 self-host해도 기본 설정에 따라 localhost Agent와
# fonts.scalar.com을 사용할 수 있다. API 문서는 on-prem/air-gap surface이므로
# 런타임 egress를 암묵적 default에 맡기지 않고 명시적으로 닫는다.
# modelsSectionLabel은 플랫폼의 public "Models" 개념과 OpenAPI schema section을
# 구분하기 위한 UI label이다. API의 Models tag 이름은 바꾸지 않는다.
SCALAR_CONFIG = json.dumps({
    "theme": "default",
    "customCss": DOCS_CUSTOM_CSS,
    "defaultHttpClient": {"targetKey": "shell", "clientKey": "curl"},
    "agent": {"disabled": True},
    "mcp": {"disabled": True},
    "telemetry": False,
    "withDefaultFonts": False,
    "showDeveloperTools": "never",
    "hideClientButton": True,
    "persistAuth": False,
    "modelsSectionLabel": "Schemas",
})


def scalar_html(openapi_url: str, title: str, *, bundle_url: str | None = None) -> str:
    """Gateway와 Risk Signal Service의 공통 API 문서 화면을 렌더링한다."""
    bundle_url = bundle_url or SCALAR_BUNDLE.route
    return f"""<!doctype html>
<html lang="ko">
  <head>
    <title>{title}</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>body {{ margin: 0; }}</style>
  </head>
  <body>
    <script
      id="api-reference"
      data-url="{openapi_url}"
      data-configuration='{SCALAR_CONFIG}'
    ></script>
    <script
      src="{bundle_url}"
      integrity="{SCALAR_BUNDLE.integrity}"
    ></script>
  </body>
</html>"""
