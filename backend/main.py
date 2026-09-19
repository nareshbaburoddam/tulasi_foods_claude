import os
import json
import secrets
import uuid
from typing import List, Optional, Any, Union
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, status, Request, Header, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from database import Base, User, CustomerRequest, UserRole, DocumentUpload
from auth import hash_password, verify_password, create_access_token, decode_access_token

# ------------------------------------------------------------------------------
# Database Connection Setup
# ------------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required.")

UPLOAD_DIR = os.getenv("APP_UPLOAD_DIR", os.path.join(os.getcwd(), "uploads"))
ALLOWED_UPLOAD_EXTENSIONS = {".xlsx", ".xls", ".doc", ".docx", ".pdf", ".txt"}
ALLOWED_UPLOAD_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/pdf",
    "text/plain",
    "application/octet-stream",
}

os.makedirs(UPLOAD_DIR, exist_ok=True)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

# ------------------------------------------------------------------------------
# FastAPI Application
# ------------------------------------------------------------------------------
app = FastAPI(title="Tulasi Foods API")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

##ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "https://bluegreen.nareshroddam.in")
ALLOWED_ORIGIN = os.getenv(
    "ALLOWED_ORIGIN",
    "https://bluegreen.nareshroddam.in"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ------------------------------------------------------------------------------
# One-time admin seeding (does NOT reset an existing password on restart)
# ------------------------------------------------------------------------------
def seed_default_admin():
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return  # at least one user already exists — never touch it again

        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD")

        generated = False
        if not admin_password:
            admin_password = secrets.token_urlsafe(12)
            generated = True

        default_admin = User(
            username=admin_username,
            hashed_password=hash_password(admin_password),
            role=UserRole.ADMIN,
        )
        db.add(default_admin)
        db.commit()

        if generated:
            print("=" * 70)
            print(f"INFO: Created default admin user '{admin_username}'.")
            print(f"INFO: No ADMIN_PASSWORD was set, so a random password was generated:")
            print(f"INFO:   {admin_password}")
            print("INFO: Save this now — it will not be shown again. Log in and change it,")
            print("INFO: or set ADMIN_PASSWORD in your .env file before the first startup.")
            print("=" * 70)
        else:
            print(f"INFO: Created default admin user '{admin_username}' from ADMIN_PASSWORD env var.")
    except Exception as e:
        db.rollback()
        print(f"ERROR: Failed to seed admin user: {e}")
    finally:
        db.close()

@app.on_event("startup")
def on_startup():
    seed_default_admin()

# ------------------------------------------------------------------------------
# Auth dependencies — these actually verify the token now
# ------------------------------------------------------------------------------
def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user

def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# ------------------------------------------------------------------------------
# Login
# ------------------------------------------------------------------------------
@app.post("/api/login")
async def login(request: Request, db: Session = Depends(get_db)):
    username = None
    password = None

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        username = body.get("username")
        password = body.get("password")
    else:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")

    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(data={"sub": str(user.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "username": user.username,
        "id": user.id,
    }

@app.get("/api/me")
def get_me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "role": user.role, "is_active": True}

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------
def clean_materials_string(raw_val: Any) -> str:
    if not raw_val:
        return ""
    parsed = raw_val
    if isinstance(raw_val, str):
        try:
            parsed = json.loads(raw_val)
        except Exception:
            return raw_val

    if isinstance(parsed, list):
        items_str = []
        for item in parsed:
            if isinstance(item, dict):
                name = item.get("material_name") or item.get("name") or item.get("material") or ""
                qty = item.get("quantity") or item.get("qty") or 1
                items_str.append(f"{name} (Qty: {qty})" if name else str(item))
            else:
                items_str.append(str(item))
        return ", ".join(items_str)

    if isinstance(parsed, dict):
        return ", ".join([f"{k}: {v}" for k, v in parsed.items()])

    return str(parsed)

def get_status_color(status_val: str) -> str:
    s = (status_val or "").strip().lower()
    if "interested" in s and "not" not in s:
        return "green"
    elif "not interested" in s or "rejected" in s or "cancelled" in s:
        return "red"
    elif "pending" in s:
        return "amber"
    return "blue"

def get_uploaded_files_for_request(db: Session, request_id: int) -> List[dict]:
    results = db.query(DocumentUpload).filter(DocumentUpload.request_id == request_id).order_by(DocumentUpload.uploaded_at.desc()).all()
    return [
        {
            "id": item.id,
            "file_name": item.file_name,
            "stored_name": item.stored_name,
            "content_type": item.content_type,
            "size_bytes": item.size_bytes,
            "uploaded_at": item.uploaded_at.strftime("%Y-%m-%d %H:%M:%S") if item.uploaded_at else "",
            "storage_path": item.storage_path,
            "download_url": f"/uploads/{item.stored_name}",
        }
        for item in results
    ]


def format_customer_request(req: CustomerRequest):
    date_str = req.date_time.strftime("%Y-%m-%d %H:%M:%S") if req.date_time else ""
    cleaned_materials = clean_materials_string(req.requested_materials)
    current_status = req.status or "Pending"
    return {
        "id": req.id,
        "date_time": date_str,
        "customer_name": req.customer_name or "Guest",
        "mobile_number": req.mobile_number or "",
        "location": req.location or "",
        "requested_materials": cleaned_materials,
        "fulfillment_type": req.fulfillment_type or "",
        "scheduled_date": req.scheduled_date or "",
        "status": current_status,
        "status_color": get_status_color(current_status),
        "remarks": req.remarks or "",
    }

# ------------------------------------------------------------------------------
# Public: customer submits a supply/franchise request — no login needed
# ------------------------------------------------------------------------------
class CustomerRequestCreate(BaseModel):
    name: Optional[str] = None
    customer_name: Optional[str] = Field(default=None, alias="customerName")
    mobile_number: Optional[str] = Field(default=None, alias="mobileNumber")
    phone: Optional[str] = None
    place: Optional[str] = None
    location: Optional[str] = None
    items: Optional[Union[List[Any], dict, str]] = None
    requested_materials: Optional[Union[List[Any], dict, str]] = Field(default=None, alias="requestedMaterials")
    fulfillment_type: Optional[str] = Field(default=None, alias="fulfillmentType")
    scheduled_date: Optional[str] = Field(default=None, alias="scheduledDate")

    class Config:
        populate_by_name = True
        extra = "allow"

def validate_upload_file(file: UploadFile) -> None:
    if not file or not file.filename:
        raise HTTPException(status_code=422, detail="Upload file is missing a filename")

    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Unsupported file type: {file.filename}")

    if file.content_type and file.content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported content type for file: {file.filename}")


def save_uploaded_file(file: UploadFile, request_id: int) -> dict:
    validate_upload_file(file)

    safe_name = os.path.basename(file.filename)
    unique_name = f"{request_id}_{uuid.uuid4().hex}_{safe_name}"
    storage_path = os.path.join(UPLOAD_DIR, unique_name)

    contents = file.file.read()
    with open(storage_path, "wb") as f:
        f.write(contents)

    upload = DocumentUpload(
        request_id=request_id,
        file_name=safe_name,
        stored_name=unique_name,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(contents),
        storage_path=storage_path,
    )
    return upload


@app.post("/api/orders", status_code=status.HTTP_201_CREATED)
async def create_customer_request(request: Request, db: Session = Depends(get_db)):
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        payload_name = form.get("name") or form.get("customerName") or "Guest"
        payload_mobile = form.get("mobile_number") or form.get("mobileNumber") or ""
        payload_location = form.get("place") or form.get("location") or ""
        payload_items = form.get("items") or form.get("requestedMaterials") or "[]"
        payload_fulfillment = form.get("fulfillment_type") or form.get("fulfillmentType") or ""
        payload_schedule = form.get("scheduled_date") or form.get("scheduledDate") or ""
        uploaded_files = form.getlist("files")

        try:
            items_value = json.loads(payload_items) if isinstance(payload_items, str) and payload_items.strip() else []
        except json.JSONDecodeError:
            items_value = []

        c_name = payload_name.strip() or "Guest"
        m_num = payload_mobile.strip() or ""
        loc = payload_location.strip() or ""
        fulfillment = payload_fulfillment.strip() or ""
        sched_date = payload_schedule.strip() or ""
        mats = items_value

        if not m_num:
            raise HTTPException(status_code=422, detail="Mobile number is required")

        if fulfillment not in ("Pickup", "Delivery"):
            raise HTTPException(status_code=422, detail="fulfillment_type must be 'Pickup' or 'Delivery'")

        if not sched_date:
            raise HTTPException(status_code=422, detail="scheduled_date is required")

        mat_str = json.dumps(mats, ensure_ascii=False) if isinstance(mats, (list, dict)) else str(mats)

        db_req = CustomerRequest(
            customer_name=c_name,
            mobile_number=m_num,
            location=loc,
            requested_materials=mat_str,
            fulfillment_type=fulfillment,
            scheduled_date=sched_date,
            status="Pending",
        )
        db.add(db_req)
        db.commit()
        db.refresh(db_req)

        for file in uploaded_files:
            if not file or not getattr(file, "filename", None):
                continue
            uploaded = save_uploaded_file(file, db_req.id)
            db.add(uploaded)

        db.commit()
        response_data = format_customer_request(db_req)
        response_data["uploaded_files"] = get_uploaded_files_for_request(db, db_req.id)
        return response_data

    payload = CustomerRequestCreate.model_validate_json(await request.body())
    c_name = payload.name or payload.customer_name or "Guest"
    m_num = payload.mobile_number or payload.phone or ""
    loc = payload.place or payload.location or ""
    mats = payload.items or payload.requested_materials or ""
    fulfillment = payload.fulfillment_type or ""
    sched_date = payload.scheduled_date or ""

    if not m_num or not m_num.strip():
        raise HTTPException(status_code=422, detail="Mobile number is required")

    if fulfillment not in ("Pickup", "Delivery"):
        raise HTTPException(status_code=422, detail="fulfillment_type must be 'Pickup' or 'Delivery'")

    if not sched_date or not sched_date.strip():
        raise HTTPException(status_code=422, detail="scheduled_date is required")

    mat_str = json.dumps(mats, ensure_ascii=False) if isinstance(mats, (list, dict)) else str(mats)

    db_req = CustomerRequest(
        customer_name=c_name,
        mobile_number=m_num,
        location=loc,
        requested_materials=mat_str,
        fulfillment_type=fulfillment,
        scheduled_date=sched_date,
        status="Pending",
    )
    db.add(db_req)
    db.commit()
    db.refresh(db_req)
    response_data = format_customer_request(db_req)
    response_data["uploaded_files"] = []
    return response_data

# ------------------------------------------------------------------------------
# Admin: view / manage requests — requires a valid logged-in user
# ------------------------------------------------------------------------------
@app.get("/api/requests")
def get_requests(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    requests = db.query(CustomerRequest).order_by(CustomerRequest.id.desc()).all()
    result = []
    for req in requests:
        item = format_customer_request(req)
        item["uploaded_files"] = get_uploaded_files_for_request(db, req.id)
        result.append(item)
    return result

class CustomerRequestUpdate(BaseModel):
    status: Optional[str] = None
    remarks: Optional[str] = None

@app.patch("/api/requests/{req_id}")
def update_request(
    req_id: int,
    update_data: CustomerRequestUpdate,
    user: User = Depends(require_admin),  # only admin role can edit
    db: Session = Depends(get_db),
):
    db_req = db.query(CustomerRequest).filter(CustomerRequest.id == req_id).first()
    if not db_req:
        raise HTTPException(status_code=404, detail="Request not found")

    if update_data.status is not None:
        db_req.status = update_data.status
    if update_data.remarks is not None:
        db_req.remarks = update_data.remarks

    db.commit()
    db.refresh(db_req)
    return format_customer_request(db_req)

@app.delete("/api/requests/{req_id}")
def delete_request(
    req_id: int,
    user: User = Depends(require_admin),  # only admin role can delete
    db: Session = Depends(get_db),
):
    db_req = db.query(CustomerRequest).filter(CustomerRequest.id == req_id).first()
    if not db_req:
        raise HTTPException(status_code=404, detail="Request not found")
    db.delete(db_req)
    db.commit()
    return {"message": "Deleted successfully", "id": req_id}

# ------------------------------------------------------------------------------
# Admin: user management — admin role only
# ------------------------------------------------------------------------------
class UserCreate(BaseModel):
    username: str
    password: str
    role: Optional[str] = "readonly"

@app.get("/api/users")
def get_users(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [{"id": u.id, "username": u.username, "role": u.role} for u in users]

@app.post("/api/users", status_code=status.HTTP_201_CREATED)
def create_user(u: UserCreate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == u.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    if len(u.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    new_user = User(username=u.username, hashed_password=hash_password(u.password), role=u.role)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"id": new_user.id, "username": new_user.username, "role": new_user.role}

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.username == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete the default admin user")
    db.delete(target)
    db.commit()
    return {"message": "User deleted successfully", "id": user_id}

# ------------------------------------------------------------------------------
# Health checks
# ------------------------------------------------------------------------------
@app.get("/")
def read_root():
    return {"message": "Tulasi Foods Backend Service Running"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}
