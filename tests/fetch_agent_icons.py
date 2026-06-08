"""Download every Valorant agent's killfeed portrait from valorant-api.com
into assets/agent_icons/reference/ as a baseline template library.

These are Riot assets, so they're downloaded on demand (gitignored) rather
than committed. Footage-extracted templates (per your own clips) are more
accurate and take precedence.
"""

from pathlib import Path

import requests

API = "https://valorant-api.com/v1/agents?isPlayableCharacter=true"
OUT = Path("assets/agent_icons/reference")


def slug(name: str) -> str:
    return name.lower().replace("/", "").replace(" ", "")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = requests.get(API, timeout=30).json()["data"]
    print(f"{len(data)} agents")
    for a in data:
        name = slug(a["displayName"])
        for field in ("killfeedPortrait", "displayIcon"):
            url = a.get(field)
            if not url:
                continue
            suffix = "" if field == "killfeedPortrait" else "_display"
            dest = OUT / f"{name}{suffix}.png"
            img = requests.get(url, timeout=30).content
            dest.write_bytes(img)
        print(f"  {name}")
    print(f"saved -> {OUT}")


if __name__ == "__main__":
    main()
