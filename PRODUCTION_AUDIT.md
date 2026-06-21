# HealthPredict AI — Production Audit Report
**Generated:** 2026-06-21  
**Engineer:** Senior Staff / Principal Architect  
**Scope:** Full-stack production readiness audit

---

## CRITICAL ISSUES

| # | Severity | File | Line | Issue | Fix Applied |
|---|----------|------|------|-------|-------------|
| 1 | 🔴 CRITICAL | `backend-node/.env` | 3 | `ML_SERVICE_URL=http://localhost:5001` — points to localhost on Render, NOT the deployed ML service | Fixed to `https://healthpredicai-main.onrender.com` |
| 2 | 🔴 CRITICAL | `backend-node/routes/ai.js` | 31–41 | `proxyRequest` and `/predict` have NO timeout set → hangs forever | Added 30s timeout |
| 3 | 🔴 CRITICAL | `backend-node/routes/ai.js` | 65–75 | `/predict` axios call has NO timeout → analysis hangs | Fixed with 30000ms timeout |
| 4 | 🔴 CRITICAL | `backend-node/routes/ai.js` | 78–88 | `/chat` axios call has NO timeout → copilot hangs | Fixed with 30000ms timeout |
| 5 | 🔴 CRITICAL | `ml_service/app.py` | 1648–1654 | Flask runs in development mode (`debug=False` but no Gunicorn/WSGI) on Render → single-threaded | Render start command must use gunicorn |
| 6 | 🔴 CRITICAL | `ml_service/.env` | 10 | Gemini API key appears truncated/invalid | Must be replaced with valid key |
| 7 | 🔴 CRITICAL | `backend-node/db.js` | 1–25 | Uses `lowdb` FileSync — on Render free tier filesystem is **ephemeral** → all user registrations LOST on redeploy | MongoDB Atlas must be used for all user data |
| 8 | 🔴 CRITICAL | `ml_service/app.py` | — | No `/health` endpoint → Render health check fails → service marked unhealthy | Added `GET /health` returning `{"status":"healthy"}` |
| 9 | 🔴 CRITICAL | `backend-node/server.js` | 60 | `/health` exists but returns `{ status: 'ok' }` — Render expects standardised response | Normalised to `{"status":"healthy"}` |
| 10 | 🔴 CRITICAL | `frontend/src/context/AuthContext.jsx` | 121 | `register()` has 10000ms (10s) timeout — on Render cold start this fails → registration timeout | Increased to 30000ms + retry |

---

## HIGH SEVERITY

| # | Severity | File | Line | Issue | Fix Applied |
|---|----------|------|------|-------|-------------|
| 11 | 🟠 HIGH | `frontend/.env` | 2–3 | `VITE_API_URL=http://localhost:5000` — correct for local but Vercel deployment must set `VITE_API_URL=https://main-backend-55dg.onrender.com` | Documented in env.example |
| 12 | 🟠 HIGH | `frontend/src/pages/AdminLogin.jsx` | 83 | Admin login POSTs to `/api/admin/login` which IS correctly routed to Node backend — but error says `port 5002` on network error, confusing operators | Fixed error message |
| 13 | 🟠 HIGH | `backend-node/routes/ai.js` | 91–106 | OCR proxy uses `formData.append('file', req.file.buffer, req.file.originalname)` — missing mime type causes ML service to reject | Added content-type metadata |
| 14 | 🟠 HIGH | `ml_service/services/chatbot_service.py` | 337 | Gemini chat request has `timeout=8` seconds — too short for cold start | Increased to 25s |
| 15 | 🟠 HIGH | `ml_service/services/ocr_service.py` | 306 | Gemini OCR request has `timeout=60` — correct, but no retry on failure | Added retry logic |
| 16 | 🟠 HIGH | `backend-node/server.js` | 87 | ML proxy catch-all timeout is 30000ms — insufficient for cold-start ML service | Increased to 60000ms |
| 17 | 🟠 HIGH | `backend-node/routes/auth.js` | — | Login endpoint does NOT accept `admin` as `expectedRole` — admin login through this route impossible | Admin has its own route, documented |
| 18 | 🟠 HIGH | `ml_service/app.py` | — | `/chat` returns no explicit timeout guard — if Gemini hangs, entire Flask thread blocks | Added request-level timeout |

---

## MEDIUM SEVERITY

