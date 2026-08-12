"""Isolated, current-shape Rack fixture for the M2UX5 plate press."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, Response

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from verification.fixture_isolation import install_fixture_isolation
from verification.m2h.scenario_app import _model
from verification.m2ux1.scenario_app import LayoutSpine

ROOT = Path(__file__).parents[2]
WEB = ROOT / "web"
PLATES = {
    "canonical": (WEB / "src" / "themes" / "cobalt-seraph-plate.png", "image/png"),
    "second": (ROOT / "verification" / "m2ux4" / "02-seraph-dressed-1280x900.png", "image/png"),
}


def _monochrome_png() -> bytes:
    """D.2 114 fixture: twelve low-contrast gray bands must fail accent / ground."""
    width = height = 120
    rows = []
    for _y in range(height):
        row = bytearray([0])
        for x in range(width):
            value = 96 + min(11, x // 10)
            row.extend((value, value, value))
        rows.append(bytes(row))
    payload = zlib.compress(b"".join(rows), level=9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", payload)
        + chunk(b"IEND", b"")
    )


def _route_around_html(plate: str) -> str:
    """Bypass only the native picker; the ordinary in-page change handler still owns the press."""
    index = (WEB / "dist" / "index.html").read_text()
    route = f"/__scenario__/plate/{plate}"
    filename = {
        "canonical": "cobalt-seraph-plate.png",
        "second": "02-seraph-dressed-1280x900.png",
        "monochrome": "low-contrast-monochrome.png",
    }[plate]
    script = f"""
<script>
(() => {{
  const route = {json.dumps(route)};
  const filename = {json.dumps(filename)};
  const deliver = async () => {{
    const input = document.querySelector('[data-testid="plate-press-input"]');
    if (!(input instanceof HTMLInputElement)) {{
      window.setTimeout(deliver, 40);
      return;
    }}
    const response = await fetch(route);
    if (!response.ok) throw new Error(`fixture plate route failed: ${{response.status}}`);
    const blob = await response.blob();
    const transfer = new DataTransfer();
    transfer.items.add(new File([blob], filename, {{ type: blob.type }}));
    history.replaceState(null, '', '/?fixture=M2UX5%20REGRESSION');
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
    const markStoredColorways = async () => {{
      const status = document.querySelector('[data-testid="plate-press-status"]');
      if (!status || !status.textContent || status.textContent.startsWith('Pressing')) {{
        window.setTimeout(markStoredColorways, 40);
        return;
      }}
      const stored = localStorage.getItem('nocturne.colorways.v1') ?? '';
      const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(stored));
      document.documentElement.dataset.m2ux5StorageDigest = Array.from(
        new Uint8Array(digest),
        (byte) => byte.toString(16).padStart(2, '0'),
      ).join('');
      document.documentElement.dataset.m2ux5StorageCount = stored
        ? String(JSON.parse(stored).length)
        : '0';
    }};
    void markStoredColorways();
  }};
  void deliver();
}})();
</script>
"""
    return index.replace("</body>", f"{script}</body>")


def create_scenario_app() -> FastAPI:
    settings = HarnessSettings(
        principal_id="m2ux5-verification",
        machine_id="m2ux5-verification",
        agent_id="m2ux5-verification",
        chat_model="local:m2ux5-verification",
        model_context_tokens=4096,
        extraction_idle_hours=None,
    )
    harness_app = create_dev_app(
        settings=settings,
        agent=HarnessAgent(settings, model=_model()),
        spine=LayoutSpine(),  # type: ignore[arg-type]
    )
    app = FastAPI(title="M2UX5 deterministic plate-press verification")
    install_fixture_isolation(app, "M2UX5 REGRESSION")

    @app.get("/__scenario__/plate/{plate}")
    async def plate_bytes(plate: str) -> Response:
        if plate == "monochrome":
            return Response(_monochrome_png(), media_type="image/png")
        entry = PLATES.get(plate)
        if entry is None:
            return Response(status_code=404)
        path, media_type = entry
        return FileResponse(path, media_type=media_type, filename=path.name)

    @app.get("/__scenario__/press/{plate}")
    async def press_route_around(plate: str) -> HTMLResponse:
        if plate not in {*PLATES, "monochrome"}:
            return HTMLResponse(status_code=404)
        return HTMLResponse(_route_around_html(plate))

    app.mount("/", harness_app)
    return app


__all__ = ["create_scenario_app"]
