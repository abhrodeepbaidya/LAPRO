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
$env:GOOGLE_CLIENT_ID = "your-google-oauth-client-id.apps.googleusercontent.com"
uvicorn main:app --reload
```

Open http://127.0.0.1:8000/docs.

## Main routes

- Health: `GET /health`
- Auth: `POST /auth/register`, `POST /auth/login`, `POST /auth/google` (Google Identity Services ID token), `POST /auth/refresh`, `GET /auth/me`
- Google sign-in: create an OAuth 2.0 Web application client in Google Cloud Console; add the exact website origin to Authorized JavaScript origins; set its Client ID as the frontend GIS client ID and backend `GOOGLE_CLIENT_ID`. Never put a Google client secret in frontend code.
- Posts: `GET/POST /posts`, `GET/PATCH/DELETE /posts/{post_id}`
- Comments: `GET/POST /posts/{post_id}/comments`, `DELETE /comments/{comment_id}`
- Likes: `POST /posts/{post_id}/like` (toggle)
- Profiles: `GET /users/{user_id}`, `GET /users/{user_id}/posts`, `GET /users?q=...`
- BGMI Community: `GET /bgmi/news` (public feed), `POST /staff/bgmi/news` (Owner/Admin/Manager/Supervisor), `DELETE /staff/bgmi/news/{news_id}` (staff)
- XP: `GET /xp/tiers`, `GET /xp/me`
- Support tickets: `POST /support/tickets`, `GET /support/tickets` (user-owned requests)
- Support admin queue: `GET /staff/support/tickets?status=open|reviewing|resolved|closed|all`, `PATCH /staff/support/tickets/{ticket_id}` (Owner/Admin/Manager/Supervisor only; resolving sends an in-app notification to the requester)
- Reports: `POST /reports`
- Staff: `GET /staff/reports`, `PATCH /staff/reports/{report_id}`, role/restriction/ban/XP/audit routes under `/staff`
- Chat maintenance: `GET /status/chat` (public status), `PUT /master/settings/chat-maintenance` (Owner) or `PUT /admin/settings/chat-maintenance` (Admin) with `enabled`, `duration_minutes` and optional `notice`; messaging and conversation reads return HTTP 503 during maintenance, then automatically resume when the timer expires.
- Inbox: `POST /messages`, `GET /messages/{other_user_id}`
- User block/unblock: `POST /users/{user_id}/block`, `DELETE /users/{user_id}/block` (blocks new messages in both directions)
- Staff warnings: `POST /staff/users/{user_id}/warning` (in-app warning; email requires SMTP provider configuration)
- Staff post management: `GET /staff/posts`, `POST /staff/posts`, `DELETE /staff/posts/{post_id}`
- Chat moderation: `DELETE /staff/conversations/{user_a_id}/{user_b_id}` (Owner/Admin only; deletes stored messages and records an audit entry)
- Notifications: `GET /notifications`, `POST /notifications/{notification_id}/read`

## Important limitations before public launch

This is a broad v1 API foundation, not a fully production-hardened social network. It still needs Alembic migrations, automated tests, email verification and password reset, refresh-token revocation/session management, persistent rate limiting, abuse/spam detection, block lists, privacy controls, encrypted backups, monitoring, and security review. Direct messages currently have no block/report workflow. Real-time chat/WebSockets and media uploads are not implemented. Staff permission granularity needs a final policy review before production. Support ticket routes are available in the API, but the static GitHub Pages frontend still needs its live API URL and real backend authentication wired in before users can submit tickets and receive resolution notifications from the website.

The first registered account only receives the Owner role when its email matches the server-side `OWNER_EMAIL` setting. Set that environment variable before creating the Owner account. Never commit JWT secrets or database credentials.


## BGMI Community

The website includes a dedicated BGMI Community entry for gamers to discuss BGMI, patch notes, esports, tournaments and updates. The API provides a public news feed and staff-only publishing/removal endpoints. Staff should include an HTTPS source link for externally sourced news. The static website preview still stores posts in the visitor's browser; live website-to-API integration is a separate deployment step.
