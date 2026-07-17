class ApplicationError(RuntimeError):
    code = "APPLICATION_ERROR"
    status_code = 500


class NotFoundError(ApplicationError):
    code = "NOT_FOUND"
    status_code = 404


class ConflictError(ApplicationError):
    code = "CONFLICT"
    status_code = 409


class ForbiddenError(ApplicationError):
    code = "FORBIDDEN"
    status_code = 403
