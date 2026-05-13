"""
Development seed routes — only available in development mode.
These endpoints make it easy to populate demo data.
Add to main.py imports and app in development:

  from backend.dev_routes import router as dev_router
  app.include_router(dev_router)
"""

import os
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.database.connection import get_db
from backend.services.data_service import DataService

router = APIRouter(prefix="/api/dev", tags=["Development"])

@router.post("/seed/{portfolio_id}")
def seed_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    """Seed portfolio with realistic demo data."""
    if os.getenv("APP_ENV", "development") == "production":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Not available in production")

    DataService().seed_demo_data(db, portfolio_id)
    return {"message": f"Portfolio {portfolio_id} seeded with demo data."}
