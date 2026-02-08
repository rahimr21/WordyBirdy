# Security Policy

This document summarizes the security features and rules in place for WordyBirdy. These safeguards protect against common vulnerabilities including unauthorized access, abuse, injection attacks, and information leakage.

---

## Authentication & Authorization

### Protected Endpoints

| Endpoint | Required Auth | Notes |
|----------|---------------|-------|
| `POST /api/transcribe` | Logged-in user | OpenAI Whisper |
| `POST /api/evaluate` | Logged-in user | Reading accuracy |
| `POST /api/coach` | Logged-in user | OpenAI GPT |
| `POST /api/tts` | Logged-in user | OpenAI TTS |
| `GET /api/assignments` | Logged-in user | Assignments list |
| `GET /api/assignments/<id>` | Logged-in user | Single assignment |
| `POST /api/assignments` | Teacher only | Create assignment |
| `GET /api/submissions` | Teacher only | All submissions |
| `GET /api/submissions/<id>` | Teacher only | Single submission |
| `POST /api/submissions` | Logged-in user | Create/update submission |
| `POST /api/submit-assignment` | Logged-in user | Mark as submitted |

### API Auth Behavior

- API routes return JSON `401 Unauthorized` or `403 Forbidden` — never redirects.
- Page routes (`/teacher`, `/student`, `/assignment`) redirect unauthenticated users to login.

---

## Rate Limiting

Rate limits are enforced via Flask-Limiter. Authenticated requests use `user_id`; unauthenticated requests use IP address.

| Route Group | Limit | Purpose |
|-------------|-------|---------|
| `POST /api/login` | 10 per 5 minutes | Brute-force protection |
| `POST /api/signup` | 5 per 5 minutes | Account creation abuse |
| `POST /api/transcribe`, `/api/coach`, `/api/tts` | 20 per minute | OpenAI quota protection |
| `POST /api/evaluate` | 60 per minute | Part of reading burst |
| Other API routes | 60 per minute | General throttle |

**Reading flow:** A single reading session (transcribe → evaluate → submissions → coach, plus optional TTS) uses 4–5 requests within ~10 seconds. Limits are set so this burst is allowed.

**429 Response:** Rate limit exceeded returns JSON: `{"error": "Rate limit exceeded. Please try again later."}`

---

## Input Validation

### Authentication

- **Email:** Valid format (email-validator), max 254 chars
- **Password:** 8–128 characters
- **Full name:** Max 200 characters
- **Role:** Allowlist `["student", "teacher"]`

### File Uploads

- **PDF:** Max 10 MB, `.pdf` extension only
- **Audio:** Max 25 MB, audio MIME type required

### Text Payloads

- **Target / transcript** (evaluate, coach): Max 50,000 chars each
- **TTS text:** Max 4,096 chars (OpenAI limit)
- **Misreads:** Max 500 items, each string max 200 chars
- **Grade level:** Allowlist `["K", "1", "2", "3", "4", "5", "6", "7", "8"]`

### Assignments

- **Title:** Max 200 chars
- **Min accuracy:** 0–100
- **Grade level:** Same allowlist as above

### Submissions

- **Assignment ID:** Required, valid integer, must exist in DB
- **Accuracy:** 0–100 if provided

---

## Secure Configuration

### Environment Variables

- **Required at startup:** `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` — app fails fast if missing
- **Production:** `SECRET_KEY` required and must not be `"dev"`
- Keys are never logged or included in error responses

### Session

- `SESSION_COOKIE_HTTPONLY = True` — no JavaScript access
- `SESSION_COOKIE_SAMESITE = "Lax"` — CSRF protection
- `SESSION_COOKIE_SECURE = True` — HTTPS only in production

### Uploads

- `MAX_CONTENT_LENGTH = 25 MB` — global upload cap

### Production

- `debug=False` when `FLASK_ENV=production`
- `SECRET_KEY` must be set and non-default

---

## XSS Prevention

- AI responses (tips, questions) and reading feedback are escaped with `escapeHtml()` before rendering
- `textContent` used where possible instead of `innerHTML` for untrusted content

---

## Error Handling

- Internal errors are logged server-side only
- Client receives generic messages: `"An error occurred. Please try again."`
- External API errors (OpenAI) are not passed through; generic messages are returned instead

---

## Reporting a Vulnerability

If you discover a security issue, please report it responsibly rather than opening a public issue. Include steps to reproduce and suggested fix if possible.
