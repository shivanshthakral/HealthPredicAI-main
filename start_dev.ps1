Write-Host "Launching HealthPredict AI..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend-node; npm start"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd ml_service; python app.py"
