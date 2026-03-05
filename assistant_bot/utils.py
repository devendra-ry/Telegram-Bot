def parse_params(args: list[str], defaults: dict) -> tuple[dict, list[str]]:
    """Parse key=value parameters from command arguments."""
    params = defaults.copy()
    remaining: list[str] = []

    for arg in args:
        if "=" not in arg:
            remaining.append(arg)
            continue

        key, _, value = arg.partition("=")
        key = key.lower()
        if key not in params:
            remaining.append(arg)
            continue

        default_val = defaults[key]
        try:
            if isinstance(default_val, bool):
                params[key] = value.lower() in ("true", "1", "yes")
            elif isinstance(default_val, int):
                params[key] = int(value)
            elif isinstance(default_val, float):
                params[key] = float(value)
            else:
                params[key] = value
        except ValueError:
            pass

    return params, remaining
