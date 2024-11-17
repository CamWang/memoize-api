import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta, timezone
import json

from app.main import app
from app.database import Base, get_db
from app.models import User, Category, Card

# Create test database
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_database():
    # Create tables
    Base.metadata.create_all(bind=engine)
    yield
    # Drop tables after tests
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def test_user():
    user_data = {
        "email": "test@example.com",
        "username": "testuser",
        "password": "TestPassword123",
    }
    return user_data

@pytest.fixture
def test_token(test_user):
    # Register user
    client.post("/register", json=test_user)
    
    # Login and get token using JSON
    login_data = {
        "username": test_user["username"],
        "password": test_user["password"]
    }
    response = client.post("/token", json=login_data)  # Changed from data to json
    return response.json()["access_token"]

@pytest.fixture
def auth_headers(test_token):
    return {"Authorization": f"Bearer {test_token}"}

def test_register_user(test_user):
    response = client.post("/register", json=test_user)
    print(response.json())
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_user["email"]
    assert data["username"] == test_user["username"]

def test_login(test_user):
    # First register
    client.post("/register", json=test_user)
    
    # Then login with JSON instead of form data
    login_data = {
        "username": test_user["username"],
        "password": test_user["password"]
    }
    response = client.post("/token", json=login_data)  # Changed from data to json
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "user" in data
    assert data["user"]["username"] == test_user["username"]
    assert data["user"]["email"] == test_user["email"]

