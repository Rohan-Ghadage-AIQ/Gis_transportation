# 🐳 Docker Setup Guide — GIS Transportation

> **One command to run everything.** No database setup, no Python/Node install, no pgAdmin.

---

## ✅ Prerequisites

You only need **one thing** installed:

### Docker Desktop
1. Download from: [https://www.docker.com/products/docker-desktop/](https://www.docker.com/products/docker-desktop/)
2. Install it (follow the installer prompts)
3. **Restart your computer** after installation
4. Open Docker Desktop and make sure it says **"Docker is running"** (green icon in system tray)

> 💡 **Windows users**: Docker Desktop requires WSL 2. The installer will guide you through enabling it.

---

## 📦 Setup (One-Time)

### Step 1: Download the Database Backup

Download the database file from teams chat:

- File name: `routing_backup.backup` (~602 MB)
- Save it in the **project root folder** (same folder as `docker-compose.yml`)

Your folder should look like this:
```
Gis_transportation/
├── docker-compose.yml        ← this file
├── routing_backup.backup     ← database file goes HERE
├── backend/
├── frontend/
├── db/
└── ...
```

### Step 2: Start Everything

Open a terminal (Command Prompt or PowerShell) in the project folder and run:

```bash
docker-compose up --build
```

**First time will take 15-25 minutes** because it:
1. Downloads base images (~2 GB)
2. Installs Python & Node dependencies
3. Restores the database from the backup file

You'll see progress in the terminal. Wait until you see:
```
gis_db       | 🚀 Database is ready for the GIS Transportation application!
gis_backend  | 🚀 BACKEND STARTING - VERSION 4 (ROBUST PARSING)
gis_backend  | ✓ Database tables initialized
```

### Step 3: Open the Application

Open your browser and go to:

| Page | URL |
|------|-----|
| **🌐 Application** | [http://localhost](http://localhost) |
| **📡 API Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) |

---

## 🔄 Daily Usage

### Start the application:
```bash
docker-compose up
```
(No `--build` needed after the first time — starts in ~30 seconds)

### Stop the application:
Press `Ctrl + C` in the terminal, or run:
```bash
docker-compose down
```

### Run in background (no terminal window):
```bash
docker-compose up -d
```
To stop: `docker-compose down`

---

## 🔧 Troubleshooting

### "Port 80 is already in use"
Another application is using port 80. Either:
- Close the other application (e.g., IIS, Skype, Apache)
- Or change the port in `docker-compose.yml`: replace `"80:80"` with `"3000:80"`, then open `http://localhost:3000`

### "Port 5432 is already in use"
You have a local PostgreSQL running. Either:
- Stop it: `net stop postgresql-x64-16` (in Admin PowerShell)
- Or change the port in `docker-compose.yml`: replace `"5432:5432"` with `"5433:5432"`

### Database seems empty / routes don't compute
The backup may not have restored. Run:
```bash
docker-compose down -v
docker-compose up --build
```
The `-v` flag removes the old database volume, forcing a fresh restore.

### "Docker is not running"
Open Docker Desktop and wait for it to show "Docker is running".

### Application is slow on first startup
This is normal! The database restore processes ~600 MB of road network data. Subsequent starts are fast (~30 seconds).

---

## 🗑️ Clean Uninstall

To remove everything Docker created:
```bash
docker-compose down -v --rmi all
```
This removes containers, database data, and built images.
