@echo off
echo ==============================================
echo  Starting Vehicle Routing Optimization System
echo ==============================================

echo Starting Backend...
start cmd /k "cd backend && python main.py"

echo Starting Frontend...
start cmd /k "cd frontend && npm run dev"

echo.
echo Application is starting! 
echo Frontend will be available at http://localhost:5173
echo Backend API will be available at http://localhost:8000
echo ==============================================
