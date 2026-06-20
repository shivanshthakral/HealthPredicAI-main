const express = require('express');
const router = express.Router();
const axios = require('axios');
const FormData = require('form-data');
const multer = require('multer');

// Configure multer for file uploads
const upload = multer({ storage: multer.memoryStorage() });

const ML_URL = process.env.ML_SERVICE_URL || 'http://127.0.0.1:5001';

// Centralized ML Service Error Handler
const handleMLError = (error, res, fallbackMessage) => {
    let rawError = error.response?.data || error.message;
    console.error(`AI Service Error:`, rawError);
    
    // Check if the response contains HTML (routing mismatch / server loop / 404 page)
    if (typeof rawError === 'string' && (rawError.trim().startsWith('<') || rawError.includes('<!DOCTYPE') || rawError.includes('Cannot POST'))) {
        rawError = `ML Service returned an invalid response (HTML). Please verify that the ML_SERVICE_URL environment variable in your Node backend's Render settings is pointing to the correct Flask ML Service (port 5001) and not the Node backend itself.`;
    }
    
    // Send structured JSON error to frontend
    res.status(error.response?.status || 500).json({
        error: rawError || fallbackMessage
    });
};

// Proxy helper
const proxyRequest = async (method, url, data, res, headers = {}) => {
    try {
        const response = await axios({
            method,
            url: `${ML_URL}${url}`,
            data,
            headers: { 'Content-Type': 'application/json', ...headers },
            timeout: 60000,
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
            contentType: file.mimetype || 'image/png'
        });
        
        const response = await axios.post(
            `${ML_URL}/ocr`,
            formData,
            { headers: { ...formData.getHeaders() } }
        );
        res.json(response.data);
    } catch (error) {
        handleMLError(error, res, 'ML Service Failed');
    }
};

// Predict Disease
router.post('/predict', async (req, res) => {
  try {
    const response = await axios.post(
      `${ML_URL}/predict`,
      req.body
    );
    res.json(response.data);
  } catch (error) {
    handleMLError(error, res, 'ML Service Failed');
  }
});

// Chat with AI
router.post('/chat', async (req, res) => {
  try {
    const response = await axios.post(
      `${ML_URL}/chat`,
      req.body
    );
    res.json(response.data);
  } catch (error) {
    handleMLError(error, res, 'ML Service Failed');
  }
});

// OCR Prescription
router.post('/ocr', upload.single('file'), async (req, res) => {
  try {
    if (!req.file) return res.status(400).json({ error: 'No file uploaded' });
    const formData = new FormData();
    formData.append('file', req.file.buffer, req.file.originalname || 'prescription.png');
    
    const response = await axios.post(
      `${ML_URL}/ocr`,
      formData,
      { headers: { ...formData.getHeaders() } }
    );
    res.json(response.data);
  } catch (error) {
    handleMLError(error, res, 'ML Service Failed');
  }
});

// Canonical endpoint per product spec (accepts field name `image` OR `file`)
router.post('/prescription', upload.any(), (req, res) => {
    const file = (req.files && req.files[0]) || req.file;
    return forwardImageToOcr(file, res);
});

// Prescription Extract — accepts EITHER multipart (image/file) OR JSON {base64}
router.post('/prescription/extract', upload.any(), async (req, res) => {
    try {
        // Multipart path
        const uploaded = (req.files && req.files[0]) || req.file;
        if (uploaded) {
            return forwardImageToOcr(uploaded, res);
        }

        // JSON base64 path (legacy)
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
            { buffer, originalname: `prescription.${ext}` },
            res,
        );
    } catch (error) {
        handleMLError(error, res, 'Prescription extraction service unavailable');
    }
});

// Medical Report Analyzer — accepts multipart (image/file/PDF) OR JSON tests/base64
router.post('/analyze-report', upload.any(), async (req, res) => {
    try {
        const gender = (req.body && req.body.gender) || 'female';
        const uploaded = (req.files && req.files[0]) || req.file;

        if (uploaded) {
            const formData = new FormData();
            formData.append('file', uploaded.buffer, uploaded.originalname || 'report.png');
            formData.append('gender', gender);

            const response = await axios.post(`${ML_URL}/analyze-report`, formData, {
                headers: { ...formData.getHeaders() },
                maxContentLength: 25 * 1024 * 1024,
                maxBodyLength: 25 * 1024 * 1024,
                timeout: 90_000,
            });
            return res.json(response.data);
        }

        // JSON path: either {tests:[...]} for manual entry, or {base64:"..."} image
        const body = req.body || {};
        if (body.base64) {
            // Translate base64 → multipart for the Python service
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
                timeout: 90_000,
            });
            return res.json(response.data);
        }

        if (body.tests) {
            const response = await axios.post(`${ML_URL}/analyze-report`, body, {
                headers: { 'Content-Type': 'application/json' },
                timeout: 60_000,
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

// Recommend specialist based on disease
router.post('/recommend-specialist', async (req, res) => {
    await proxyRequest('post', '/recommend-specialist', req.body, res);
});

// Reference ranges (passthrough GET)
router.get('/reference-ranges', async (req, res) => {
    try {
        const response = await axios.get(`${ML_URL}/reference-ranges`, { timeout: 15_000 });
        res.json(response.data);
    } catch (error) {
        handleMLError(error, res, 'Reference range service unavailable');
    }
});

module.exports = router;
