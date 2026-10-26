"""Custom exceptions for the application."""


# ==========================================================
# Base Application Error
# ==========================================================

class AppError(Exception):
    """Base exception for all application errors."""

    def __init__(self, message: str = "An unexpected error occurred."):
        self.message = message
        super().__init__(self.message)


# ==========================================================
# OTP Exceptions
# ==========================================================

class OTPError(AppError):
    """Base exception for OTP-related errors."""

    def __init__(
        self,
        message: str = "OTP verification failed.",
        remaining_attempts: int | None = None,
    ):
        self.remaining_attempts = remaining_attempts
        super().__init__(message)


class InvalidOTPError(OTPError):
    """Raised when the OTP code does not match."""

    def __init__(self, remaining_attempts: int | None = None, message: str | None = None):
        msg = message or "Invalid OTP."
        if not message and remaining_attempts is not None and remaining_attempts > 0:
            msg = f"Invalid OTP. {remaining_attempts} attempt(s) remaining."
        super().__init__(message=msg, remaining_attempts=remaining_attempts)


class OTPExpiredError(OTPError):
    """Raised when the OTP has expired or does not exist."""

    def __init__(self, remaining_attempts: int | None = None, message: str | None = None):
        msg = message or "OTP has expired. Please request a new one."
        if not message and remaining_attempts is not None and remaining_attempts > 0:
            msg = f"OTP has expired. {remaining_attempts} attempt(s) remaining."
        super().__init__(message=msg, remaining_attempts=remaining_attempts)


class MaxAttemptsExceededError(OTPError):
    """Raised when the maximum number of OTP verification attempts is reached."""

    def __init__(self, message: str | None = None):
        super().__init__(
            message=message or "Maximum OTP verification attempts exceeded. Please try again later.",
            remaining_attempts=0,
        )


# ==========================================================
# Auth Exceptions
# ==========================================================

class AuthenticationError(AppError):
    """Raised for authentication failures."""
    pass


class AuthorizationError(AppError):
    """Raised when a user lacks required permissions."""
    pass
