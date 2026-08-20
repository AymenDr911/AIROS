import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

@st.cache_resource
def get_db_engine():
    """
    Creates and caches the SQLAlchemy database engine using Streamlit secrets.
    """
    try:
        db_url = st.secrets["connections"]["sql"]["url"]
        engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10
        )
        return engine
    except Exception as e:
        st.error(f"Failed to load database configuration: {e}")
        return None

def get_db_session():
    """
    Provides a transactional database session context.
    """
    engine = get_db_engine()
    if engine is None:
        raise ConnectionError("Database engine is not initialized.")
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()

def test_db_connection():
    """
    Utility function to test database reachability.
    """
    try:
        engine = get_db_engine()
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1;"))
            return result.scalar() == 1
    except Exception as e:
        st.error(f"Database connection error: {e}")
        return False