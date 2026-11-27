import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from typing import Annotated, Dict
from pydantic import EmailStr
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.config import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_ALGORITHM, JWT_SECRET_KEY

# Tells FastAPI where clients get a token (used by Swagger UI & header extraction)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/api/auth/login')

def hash_password(plain_password: str) -> str:
    # converting password to array of bytes
    password_bytes = plain_password.encode('utf-8')

    # generating the salt
    salt = bcrypt.gensalt()

    # Hashing the password
    hash = bcrypt.hashpw(password_bytes, salt)
    return hash.decode('utf-8')

def verify_password(plain_password: str, hash: str) -> bool:
    # encoding user password
    password_bytes = plain_password.encode('utf-8')
    hashed_password = hash.encode('utf-8')

    # checking password
    result = bcrypt.checkpw(password_bytes, hashed_password)

    return result

def create_access_token(user_id: str, email: EmailStr) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes = ACCESS_TOKEN_EXPIRE_MINUTES)
    payload  = {'sub': user_id, 'email': email, 'exp': expire}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def verify_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None

def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> Dict[str, str]:
    credentials_error = HTTPException(
        status_code = status.HTTP_401_UNAUTHORIZED,
        detail = "Invalid or expired token",
        headers = {"WWW-Authenticate": "Bearer"}
    )

    payload = verify_token(token)

    if payload is None:
        raise credentials_error
        
    user_id: str | None = payload.get('sub')
    email: EmailStr | None = payload.get('email')
        
    if not user_id or not email:
        raise credentials_error
    return {'id': user_id, "email": email}