| # | Severity | File | Line | Issue | Fix Applied |
|---|----------|------|------|-------|-------------|
| 19 | 🟡 MED | `backend-node/server.js` | 6 | `ML_SERVICE_URL` default is `http://127.0.0.1:5001` — useless in production | Env must override |
| 20 | 🟡 MED | `backend-node/config/constants.js` | 13 | JWT secret fallback `'health-predict-secret-key-change-in-prod'` — must be overridden in Render env vars | Documented |
| 21 | 🟡 MED | `ml_service/.env` | 17 | `JWT_SECRET=your-super-secret-jwt-key-here` — must match Node backend | Must match in Render |
| 22 | 🟡 MED | `frontend/src/pages/Predict.jsx` | 295 | Uses bare `fetch()` with no timeout → can hang | Wrapped with AbortController + 30s timeout |
| 23 | 🟡 MED | `ml_service/app.py` | 34 | `CORS(app, resources={r"/*": {"origins": "*"}})` — too permissive for production | Acceptable for this architecture |
| 24 | 🟡 MED | `backend-node/server.js` | 39–40 | JSON body limit is `50mb` — correct for image uploads | OK |
| 25 | 🟡 MED | `ml_service/services/chatbot_service.py` | 219–275 | `g4f` fallback uses unofficial providers (GeminiPro, Yqcloud, PollinationsAI) — unreliable in production | Added proper error handling |
| 26 | 🟡 MED | `ml_service/services/report_analyzer_service.py` | 67 | Uses `gemini-2.0-flash` which may not be available on all API tiers | Falls back gracefully |

---

## LOW SEVERITY / INFORMATIONAL

| # | Severity | File | Issue | Fix Applied |
|---|----------|------|-------|-------------|
| 27 | 🔵 INFO | `backend-node/db.js` | lowdb stores data in `/data/*.json` — these persist across restarts on dev but NOT on Render free tier | Users registered in production will be lost on next deploy |
| 28 | 🔵 INFO | `ml_service/app.py` | ML models stored in `/models/` — if not in repo, prediction falls to rule-based | Models should be committed or downloaded at startup |
| 29 | 🔵 INFO | `frontend/vite.config.js` | Console/debugger stripped in production build — good | OK |
| 30 | 🔵 INFO | `backend-node/routes/ai.js` | predict route: `POST /api/ai/predict` → proxies to ML `/predict` — route mapping is CORRECT | OK |
| 31 | 🔵 INFO | All services | No rate limiting on any endpoint | Added express-rate-limit on backend |
| 32 | 🔵 INFO | All services | No structured logging or request tracing | Added morgan + request IDs |

---

## Route Mapping Verification

| Frontend Call | Backend Route | ML Service Route | Status |
|---------------|---------------|------------------|--------|
| `POST /api/ai/predict` | `/api/ai/predict` → proxy | `/predict` | ✅ CORRECT |
| `POST /api/ai/chat` or `/api/chat` | `/api/ai/chat` + alias `/api/chat` | `/chat` | ✅ CORRECT |
| `POST /api/ai/ocr` | `/api/ai/ocr` → proxy | `/ocr` | ✅ CORRECT |
| `POST /api/ai/analyze-report` | `/api/ai/analyze-report` → proxy | `/analyze-report` | ✅ CORRECT |
| `POST /api/auth/register` | `/api/auth/register` → Node | N/A | ✅ CORRECT |
| `POST /api/auth/login` | `/api/auth/login` → Node | N/A | ✅ CORRECT |
| `POST /api/admin/login` | `/api/admin/login` → Node | N/A | ✅ CORRECT |
| `GET /health` | `/health` (Node) | `/health` (Flask - NEW) | ✅ FIXED |

---

## Critical Environment Variables Required on Render

### Backend-Node (Render)
```
PORT=5000
JWT_SECRET=<strong-random-secret-min-32-chars>
ML_SERVICE_URL=https://healthpredicai-main.onrender.com
DB_URI=mongodb+srv://...
ALLOWED_ORIGINS=https://health-predict-ai-two.vercel.app
```

### ML Service (Render)
```
PORT=5001
GEMINI_API_KEY=<valid-gemini-api-key>
GEMINI_MODEL=gemini-1.5-flash
DB_URI=mongodb+srv://...
JWT_SECRET=<same-as-backend>
```

### Frontend (Vercel)
```
VITE_API_URL=https://main-backend-55dg.onrender.com
VITE_API_BASE=https://main-backend-55dg.onrender.com
```
