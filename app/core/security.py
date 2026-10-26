from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings


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

    return pwd_context.hash(
        password
    )



def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:

    return pwd_context.verify(
        plain_password,
        hashed_password,
    )




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