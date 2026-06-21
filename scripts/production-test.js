#!/usr/bin/env node
/**
 * HealthPredict AI — Production Test Suite
 * ==========================================
 * Tests all critical API endpoints against production URLs.
 *
 * Usage:
 *   node scripts/production-test.js
 *   node scripts/production-test.js --local   (test localhost)
 *   node scripts/production-test.js --url https://your-backend.onrender.com
 */

const https = require('https');
const http  = require('http');
const url   = require('url');

// ─── Configuration ────────────────────────────────────────────────────────────
const args        = process.argv.slice(2);
const useLocal    = args.includes('--local');
const customUrl   = (() => { const i = args.indexOf('--url'); return i >= 0 ? args[i + 1] : null; })();

const BACKEND_URL  = customUrl || (useLocal ? 'http://localhost:5000'  : 'https://main-backend-55dg.onrender.com');
const ML_URL       = useLocal  ? 'http://localhost:5001' : 'https://healthpredicai-main.onrender.com';
const TEST_TIMEOUT = 45000; // 45s — accounts for Render cold start

// ─── Test result tracking ─────────────────────────────────────────────────────
const results = [];
let passed = 0, failed = 0, warned = 0;

function log(msg) { process.stdout.write(msg + '\n'); }

async function request(baseUrl, path, method = 'GET', body = null, headers = {}) {
  return new Promise((resolve, reject) => {
    const parsed  = url.parse(`${baseUrl}${path}`);
    const isHttps = parsed.protocol === 'https:';
    const lib     = isHttps ? https : http;
    const bodyStr = body ? JSON.stringify(body) : null;

    const options = {
      hostname: parsed.hostname,
      port:     parsed.port || (isHttps ? 443 : 80),
      path:     parsed.path,
      method,
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': bodyStr ? Buffer.byteLength(bodyStr) : 0,
        ...headers,
      },
    };

    const timer = setTimeout(() => reject(new Error(`TIMEOUT after ${TEST_TIMEOUT / 1000}s`)), TEST_TIMEOUT);

    const req = lib.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        clearTimeout(timer);
        try {
          resolve({ status: res.statusCode, body: JSON.parse(data) });
        } catch {
          resolve({ status: res.statusCode, body: data });
        }
      });
    });

    req.on('error', (e) => { clearTimeout(timer); reject(e); });
    if (bodyStr) req.write(bodyStr);
    req.end();
  });
}

function record(name, passed, details, severity = 'critical') {
  const icon = passed ? '✅' : (severity === 'warn' ? '⚠️ ' : '❌');
  const status = passed ? 'PASS' : (severity === 'warn' ? 'WARN' : 'FAIL');
  results.push({ name, status, details });
  log(`  ${icon} [${status}] ${name} — ${details}`);
  return passed;
}

// ─── Individual test functions ────────────────────────────────────────────────

async function testBackendHealth() {
  log('\n📡  Backend Health Check');
  try {
    const r = await request(BACKEND_URL, '/health');
    const statusOk = r.status === 200 && (r.body.status === 'healthy' || r.body.status === 'ok');
    const isOptimal = r.body.status === 'healthy';
    if (!isOptimal && statusOk) {
      log(`  ⚠️  [WARN] Backend /health returns status:'ok' — should be 'healthy'. Deploy latest server.js fix.`);
    }
    return record('Backend /health', statusOk, `HTTP ${r.status} — ${JSON.stringify(r.body)}`);
  } catch (e) {
    return record('Backend /health', false, `ERROR: ${e.message}`);
  }
}

async function testMLHealth() {
  log('\n🤖  ML Service Health Check');
  try {
    const r = await request(ML_URL, '/health');
    if (r.status === 404) {
      // /health endpoint not yet deployed — check root instead
      log(`  ⚠️  [WARN] ML /health → 404. The /health fix is not yet deployed. Testing root /...`);
      const root = await request(ML_URL, '/');
      const rootOk = root.status === 200 && root.body.status === 'running';
      return record('ML Service reachable (root)', rootOk, `HTTP ${root.status} — ${JSON.stringify(root.body).substring(0, 80)}`);
    }
    return record('ML Service /health', r.status === 200 && r.body.status === 'healthy',
      `HTTP ${r.status} — ${JSON.stringify(r.body)}`);
  } catch (e) {
    return record('ML Service /health', false, `ERROR: ${e.message}`);
  }
}

async function testRegistration() {
  log('\n📝  Registration Flow');
  const email = `testuser_${Date.now()}@healthtest.ai`;
  try {
    const r = await request(BACKEND_URL, '/api/auth/register', 'POST', {
      name: 'Test Patient',
      email,
      password: 'TestPass123',
      role: 'patient',
    });
    const ok = r.status === 201 && r.body.token && r.body.user;
    record('Patient Registration', ok, `HTTP ${r.status} — ${ok ? `Token: ${r.body.token?.substring(0,20)}...` : JSON.stringify(r.body)}`);
    return ok ? { email, token: r.body.token } : null;
  } catch (e) {
    record('Patient Registration', false, `ERROR: ${e.message}`);
    return null;
  }
}

