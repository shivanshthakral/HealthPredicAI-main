const express = require('express');
const router = express.Router();
const axios = require('axios');
const FormData = require('form-data');
const multer = require('multer');

// Configure multer for file uploads
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 25 * 1024 * 1024 } });

const ML_URL = process.env.ML_SERVICE_URL || 'https://healthpredicai-main.onrender.com';

// ── Timeouts ──────────────────────────────────────────────────────────────────
const PREDICT_TIMEOUT  = 30_000;  // 30s — ML model inference
const CHAT_TIMEOUT     = 30_000;  // 30s — Gemini / GPT call
const OCR_TIMEOUT      = 60_000;  // 60s — vision OCR call
const REPORT_TIMEOUT   = 90_000;  // 90s — report analysis
const GENERAL_TIMEOUT  = 30_000;  // 30s — all other ML calls

// ── Centralized ML Service Error Handler ─────────────────────────────────────
const handleMLError = (error, res, fallbackMessage) => {
    const reqId = res.req?.requestId || 'unknown';
    let rawError = error.response?.data || error.message;
    
    console.log("--- ML Service Error Details ---");
    console.log("Current ML_SERVICE_URL =", ML_URL);
    console.log("Actual request URL =", error.config?.url || 'unknown');
    if (error.response) {
        console.log("Response status code =", error.response.status);
        const snippet = typeof error.response.data === 'string'
            ? error.response.data
            : JSON.stringify(error.response.data);
        console.log("Response body snippet (first 200 chars):", snippet.slice(0, 200));
    } else {
        console.log("No response received. Error message:", error.message);
    }
    console.log("--------------------------------");

    console.error(`[AI Error] [${reqId}] ${fallbackMessage}:`, rawError);

    // Check if the response contains HTML (routing mismatch / 404 page)
    if (typeof rawError === 'string' && (rawError.trim().startsWith('<') || rawError.includes('<!DOCTYPE') || rawError.includes('Cannot POST'))) {
        rawError = `ML Service returned an invalid response (HTML). Verify ML_SERVICE_URL env var points to the Flask ML Service, not the Node backend.`;
    }

    if (error.code === 'ECONNABORTED' || error.message?.includes('timeout')) {
        return res.status(504).json({
            error: 'ML Service timed out. The service may be waking up from sleep (Render free tier). Please retry in 30 seconds.',
            retry: true,
        });
    }

    if (error.code === 'ECONNREFUSED' || error.code === 'ENOTFOUND') {
        return res.status(503).json({
            error: 'ML Service is unreachable. Check ML_SERVICE_URL environment variable.',
            ml_url: ML_URL,
        });
    }

    res.status(error.response?.status || 500).json({
        error: rawError || fallbackMessage,
    });
};

// ── Proxy helper with configurable timeout ────────────────────────────────────
const proxyRequest = async (method, url, data, res, headers = {}, timeout = GENERAL_TIMEOUT) => {
    try {
        const response = await axios({
            method,
            url: `${ML_URL}${url}`,
            data,
            headers: { 'Content-Type': 'application/json', ...headers },
            timeout,
        });
        res.json(response.data);
    } catch (error) {
        handleMLError(error, res, 'AI Service Unavailable');
    }
};

const forwardImageToOcr = async (file, res) => {
    try {
        if (!file) return res.status(400).json({ error: 'No file uploaded' });
        const formData = new FormData();
        formData.append('file', file.buffer, {
            filename: file.originalname || 'prescription.png',
            contentType: file.mimetype || 'image/png',
        });

        const response = await axios.post(
            `${ML_URL}/ocr`,
            formData,
            {
                headers: { ...formData.getHeaders() },
                timeout: OCR_TIMEOUT,
                maxContentLength: 25 * 1024 * 1024,
                maxBodyLength: 25 * 1024 * 1024,
            }
        );
        res.json(response.data);
    } catch (error) {
        handleMLError(error, res, 'ML Service OCR Failed');
    }
};

// ── Predict Disease ───────────────────────────────────────────────────────────
router.post('/predict', async (req, res) => {
    try {
        const response = await axios.post(
            `${ML_URL}/predict`,
            req.body,
            { timeout: PREDICT_TIMEOUT }
        );
        res.json(response.data);
    } catch (error) {
        handleMLError(error, res, 'Prediction Service Failed');
    }
});

// ── Chat with AI ──────────────────────────────────────────────────────────────
router.post('/chat', async (req, res) => {
    try {
        console.log("ML_URL =", ML_URL);
        const response = await axios.post(
            `${ML_URL}/chat`,
            req.body,
            { timeout: CHAT_TIMEOUT }
        );
        res.json(response.data);
    } catch (error) {
        handleMLError(error, res, 'Chat Service Failed');
    }
});

