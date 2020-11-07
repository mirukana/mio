def remove_none(from_dict: dict) -> dict:
    return {k: v for k, v in from_dict.items() if v is not None}