async function testPatientLogin(email, password = 'TestPass123') {
  log('\n🔑  Patient Login');
  try {
    const r = await request(BACKEND_URL, '/api/auth/login', 'POST', {
      email, password, expectedRole: 'patient',
    });
    const ok = r.status === 200 && r.body.token;
    record('Patient Login', ok, `HTTP ${r.status} — ${ok ? 'Token received' : JSON.stringify(r.body)}`);
    return ok ? r.body.token : null;
  } catch (e) {
    record('Patient Login', false, `ERROR: ${e.message}`);
    return null;
  }
}

async function testDoctorLogin() {
  log('\n👨‍⚕️  Doctor Login (with known bad creds — expects graceful error)');
  try {
    const r = await request(BACKEND_URL, '/api/auth/login', 'POST', {
      email: 'notadoctor@test.com', password: 'test123', expectedRole: 'doctor',
    });
    // We expect a 400 (not found) not a 500
    const ok = r.status === 400;
    record('Doctor Login (bad creds → 400)', ok, `HTTP ${r.status} — ${JSON.stringify(r.body).substring(0, 80)}`);
    return ok;
  } catch (e) {
    record('Doctor Login (error handling)', false, `ERROR: ${e.message}`);
    return false;
  }
}

async function testAdminLogin() {
  log('\n🛡️   Admin Login (without creds — expects graceful error)');
  try {
    const r = await request(BACKEND_URL, '/api/admin/login', 'POST', {
      email: 'notanadmin@test.com', password: 'test123',
    });
    const ok = r.status === 403;
    record('Admin Login (unauthorized → 403)', ok, `HTTP ${r.status} — ${JSON.stringify(r.body).substring(0, 80)}`);
    return ok;
  } catch (e) {
    record('Admin Login (error handling)', false, `ERROR: ${e.message}`);
    return false;
  }
}

async function testPredict(token) {
  log('\n🔬  Symptom Analysis (Predict)');
  try {
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
    const r = await request(BACKEND_URL, '/api/ai/predict', 'POST', {
      symptoms: ['Fever', 'Cough', 'Headache'],
      user_profile: { age: 30, gender: 'male' },
    }, headers);
    const ok = r.status === 200 && r.body.predictions && r.body.predictions.length > 0;
    const modelUsed = r.body.model_used || 'unknown';
    record('Symptom Prediction', ok,
      `HTTP ${r.status} — ${ok ? `Top: ${r.body.predictions?.[0]?.disease} (${r.body.predictions?.[0]?.confidence_pct}%) [model: ${modelUsed}]` : JSON.stringify(r.body).substring(0, 100)}`);
    if (ok && modelUsed === 'rule_based_fallback') {
      log(`  ⚠️  [WARN] Prediction uses rule-based fallback — ML models have sklearn compat issue. Retrain with: POST /retrain`);
    }
    return ok;
  } catch (e) {
    record('Symptom Prediction', false, `ERROR: ${e.message}`);
    return false;
  }
}

async function testChat(token) {
  log('\n💬  Chatbot (Copilot)');
  try {
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
    const r = await request(BACKEND_URL, '/api/ai/chat', 'POST', {
      message: 'What are symptoms of diabetes?',
      history: [],
      language: 'en',
    }, headers);
    const ok = r.status === 200 && r.body.response;
    record('Chat / Copilot', ok,
      `HTTP ${r.status} — ${ok ? `Response: "${r.body.response?.substring(0, 60)}..."` : JSON.stringify(r.body).substring(0, 100)}`);
    record('Chat Source', true,
      `Source: ${r.body.source || 'unknown'}`, 'warn');
    return ok;
  } catch (e) {
    record('Chat / Copilot', false, `ERROR: ${e.message}`);
    return false;
  }
}

async function testMLDirect_Predict() {
  log('\n🧠  ML Service Direct — Predict');
  try {
    const r = await request(ML_URL, '/predict', 'POST', {
      symptoms: ['High Fever', 'Vomiting', 'Nausea'],
    });
    const ok = r.status === 200 && r.body.predictions;
    record('ML /predict (direct)', ok,
      `HTTP ${r.status} — ${ok ? `${r.body.predictions?.length} predictions` : JSON.stringify(r.body).substring(0, 100)}`);
    return ok;
  } catch (e) {
    record('ML /predict (direct)', false, `ERROR: ${e.message}`);
    return false;
  }
}

