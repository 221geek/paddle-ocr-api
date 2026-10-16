class DomainError(Exception):
    code = "domain_error"
    status_code = 400

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class InvalidInputError(DomainError):
    code = "invalid_input"
    status_code = 422


class UnsupportedMediaError(DomainError):
    code = "unsupported_media_type"
    status_code = 415


class PayloadTooLargeError(DomainError):
    code = "payload_too_large"
    status_code = 413


class QueueSaturatedError(DomainError):
    code = "queue_saturated"
    status_code = 429


class NotReadyError(DomainError):
    code = "ocr_not_ready"
    status_code = 503


class JobNotFoundError(DomainError):
    code = "job_not_found"
    status_code = 404


class ResultExpiredError(DomainError):
    code = "result_expired"
    status_code = 410
