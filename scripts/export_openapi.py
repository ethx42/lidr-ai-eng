"""Write the committed API contract (`make openapi`); `tests/test_openapi_snapshot.py` checks it."""

import json
from pathlib import Path

from app.main import create_app

CONTRACT = Path(__file__).resolve().parent.parent / "contracts" / "openapi.json"


def main() -> None:
    CONTRACT.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT.write_text(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {CONTRACT}")


if __name__ == "__main__":
    main()
