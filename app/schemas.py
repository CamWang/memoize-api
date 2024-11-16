from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    username: str

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: int
    
    model_config = {
        "from_attributes": True
    }

class Token(BaseModel):
    access_token: str
    token_type: str 

class CategoryBase(BaseModel):
    name: str
    description: str
    priority: int = 0

class CategoryCreate(CategoryBase):
    pass

class Category(CategoryBase):
    id: int
    created_at: datetime
    created_by: str

    model_config = {
        "from_attributes": True
    }

class CardBase(BaseModel):
    front: str
    back: str
    tags: List[str] = []
    category_id: int

class CardCreate(CardBase):
    pass

class CardUpdate(BaseModel):
    front: Optional[str] = None
    back: Optional[str] = None
    tags: Optional[List[str]] = None
    category_id: Optional[int] = None
    next_study: Optional[datetime] = None

class Card(CardBase):
    id: int
    created_at: datetime
    username: str
    study_count: int
    next_study: Optional[datetime]
    category: Category

    model_config = {
        "from_attributes": True
    }