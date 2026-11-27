from fastapi import APIRouter, Depends, HTTPException, status

from app.api.schemas.auth import UserAuthRequest, TokenResponse
from app.auth.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

from app.memory.stm import pool
router = APIRouter()

@router.post("/signup", response_model = TokenResponse)
def signup(req: UserAuthRequest):
    email = req.email.lower().strip()
    pw_hash = hash_password(req.password)

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE email=%s", (email,))
            if cur.fetchone():
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail = "Email already exists")

            cur.execute(
                "INSERT INTO users (email, hashed_password) VALUES(%s, %s) RETURNING id", (email, pw_hash)
            )
            user_id = str(cur.fetchone()['id'])

    token = create_access_token(user_id=user_id, email=email)
    return TokenResponse(
        access_token = token,
        user_id = user_id,
        email = email
    )

@router.post("/login", response_model = TokenResponse)
def login(req: UserAuthRequest):
    email = req.email.lower().strip()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, hashed_password FROM users
                WHERE email=%s""", (email,)
            )
            row = cur.fetchone()
    if not row or not verify_password(req.password, row['hashed_password']):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail = "Invalid Credentials!")
    return TokenResponse(
        access_token = create_access_token(user_id = str(row['id']),
        email = email
        ),
        user_id = str(row['id']),
        email = email
    )

@router.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    return current_user