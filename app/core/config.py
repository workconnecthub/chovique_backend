"""
Application configuration.

Loads environment variables from .env using Pydantic Settings.
Works with local development, Render, and Vercel deployments.
"""

import json
from functools import lru_cache
from typing import Annotated, List

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # =========================================================
    # APPLICATION
    # =========================================================

    APP_NAME: str = "Chovique Chocolatier"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # =========================================================
    # API
    # =========================================================

    API_V1_PREFIX: str = "/api/v1"
    BACKEND_URL: str = ""

    # =========================================================
    # DATABASE
    # =========================================================

    DATABASE_URL: str
    DB_ECHO: bool = False

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_url(cls, value):

        if not isinstance(value, str):
            return value

        value = value.strip()

        if value.startswith("postgres://"):
            value = value.replace(
                "postgres://",
                "postgresql+asyncpg://",
                1,
            )
        elif (
            value.startswith("postgresql://")
            and not value.startswith("postgresql+asyncpg://")
        ):
            value = value.replace(
                "postgresql://",
                "postgresql+asyncpg://",
                1,
            )

        # asyncpg does not accept 'sslmode', it requires 'ssl'
        if "sslmode=" in value:
            value = value.replace("sslmode=", "ssl=")

        return value

    # =========================================================
    # REDIS
    # =========================================================

    REDIS_URL: str = ""

    # =========================================================
    # JWT / AUTHENTICATION
    # =========================================================

    SECRET_KEY: str

    ALGORITHM: str = "HS256"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # =========================================================
    # CORS
    # =========================================================

    # NoDecode is important here.
    #
    # Without NoDecode, Pydantic Settings tries to JSON-decode
    # ALLOWED_ORIGINS before our validator runs.
    #
    # This allows both:
    #
    # https://example.com,http://localhost:5173
    #
    # and:
    #
    # ["https://example.com","http://localhost:5173"]

    ALLOWED_ORIGINS: Annotated[List[str], NoDecode]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, value):

        if value is None:
            return []

        # Already a list
        if isinstance(value, list):
            return [
                origin.strip().rstrip("/")
                for origin in value
                if isinstance(origin, str) and origin.strip()
            ]

        # String from Render / .env
        if isinstance(value, str):

            value = value.strip()

            if not value:
                return []

            # -------------------------------------------------
            # JSON array
            # -------------------------------------------------

            if value.startswith("[") and value.endswith("]"):
                try:
                    origins = json.loads(value)

                    if isinstance(origins, list):
                        return [
                            origin.strip().rstrip("/")
                            for origin in origins
                            if isinstance(origin, str)
                            and origin.strip()
                        ]

                except json.JSONDecodeError:
                    pass

            # -------------------------------------------------
            # Comma-separated values
            # -------------------------------------------------

            return [
                origin.strip().rstrip("/")
                for origin in value.split(",")
                if origin.strip()
            ]

        return []

    # =========================================================
    # SMTP / EMAIL
    # =========================================================

    MAIL_SERVER: str = ""
    MAIL_PORT: int = 587

    MAIL_USERNAME: str = ""
    MAIL_PASSWORD: str = ""
    MAIL_FROM: str = ""
    MAIL_FROM_NAME: str = "Chovique Chocolatier"

    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False
    MAIL_TIMEOUT: int = 10

    # Brevo HTTP API key — preferred over SMTP on cloud hosts (Render, Railway, etc.)
    # Get from: Brevo Dashboard → Settings → SMTP & API → API Keys
    BREVO_API_KEY: str = ""

    @field_validator("MAIL_TIMEOUT", mode="before")
    @classmethod
    def parse_mail_timeout(cls, value):

        if value is None or value == "":
            return 10

        try:
            return int(value)

        except (ValueError, TypeError):
            return 10

    # =========================================================
    # OTP
    # =========================================================

    OTP_EXPIRE_SECONDS: int = 300
    MAX_OTP_ATTEMPTS: int = 3
    MAX_OTP_RESEND_ATTEMPTS: int = 3
    OTP_RESEND_LOCKOUT_SECONDS: int = 600

    @field_validator("OTP_EXPIRE_SECONDS", mode="before")
    @classmethod
    def parse_otp_expire_seconds(cls, value):

        if value is None or value == "":
            return 300

        try:
            return max(int(value), 300)

        except (ValueError, TypeError):
            return 300

    # =========================================================
    # GOOGLE OAUTH
    # =========================================================

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # =========================================================
    # RAZORPAY
    # =========================================================

    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""

    # =========================================================
    # RESEND
    # =========================================================

    RESEND_API_KEY: str = ""

    # =========================================================
    # CLOUDINARY (inactive — fields kept to avoid env-var parse errors on Railway)
    # =========================================================

    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    KNOWN_TIGRIS_BUCKET: str = "neat-crate-hruffn9s2hbs2l"

    S3_ENDPOINT_URL: str = Field(
        default="https://t3.storageapi.dev",
        validation_alias=AliasChoices(
            "S3_ENDPOINT_URL",
            "s3_endpoint_url",
            "ENDPOINT_URL",
            "endpoint_url",
            "ENDPOINT",
            "endpoint",
            "AWS_ENDPOINT_URL_S3",
            "AWS_ENDPOINT_URL",
            "TIGRIS_URI",
        ),
    )
    S3_REGION: str = Field(
        default="auto",
        validation_alias=AliasChoices(
            "S3_REGION",
            "s3_region",
            "REGION",
            "region",
            "AWS_REGION",
            "AWS_DEFAULT_REGION",
        ),
    )
    S3_BUCKET_NAME: str = Field(
        default="neat-crate-hruffn9s2hbs2l",
        validation_alias=AliasChoices(
            "S3_BUCKET_NAME",
            "s3_bucket_name",
            "BUCKET_NAME",
            "bucket_name",
            "BUCKET",
            "bucket",
            "TIGRIS_BUCKET",
            "tigris_bucket",
            "AWS_BUCKET_NAME",
            "aws_bucket_name",
        ),
    )
    S3_ACCESS_KEY_ID: str = Field(
        default="tid_EDugeawmRaDxnVsqsFb_apMUGZyYLAeYZRZQkCee_vwFeDXkng",
        validation_alias=AliasChoices(
            "S3_ACCESS_KEY_ID",
            "s3_access_key_id",
            "ACCESS_KEY_ID",
            "access_key_id",
            "AWS_ACCESS_KEY_ID",
            "aws_access_key_id",
            "TIGRIS_ACCESS_KEY_ID",
            "tigris_access_key_id",
        ),
    )
    S3_SECRET_ACCESS_KEY: str = Field(
        default="tsec_3y2xQ5ojwe60m+iqVKvzmXYa8ymuVDZis6WtugaKbYGSmbvxBW5If+QtZy_+SHvFyIk_ra",
        validation_alias=AliasChoices(
            "S3_SECRET_ACCESS_KEY",
            "s3_secret_access_key",
            "SECRET_ACCESS_KEY",
            "secret_access_key",
            "AWS_SECRET_ACCESS_KEY",
            "aws_secret_access_key",
            "TIGRIS_SECRET_ACCESS_KEY",
            "tigris_secret_access_key",
        ),
    )
    # Base URL served to clients. Leave blank to auto-derive from endpoint + bucket.
    S3_PUBLIC_BASE_URL: str = Field(
        default="https://neat-crate-hruffn9s2hbs2l.t3.storageapi.dev",
        validation_alias=AliasChoices(
            "S3_PUBLIC_BASE_URL",
            "s3_public_base_url",
            "PUBLIC_BASE_URL",
            "public_base_url",
        ),
    )

    @field_validator("S3_BUCKET_NAME", mode="before")
    @classmethod
    def clean_bucket_name(cls, value):
        known_bucket = "neat-crate-hruffn9s2hbs2l"
        if not value or not str(value).strip():
            return known_bucket
        val = str(value).strip().strip("'\"").rstrip("/")
        # If the user only gave the display prefix (neat-crate) without the Tigris hash suffix
        if val == "neat-crate" or (val.startswith("neat-crate") and not val.endswith("-hruffn9s2hbs2l")):
            return known_bucket
        if val.lower() in ("chocolate-world", "chovique", "chovique-bucket", "neat_crate"):
            return known_bucket
        return val

    @field_validator("S3_ACCESS_KEY_ID", mode="before")
    @classmethod
    def clean_access_key(cls, value):
        if not value or not str(value).strip():
            return "tid_EDugeawmRaDxnVsqsFb_apMUGZyYLAeYZRZQkCee_vwFeDXkng"
        return str(value).strip().strip("'\"")

    @field_validator("S3_SECRET_ACCESS_KEY", mode="before")
    @classmethod
    def clean_secret_key(cls, value):
        if not value or not str(value).strip():
            return "tsec_3y2xQ5ojwe60m+iqVKvzmXYa8ymuVDZis6WtugaKbYGSmbvxBW5If+QtZy_+SHvFyIk_ra"
        return str(value).strip().strip("'\"")

    @field_validator("S3_ENDPOINT_URL", mode="before")
    @classmethod
    def clean_endpoint_url(cls, value):
        if not value or not str(value).strip():
            return "https://t3.storageapi.dev"
        return str(value).strip().strip("'\"").rstrip("/")

    # =========================================================
    # SUPERADMIN
    # =========================================================

    SUPERADMIN_EMAIL: str = Field(
        validation_alias=AliasChoices(
            "SUPERADMIN_EMAIL",
            "SUPER_ADMIN_EMAIL",
        )
    )

    SUPERADMIN_PASSWORD: str = Field(
        validation_alias=AliasChoices(
            "SUPERADMIN_PASSWORD",
            "SUPER_ADMIN_PASSWORD",
        )
    )

    # =========================================================
    # GOOGLE GEMINI AI
    # =========================================================

    GEMINI_API_KEY: str = ""


# =============================================================
# SETTINGS INSTANCE
# =============================================================

@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()