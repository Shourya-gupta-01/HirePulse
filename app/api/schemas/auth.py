from pydantic import BaseModel, EmailStr, Field

class UserAuthRequest(BaseModel):
    email : EmailStr
    password : str = Field(min_length = 8)

class TokenResponse(BaseModel):
    access_token : str
    token_type : str = "bearer"
    user_id: str
    email: str