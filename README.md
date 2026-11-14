# LAPRO

LAPRO is a prototype for a global anonymous thoughts and feelings community.

## Current prototype
- Responsive landing page and community feed
- Sample posts across feelings, thoughts, facts and questions
- Local-only post preview and category filtering
- Anonymous alias entry UI (demo only)

## Important status
This is a frontend prototype. Authentication, persistence, real-time messaging, moderation workflows, staff roles, owner controls and production privacy/security are **not implemented yet**. Do not use it to collect real user data.

## Planned architecture
- Frontend: Next.js + TypeScript
- API: Python FastAPI
- Database: PostgreSQL
- Realtime: WebSockets
- Deployment: Vercel (frontend) + Render (API)

## Run locally
Open `index.html` in a browser, or serve the folder with any static HTTP server.

## Privacy and moderation
Anonymous public display is not the same as zero data collection. A production release needs a clear privacy notice, data minimization, access controls, encryption in transit and at rest, audited moderator access, retention/deletion rules, abuse reporting, and applicable legal review.
