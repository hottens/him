"""
Pytest configuration and fixtures for testing.

Provides a fresh in-memory SQLite database and test client for each test.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


# Create an in-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # Required for in-memory SQLite with multiple threads
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Override the get_db dependency for testing."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        # Drop all tables after the test
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client with the overridden database dependency."""
    # Override the get_db dependency
    app.dependency_overrides[get_db] = override_get_db
    
    # Create all tables for this test
    Base.metadata.create_all(bind=engine)
    
    with TestClient(app) as test_client:
        yield test_client
    
    # Clean up
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def sample_item(client):
    """Create a sample item for testing."""
    response = client.post(
        "/api/items",
        json={"name": "Milk", "location": "inventory", "barcode": "123456789"}
    )
    return response.json()


@pytest.fixture
def sample_items(client):
    """Create multiple sample items for testing."""
    items = []
    
    # Inventory items
    for name, barcode in [("Milk", "111111"), ("Eggs", "222222"), ("Butter", "333333")]:
        response = client.post(
            "/api/items",
            json={"name": name, "location": "inventory", "barcode": barcode}
        )
        items.append(response.json())
    
    # Grocery list items
    for name, barcode in [("Bread", "444444"), ("Cheese", "555555")]:
        response = client.post(
            "/api/items",
            json={"name": name, "location": "grocery_list", "barcode": barcode}
        )
        items.append(response.json())
    
    # Neither location
    response = client.post(
        "/api/items",
        json={"name": "Yogurt", "location": "neither"}
    )
    items.append(response.json())
    
    return items