// ── OCR Prescription ──────────────────────────────────────────────────────────
router.post('/ocr', upload.single('file'), async (req, res) => {
    try {
        if (!req.file) return res.status(400).json({ error: 'No file uploaded' });
        const formData = new FormData();
        formData.append('file', req.file.buffer, {
            filename: req.file.originalname || 'prescription.png',
            contentType: req.file.mimetype || 'image/png',
        });

        const response = await axios.post(
            `${ML_URL}/ocr`,
            formData,
            {
                headers: { ...formData.getHeaders() },
                timeout: OCR_TIMEOUT,
                maxContentLength: 25 * 1024 * 1024,
                maxBodyLength: 25 * 1024 * 1024,
            }
        );
        res.json(response.data);
    } catch (error) {
        handleMLError(error, res, 'OCR Service Failed');
    }
});

// ── Prescription (canonical, accepts `image` OR `file`) ──────────────────────
router.post('/prescription', upload.any(), (req, res) => {
    const file = (req.files && req.files[0]) || req.file;
    return forwardImageToOcr(file, res);
});

// ── Prescription Extract ──────────────────────────────────────────────────────
router.post('/prescription/extract', upload.any(), async (req, res) => {
    try {
        const uploaded = (req.files && req.files[0]) || req.file;
        if (uploaded) {
            return forwardImageToOcr(uploaded, res);
        }

        const { base64 } = req.body || {};
        if (!base64) {
            return res.status(400).json({
                error: 'No image data provided. Send multipart `image`/`file` OR JSON {"base64":"..."}.',
            });
        }

        const matches = base64.match(/^data:(.+);base64,(.+)$/);
        const mimeType = matches ? matches[1] : 'image/png';
        const rawBase64 = matches ? matches[2] : base64;
        const buffer = Buffer.from(rawBase64, 'base64');
        const ext = mimeType.includes('jpeg') || mimeType.includes('jpg') ? 'jpg' : 'png';

        return forwardImageToOcr(
            { buffer, originalname: `prescription.${ext}`, mimetype: mimeType },
            res,
        );
    } catch (error) {
        handleMLError(error, res, 'Prescription extraction service unavailable');
    }
});

// ── Medical Report Analyzer ───────────────────────────────────────────────────
router.post('/analyze-report', upload.any(), async (req, res) => {
    try {
        const gender = (req.body && req.body.gender) || 'female';
        const uploaded = (req.files && req.files[0]) || req.file;

        if (uploaded) {
            const formData = new FormData();
            formData.append('file', uploaded.buffer, {
                filename: uploaded.originalname || 'report.png',
                contentType: uploaded.mimetype || 'image/png',
            });
            formData.append('gender', gender);

            const response = await axios.post(`${ML_URL}/analyze-report`, formData, {
                headers: { ...formData.getHeaders() },
                maxContentLength: 25 * 1024 * 1024,
                maxBodyLength: 25 * 1024 * 1024,
                timeout: REPORT_TIMEOUT,
            });
            return res.json(response.data);
        }

        const body = req.body || {};
        if (body.base64) {
            const matches = body.base64.match(/^data:(.+);base64,(.+)$/);
            const mimeType = matches ? matches[1] : 'image/png';
            const rawBase64 = matches ? matches[2] : body.base64;
            const buffer = Buffer.from(rawBase64, 'base64');
            const ext = mimeType.includes('pdf') ? 'pdf'
                : (mimeType.includes('jpeg') || mimeType.includes('jpg')) ? 'jpg' : 'png';

            const formData = new FormData();
            formData.append('file', buffer, { filename: `report.${ext}`, contentType: mimeType });
            formData.append('gender', gender);

            const response = await axios.post(`${ML_URL}/analyze-report`, formData, {
                headers: { ...formData.getHeaders() },
                timeout: REPORT_TIMEOUT,
                maxContentLength: 25 * 1024 * 1024,
                maxBodyLength: 25 * 1024 * 1024,
            });
            return res.json(response.data);
        }

        if (body.tests) {
            const response = await axios.post(`${ML_URL}/analyze-report`, body, {
                headers: { 'Content-Type': 'application/json' },
                timeout: REPORT_TIMEOUT,
            });
            return res.json(response.data);
        }

        return res.status(400).json({
            error: 'Provide multipart `file`/`image`, or JSON {"tests":[...]} for manual values, or {"base64":"..."} for an image.',
        });
    } catch (error) {
        handleMLError(error, res, 'Report analysis service unavailable');
    }
});

// ── Recommend specialist ──────────────────────────────────────────────────────
router.post('/recommend-specialist', async (req, res) => {
    await proxyRequest('post', '/recommend-specialist', req.body, res, {}, GENERAL_TIMEOUT);
});

// ── Reference ranges ──────────────────────────────────────────────────────────
router.get('/reference-ranges', async (req, res) => {
    try {
        const response = await axios.get(`${ML_URL}/reference-ranges`, { timeout: 15_000 });
        res.json(response.data);
    } catch (error) {
        handleMLError(error, res, 'Reference range service unavailable');
    }
});

module.exports = router;