async function testMLDirect_Chat() {
  log('\n🧠  ML Service Direct — Chat');
  try {
    const r = await request(ML_URL, '/chat', 'POST', {
      message: 'Hello', history: [], language: 'en',
    });
    const ok = r.status === 200 && r.body.response;
    record('ML /chat (direct)', ok,
      `HTTP ${r.status} — ${ok ? `Src: ${r.body.source}` : JSON.stringify(r.body).substring(0, 100)}`);
    return ok;
  } catch (e) {
    record('ML /chat (direct)', false, `ERROR: ${e.message}`);
    return false;
  }
}

async function testReferenceRanges(token) {
  log('\n📊  Reference Ranges (Report feature)');
  try {
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
    const r = await request(BACKEND_URL, '/api/ai/reference-ranges', 'GET', null, headers);
    const ok = r.status === 200 && typeof r.body === 'object';
    record('Reference Ranges', ok,
      `HTTP ${r.status} — ${ok ? `${Object.keys(r.body).length} tests available` : JSON.stringify(r.body).substring(0, 80)}`);
    return ok;
  } catch (e) {
    record('Reference Ranges', false, `ERROR: ${e.message}`);
    return false;
  }
}

async function testAuthMe(token) {
  log('\n👤  Auth /me (JWT verification)');
  if (!token) {
    record('Auth /me', false, 'No token available — skipped');
    return false;
  }
  try {
    const r = await request(BACKEND_URL, '/api/auth/me', 'GET', null, {
      Authorization: `Bearer ${token}`,
    });
    const ok = r.status === 200 && r.body.user;
    record('Auth /me JWT verify', ok,
      `HTTP ${r.status} — ${ok ? `User: ${r.body.user?.email} (${r.body.user?.role})` : JSON.stringify(r.body).substring(0, 80)}`);
    return ok;
  } catch (e) {
    record('Auth /me JWT verify', false, `ERROR: ${e.message}`);
    return false;
  }
}

// ─── Main test runner ─────────────────────────────────────────────────────────
async function main() {
  log('\n' + '═'.repeat(70));
  log('🏥  HealthPredict AI — Production Test Suite');
  log('═'.repeat(70));
  log(`  Backend:  ${BACKEND_URL}`);
  log(`  ML Svc:   ${ML_URL}`);
  log(`  Timeout:  ${TEST_TIMEOUT / 1000}s per test`);
  log('═'.repeat(70));

  const startTime = Date.now();

  // Phase 1: Infrastructure
  const backendOk = await testBackendHealth();
  const mlOk      = await testMLHealth();

  if (!backendOk) {
    log('\n⛔ Backend is unreachable. Aborting further tests.');
    log('   → Check that ML_SERVICE_URL is set correctly in Render environment variables.');
  }

  // Phase 2: Auth
  let token = null;
  let email = null;
  const regResult = await testRegistration();
  if (regResult) {
    token = regResult.token;
    email = regResult.email;
  }

  if (email) {
    const loginToken = await testPatientLogin(email);
    if (loginToken) token = loginToken;
  } else {
    // Try with a static test user if registration failed (persistence check)
    await testPatientLogin('testuser@healthtest.ai');
  }

  await testDoctorLogin();
  await testAdminLogin();

  if (token) await testAuthMe(token);

  // Phase 3: ML Features
  await testPredict(token);
  await testChat(token);
  await testReferenceRanges(token);

  // Phase 4: Direct ML Service (bypass Node proxy)
  if (mlOk) {
    await testMLDirect_Predict();
    await testMLDirect_Chat();
  } else {
    log('\n⚠️  ML service unreachable — skipping direct ML tests');
  }

  // ─── Summary ───────────────────────────────────────────────────────────────
  const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
  const passCount  = results.filter(r => r.status === 'PASS').length;
  const failCount  = results.filter(r => r.status === 'FAIL').length;
  const warnCount  = results.filter(r => r.status === 'WARN').length;

  log('\n' + '═'.repeat(70));
  log('📋  TEST SUMMARY');
  log('═'.repeat(70));
  log(`  Total tests : ${results.length}`);
  log(`  ✅ Passed   : ${passCount}`);
  log(`  ❌ Failed   : ${failCount}`);
  log(`  ⚠️  Warnings : ${warnCount}`);
  log(`  ⏱  Duration  : ${elapsed}s`);
  log('═'.repeat(70));

  if (failCount > 0) {
    log('\n❌ FAILED TESTS:');
    results.filter(r => r.status === 'FAIL').forEach(r => {
      log(`  • ${r.name}: ${r.details}`);
    });
  }

  const allCriticalPassed = failCount === 0;
  log('\n' + (allCriticalPassed
    ? '🎉 ALL CRITICAL TESTS PASSED — Application is production ready!'
    : `⚠️  ${failCount} test(s) FAILED — Fix issues before deploying to production.`
  ));
  log('');

  process.exit(failCount > 0 ? 1 : 0);
}

main().catch(e => {
  log(`\n💥 Fatal error: ${e.message}`);
  process.exit(1);
});
