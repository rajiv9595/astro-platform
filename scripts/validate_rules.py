
import json, os, sys
from jsonschema import validate, ValidationError

schema = {
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Astro Rule",
  "type": "object",
  "required": ["id","signals"],
  "properties": {
    "id": {"type":"string"},
    "description": {"type":"string"},
    "orb_deg": {"type":"number"},
    "signals": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id","predicate"],
        "properties": {
          "id": {"type":"string"},
          "predicate": {"type":"string"},
          "params": {"type":"object"}
        },
        "additionalProperties": False
      }
    },
    "weights": {"type":"object"},
    "strength_weights": {"type":"object"},
    "active_if": {"type":"string"},
    "strong_if": {"type":"string"}
  },
  "additionalProperties": False
}

def main():
    rd = os.path.join(os.path.dirname(os.path.dirname(__file__)), "rulesets")
    errors = []
    for fname in os.listdir(rd):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(rd, fname)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            errors.append((fname, f"JSON parse error: {e}"))
            continue
        try:
            validate(instance=data, schema=schema)
        except ValidationError as e:
            errors.append((fname, f"Schema validation error: {e.message}"))
    if errors:
        print("Validation FAILED")
        for e in errors:
            print(e)
        sys.exit(2)
    print("All rule JSON files valid.")
    sys.exit(0)

if __name__ == '__main__':
    main()
