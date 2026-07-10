# Quick Start Guide

## 🚀 Get Started in 5 Minutes

### 1. Install Dependencies

**Backend:**
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

**Frontend:**
```bash
cd frontend
npm install
```

### 2. Set Up Environment

Copy `.env.example` to `.env` in the `backend/` directory and add your NVIDIA API key:

```bash
cd backend
copy .env.example .env  # Windows
# cp .env.example .env  # macOS/Linux
```

Edit `.env` and set:
```
NVIDIA_API_KEY=your_actual_nvidia_api_key
```
(Get one free at https://build.nvidia.com/settings/api-keys)

### 3. Start the Servers

**Terminal 1 - Backend:**
```bash
cd backend
.venv\Scripts\activate
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

**Terminal 2 - Frontend:**
```bash
cd frontend
npm run dev
```

### 4. Access the Application

Open your browser to:
- **Frontend**: http://localhost:3000
- **API Docs**: http://localhost:8000/docs

### 5. Create an Account

1. Go to http://localhost:3000/signup
2. Fill in your details (password must be 8+ chars with uppercase, lowercase, and number)
3. Click "Create Account"
4. Login at http://localhost:3000/login

### 6. Process Your First Document

1. Go to "New Job" from the dashboard
2. Upload a PDF or text file
3. Select processing mode (Balanced, Eco, or Performance)
4. Watch the real-time progress
5. View results and carbon savings!

---

## 🔧 Troubleshooting

**Backend won't start?**
- Make sure virtual environment is activated
- Check that all dependencies are installed: `pip install -r requirements.txt`
- Verify Python version is 3.10+

**Frontend errors?**
- Clear node_modules and reinstall: `rm -rf node_modules && npm install`
- Check Node.js version is 18+

**Authentication not working?**
- Restart the backend server after installing auth dependencies
- Check that `python-jose[cryptography]` and `passlib[bcrypt]` are installed

**Models not loading?**
- Verify `NVIDIA_API_KEY` is set correctly in `backend/.env`
- Confirm the key works at https://build.nvidia.com

---

## 📖 Next Steps

- Read the full [README.md](README.md) for detailed documentation
- Check the [API Documentation](http://localhost:8000/docs)
- Explore the dashboard to see carbon savings metrics
- Try RAG queries on processed documents

---

**Need Help?** Check the [Known Issues](README.md#known-issues-and-limitations) section in the main README.
