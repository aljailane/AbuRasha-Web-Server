# AbuRasha Web Server

AbuRasha Web Server is a professional, portable local development server environment for Windows. It provides a simple and high-performance alternative to traditional local stacks, featuring a custom GUI Control Panel and a web-based administration panel designed for seamless local development.

## 🚀 Features

- **Portable Stack:** Runs out of the box without installation. Includes pre-configured runtimes for:
  - **Apache Web Server** (multiple versions)
  - **PHP Runtime** (multiple versions)
  - **MariaDB Database** (MySQL compatible)
- **Interactive GUI Manager:** A modern desktop dashboard built using Python and CustomTkinter to start/stop services, download additional components, and monitor system states.
- **AbuRasha Web Panel (`adminserver.php`):** A web-based admin control panel allowing developers to:
  - Switch PHP runtimes for projects on the fly.
  - Set independent PHP versions for phpMyAdmin.
  - Switch Apache and MariaDB daemon versions.
  - Enable/disable the SQLite3 PDO extension with one click.
  - View real-time Apache and PHP logs with terminal-style viewer and clearing utilities.
  - Perform instant service reboots with a smart loading overlay (intercepts connections and reloads automatically once the server is back online).

## 🛠️ Technology Stack

- **Backend Logic:** PHP & Python
- **GUI Desktop App:** Python (CustomTkinter)
- **Web Frontend:** HTML, CSS, JavaScript (Vanilla implementation matching classic web panel styling)

## 📁 Repository Structure

```text
├── bin/                 # Component runtimes (Apache, PHP, MariaDB)
├── config/              # Configuration templates & active server settings
├── www/                 # Server web root containing index.php & adminserver.php
├── manager.py           # GUI Desktop Control Panel source code
├── AbuRashaServ.exe     # Compiled Windows Desktop executable manager
└── start.bat            # Quick launcher script
```

## ⚙️ How to Use

1. Clone or download the repository into a directory on your Windows PC.
2. Launch `start.bat` or run `AbuRashaServ.exe` to open the Control Panel.
3. Start the services (Apache, MariaDB) from the desktop dashboard.
4. Open `http://localhost:8080` in your web browser to access the Server Index.
5. Click **AbuRasha Web Panel** to configure runtimes or view error logs.

## 📄 License

This project is open-source and available under the MIT License.
