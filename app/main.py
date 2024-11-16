from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app import models, schemas, auth
from app.database import engine, get_db
from datetime import timedelta, datetime, timezone
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import re

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

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
    
    # Additional password validation
    if not any(c.isupper() for c in user.password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one uppercase letter"
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
        hashed_password=hashed_password
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.post("/token", response_model=schemas.Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(
        models.User.username == form_data.username
    ).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not auth.verify_password(form_data.password, user.hashed_password):
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

# Category endpoints
@app.post("/categories/", response_model=schemas.Category)
def create_category(
    category: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    current_user: str = Depends(oauth2_scheme)
):
    db_category = models.Category(
        **category.model_dump(),
        created_by=current_user
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
    current_user: str = Depends(oauth2_scheme)
):
    categories = db.query(models.Category).offset(skip).limit(limit).all()
    return categories

# Card endpoints
@app.post("/cards/", response_model=schemas.Card)
def create_card(
    card: schemas.CardCreate,
    db: Session = Depends(get_db),
    current_user: str = Depends(oauth2_scheme)
):
    # Verify category exists
    category = db.query(models.Category).filter(models.Category.id == card.category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    db_card = models.Card(
        **card.dict(),
        username=current_user,
        next_study=datetime.now(timezone.utc) + timedelta(days=1)  # Default to tomorrow
    )
    db.add(db_card)
    db.commit()
    db.refresh(db_card)
    return db_card

@app.get("/cards/", response_model=List[schemas.Card])
def list_cards(
    skip: int = 0,
    limit: int = 100,
    category_id: Optional[int] = None,
    tag: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: str = Depends(oauth2_scheme)
):
    query = db.query(models.Card).filter(models.Card.username == current_user)
    
    if category_id:
        query = query.filter(models.Card.category_id == category_id)
    
    if tag:
        query = query.filter(models.Card.tags.contains([tag]))
    
    cards = query.offset(skip).limit(limit).all()
    return cards

@app.put("/cards/{card_id}", response_model=schemas.Card)
def update_card(
    card_id: int,
    card_update: schemas.CardUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(oauth2_scheme)
):
    db_card = db.query(models.Card).filter(
        models.Card.id == card_id,
        models.Card.username == current_user
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
    current_user: str = Depends(oauth2_scheme)
):
    db_card = db.query(models.Card).filter(
        models.Card.id == card_id,
        models.Card.username == current_user
    ).first()
    
    if not db_card:
        raise HTTPException(status_code=404, detail="Card not found")
    
    db.delete(db_card)
    db.commit()
    return {"message": "Card deleted successfully"}

@app.post("/cards/{card_id}/study")
def record_study(
    card_id: int,
    success: bool = Query(..., description="Whether the study was successful"),
    db: Session = Depends(get_db),
    current_user: str = Depends(oauth2_scheme)
):
    db_card = db.query(models.Card).filter(
        models.Card.id == card_id,
        models.Card.username == current_user
    ).first()
    
    if not db_card:
        raise HTTPException(status_code=404, detail="Card not found")
    
    # Increment study count
    db_card.study_count += 1
    
    now = datetime.now(timezone.utc)
    
    # Update next study time based on success
    if success:
        # Simple spaced repetition: double the interval each time
        if db_card.next_study:
            # Ensure next_study is timezone-aware before subtraction
            next_study = db_card.next_study.replace(tzinfo=timezone.utc) if db_card.next_study.tzinfo is None else db_card.next_study
            current_interval = (next_study - now).days
        else:
            current_interval = 1
        next_interval = max(1, current_interval * 2)
        db_card.next_study = now + timedelta(days=next_interval)
    else:
        # If failed, review tomorrow
        db_card.next_study = now + timedelta(days=1)
    
    db.commit()
    return {"message": "Study recorded successfully"} 