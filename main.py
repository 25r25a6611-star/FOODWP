from datetime import datetime, timedelta
from pathlib import Path
import secrets
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB = BASE / "foodloop.db"
app = FastAPI(title="FoodLoop Campus API", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS listings (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          donor TEXT NOT NULL, food_type TEXT NOT NULL,
          portions INTEGER NOT NULL CHECK(portions > 0),
          allergens TEXT NOT NULL, prepared_at TEXT NOT NULL,
          deadline TEXT NOT NULL, storage TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'available', recipient TEXT,
          pickup_code TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS handovers (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          listing_id INTEGER NOT NULL REFERENCES listings(id),
          recipient TEXT NOT NULL, portions INTEGER NOT NULL,
          confirmed_at TEXT NOT NULL
        );
        """)
        if con.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0:
            now = datetime.now().astimezone()
            for donor, food, portions, allergen, hours, storage in [
                ("Campus Canteen", "Veg lunch boxes", 25, "Contains wheat", 2, "Keep chilled"),
                ("Tech Fest Team", "Sealed fruit packs", 40, "None declared", 4, "Room temperature"),
            ]:
                con.execute(
                    """INSERT INTO listings
                    (donor,food_type,portions,allergens,prepared_at,deadline,storage,notes,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (donor, food, portions, allergen, now.isoformat(timespec="minutes"),
                     (now + timedelta(hours=hours)).isoformat(timespec="minutes"),
                     storage, "Demo listing; verify handling before pickup.", now.isoformat())
                )


init_db()


class ListingIn(BaseModel):
    donor: str = Field(min_length=2, max_length=100)
    food_type: str = Field(min_length=2, max_length=120)
    portions: int = Field(gt=0, le=10000)
    allergens: str = Field(min_length=1, max_length=300)
    prepared_at: str
    deadline: str
    storage: str = Field(min_length=2, max_length=100)
    notes: str = Field(default="", max_length=500)
    handling_confirmed: bool


class ReserveIn(BaseModel):
    recipient: str = Field(min_length=2, max_length=100)
    capacity: int = Field(gt=0, le=10000)


class ConfirmIn(BaseModel):
    pickup_code: str = Field(min_length=4, max_length=12)


def public_row(row):
    data = dict(row)
    data.pop("pickup_code", None)
    return data


@app.get("/")
def home():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "FoodLoop Campus"}


@app.get("/api/listings")
def get_listings():
    now = datetime.now().astimezone()
    with connect() as con:
        rows = con.execute("SELECT * FROM listings ORDER BY id DESC").fetchall()
        for row in rows:
            if row["status"] == "available":
                try:
                    expired = datetime.fromisoformat(row["deadline"]) <= now
                except ValueError:
                    expired = True
                if expired:
                    con.execute("UPDATE listings SET status='expired' WHERE id=?", (row["id"],))
        rows = con.execute("SELECT * FROM listings ORDER BY id DESC").fetchall()
    return [public_row(row) for row in rows]


@app.post("/api/listings", status_code=201)
def create_listing(item: ListingIn):
    if not item.handling_confirmed:
        raise HTTPException(400, "Confirm the declared handling and storage details.")
    try:
        prepared = datetime.fromisoformat(item.prepared_at)
        deadline = datetime.fromisoformat(item.deadline)
    except ValueError:
        raise HTTPException(400, "Invalid preparation or deadline date.")
    if deadline <= datetime.now().astimezone() or deadline <= prepared:
        raise HTTPException(400, "Deadline must be in the future and after preparation.")
    with connect() as con:
        cur = con.execute(
            """INSERT INTO listings
            (donor,food_type,portions,allergens,prepared_at,deadline,storage,notes,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (item.donor, item.food_type, item.portions, item.allergens, item.prepared_at,
             item.deadline, item.storage, item.notes, datetime.now().astimezone().isoformat())
        )
        row = con.execute("SELECT * FROM listings WHERE id=?", (cur.lastrowid,)).fetchone()
    return public_row(row)


@app.get("/api/listings/{listing_id}/matches")
def matches(listing_id: int):
    with connect() as con:
        row = con.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Listing not found.")
    if row["status"] != "available" or datetime.fromisoformat(row["deadline"]) <= datetime.now().astimezone():
        return {"matches": [], "reason": "This listing is not currently available."}
    recipients = [
        {"name": "Campus Support Centre", "capacity": 100, "area": "North campus"},
        {"name": "Student Volunteers Club", "capacity": 50, "area": "Main campus"},
        {"name": "Green Society", "capacity": 15, "area": "East campus"},
    ]
    eligible = [r for r in recipients if r["capacity"] >= row["portions"]]
    eligible.sort(key=lambda r: (r["capacity"] - row["portions"], r["name"]))
    return {"matches": eligible, "reason": "Illustrative matches based on declared capacity; verify dietary needs and pickup feasibility."}


@app.post("/api/listings/{listing_id}/reserve")
def reserve(listing_id: int, item: ReserveIn):
    with connect() as con:
        row = con.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Listing not found.")
        if row["status"] != "available":
            raise HTTPException(409, "Listing is no longer available.")
        if datetime.fromisoformat(row["deadline"]) <= datetime.now().astimezone():
            con.execute("UPDATE listings SET status='expired' WHERE id=?", (listing_id,))
            raise HTTPException(409, "Pickup deadline has passed.")
        if item.capacity < row["portions"]:
            raise HTTPException(400, "Recipient capacity is smaller than the batch.")
        code = str(secrets.randbelow(900000) + 100000)
        changed = con.execute(
            "UPDATE listings SET status='reserved',recipient=?,pickup_code=? WHERE id=? AND status='available'",
            (item.recipient, code, listing_id)
        ).rowcount
        if not changed:
            raise HTTPException(409, "Listing was reserved by another request.")
    return {"message": "Reservation created.", "pickup_code": code, "listing_id": listing_id}


@app.post("/api/listings/{listing_id}/confirm")
def confirm(listing_id: int, item: ConfirmIn):
    with connect() as con:
        row = con.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Listing not found.")
        if row["status"] != "reserved":
            raise HTTPException(409, "Reserve the listing before confirming pickup.")
        if not secrets.compare_digest(row["pickup_code"] or "", item.pickup_code):
            raise HTTPException(400, "Pickup code does not match.")
        con.execute("INSERT INTO handovers(listing_id,recipient,portions,confirmed_at) VALUES(?,?,?,?)",
                    (listing_id, row["recipient"], row["portions"], datetime.now().astimezone().isoformat()))
        con.execute("UPDATE listings SET status='completed',pickup_code=NULL WHERE id=?", (listing_id,))
    return {"message": "Handover recorded.", "listing_id": listing_id}


@app.get("/api/reports/impact")
def impact():
    with connect() as con:
        portions = con.execute("SELECT COALESCE(SUM(portions),0) FROM handovers").fetchone()[0]
        completed = con.execute("SELECT COUNT(*) FROM handovers").fetchone()[0]
        active = con.execute("SELECT COUNT(*) FROM listings WHERE status IN ('available','reserved')").fetchone()[0]
        expired = con.execute("SELECT COUNT(*) FROM listings WHERE status='expired'").fetchone()[0]
    return {"portions_redistributed": portions, "completed_pickups": completed,
            "active_listings": active, "expired_unclaimed": expired}
