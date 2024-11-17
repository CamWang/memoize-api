from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from app import models, schemas, auth
from app.database import engine, get_db
from datetime import timedelta, datetime, timezone
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import re
from jose import JWTError, ExpiredSignatureError

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/register", response_model=schemas.User)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    # Check if email already exists
    db_user_email = db.query(models.User).filter(
        models.User.email == user.email
    ).first()
    if db_user_email:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )
    
    # Check if username already exists
    db_user_username = db.query(models.User).filter(
        models.User.username == user.username
    ).first()
    if db_user_username:
        raise HTTPException(
            status_code=400,
            detail="Username already taken"
        )
    
    if len(user.password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters long"
        )
    
    if not any(c.islower() for c in user.password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one lowercase letter"
        )
    if not any(c.isdigit() for c in user.password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one number"
        )
    
    # Create new user
    hashed_password = auth.get_password_hash(user.password)
    db_user = models.User(
        email=user.email,
        username=user.username,
        hashed_password=hashed_password,
        created_at=datetime.now(timezone.utc)
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.post("/token", response_model=schemas.TokenResponse)
async def login(
    login_data: LoginRequest,  # Changed from OAuth2PasswordRequestForm
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(
        models.User.username == login_data.username  # Changed from form_data to login_data
    ).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not auth.verify_password(login_data.password, user.hashed_password):  # Changed from form_data to login_data
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    
    # Return token and user information
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "created_at": user.created_at
        }
    }

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = auth.verify_token(token)
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        raise credentials_exception
    
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise credentials_exception
    return user

# Category endpoints
@app.post("/categories/", response_model=schemas.Category)
def create_category(
    category: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    db_category = models.Category(
        **category.model_dump(),
        created_by=current_user.username
    )
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category

@app.get("/categories/", response_model=List[schemas.Category])
def list_categories(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    categories = db.query(models.Category).offset(skip).limit(limit).all()
    return categories

# Card endpoints
@app.post("/cards/", response_model=schemas.Card)
def create_card(
    card: schemas.CardCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Verify category exists
    category = db.query(models.Category).filter(models.Category.id == card.category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    db_card = models.Card(
        **card.dict(),
        username=current_user.username,
        next_study=datetime.now(timezone.utc)
    )
    db.add(db_card)
    db.commit()
    db.refresh(db_card)
    return db_card

@app.get("/cards/")
async def list_cards(
    study: bool = False,
    category_id: Optional[int] = None,
    tag: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Start with base query
    base_query = db.query(models.Card).filter(models.Card.username == current_user.username)
    
    if category_id:
        base_query = base_query.filter(models.Card.category_id == category_id)
    
    if tag:
        base_query = base_query.filter(models.Card.tags.contains([tag]))
    
    if study:
        # For study mode, order by next_study date, putting NULL dates last
        base_query = base_query.order_by(
            # This will put NULL values last
            models.Card.next_study.is_(None).asc(),
            models.Card.next_study.asc()
        )
    
    # Apply pagination
    results = base_query.offset(skip).limit(limit).all()
    
    # Manually load categories to avoid the joinedload issue
    category_ids = {card.category_id for card in results}
    categories = {
        cat.id: cat 
        for cat in db.query(models.Category)
        .filter(models.Category.id.in_(category_ids))
        .all()
    }
    
    # Manually set the category relationship
    for card in results:
        card.category = categories.get(card.category_id)
    
    return results

@app.put("/cards/{card_id}", response_model=schemas.Card)
def update_card(
    card_id: int,
    card_update: schemas.CardUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    db_card = db.query(models.Card).filter(
        models.Card.id == card_id,
        models.Card.username == current_user.username
    ).first()
    
    if not db_card:
        raise HTTPException(status_code=404, detail="Card not found")
    
    update_data = card_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_card, field, value)
    
    db.commit()
    db.refresh(db_card)
    return db_card

@app.delete("/cards/{card_id}")
def delete_card(
    card_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    db_card = db.query(models.Card).filter(
        models.Card.id == card_id,
        models.Card.username == current_user.username
    ).first()
    
    if not db_card:
        raise HTTPException(status_code=404, detail="Card not found")
    
    db.delete(db_card)
    db.commit()
    return {"message": "Card deleted successfully"}

@app.post("/cards/{card_id}/study")
def record_study(
    card_id: int,
    study_data: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if "success" not in study_data:
        raise HTTPException(status_code=400, detail="success field is required")
    
    success = study_data["success"]
    
    db_card = db.query(models.Card).filter(
        models.Card.id == card_id,
        models.Card.username == current_user.username
    ).first()
    
    if not db_card:
        raise HTTPException(status_code=404, detail="Card not found")
    
    # Increment study count before calculating next study date
    db_card.study_count += 1
    
    now = datetime.now(timezone.utc)
    
    # Calculate next study date
    if not success or db_card.study_count == 1:
        # For first study or unsuccessful attempts, schedule for beginning of next day
        next_day = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        db_card.next_study = next_day
    else:
        # For successful subsequent studies
        from random import randint
        days_multiplier = randint(3, 5)
        next_interval = min((db_card.study_count - 1) * days_multiplier, 30)  # Cap at 30 days
        db_card.next_study = now + timedelta(days=next_interval)
    
    db.commit()
    return {"message": "Study recorded successfully"} 