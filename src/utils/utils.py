def json_converter(obj):
    if isinstance(obj, str):
        try:
            return int(obj)
        except ValueError:
            return obj
    elif isinstance(obj, list):
        return [json_converter(item) for item in obj]
    elif isinstance(obj, dict):
        return {json_converter(key): json_converter(value) for key, value in obj.items()}
    else:
        return obj