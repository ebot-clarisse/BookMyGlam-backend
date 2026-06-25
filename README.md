# BookMyGlam — Python Backend API

FastAPI + Supabase backend for the BookMyGlam beauty appointment platform.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy the environment file and fill in your values:
```bash
cp .env.example .env
```

3. Fill in `.env`:
```
SUPABASE_URL=https://rtamivwoaywqmgqzwibu.supabase.co
SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_KEY=your_service_role_key  ← get from Supabase Settings > API > Legacy tab
SECRET_KEY=any_random_string_32_chars
ALLOWED_ORIGINS=https://your-vercel-url.vercel.app
```

4. Run locally:
```bash
uvicorn main:app --reload --port 8000
```

5. Open API docs at: http://localhost:8000/docs

---

## API Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/` | API info | None |
| GET | `/health` | Health check | None |
| GET | `/api/stylists` | Browse all stylists | None |
| GET | `/api/stylists/{id}` | Single stylist profile | None |
| GET | `/api/reviews/{stylist_id}` | Stylist reviews | None |
| GET | `/api/portfolio/{stylist_id}` | Stylist portfolio | None |
| GET | `/api/profile/me` | My profile | Bearer token |
| PATCH | `/api/profile/me` | Update my profile | Bearer token |
| GET | `/api/bookings` | My bookings | Bearer token |
| POST | `/api/bookings` | Create booking | Customer |
| PATCH | `/api/bookings/{id}` | Update booking status | Customer/Pro |
| GET | `/api/notifications` | My notifications | Bearer token |
| PATCH | `/api/notifications/read-all` | Mark all read | Bearer token |
| GET | `/api/services` | My services | Pro |
| POST | `/api/services` | Add service | Pro |
| PATCH | `/api/services/{id}` | Update service | Pro |
| DELETE | `/api/services/{id}` | Delete service | Pro |
| POST | `/api/portfolio` | Add portfolio photo | Pro |
| DELETE | `/api/portfolio/{id}` | Delete portfolio photo | Pro |
| POST | `/api/reviews` | Submit review | Customer |
| GET | `/api/plans/me` | My subscription plan | Pro |
| POST | `/api/plans` | Activate plan | Pro |
| GET | `/api/saved` | My saved stylists | Customer |
| POST | `/api/saved/{stylist_id}` | Save a stylist | Customer |
| DELETE | `/api/saved/{stylist_id}` | Unsave a stylist | Customer |
| GET | `/api/admin/users` | All users | Admin |
| PATCH | `/api/admin/users/{id}/status` | Set user status | Admin |
| DELETE | `/api/admin/users/{id}` | Delete user | Admin |
| GET | `/api/admin/bookings` | All bookings | Admin |
| PATCH | `/api/admin/bookings/{id}` | Update any booking | Admin |
| GET | `/api/admin/revenue` | Revenue data | Admin |
| GET | `/api/admin/reviews` | All reviews | Admin |
| DELETE | `/api/admin/reviews/{id}` | Delete review | Admin |
| POST | `/api/admin/broadcast` | Send broadcast notification | Admin |

---

## Authentication

All protected routes require a Supabase JWT token in the Authorization header:
```
Authorization: Bearer eyJhbGci...
```

The token is obtained from `supabase.auth.getSession()` in the frontend.

---

## Deploy to Railway (free)

1. Go to https://railway.app
2. Click New Project → Deploy from GitHub repo
3. Select your backend repository
4. Add environment variables from your .env file
5. Railway auto-detects FastAPI and deploys it

Then update your frontend `db.js` to call the API URL for any operations
you want to route through the Python backend.

---

## Deploy to Render (free)

1. Go to https://render.com
2. New → Web Service → Connect your GitHub repo
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add environment variables
6. Deploy