def test_create_category(auth_headers):
    category_data = {
        "name": "Test Category",
        "description": "Test Description",
        "priority": 1
    }
    response = client.post("/categories/", json=category_data, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == category_data["name"]
    assert data["description"] == category_data["description"]
    return data

def test_list_categories(auth_headers):
    # Create multiple categories
    categories = [
        {"name": f"Category {i}", "description": f"Description {i}", "priority": i}
        for i in range(3)
    ]
    for category in categories:
        client.post("/categories/", json=category, headers=auth_headers)
    
    response = client.get("/categories/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3

def test_create_card(auth_headers):
    # First create a category
    category = test_create_category(auth_headers)
    
    card_data = {
        "front": "<p>Test Front</p>",
        "back": "<p>Test Back</p>",
        "tags": ["test", "example"],
        "category_id": category["id"]
    }
    
    response = client.post("/cards/", json=card_data, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["front"] == card_data["front"]
    assert data["back"] == card_data["back"]
    assert data["tags"] == card_data["tags"]
    return data

def test_list_cards(auth_headers):
    # Create a category and multiple cards
    category = test_create_category(auth_headers)
    
    # Create cards with different next_study dates
    cards = [
        {
            "front": f"Front {i}",
            "back": f"Back {i}",
            "category_id": category["id"],
            "tags": [f"tag{i}"]
        }
        for i in range(3)
    ]
    
    created_cards = []
    for card in cards:
        response = client.post("/cards/", json=card, headers=auth_headers)
        assert response.status_code == 200
        created_cards.append(response.json())
    
    # Test default listing (no study parameter)
    response = client.get("/cards/", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()) == 3
    
    # Test pagination
    response = client.get("/cards/?limit=2", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()) == 2
    
    response = client.get("/cards/?skip=2&limit=2", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()) == 1

def test_list_cards_study_order(auth_headers):
    # Create a category
    category = test_create_category(auth_headers)
    
    # Create cards with different study dates
    cards = [
        {
            "front": f"Front {i}",
            "back": f"Back {i}",
            "category_id": category["id"],
            "tags": [f"tag{i}"]
        }
        for i in range(4)
    ]
    
    created_cards = []
    for card in cards:
        response = client.post("/cards/", json=card, headers=auth_headers)
        assert response.status_code == 200
        created_cards.append(response.json())
        
    print(json.dumps(created_cards, indent=2))
    print("--------------------------------")
        
    # Card 0: First time study success (should be tomorrow)
    client.post(
        f"/cards/{created_cards[0]['id']}/study",
        json={"success": True},
        headers=auth_headers
    )
    
    # Card 1: First time study fail (should be tomorrow)
    client.post(
        f"/cards/{created_cards[1]['id']}/study",
        json={"success": False},
        headers=auth_headers
    )
    
    # Card 2: Study twice with success (should be 3-5 days later)
    client.post(
        f"/cards/{created_cards[2]['id']}/study",
        json={"success": True},
        headers=auth_headers
    )
    # Second study for card 2
    client.post(
        f"/cards/{created_cards[2]['id']}/study",
        json={"success": True},
        headers=auth_headers
    )
    
    # Card 3: Leave unstudied (no next_study date)
    
    # Test study ordering
    response = client.get("/cards/?study=true", headers=auth_headers)
    assert response.status_code == 200
    cards = response.json()
    assert len(cards) == 4
    
    print(json.dumps(cards, indent=2))
    
    now = datetime.now(timezone.utc)
    
    # First two cards (first-time studied) should be scheduled for tomorrow at 00:00
    next_day = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
    )
    
    # Check first card, didn't study yet\
    assert created_cards[3]['id'] == cards[0]['id']
    
    # Check first card (success on first try)
    first_card_next_study = datetime.fromisoformat(cards[1]["next_study"].replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
    assert first_card_next_study == next_day
    
    # Check second card (fail on first try)
    second_card_next_study = datetime.fromisoformat(cards[2]["next_study"].replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
    assert second_card_next_study == next_day
    
    # Check third card (success on second try)
    third_card_next_study = datetime.fromisoformat(cards[3]["next_study"].replace('Z', '+00:00')).replace(tzinfo=timezone.utc) + timedelta(minutes=5) # compensate for test execution time
    days_diff = (third_card_next_study - now).days
    assert 3 <= days_diff <= 5  # Should be scheduled 3-5 days away since study_count=2


def test_update_card(auth_headers):
    # Create a card first
    card = test_create_card(auth_headers)
    
    update_data = {
        "front": "<p>Updated Front</p>",
        "tags": ["updated", "test"]
    }
    
    response = client.put(
        f"/cards/{card['id']}", 
        json=update_data,
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["front"] == update_data["front"]
    assert data["tags"] == update_data["tags"]
    # Check that unupdated fields remain the same
    assert data["back"] == card["back"]

def test_delete_card(auth_headers):
    # Create a card first
    card = test_create_card(auth_headers)
    
    # Delete the card
    response = client.delete(f"/cards/{card['id']}", headers=auth_headers)
    assert response.status_code == 200
    
    # Verify card is deleted
    response = client.get("/cards/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 0

def test_study_card(auth_headers):
    # Create a card first
    card = test_create_card(auth_headers)
    
    # Record successful study using JSON
    study_data = {"success": True}
    response = client.post(
        f"/cards/{card['id']}/study",
        json=study_data,  # Changed from params to json
        headers=auth_headers
    )
    assert response.status_code == 200
    
    # Verify study count increased
    response = client.get("/cards/", headers=auth_headers)
    updated_card = response.json()[0]
    assert updated_card["study_count"] == 1

def test_filter_cards_by_category(auth_headers):
    # Create two categories
    category1 = test_create_category(auth_headers)
    category2 = client.post("/categories/", 
        json={"name": "Category 2", "description": "Description 2", "priority": 2},
        headers=auth_headers
    ).json()
    
    # Create cards in different categories
    cards = [
        {
            "front": "<p>Card 1</p>",
            "back": "<p>Back 1</p>",
            "tags": ["test"],
            "category_id": category1["id"]
        },
        {
            "front": "<p>Card 2</p>",
            "back": "<p>Back 2</p>",
            "tags": ["test"],
            "category_id": category2["id"]
        }
    ]
    
    for card in cards:
        client.post("/cards/", json=card, headers=auth_headers)
    
    # Filter by category1
    response = client.get(f"/cards/?category_id={category1['id']}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["category"]["id"] == category1["id"]

def test_filter_cards_by_tag(auth_headers):
    # Create a category
    category = test_create_category(auth_headers)
    
    # Create cards with different tags
    cards = [
        {
            "front": "<p>Card 1</p>",
            "back": "<p>Back 1</p>",
            "tags": ["python"],
            "category_id": category["id"]
        },
        {
            "front": "<p>Card 2</p>",
            "back": "<p>Back 2</p>",
            "tags": ["javascript"],
            "category_id": category["id"]
        }
    ]
    
    for card in cards:
        client.post("/cards/", json=card, headers=auth_headers)
    
    # Filter by tag
    response = client.get("/cards/?tag=python", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert "python" in data[0]["tags"] 