import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    READONLY = "readonly"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)  # real bcrypt hash, no plaintext default
    role = Column(String, default=UserRole.ADMIN, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class CustomerRequest(Base):
    """Single source of truth for customer supply orders / franchise enquiries.
    (Previously this data was duplicated into a separate 'orders' table on every
    write, which risked the two tables drifting out of sync. Consolidated here.)"""
    __tablename__ = "customer_requests"

    id = Column(Integer, primary_key=True, index=True)
    date_time = Column(DateTime, default=datetime.utcnow)
    customer_name = Column(String, nullable=False)
    mobile_number = Column(String, nullable=False)
    location = Column(String, nullable=False)
    requested_materials = Column(Text, nullable=False)
    fulfillment_type = Column(String, nullable=True)   # "Pickup" or "Delivery"
    scheduled_date = Column(String, nullable=True)      # date customer picks (pickup) or wants delivery
    status = Column(String, default="Pending")
    remarks = Column(Text, nullable=True)
