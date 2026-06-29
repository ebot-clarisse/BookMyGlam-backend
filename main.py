"""
BookMyGlam — Python Backend API
Built with FastAPI + Supabase

Run locally:
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

Deploy to Railway / Render / Fly.io
"""

from fastapi import FastAPI, HTTPException, Depends, Header, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from supabase import create_client, Client
from typing import Optional, List
import os, httpx

load_dotenv()

# ── Supabase clients ────────────────────────────────────────────────────────
SUPABASE_URL         = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY    = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# Public client (honours Row Level Security)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# Admin client (bypasses RLS — used only for admin routes)
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ── App setup ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="BookMyGlam API",
    description="Backend API for the BookMyGlam beauty appointment platform",
    version="1.0.0",
)

# Allow all origins — frontend is on Vercel, backend on Railway
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# Always include common Vercel URLs
ALL_ORIGINS = list(set(ALLOWED_ORIGINS + [
    "https://book-my-glam-ten.vercel.app",
    "https://book-my-glam-sth6.vercel.app",
    "http://localhost:5500",
    "http://localhost:3000",
    "http://127.0.0.1:5500",
]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth dependency ─────────────────────────────────────────────────────────
async def get_current_user(authorization: Optional[str] = Header(None)):
    """Extract and verify the Supabase JWT from the Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization.split(" ")[1]
    try:
        user_response = supabase.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return user_response.user
    except Exception as e:
        raise HTTPException(status_code=401, detail="Authentication failed: " + str(e))

async def get_current_profile(user=Depends(get_current_user)):
    """Get the full profile record for the authenticated user."""
    response = supabase_admin.from_("profiles").select("*").eq("id", user.id).single().execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Profile not found")
    return response.data

async def require_admin(profile=Depends(get_current_profile)):
    """Require the authenticated user to be an administrator."""
    if profile.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return profile

async def require_pro(profile=Depends(get_current_profile)):
    """Require the authenticated user to be a beauty professional."""
    if profile.get("role") not in ("pro", "admin"):
        raise HTTPException(status_code=403, detail="Professional access required")
    return profile

# ══════════════════════════════════════════════════════════════════════════
#  ROOT
# ══════════════════════════════════════════════════════════════════════════

@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "BookMyGlam API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }

@app.get("/health", tags=["Root"])
async def health():
    """Health check endpoint for deployment platforms."""
    try:
        supabase.from_("profiles").select("id").limit(1).execute()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})

# ══════════════════════════════════════════════════════════════════════════
#  PROFILES
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/profile/me", tags=["Profile"])
async def get_my_profile(profile=Depends(get_current_profile)):
    """Get the authenticated user's full profile."""
    return {"success": True, "data": profile}

@app.patch("/api/profile/me", tags=["Profile"])
async def update_my_profile(updates: dict, user=Depends(get_current_user)):
    """Update the authenticated user's profile. Only safe fields are allowed."""
    SAFE_FIELDS = {"name","phone","location","bio","avatar_url",
                   "instagram","business_name","cancel_policy","email_notif","sms_notif",
                   "experience","tags"}
    clean = {k: v for k, v in updates.items() if k in SAFE_FIELDS}
    if not clean:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    response = supabase_admin.from_("profiles").update(clean).eq("id", user.id).execute()
    return {"success": True, "data": response.data}

# ══════════════════════════════════════════════════════════════════════════
#  STYLISTS (public browse)
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/stylists", tags=["Stylists"])
async def get_stylists(
    category: Optional[str] = None,
    location: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
):
    """Get all active beauty professionals with their services and portfolio count."""
    query = supabase.from_("profiles")\
        .select("id,name,email,location,bio,avatar_url,instagram,business_name,cancel_policy,services(id,name,price,duration,category),portfolio(id)")\
        .eq("role", "pro")\
        .eq("active", True)\
        .range(offset, offset + limit - 1)

    if location:
        query = query.ilike("location", f"%{location}%")

    response = query.execute()
    stylists = response.data or []

    # Filter by service category if requested
    if category and category != "all":
        stylists = [
            s for s in stylists
            if any(svc.get("category","").lower() == category.lower()
                   for svc in (s.get("services") or []))
        ]

    return {"success": True, "data": stylists, "count": len(stylists)}

@app.get("/api/stylists/{stylist_id}", tags=["Stylists"])
async def get_stylist(stylist_id: str):
    """Get a single stylist profile with services, portfolio, and reviews."""
    response = supabase.from_("profiles")\
        .select("*,services(*),portfolio(*),reviews(rating,text,created_at,customer:profiles!reviews_customer_id_fkey(name,avatar_url))")\
        .eq("id", stylist_id).eq("role", "pro").single().execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Stylist not found")
    return {"success": True, "data": response.data}

# ══════════════════════════════════════════════════════════════════════════
#  BOOKINGS
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/bookings", tags=["Bookings"])
async def get_my_bookings(profile=Depends(get_current_profile)):
    """Get all bookings for the authenticated user (customer or stylist)."""
    role = profile.get("role")
    uid  = profile.get("id")

    if role == "customer":
        response = supabase_admin.from_("bookings")\
            .select("*,stylist:profiles!bookings_stylist_id_fkey(name,email,avatar_url)")\
            .eq("customer_id", uid)\
            .order("date", desc=True).execute()
    else:
        response = supabase_admin.from_("bookings")\
            .select("*,customer:profiles!bookings_customer_id_fkey(name,email,avatar_url)")\
            .eq("stylist_id", uid)\
            .order("date", desc=True).execute()

    return {"success": True, "data": response.data or []}

@app.post("/api/bookings", tags=["Bookings"])
async def create_booking(booking: dict, profile=Depends(get_current_profile)):
    """Create a new booking. Only customers can create bookings."""
    if profile.get("role") != "customer":
        raise HTTPException(status_code=403, detail="Only customers can create bookings")

    required = {"stylist_id", "service_name", "service_price", "date", "time"}
    if not required.issubset(booking.keys()):
        raise HTTPException(status_code=400, detail=f"Missing required fields: {required}")

    new_booking = {
        "customer_id":   profile["id"],
        "stylist_id":    booking["stylist_id"],
        "service_name":  booking["service_name"],
        "service_price": int(booking["service_price"]),
        "date":          booking["date"],
        "time":          booking["time"],
        "location":      booking.get("location", ""),
        "notes":         booking.get("notes", ""),
        "status":        "pending",
    }

    response = supabase_admin.from_("bookings").insert(new_booking).execute()
    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to create booking")

    created = response.data[0]

    # Send notification to stylist
    supabase_admin.from_("notifications").insert({
        "user_id": booking["stylist_id"],
        "icon":    "📅",
        "title":   "New Booking Request",
        "message": f"New request for {booking['service_name']} on {booking['date']} at {booking['time']}.",
        "read":    False,
    }).execute()

    return {"success": True, "data": created}

@app.patch("/api/bookings/{booking_id}", tags=["Bookings"])
async def update_booking_status(booking_id: str, body: dict, profile=Depends(get_current_profile)):
    """Update booking status. Stylists confirm/cancel; customers can cancel their own."""
    new_status = body.get("status")
    if new_status not in ("confirmed", "cancelled", "completed"):
        raise HTTPException(status_code=400, detail="Invalid status")

    # Fetch the booking first
    bk_resp = supabase_admin.from_("bookings").select("*").eq("id", booking_id).single().execute()
    if not bk_resp.data:
        raise HTTPException(status_code=404, detail="Booking not found")
    bk = bk_resp.data

    # Authorise
    uid  = profile["id"]
    role = profile["role"]
    if role == "customer" and bk["customer_id"] != uid:
        raise HTTPException(status_code=403, detail="Not your booking")
    if role == "pro" and bk["stylist_id"] != uid:
        raise HTTPException(status_code=403, detail="Not your booking")

    # Update
    upd = supabase_admin.from_("bookings").update({"status": new_status}).eq("id", booking_id).execute()

    # Notify the other party
    if new_status == "confirmed":
        supabase_admin.from_("notifications").insert({
            "user_id": bk["customer_id"],
            "icon": "✅", "title": "Booking Confirmed!",
            "message": f"Your {bk['service_name']} on {bk['date']} at {bk['time']} is confirmed.",
            "read": False,
        }).execute()
    elif new_status == "cancelled":
        notify_id = bk["customer_id"] if role == "pro" else bk["stylist_id"]
        supabase_admin.from_("notifications").insert({
            "user_id": notify_id,
            "icon": "❌", "title": "Booking Cancelled",
            "message": f"The {bk['service_name']} appointment on {bk['date']} was cancelled.",
            "read": False,
        }).execute()

    return {"success": True, "data": upd.data}

# ══════════════════════════════════════════════════════════════════════════
#  NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/notifications", tags=["Notifications"])
async def get_notifications(profile=Depends(get_current_profile)):
    """Get all notifications for the authenticated user."""
    response = supabase_admin.from_("notifications")\
        .select("*").eq("user_id", profile["id"])\
        .order("created_at", desc=True).limit(50).execute()
    return {"success": True, "data": response.data or []}

@app.patch("/api/notifications/read-all", tags=["Notifications"])
async def mark_all_read(profile=Depends(get_current_profile)):
    """Mark all notifications as read for the authenticated user."""
    supabase_admin.from_("notifications")\
        .update({"read": True})\
        .eq("user_id", profile["id"]).eq("read", False).execute()
    return {"success": True}

# ══════════════════════════════════════════════════════════════════════════
#  SERVICES (stylist's menu)
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/services", tags=["Services"])
async def get_my_services(profile=Depends(require_pro)):
    """Get all services for the authenticated stylist."""
    response = supabase_admin.from_("services")\
        .select("*").eq("stylist_id", profile["id"]).eq("active", True)\
        .order("created_at").execute()
    return {"success": True, "data": response.data or []}

@app.post("/api/services", tags=["Services"])
async def create_service(service: dict, profile=Depends(require_pro)):
    """Create a new service for the authenticated stylist."""
    required = {"name", "price"}
    if not required.issubset(service.keys()):
        raise HTTPException(status_code=400, detail="name and price are required")
    new_svc = {
        "stylist_id": profile["id"],
        "name":       service["name"],
        "price":      int(service["price"]),
        "duration":   service.get("duration", ""),
        "category":   service.get("category", ""),
        "active":     True,
    }
    response = supabase_admin.from_("services").insert(new_svc).execute()
    return {"success": True, "data": response.data[0] if response.data else None}

@app.patch("/api/services/{service_id}", tags=["Services"])
async def update_service(service_id: str, updates: dict, profile=Depends(require_pro)):
    """Update a service. Only the owning stylist can update."""
    SAFE = {"name", "price", "duration", "category", "active"}
    clean = {k: v for k, v in updates.items() if k in SAFE}
    response = supabase_admin.from_("services")\
        .update(clean).eq("id", service_id).eq("stylist_id", profile["id"]).execute()
    return {"success": True, "data": response.data}

@app.delete("/api/services/{service_id}", tags=["Services"])
async def delete_service(service_id: str, profile=Depends(require_pro)):
    """Soft-delete a service (sets active=False)."""
    supabase_admin.from_("services")\
        .update({"active": False}).eq("id", service_id).eq("stylist_id", profile["id"]).execute()
    return {"success": True}

# ══════════════════════════════════════════════════════════════════════════
#  PORTFOLIO
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/portfolio/{stylist_id}", tags=["Portfolio"])
async def get_portfolio(stylist_id: str):
    """Get portfolio photos for a stylist (public)."""
    response = supabase.from_("portfolio")\
        .select("*").eq("stylist_id", stylist_id)\
        .order("created_at", desc=True).execute()
    return {"success": True, "data": response.data or []}

@app.post("/api/portfolio", tags=["Portfolio"])
async def add_portfolio_photo(photo: dict, profile=Depends(require_pro)):
    """Add a portfolio photo. The URL should be a Supabase Storage public URL."""
    if "url" not in photo:
        raise HTTPException(status_code=400, detail="url is required")
    new_photo = {
        "stylist_id": profile["id"],
        "url":        photo["url"],
        "caption":    photo.get("caption", ""),
        "category":   photo.get("category", ""),
    }
    response = supabase_admin.from_("portfolio").insert(new_photo).execute()
    return {"success": True, "data": response.data[0] if response.data else None}

@app.delete("/api/portfolio/{photo_id}", tags=["Portfolio"])
async def delete_portfolio_photo(photo_id: str, profile=Depends(require_pro)):
    """Delete a portfolio photo."""
    supabase_admin.from_("portfolio")\
        .delete().eq("id", photo_id).eq("stylist_id", profile["id"]).execute()
    return {"success": True}

# ══════════════════════════════════════════════════════════════════════════
#  REVIEWS
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/reviews/{stylist_id}", tags=["Reviews"])
async def get_reviews(stylist_id: str):
    """Get all reviews for a stylist (public)."""
    response = supabase.from_("reviews")\
        .select("*,customer:profiles!reviews_customer_id_fkey(name,avatar_url)")\
        .eq("stylist_id", stylist_id)\
        .order("created_at", desc=True).execute()
    return {"success": True, "data": response.data or []}

@app.post("/api/reviews", tags=["Reviews"])
async def create_review(review: dict, profile=Depends(get_current_profile)):
    """Create a review. Only customers can review stylists."""
    if profile.get("role") != "customer":
        raise HTTPException(status_code=403, detail="Only customers can submit reviews")
    required = {"stylist_id", "rating"}
    if not required.issubset(review.keys()):
        raise HTTPException(status_code=400, detail="stylist_id and rating are required")
    rating = int(review["rating"])
    if not 1 <= rating <= 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")
    new_review = {
        "customer_id": profile["id"],
        "stylist_id":  review["stylist_id"],
        "booking_id":  review.get("booking_id"),
        "rating":      rating,
        "text":        review.get("text", ""),
    }
    response = supabase_admin.from_("reviews").insert(new_review).execute()
    # Notify stylist
    supabase_admin.from_("notifications").insert({
        "user_id": review["stylist_id"],
        "icon": "⭐", "title": "New Review!",
        "message": f"You received a {rating}-star review: \"{review.get('text','')[:80]}\"",
        "read": False,
    }).execute()
    return {"success": True, "data": response.data[0] if response.data else None}

# ══════════════════════════════════════════════════════════════════════════
#  PLANS (subscriptions)
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/plans/me", tags=["Plans"])
async def get_my_plan(profile=Depends(require_pro)):
    """Get the active subscription plan for the authenticated stylist."""
    response = supabase_admin.from_("plans")\
        .select("*").eq("stylist_id", profile["id"]).maybeSingle().execute()
    return {"success": True, "data": response.data}

@app.post("/api/plans", tags=["Plans"])
async def activate_plan(body: dict, profile=Depends(require_pro)):
    """Activate a subscription plan for the authenticated stylist."""
    PLANS = {
        "starter":      {"name": "Starter",      "price": 5000},
        "professional": {"name": "Professional",  "price": 10000},
        "salon_team":   {"name": "Salon Team",    "price": 20000},
    }
    plan_key = body.get("plan_key")
    if plan_key not in PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan. Choose from: {list(PLANS.keys())}")

    from datetime import datetime, timedelta
    paid_until = (datetime.utcnow() + timedelta(days=30)).isoformat()
    plan_data  = {
        "stylist_id": profile["id"],
        "plan_key":   plan_key,
        "plan_name":  PLANS[plan_key]["name"],
        "price_xaf":  PLANS[plan_key]["price"],
        "paid_until": paid_until,
        "active":     True,
    }
    response = supabase_admin.from_("plans").upsert(plan_data).execute()
    # Notify stylist
    supabase_admin.from_("notifications").insert({
        "user_id": profile["id"],
        "icon": "🎉", "title": "Plan Activated!",
        "message": f"Your {PLANS[plan_key]['name']} plan is now active. Full access unlocked.",
        "read": False,
    }).execute()
    return {"success": True, "data": response.data[0] if response.data else plan_data}

# ══════════════════════════════════════════════════════════════════════════
#  SAVED PROFESSIONALS
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/saved", tags=["Saved"])
async def get_saved_pros(profile=Depends(get_current_profile)):
    """Get all saved beauty professionals for the authenticated customer."""
    response = supabase_admin.from_("saved_professionals")\
        .select("*,stylist:profiles!saved_professionals_stylist_id_fkey(id,name,email,avatar_url,location)")\
        .eq("customer_id", profile["id"]).execute()
    stylists = [d["stylist"] for d in (response.data or []) if d.get("stylist")]
    return {"success": True, "data": stylists}

@app.post("/api/saved/{stylist_id}", tags=["Saved"])
async def save_pro(stylist_id: str, profile=Depends(get_current_profile)):
    """Save a beauty professional to the customer's saved list."""
    supabase_admin.from_("saved_professionals")\
        .upsert({"customer_id": profile["id"], "stylist_id": stylist_id}).execute()
    return {"success": True}

@app.delete("/api/saved/{stylist_id}", tags=["Saved"])
async def unsave_pro(stylist_id: str, profile=Depends(get_current_profile)):
    """Remove a beauty professional from the customer's saved list."""
    supabase_admin.from_("saved_professionals")\
        .delete().eq("customer_id", profile["id"]).eq("stylist_id", stylist_id).execute()
    return {"success": True}

# ══════════════════════════════════════════════════════════════════════════
#  ADMIN ROUTES
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/admin/users", tags=["Admin"])
async def admin_get_users(admin=Depends(require_admin)):
    """Admin: get all registered users."""
    response = supabase_admin.from_("profiles")\
        .select("*").order("created_at", desc=True).execute()
    return {"success": True, "data": response.data or [], "count": len(response.data or [])}

@app.patch("/api/admin/users/{user_id}/status", tags=["Admin"])
async def admin_set_user_status(user_id: str, body: dict, admin=Depends(require_admin)):
    """Admin: set a user's status (active, suspended, pending)."""
    status_val = body.get("status")
    if status_val not in ("active", "suspended", "pending"):
        raise HTTPException(status_code=400, detail="Invalid status")
    supabase_admin.from_("profiles").update({"status": status_val}).eq("id", user_id).execute()
    return {"success": True}

@app.delete("/api/admin/users/{user_id}", tags=["Admin"])
async def admin_delete_user(user_id: str, admin=Depends(require_admin)):
    """Admin: permanently delete a user and all their data."""
    for table, col in [
        ("notifications", "user_id"), ("bookings", "customer_id"),
        ("bookings", "stylist_id"),   ("portfolio", "stylist_id"),
        ("services", "stylist_id"),   ("plans", "stylist_id"),
        ("reviews", "customer_id"),   ("reviews", "stylist_id"),
        ("saved_professionals", "customer_id"),
        ("saved_professionals", "stylist_id"),
    ]:
        supabase_admin.from_(table).delete().eq(col, user_id).execute()
    supabase_admin.from_("profiles").delete().eq("id", user_id).execute()
    return {"success": True}

@app.get("/api/admin/bookings", tags=["Admin"])
async def admin_get_bookings(admin=Depends(require_admin)):
    """Admin: get all bookings on the platform."""
    response = supabase_admin.from_("bookings")\
        .select("*,customer:profiles!bookings_customer_id_fkey(name,email),stylist:profiles!bookings_stylist_id_fkey(name,email)")\
        .order("created_at", desc=True).execute()
    return {"success": True, "data": response.data or []}

@app.patch("/api/admin/bookings/{booking_id}", tags=["Admin"])
async def admin_update_booking(booking_id: str, body: dict, admin=Depends(require_admin)):
    """Admin: update any booking status."""
    status_val = body.get("status")
    if status_val not in ("confirmed", "cancelled", "completed", "pending"):
        raise HTTPException(status_code=400, detail="Invalid status")
    supabase_admin.from_("bookings").update({"status": status_val}).eq("id", booking_id).execute()
    return {"success": True}

@app.get("/api/admin/revenue", tags=["Admin"])
async def admin_get_revenue(admin=Depends(require_admin)):
    """Admin: get all confirmed bookings for revenue calculation."""
    response = supabase_admin.from_("bookings")\
        .select("service_price,date,status,service_name")\
        .in_("status", ["confirmed", "completed"])\
        .order("date").execute()
    bookings = response.data or []
    total    = sum(b["service_price"] for b in bookings)
    return {"success": True, "data": bookings, "total_xaf": total, "count": len(bookings)}

@app.get("/api/admin/reviews", tags=["Admin"])
async def admin_get_reviews(admin=Depends(require_admin)):
    """Admin: get all reviews on the platform."""
    response = supabase_admin.from_("reviews")\
        .select("*,customer:profiles!reviews_customer_id_fkey(name),stylist:profiles!reviews_stylist_id_fkey(name)")\
        .order("created_at", desc=True).execute()
    return {"success": True, "data": response.data or []}

@app.delete("/api/admin/reviews/{review_id}", tags=["Admin"])
async def admin_delete_review(review_id: str, admin=Depends(require_admin)):
    """Admin: delete any review."""
    supabase_admin.from_("reviews").delete().eq("id", review_id).execute()
    return {"success": True}

@app.post("/api/admin/broadcast", tags=["Admin"])
async def admin_broadcast(body: dict, admin=Depends(require_admin)):
    """Admin: send a notification to all users or a specific role group."""
    title    = body.get("title", "")
    message  = body.get("message", "")
    icon     = body.get("icon", "📢")
    audience = body.get("audience", "all")  # "all", "customer", "pro"

    if not title or not message:
        raise HTTPException(status_code=400, detail="title and message are required")

    query = supabase_admin.from_("profiles").select("id")
    if audience in ("customer", "pro"):
        query = query.eq("role", audience)

    user_resp = query.execute()
    user_ids  = [u["id"] for u in (user_resp.data or [])]

    if not user_ids:
        return {"success": True, "sent": 0}

    rows = [{"user_id": uid, "title": title, "message": message, "icon": icon, "read": False}
            for uid in user_ids]
    supabase_admin.from_("notifications").insert(rows).execute()

    return {"success": True, "sent": len(user_ids)}
