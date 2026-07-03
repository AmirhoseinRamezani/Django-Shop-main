# tests/helpers/json.py
import json


def pretty(data):

    return json.dumps(
        data,
        indent=4,
        ensure_ascii=False,
        sort_keys=True,
    )