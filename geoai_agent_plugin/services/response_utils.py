def success_response(message="", data=None, warnings=None, artifacts=None, **extra):
    response = {
        "status": "success",
        "message": message,
        "data": {} if data is None else data,
        "warnings": [] if warnings is None else warnings,
        "artifacts": {} if artifacts is None else artifacts,
    }
    response.update(extra)
    return response


def error_response(message, data=None, warnings=None, artifacts=None, **extra):
    response = {
        "status": "error",
        "message": message,
        "data": {} if data is None else data,
        "warnings": [] if warnings is None else warnings,
        "artifacts": {} if artifacts is None else artifacts,
    }
    response.update(extra)
    return response
