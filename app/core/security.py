from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings


import logging

logger = logging.getLogger(__name__)

pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated="auto",
)



# ==========================================================
# Password Hashing
# ==========================================================

def hash_password(
    password: str
) -> str:
    try:
        return pwd_context.hash(password)
    except Exception as e:
        logger.warning("Primary pwd_context.hash failed (%s). Falling back to direct bcrypt.", e)
        try:
            import bcrypt
            salt = bcrypt.gensalt()
            return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")
        except Exception:
            raise e



def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    if not hashed_password or not plain_password:
        return False
    try:
        return pwd_context.verify(
            plain_password,
            hashed_password,
        )
    except Exception as e:
        logger.warning("pwd_context.verify failed (%s). Attempting fallback check.", e)
        try:
            import bcrypt
            if hashed_password.startswith("$2") or hashed_password.startswith("$2b$") or hashed_password.startswith("$2a$"):
                return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
        except Exception:
            pass
        return False




# ==========================================================
# Create Access Token
# ==========================================================

from typing import Optional

def create_access_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
) -> str:


    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = (
            datetime.now(timezone.utc)
            +
            timedelta(
                minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
            )
        )


    payload = {

        "sub": subject,

        "type": "access",

        "exp": expire,

    }


    return jwt.encode(

        payload,

        settings.SECRET_KEY,

        algorithm=settings.ALGORITHM,

    )




# ==========================================================
# Create Refresh Token
# ==========================================================

def create_refresh_token(
    subject: str,
) -> tuple[str, str]:


    jti = str(
        uuid.uuid4()
    )


    expire = (

        datetime.now(timezone.utc)

        +

        timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

    )


    payload = {

        "sub": subject,

        "jti": jti,

        "type": "refresh",

        "exp": expire,

    }


    token = jwt.encode(

        payload,

        settings.SECRET_KEY,

        algorithm=settings.ALGORITHM,

    )


    return token, jti




# ==========================================================
# Decode JWT Token
# ==========================================================

def decode_token(
    token: str,
) -> dict[str, Any] | None:


    try:

        payload = jwt.decode(

            token,

            settings.SECRET_KEY,

            algorithms=[
                settings.ALGORITHM
            ],

        )


        return payload



    except JWTError:

        return None




# ==========================================================
# Validate Token Type
# ==========================================================

def verify_token_type(
    payload: dict[str, Any],
    token_type: str,
) -> bool:


    return payload.get(
        "type"
    ) == token_type