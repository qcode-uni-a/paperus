"""Print the API's OpenAPI schema, for generating the frontend's types.

``python -m paperus.openapi > ../web/src/lib/api/openapi.json``
"""

import json

from paperus.app import create_app

if __name__ == "__main__":
    print(json.dumps(create_app().openapi(), indent=2))
