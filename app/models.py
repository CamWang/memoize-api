from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String) 

class Category(Base):
    __tablename__ = "categories"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    description = Column(Text)
    priority = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    created_by = Column(String, ForeignKey("users.username"))

    # Relationship
    cards = relationship("Card", back_populates="category")

class Card(Base):
    __tablename__ = "cards"
    
    id = Column(Integer, primary_key=True, index=True)
    front = Column(Text)  # HTML string
    back = Column(Text)   # HTML string
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    username = Column(String, ForeignKey("users.username"))
    study_count = Column(Integer, default=0)
    next_study = Column(DateTime)
    tags = Column(JSON, default=list)  # Store as JSON array
    category_id = Column(Integer, ForeignKey("categories.id"))
    
    # Relationship
    category = relationship("Category", back_populates="cards") 