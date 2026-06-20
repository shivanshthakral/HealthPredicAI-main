# 🌐 Live Production Deployment Guide for HealthPredict AI

This guide details the complete process for deploying the **HealthPredict AI** application live in production.

HealthPredict AI is built on a **three-tier architecture**:
1. **Frontend**: Vite + React + Tailwind CSS (Static Asset Site)
2. **Node Backend**: Express API Server (LowDB local storage)
3. **ML Service**: Python Flask Microservice (MongoDB + AI APIs)

We recommend using **Vercel** for the Frontend and **Render** (or **Railway**) for the backends.

---

## 🗺️ System Architecture in Production

```
+------------------------------------+
|         Browser Client             |
+------------------------------------+
                  |
                  | (HTTPS)
                  v
+------------------------------------+
|      Frontend (Vercel)             |
+------------------------------------+
                  |
                  | (API Requests)
                  v
+------------------------------------+
|     Node.js API (Render)           | <=== [Persistent Disk Mount (LowDB)]
+------------------------------------+
                  |
                  | (Proxy Calls)
                  v
+------------------------------------+
|    Python Flask ML (Render)        |
+------------------------------------+
        |                    |
        v                    v
  [MongoDB Atlas]       [Gemini API]
```

---

## 📦 Step 1: Deploying the Flask ML Service (Python)
Since the Node API depends on the Flask ML Service, the ML service **must be deployed first**.

### Recommended Hosting: **Render** (Web Service) or **Railway**
1. **GitHub Connection**: Sync your repository.
2. **Root Directory**: `ml_service`
3. **Environment**: `Python 3`
4. **Build Command**: 
   ```bash
   pip install -r requirements.txt
   ```
5. **Start Command**:
   ```bash
   gunicorn app:app --bind 0.0.0.0:$PORT
   ```

### Environment Variables
Configure these variables in your dashboard:
| Key | Value / Example | Purpose |
| :--- | :--- | :--- |
| `PORT` | `5001` | Server listening port |
| `DB_URI` | `mongodb+srv://...` | MongoDB database connection |
| `JWT_SECRET` | `your-secure-random-32char-secret` | Authentication token signing |
| `GEMINI_API_KEY` | `AIzaSy...` | Gemini API key (optional; if missing, falls back to optimized `g4f` engine) |

---

## ⚡ Step 2: Deploying the Node.js API Backend
The Express API acts as the main gateway and coordinates authentication, orders, database records, and proxies OCR/chatbot commands to the Flask ML Service.

### Recommended Hosting: **Render** (Web Service) or **Railway**
1. **GitHub Connection**: Sync your repository.
2. **Root Directory**: `backend-node`
3. **Environment**: `Node`
4. **Build Command**:
   ```bash
   npm install
   ```
5. **Start Command**:
   ```bash
   node server.js
   ```

### Environment Variables
| Key | Value / Example | Purpose |
| :--- | :--- | :--- |
| `PORT` | `5000` | Node.js listening port |
| `NODE_ENV` | `production` | Enables Express production optimizations |
| `JWT_SECRET` | `your-secure-random-32char-secret` | Must match the `JWT_SECRET` used in the ML Service |
| `ML_SERVICE_URL` | `https://your-ml-service.onrender.com` | URL of the live Flask service deployed in **Step 1** (no trailing slash) |
| `ALLOWED_ORIGINS` | `https://your-app.vercel.app` | URL of the live Frontend site deployed in **Step 3** |

### 💾 CRITICAL: Persistent Data Disk Mount (LowDB)
Because the Node API uses **LowDB** (storing users, doctor bookings, and orders in local JSON files inside `data/`), standard ephemeral cloud filesystems will wipe out your database on every server restart or redeploy.

To make database data permanent, you **must mount a Persistent Volume**:
- **Mount Path**: `/opt/render/project/src/backend-node/data`
- **Size**: `1 GB` (free/basic volume is plenty for text/JSON storage)

---

## 🎨 Step 3: Deploying the React Frontend
Once both backends are live, build and deploy the React frontend pointing to your live Node.js API.

### Recommended Hosting: **Vercel** or **Netlify**
1. **Create Project**: Connect your GitHub repository.
2. **Root Directory**: Set to `frontend`
3. **Framework Preset**: `Vite`
4. **Build Command**:
   ```bash
   npm run build
   ```
5. **Output Directory**: `dist`

### Environment Variables (Build Time)
Vite embeds these variables directly into your static JS bundle during build. They must be set in your Vercel Dashboard before compiling:
| Key | Value | Purpose |
| :--- | :--- | :--- |
| `VITE_API_URL` | `https://your-node-api.onrender.com` | Live Node API URL deployed in **Step 2** (without trailing slash) |
| `VITE_API_BASE` | `https://your-node-api.onrender.com` | Duplicate parameter for endpoint compatibility |

---

## 🚦 Step 4: Verification Checklist

1. **Verify CORS**:
   - Inspect browser console logs on your live Vercel site. If you see CORS errors, double-check that `ALLOWED_ORIGINS` in your Node Backend includes your exact Vercel URL (e.g. `https://health-predict-ai.vercel.app`).
2. **Verify User Database**:
   - Register a new patient account, log out, and log back in to ensure database persistence works.
3. **Verify Chatbot fallbacks**:
   - Open the **AI Copilot** chatbot and send a query in Hindi/Tamil (or change language dropdown). It should reply dynamically in 2–3s using the fallback routing configuration.
4. **Verify Medical OCR & Analyzer**:
   - Upload a sample prescription or lab report image. Verify that the files are proxied from the Node API to the Flask ML Service, analyzed, and return clean JSON to the frontend.
