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


class UnsupportedMediaTypeError(ValueError, ApplicationError):
    """A file reached the server fine but its media type cannot be processed.

    Dual inheritance on purpose: it is a ``ValueError`` so service-layer code
    that guards with ``except ValueError`` still catches it, AND an
    ``ApplicationError`` so the HTTP routers map it to 415 (not the generic
    422). Example: a genuine PDF — uploaded successfully — whose text layer
    we cannot read from raw bytes.
    """

    code = "UNSUPPORTED_MEDIA_TYPE"
    status_code = 415
