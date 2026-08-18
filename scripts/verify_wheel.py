"""Verify an installed nocturne-ai wheel from outside its source checkout."""

from __future__ import annotations

import re
from importlib import resources
from importlib.metadata import distribution, version

from fastapi.testclient import TestClient

from harness import __version__
from harness.daemon import create_app


def main() -> None:
    """Prove metadata, command wiring, bundled assets, and clone-free serving."""

    package = distribution("nocturne-ai")
    assert version("nocturne-ai") == version("nocturne-spine") == __version__ == "0.1.5"
    assert "nocturne-spine==0.1.5" in (package.requires or [])
    assert any(
        entry.name == "nocturne" and entry.value == "harness.cli:main"
        for entry in package.entry_points
        if entry.group == "console_scripts"
    )

    web_root = resources.files("harness").joinpath("_web")
    index = web_root.joinpath("index.html").read_text(encoding="utf-8")
    references = re.findall(r'(?:src|href)="/([^"?#]+)', index)
    assert references
    assert all(web_root.joinpath(reference).is_file() for reference in references)
    assert resources.files("harness").joinpath("resources", "docker-compose.yml").is_file()

    pi_root = resources.files("harness").joinpath("_pi")
    assert all(
        pi_root.joinpath(name).is_file()
        for name in (
            "LICENSE.upstream",
            "README.md",
            "dependency.json",
            "location_fence.mjs",
            "nocturne_location.mjs",
            "package-lock.json",
            "package.json",
        )
    )

    installed_names = {str(path) for path in package.files or ()}
    assert not any("node_modules" in path for path in installed_names)
    assert not any("garden/" in path.lower() for path in installed_names)
    assert not any(path.startswith("web/src/") for path in installed_names)

    with resources.as_file(web_root) as web_directory:
        with TestClient(create_app(web_directory)) as client:
            response = client.get("/")
    assert response.status_code == 200
    assert "NOCTURNE" in response.text

    print("nocturne-ai installed-wheel smoke passed")


if __name__ == "__main__":
    main()
