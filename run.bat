@echo off
echo Starting HealthPredict AI Services...

:: Start Node API Backend
start cmd /k "cd backend-node && npm start"

:: Start Vite Frontend
start cmd /k "cd frontend && npm run dev"

:: Start Python ML Service
start cmd /k "cd ml_service && python app.py"
