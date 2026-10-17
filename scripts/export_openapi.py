import json
from pathlib import Path

from patient_memory.api import create_app

if __name__ == "__main__":
    path = Path("docs/openapi.json")
    path.write_text(json.dumps(create_app().openapi(), indent=2), encoding="utf-8")
    print(path)
