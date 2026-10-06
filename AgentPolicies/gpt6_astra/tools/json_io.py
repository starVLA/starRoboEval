"""Strict JSON helpers shared by the active model methods."""

def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate response field")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("non-finite JSON")
