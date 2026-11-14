# LAPRO

**Thoughts without identity.** LAPRO is an early-stage community product concept for sharing feelings, thoughts, facts and questions under a public alias.

## Current release: frontend prototype

The GitHub Pages site currently includes:
- Responsive layout for desktop and mobile
- Global feed with category filters
- Public channel filters
- Search across posts and answers
- Create thought, feeling, fact or question
- Ask & Answer threads, including unanswered-question and supported-post views
- Support reactions, share-link UI and alias selection
- Browser-local persistence using localStorage

## Important limitations

This release is a **single-browser frontend demo**, not a production social network:
- Posts, answers and aliases are stored only in the visitor's browser.
- Visitors do not see each other's posts.
- There is no real account authentication, server database, cross-device sync, live chat, private inbox, staff moderation or owner console yet.
- Report actions are placeholders and do not contact moderators.
- Do not enter personal, sensitive or confidential information.

A public alias hides a name from the public interface; it does not guarantee anonymity from the service operator or network providers. A production service must explain what operational data is collected and why.

## Planned production architecture

- Frontend: Next.js + TypeScript
- API: Python FastAPI
- Database: PostgreSQL
- Real-time channel chat: WebSockets
- Hosting: Vercel (frontend) + Render (API/database)
- Authentication: pseudonymous account IDs, secure passwordless or credential flow, session rotation and rate limits
- Authorization: server-enforced owner, admin, manager, supervisor, guard and user permissions

## Planned product milestones

1. Backend API and persistent accounts/posts/questions/answers
2. Secure authentication, role-based permissions and owner console
3. Channel chat and private inbox with blocking/reporting controls
4. Moderation queue, warnings, timed restrictions/bans and immutable staff audit trail
5. Privacy policy, data retention/deletion controls, security review and launch readiness

## Local preview

Open `index.html` in a browser, or run a static server in this directory:

```bash
python -m http.server 8000
```

Then visit http://localhost:8000.

## Privacy and safety requirements before public launch

Use least-privilege staff access, TLS, encrypted database storage/backups, secure secret management, rate limiting, abuse reporting, audited moderator access, retention/deletion policies, backups and incident response. Moderation access to message content must be clearly disclosed. Do not promise end-to-end privacy if staff can inspect message content.
