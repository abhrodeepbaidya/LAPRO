# LAPRO API — Backend v1 starter

This is the first backend milestone: health check, account registration, login, and authenticated profile lookup.

## Run locally

1. Install Python 3.11 or newer.
2. Open a terminal in the `backend` directory.
3. Create and activate a virtual environment.
4. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

5. Copy `.env.example` to `.env` and set a long random `JWT_SECRET`.
6. Load the environment variables, then run:

   ```bash
   uvicorn main:app --reload
   ```

7. Open `http://127.0.0.1:8000/docs`.

For local testing, SQLite is used by default. Production must use PostgreSQL and a secret stored in the hosting provider's environment settings.

## First endpoints

- `GET /health`
- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me` (Bearer token required)

## Important

This is a development starter, not a production-ready launch. Before public launch, add database migrations, email verification, password reset, login/register rate limits, refresh-token/session revocation, security logging, and automated tests. Do not commit real secrets or a production database URL.
