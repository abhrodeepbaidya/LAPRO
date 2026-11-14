# LAPRO API — backend v1

FastAPI backend starter for LAPRO. Includes accounts, posts, comments, likes, XP events, reports, staff actions, inbox messages and notifications.

## Run locally

Requires Python 3.11+.

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:JWT_SECRET = (py -c "import secrets; print(secrets.token_urlsafe(48))")
$env:DATABASE_URL = "sqlite:///./lapro_dev.db"
$env:FRONTEND_ORIGINS = "http://localhost:5500,http://127.0.0.1:5500,https://abhrodeepbaidya.github.io"
$env:OWNER_EMAIL = "your-owner-email@example.com"
uvicorn main:app --reload
```

Open http://127.0.0.1:8000/docs.

## Main routes

- Health: `GET /health`
- Auth: `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`
- Posts: `GET/POST /posts`, `GET/PATCH/DELETE /posts/{post_id}`
- Comments: `GET/POST /posts/{post_id}/comments`, `DELETE /comments/{comment_id}`
- Likes: `POST /posts/{post_id}/like` (toggle)
- Profiles: `GET /users/{user_id}`, `GET /users/{user_id}/posts`, `GET /users?q=...`
- XP: `GET /xp/tiers`, `GET /xp/me`
- Reports: `POST /reports`
- Staff: `GET /staff/reports`, `PATCH /staff/reports/{report_id}`, role/restriction/ban/XP/audit routes under `/staff`
- Inbox: `POST /messages`, `GET /messages/{other_user_id}`
- Notifications: `GET /notifications`, `POST /notifications/{notification_id}/read`

## Important limitations before public launch

This is a broad v1 API foundation, not a fully production-hardened social network. It still needs Alembic migrations, automated tests, email verification and password reset, refresh-token revocation/session management, persistent rate limiting, abuse/spam detection, block lists, privacy controls, encrypted backups, monitoring, and security review. Direct messages currently have no block/report workflow. Real-time chat/WebSockets and media uploads are not implemented. Staff permission granularity needs a final policy review before production.

The first registered account only receives the Owner role when its email matches the server-side `OWNER_EMAIL` setting. Set that environment variable before creating the Owner account. Never commit JWT secrets or database credentials.
