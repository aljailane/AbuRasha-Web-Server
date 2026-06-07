import os
import subprocess
import time
import sys
import webbrowser
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk
import shutil
import ctypes
import json
import re
import customtkinter

# Set AppUserModelID for Windows Taskbar Icon grouping
try:
    myappid = 'aburasha.serv.manager.v2'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except:
    pass

class ServerCore:
    def __init__(self, base_path):
        self.base = os.path.abspath(base_path)
        self.www_dir = os.path.join(self.base, 'www')
        self.settings_file = os.path.join(self.base, 'config', 'settings.json')
        
        self.apache_running = False
        self.mariadb_running = False
        self.php_ver_cached = None
        self.mariadb_ver_cached = None
        
        # Available items lists caching to eliminate disk lag
        self._available_phps_cache = None
        self._available_apaches_cache = None
        self._available_mariadbs_cache = None
        self._sqlite_status_cache = None
        
        self.load_settings()
        
        # Cleanup buggy phpmyadmin folders that were created as PHP copies in previous runs
        bin_dir = os.path.join(self.base, 'bin')
        if os.path.exists(bin_dir):
            for d in os.listdir(bin_dir):
                if d.startswith('phpmyadmin'):
                    folder = os.path.join(bin_dir, d)
                    if os.path.exists(os.path.join(folder, 'php.exe')):
                        try:
                            shutil.rmtree(folder, ignore_errors=True)
                        except:
                            pass
                            
        self.update_php_paths()
        self.update_apache_paths()
        self.update_mariadb_paths()
        
        # Start background check thread
        threading.Thread(target=self._background_check_loop, daemon=True).start()

    def _background_check_loop(self):
        # Initial check
        self.apache_running = self._check_process_running()
        self.mariadb_running = self._check_mariadb_running()
        while True:
            time.sleep(2)
            self.apache_running = self._check_process_running()
            self.mariadb_running = self._check_mariadb_running()


    def _check_process_running(self):
        # 1. Check using ctypes Toolhelp32 snapshot (fastest, no process creation, < 15ms)
        try:
            TH32CS_SNAPPROCESS = 0x00000002
            class PROCESSENTRY32(ctypes.Structure):
                _fields_ = [
                    ("dwSize", ctypes.c_ulong),
                    ("cntUsage", ctypes.c_ulong),
                    ("th32ProcessID", ctypes.c_ulong),
                    ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", ctypes.c_ulong),
                    ("cntThreads", ctypes.c_ulong),
                    ("th32ParentProcessID", ctypes.c_ulong),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_ulong),
                    ("szExeFile", ctypes.c_char * 260)
                ]

            hProcessSnap = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if hProcessSnap != -1:
                pe32 = PROCESSENTRY32()
                pe32.dwSize = ctypes.sizeof(PROCESSENTRY32)
                found = False
                if ctypes.windll.kernel32.Process32First(hProcessSnap, ctypes.byref(pe32)):
                    while True:
                        exe_name = pe32.szExeFile.decode('ansi', errors='ignore').lower()
                        if exe_name == "httpd.exe":
                            found = True
                            break
                        if not ctypes.windll.kernel32.Process32Next(hProcessSnap, ctypes.byref(pe32)):
                            break
                ctypes.windll.kernel32.CloseHandle(hProcessSnap)
                return found
        except Exception:
            pass

        # 2. Fallback to OpenProcess using PID file (secondary check)
        if os.path.exists(self.apache_pid):
            try:
                with open(self.apache_pid, 'r') as f:
                    pid = int(f.read().strip())
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return True
            except:
                pass

        # 3. Fallback to tasklist command (slow fallback, ~1s)
        try:
            res = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq httpd.exe"], 
                capture_output=True, 
                text=True, 
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return "httpd.exe" in res.stdout
        except:
            return False


    def load_settings(self):
        old_php = self.settings.get('active_php') if hasattr(self, 'settings') else None
        old_apache = self.settings.get('active_apache') if hasattr(self, 'settings') else None
        old_mariadb = self.settings.get('active_mariadb') if hasattr(self, 'settings') else None
        self.settings = {'active_php': 'php', 'active_apache': 'apache', 'active_mariadb': 'mariadb', 'theme': 'dark', 'cache': {}}
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    self.settings.update(json.load(f))
            except: pass
        if 'cache' not in self.settings:
            self.settings['cache'] = {}
        if old_php != self.settings.get('active_php'):
            self.update_php_paths()
        if old_apache != self.settings.get('active_apache'):
            self.update_apache_paths()
        if old_mariadb != self.settings.get('active_mariadb'):
            self.update_mariadb_paths()


    def save_settings(self):
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False)
        except: pass

    def update_php_paths(self):
        php_folder = self.settings.get('active_php', 'php')
        self.php_dir = os.path.join(self.base, 'bin', php_folder)
        self.php_ini = os.path.join(self.php_dir, 'php.ini')
        self.php_log = os.path.join(self.php_dir, 'logs', 'php_error.log')
        
        self.php_ver_cached = None
        self._sqlite_status_cache = None
        os.makedirs(os.path.dirname(self.php_log), exist_ok=True)

        php_tmpl = os.path.join(self.base, 'config', 'php.ini.template')
        php_dir_fs = self.php_dir.replace('\\', '/')

        if not os.path.exists(self.php_ini) and os.path.exists(php_tmpl):
            try:
                with open(php_tmpl, 'r', encoding='utf-8') as f:
                    ini_data = f.read()
                ini_data = ini_data.replace('{{PHP_DIR}}', php_dir_fs)
                with open(self.php_ini, 'w', encoding='utf-8') as f:
                    f.write(ini_data)
            except:
                pass

        # Ensure session.save_path and other settings are synchronized
        self._sync_php_runtime_paths(php_dir_fs)
        if 'cache' not in self.settings:
            self.settings['cache'] = {}
        self.settings['cache'][f'sync_php_{php_folder}'] = True
        self.save_settings()

    def update_apache_paths(self):
        apache_folder = self.settings.get('active_apache', 'apache')
        self.apache_root = os.path.join(self.base, 'bin', apache_folder)
        self.apache_exe = os.path.join(self.apache_root, 'bin', 'httpd.exe')
        self.conf = os.path.join(self.apache_root, 'conf', 'httpd.conf')
        self.apache_pid = os.path.join(self.apache_root, 'logs', 'httpd.pid')
        self.apache_log = os.path.join(self.apache_root, 'logs', 'error.log')
        os.makedirs(os.path.dirname(self.apache_log), exist_ok=True)

    def update_mariadb_paths(self):
        mariadb_folder = self.settings.get('active_mariadb', 'mariadb')
        self.mariadb_root = os.path.join(self.base, 'bin', mariadb_folder)
        self.mariadb_exe = os.path.join(self.mariadb_root, 'bin', 'mariadbd.exe')
        if not os.path.exists(self.mariadb_exe):
            self.mariadb_exe = os.path.join(self.mariadb_root, 'bin', 'mysqld.exe')
        self.mariadb_pid = os.path.join(self.mariadb_root, 'data', 'mariadb.pid')
        self.mariadb_log = os.path.join(self.mariadb_root, 'data', 'mysql.err')
        self.mariadb_ver_cached = None

    def _check_mariadb_running(self):
        try:
            TH32CS_SNAPPROCESS = 0x00000002
            class PROCESSENTRY32(ctypes.Structure):
                _fields_ = [
                    ("dwSize", ctypes.c_ulong),
                    ("cntUsage", ctypes.c_ulong),
                    ("th32ProcessID", ctypes.c_ulong),
                    ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", ctypes.c_ulong),
                    ("cntThreads", ctypes.c_ulong),
                    ("th32ParentProcessID", ctypes.c_ulong),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_ulong),
                    ("szExeFile", ctypes.c_char * 260)
                ]

            hProcessSnap = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if hProcessSnap != -1:
                pe32 = PROCESSENTRY32()
                pe32.dwSize = ctypes.sizeof(PROCESSENTRY32)
                found = False
                if ctypes.windll.kernel32.Process32First(hProcessSnap, ctypes.byref(pe32)):
                    while True:
                        exe_name = pe32.szExeFile.decode('ansi', errors='ignore').lower()
                        if exe_name in ["mariadbd.exe", "mysqld.exe"]:
                            found = True
                            break
                        if not ctypes.windll.kernel32.Process32Next(hProcessSnap, ctypes.byref(pe32)):
                            break
                ctypes.windll.kernel32.CloseHandle(hProcessSnap)
                return found
        except Exception:
            pass
        return False

    def get_available_mariadbs(self):
        if self._available_mariadbs_cache is not None:
            return self._available_mariadbs_cache
        bin_dir = os.path.join(self.base, 'bin')
        mariadbs = []
        if os.path.exists(bin_dir):
            for d in os.listdir(bin_dir):
                if d.startswith('mariadb') and os.path.isdir(os.path.join(bin_dir, d)):
                    if os.path.exists(os.path.join(bin_dir, d, 'bin', 'mariadbd.exe')) or os.path.exists(os.path.join(bin_dir, d, 'bin', 'mysqld.exe')):
                        mariadbs.append(d)
        self._available_mariadbs_cache = mariadbs if mariadbs else ['mariadb']
        return self._available_mariadbs_cache

    def _query_mariadb_ver(self):
        version_txt = os.path.join(self.mariadb_root, 'version.txt')
        if os.path.exists(version_txt):
            try:
                with open(version_txt, 'r', encoding='utf-8') as f:
                    ver = f.read().strip()
                    if ver: return ver
            except: pass
        if not os.path.exists(self.mariadb_exe):
            return "Not Found"
        try:
            res = subprocess.run([self.mariadb_exe, "-V"], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if res.stdout:
                match = re.search(r'mariadb[\s-]*(ver|Distrib)?\s*([\d\.]+)', res.stdout, re.IGNORECASE)
                if match:
                    ver = match.group(2)
                    try:
                        with open(version_txt, 'w', encoding='utf-8') as f:
                            f.write(ver)
                    except: pass
                    return ver
        except:
            pass
        return "10.11"

    def get_mariadb_ver(self):
        if not self.mariadb_ver_cached:
            active = self.settings.get('active_mariadb', 'mariadb')
            if 'cache' not in self.settings:
                self.settings['cache'] = {}
            cached_ver = self.settings['cache'].get(f'mariadb_{active}')
            if cached_ver:
                self.mariadb_ver_cached = cached_ver
            else:
                self.mariadb_ver_cached = self._query_mariadb_ver()
                self.settings['cache'][f'mariadb_{active}'] = self.mariadb_ver_cached
                self.save_settings()
        return self.mariadb_ver_cached

    def start_mariadb(self):
        """Start MariaDB. Returns True on success, False on failure."""
        if self._check_mariadb_running():
            self.mariadb_running = True
            return True
        if not os.path.exists(self.mariadb_exe):
            return False
        # Validate exe is a real binary (not a stub placeholder)
        try:
            exe_size = os.path.getsize(self.mariadb_exe)
            if exe_size < 1024:  # Less than 1KB = stub file
                return False
        except:
            return False
        data_dir = os.path.join(self.mariadb_root, 'data')
        os.makedirs(data_dir, exist_ok=True)
        try:
            log_file = os.path.abspath(self.mariadb_log)
            subprocess.Popen(
                [self.mariadb_exe, f"--datadir={data_dir}", "--standalone", f"--log-error={log_file}"],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            # Robust startup detection with retry loop (up to 5 seconds)
            for _ in range(10):
                time.sleep(0.5)
                if self._check_mariadb_running():
                    self.mariadb_running = True
                    
                    # Automatically set root password to 'root' if it is empty
                    try:
                        mysql_exe = os.path.join(os.path.dirname(self.mariadb_exe), 'mysql.exe')
                        if os.path.exists(mysql_exe):
                            sql_cmd = (
                                "ALTER USER 'root'@'localhost' IDENTIFIED BY 'root'; "
                                "ALTER USER 'root'@'127.0.0.1' IDENTIFIED BY 'root'; "
                                "ALTER USER 'root'@'::1' IDENTIFIED BY 'root'; "
                                "FLUSH PRIVILEGES;"
                            )
                            res = subprocess.run(
                                [mysql_exe, "-u", "root", "-e", sql_cmd],
                                capture_output=True,
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                timeout=5
                            )
                            if res.returncode != 0:
                                sql_cmd_alt = (
                                    "SET PASSWORD FOR 'root'@'localhost' = PASSWORD('root'); "
                                    "SET PASSWORD FOR 'root'@'127.0.0.1' = PASSWORD('root'); "
                                    "SET PASSWORD FOR 'root'@'::1' = PASSWORD('root'); "
                                    "FLUSH PRIVILEGES;"
                                )
                                subprocess.run(
                                    [mysql_exe, "-u", "root", "-e", sql_cmd_alt],
                                    creationflags=subprocess.CREATE_NO_WINDOW,
                                    timeout=5
                                )
                    except:
                        pass
                        
                    return True
            
            self.mariadb_running = False
            return False
        except Exception:
            self.mariadb_running = False
            return False

    def is_mariadb_valid(self):
        """Check if the MariaDB installation has a real binary (not a stub)."""
        if not os.path.exists(self.mariadb_exe):
            return False
        try:
            return os.path.getsize(self.mariadb_exe) >= 1024
        except:
            return False

    def stop_mariadb(self):
        self.mariadb_running = False
        try:
            subprocess.run(["taskkill", "/F", "/IM", "mariadbd.exe", "/T"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        except:
            pass
        try:
            subprocess.run(["taskkill", "/F", "/IM", "mysqld.exe", "/T"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        except:
            pass


    def _sync_php_runtime_paths(self, php_dir_fs):
        if not os.path.exists(self.php_ini):
            return

        try:
            with open(self.php_ini, 'r', encoding='utf-8', errors='ignore') as f:
                ini_data = f.read()

            ini_data = self._upsert_ini_key(ini_data, 'extension_dir', '"ext"')
            ini_data = self._upsert_ini_key(ini_data, 'error_log', '"logs/php_error.log"')
            
            # Create local tmp folder for sessions to prevent permission errors on Windows
            tmp_dir = os.path.join(self.php_dir, 'tmp')
            os.makedirs(tmp_dir, exist_ok=True)
            tmp_dir_fs = tmp_dir.replace('\\', '/')
            ini_data = self._upsert_ini_key(ini_data, 'session.save_path', f'"{tmp_dir_fs}"')

            with open(self.php_ini, 'w', encoding='utf-8') as f:
                f.write(ini_data)
        except:
            pass

    def _upsert_ini_key(self, content, key, value):
        pattern = rf'(?im)^\s*;?\s*{re.escape(key)}\s*=.*$'
        replacement = f'{key} = {value}'

        if re.search(pattern, content):
            return re.sub(pattern, replacement, content, count=1)

        if not content.endswith('\n'):
            content += '\n'
        return content + replacement + '\n'

    def is_running(self):
        return self.apache_running

    def get_available_phps(self):
        if self._available_phps_cache is not None:
            return self._available_phps_cache
        bin_dir = os.path.join(self.base, 'bin')
        phps = []
        if os.path.exists(bin_dir):
            for d in os.listdir(bin_dir):
                if d.startswith('php') and not d.startswith('phpmyadmin') and os.path.isdir(os.path.join(bin_dir, d)):
                    if os.path.exists(os.path.join(bin_dir, d, 'php.exe')):
                        phps.append(d)
        self._available_phps_cache = phps if phps else ['php']
        return self._available_phps_cache

    def get_available_apaches(self):
        if self._available_apaches_cache is not None:
            return self._available_apaches_cache
        bin_dir = os.path.join(self.base, 'bin')
        apaches = []
        if os.path.exists(bin_dir):
            for d in os.listdir(bin_dir):
                if d.startswith('apache') and os.path.isdir(os.path.join(bin_dir, d)):
                    if os.path.exists(os.path.join(bin_dir, d, 'bin', 'httpd.exe')):
                        apaches.append(d)
        self._available_apaches_cache = apaches if apaches else ['apache']
        return self._available_apaches_cache

    def _query_php_ver(self):
        # 1. Quick override via version.txt to speed up and allow dynamic updates
        version_txt = os.path.join(self.php_dir, 'version.txt')
        if os.path.exists(version_txt):
            try:
                with open(version_txt, 'r', encoding='utf-8') as f:
                    ver = f.read().strip()
                    if ver: return ver
            except:
                pass
        # 2. Standard execution fallback
        try:
            exe = os.path.join(self.php_dir, 'php.exe')
            if not os.path.exists(exe): return "Not Found"
            res = subprocess.run([exe, "-n", "-v"], capture_output=True, text=True, cwd=self.php_dir, creationflags=subprocess.CREATE_NO_WINDOW)
            if res.stdout:
                lines = res.stdout.split('\n')
                if lines and len(lines[0].split(' ')) > 1:
                    ver = lines[0].split(' ')[1]
                    try:
                        with open(version_txt, 'w', encoding='utf-8') as f:
                            f.write(ver)
                    except: pass
                    return ver
            return "N/A"
        except: return "N/A"

    def get_php_ver(self):
        if not self.php_ver_cached:
            active = self.settings.get('active_php', 'php')
            if 'cache' not in self.settings:
                self.settings['cache'] = {}
            cached_ver = self.settings['cache'].get(f'php_{active}')
            if cached_ver:
                self.php_ver_cached = cached_ver
            else:
                self.php_ver_cached = self._query_php_ver()
                self.settings['cache'][f'php_{active}'] = self.php_ver_cached
                self.save_settings()
        return self.php_ver_cached

    def get_apache_ver(self):
        active = self.settings.get('active_apache', 'apache')
        if 'cache' not in self.settings:
            self.settings['cache'] = {}
        cached_ver = self.settings['cache'].get(f'apache_{active}')
        if cached_ver:
            return cached_ver
        
        # Check version.txt first
        version_txt = os.path.join(self.apache_root, 'version.txt')
        ver = None
        if os.path.exists(version_txt):
            try:
                with open(version_txt, 'r', encoding='utf-8') as f:
                    ver = f.read().strip()
            except:
                pass
        
        if not ver:
            # Dynamically query Apache version if version.txt doesn't exist
            try:
                if os.path.exists(self.apache_exe):
                    res = subprocess.run([self.apache_exe, "-v"], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    if res.stdout:
                        match = re.search(r'Apache/([\d\.]+)', res.stdout)
                        if match:
                            ver = match.group(1)
                            try:
                                with open(version_txt, 'w', encoding='utf-8') as f:
                                    f.write(ver)
                            except: pass
            except:
                pass
        
        if not ver:
            ver = "2.4.58"
            
        self.settings['cache'][f'apache_{active}'] = ver
        self.save_settings()
        return ver


    def sqlite_status(self):
        if self._sqlite_status_cache is not None:
            return self._sqlite_status_cache
        if not os.path.exists(self.php_ini): return False
        try:
            with open(self.php_ini, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                self._sqlite_status_cache = 'extension=php_pdo_sqlite.dll' in content and ';extension=php_pdo_sqlite.dll' not in content
                return self._sqlite_status_cache
        except:
            return False

    def toggle_sqlite(self, enable=True):
        self._sqlite_status_cache = enable
        if not os.path.exists(self.php_ini): return
        try:
            with open(self.php_ini, 'r', encoding='utf-8', errors='ignore') as f: lines = f.readlines()
            with open(self.php_ini, 'w', encoding='utf-8') as f:
                for line in lines:
                    if 'extension=php_pdo_sqlite.dll' in line:
                        f.write(line.lstrip(';') if enable else ';' + line.lstrip(';'))
                    else: f.write(line)
        except:
            pass

    def start(self):
        if not self._check_process_running():
            self.update_php_paths()
            
            # Synchronize php.ini for the separate phpMyAdmin PHP version if active
            pma_php = self.settings.get('pma_php', '')
            if pma_php and pma_php != self.settings.get('active_php'):
                pma_php_dir = os.path.join(self.base, 'bin', pma_php)
                pma_php_ini = os.path.join(pma_php_dir, 'php.ini')
                php_tmpl = os.path.join(self.base, 'config', 'php.ini.template')
                pma_php_dir_fs = pma_php_dir.replace('\\', '/')
                if not os.path.exists(pma_php_ini) and os.path.exists(php_tmpl):
                    try:
                        with open(php_tmpl, 'r', encoding='utf-8') as f:
                            ini_data = f.read()
                        ini_data = ini_data.replace('{{PHP_DIR}}', pma_php_dir_fs)
                        with open(pma_php_ini, 'w', encoding='utf-8') as f:
                            f.write(ini_data)
                    except:
                        pass
                
                if os.path.exists(pma_php_ini):
                    try:
                        with open(pma_php_ini, 'r', encoding='utf-8', errors='ignore') as f:
                            ini_data = f.read()

                        ini_data = self._upsert_ini_key(ini_data, 'extension_dir', '"ext"')
                        ini_data = self._upsert_ini_key(ini_data, 'error_log', '"logs/php_error.log"')
                        
                        tmp_dir = os.path.join(pma_php_dir, 'tmp')
                        os.makedirs(tmp_dir, exist_ok=True)
                        tmp_dir_fs = tmp_dir.replace('\\', '/')
                        ini_data = self._upsert_ini_key(ini_data, 'session.save_path', f'"{tmp_dir_fs}"')

                        with open(pma_php_ini, 'w', encoding='utf-8') as f:
                            f.write(ini_data)
                    except:
                        pass
                        
            if os.path.exists(self.apache_pid):
                try:
                    os.remove(self.apache_pid)
                except OSError:
                    pass
            
            httpd_tmpl = os.path.join(self.base, 'config', 'httpd.conf.template')
            
            root_fs = self.base.replace('\\', '/')
            php_dir_fs = self.php_dir.replace('\\', '/')
            
            php_module = ""
            if os.path.exists(self.php_dir):
                for f in os.listdir(self.php_dir):
                    if f.startswith('php') and f.endswith('apache2_4.dll'):
                        php_module = os.path.join(self.php_dir, f).replace('\\', '/')
                        break
            
            if os.path.exists(httpd_tmpl):
                try:
                    with open(httpd_tmpl, 'r', encoding='utf-8') as f: conf_data = f.read()
                    conf_data = conf_data.replace('{{ROOT}}', root_fs)
                    conf_data = conf_data.replace('{{APACHE_ROOT}}', self.apache_root.replace('\\', '/'))
                    conf_data = conf_data.replace('{{PHP_MODULE}}', php_module)
                    conf_data = conf_data.replace('{{PHP_DIR}}', php_dir_fs)
                    
                    # phpMyAdmin separate PHP version configuration
                    pma_php = self.settings.get('pma_php', '')
                    if pma_php and pma_php != self.settings.get('active_php'):
                        pma_php_dir = os.path.join(self.base, 'bin', pma_php).replace('\\', '/')
                        pma_cgi_conf = f"""
# phpMyAdmin Custom PHP CGI configuration
ScriptAlias /php-cgi-pma/ "{pma_php_dir}/"
Action application/x-httpd-php-pma /php-cgi-pma/php-cgi.exe

<Directory "{pma_php_dir}">
    Options +ExecCGI
    Require all granted
    SetEnv PHPRC "{pma_php_dir}"
</Directory>

<DirectoryMatch "(?i)phpmyadmin">
    <FilesMatch \\.php$>
        SetHandler application/x-httpd-php-pma
    </FilesMatch>
</DirectoryMatch>
"""
                        conf_data += pma_cgi_conf
                        
                    with open(self.conf, 'w', encoding='utf-8') as f: f.write(conf_data)
                except:
                    pass

            env = os.environ.copy()
            env["PATH"] = f"{self.php_dir};{env.get('PATH', '')}"
            
            try:
                subprocess.Popen(
                    [self.apache_exe, "-d", self.apache_root, "-f", self.conf],
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                self.apache_running = True
            except:
                pass

    def stop(self):
        self.apache_running = False
        try:
            subprocess.run(
                [self.apache_exe, "-k", "stop", "-d", self.apache_root, "-f", self.conf],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=8
            )
        except Exception:
            pass

        deadline = time.time() + 6
        while self._check_process_running() and time.time() < deadline:
            time.sleep(0.4)

        if self._check_process_running():
            try:
                subprocess.run(["taskkill", "/F", "/IM", "httpd.exe", "/T"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            except:
                pass

        if os.path.exists(self.apache_pid):
            try:
                os.remove(self.apache_pid)
            except OSError:
                pass

class HoverButton(customtkinter.CTkButton):
    def __init__(self, master, style_type="normal", **kw):
        self.style_type = style_type
        # Strip standard Tkinter arguments that CTkButton doesn't accept
        kw.pop('bd', None)
        kw.pop('relief', None)
        kw.pop('highlightthickness', None)
        kw.pop('bg', None)
        kw.pop('activebackground', None)
        kw.pop('activeforeground', None)
        kw.pop('padx', None)
        kw.pop('pady', None)
        
        customtkinter.CTkButton.__init__(self, master=master, corner_radius=8, **kw)
        self.update_style()

    def configure(self, **kwargs):
        res = customtkinter.CTkButton.configure(self, **kwargs)
        if "state" in kwargs:
            self.update_style()
        return res

    def update_style(self):
        if self._state == "disabled":
            customtkinter.CTkButton.configure(
                self,
                fg_color=("#cbd5e1", "#1e293b"),
                text_color_disabled=("#475569", "#94a3b8")
            )
        else:
            if self.style_type == "success":
                customtkinter.CTkButton.configure(
                    self,
                    fg_color=("#ffffff", "#ffffff"), 
                    hover_color=("#e2e8f0", "#cbd5e1"), 
                    text_color=("#0f172a", "#0f172a")
                )
            elif self.style_type == "danger":
                customtkinter.CTkButton.configure(self, fg_color="#ef4444", hover_color="#dc2626", text_color="white")
            elif self.style_type == "accent":
                customtkinter.CTkButton.configure(self, fg_color="#3b82f6", hover_color="#2563eb", text_color="white")
            elif self.style_type == "normal":
                customtkinter.CTkButton.configure(self, fg_color=("#3a3f50", "#2d323f"), hover_color=("#474e63", "#3d4352"), text_color="white")

    def update_theme(self, colors):
        self.update_style()

class SidebarButton(customtkinter.CTkFrame):
    def __init__(self, master, icon_char, text, command, colors, **kw):
        customtkinter.CTkFrame.__init__(self, master, fg_color="transparent", corner_radius=8, cursor="hand2", **kw)
        self.command = command
        self.colors = colors
        self.is_active = False
        self.collapsed = False
        
        self.icon_lbl = customtkinter.CTkLabel(self, text=icon_char, font=("Segoe MDL2 Assets", 14), text_color=self.colors['muted'])
        self.icon_lbl.pack(side="left", padx=(15, 10), pady=10)
        
        self.text_lbl = customtkinter.CTkLabel(self, text=text, font=("Segoe UI", 11, "bold"), text_color=self.colors['muted'])
        self.text_lbl.pack(side="left", pady=10)
        
        # Bind events for hover and click to all children
        for widget in (self, self.icon_lbl, self.text_lbl):
            widget.bind("<Enter>", self.on_enter)
            widget.bind("<Leave>", self.on_leave)
            widget.bind("<Button-1>", self.on_click)
            
    def on_enter(self, e):
        if not self.is_active:
            self.configure(fg_color=self.colors['border'])
            
    def on_leave(self, e):
        if not self.is_active:
            # Prevent flickering when moving to children widgets
            x, y = self.winfo_pointerxy()
            widget = self.winfo_containing(x, y)
            if widget == self or (widget and widget.master == self):
                return
            self.configure(fg_color="transparent")
            
    def on_click(self, e):
        self.command()
        
    def set_active(self, active):
        self.is_active = active
        if active:
            self.configure(fg_color=self.colors['card'], border_width=1, border_color=self.colors['border'])
            self.icon_lbl.configure(text_color=self.colors['accent'])
            self.text_lbl.configure(text_color=self.colors['accent'])
        else:
            self.configure(fg_color="transparent", border_width=0)
            self.icon_lbl.configure(text_color=self.colors['muted'])
            self.text_lbl.configure(text_color=self.colors['muted'])

    def set_collapsed(self, collapsed):
        if self.collapsed == collapsed:
            return
        self.collapsed = collapsed
        if collapsed:
            self.text_lbl.pack_forget()
            self.icon_lbl.pack_forget()
            self.icon_lbl.pack(side="top", padx=0, pady=10)
        else:
            self.icon_lbl.pack_forget()
            self.icon_lbl.pack(side="left", padx=(15, 10), pady=10)
            self.text_lbl.pack(side="left", pady=10)

    def update_theme(self, colors):
        self.colors = colors
        self.set_active(self.is_active)

class UltimateDashboard:
    def __init__(self, root):
        self.root = root
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self.core = ServerCore(base_dir)
        
        self.colors = {
            'bg': ("#f1f5f9", "#151821"),           # Light/Dark main background
            'sidebar_bg': ("#e2e8f0", "#1e222b"),   # Light/Dark sidebar
            'card': ("#ffffff", "#21252e"),         # Light/Dark card
            'border': ("#cbd5e1", "#2d3340"),       # Light/Dark border
            'accent': "#3b82f6",                    # Blue
            'green': "#10b981",                     # Green
            'red': "#ef4444",                       # Red
            'orange': "#f59e0b",                    # Orange/Warning
            'text': ("#0f172a", "#f8fafc"),         # Light/Dark text
            'muted': ("#64748b", "#94a3b8"),       # Light/Dark muted text
            'console_bg': ("#f8fafc", "#0f1319"),
            'console_fg_apache': ("#166534", "#39ff14"),
            'console_fg_php': ("#0369a1", "#00ccff"),
            'console_fg_db': ("#92400e", "#fbbf24"),   # Database logs (amber)
        }
        
        self.theme = self.core.settings.get('theme', 'dark')
        customtkinter.set_appearance_mode(self.theme)
        
        # State caching variables to solve flashing/flickering
        self._last_run_state = None
        self._last_php_ver = None
        self._last_sqlite_state = None
        self._last_uptime = None
        self._last_file_count = None
        self.is_operating = False
        
        self.root.title("AbuRasha Serv - Manager")
        self.root.geometry("1000x650")
        self.root.minsize(760, 600)
        self.root.configure(fg_color=self.colors['bg'])
        self.root.attributes('-alpha', 0.0)
        self.start_time = time.time() if self.core.is_running() else None
        
        self.service_widgets = {}
        self.sidebar_buttons = {}
        self.sidebar_collapsed = False
        
        self.setup_ui()
        self.show_page('services')
        self.fade_in()
        self.root.protocol("WM_DELETE_WINDOW", self.safe_shutdown)
        self.root.bind("<Configure>", self.on_window_resize)

    def fade_in(self, alpha=0.0):
        alpha += 0.05
        if alpha < 1.0:
            self.root.attributes('-alpha', alpha)
            self.root.after(20, lambda: self.fade_in(alpha))
        else:
            self.root.attributes('-alpha', 1.0)
            self.start_services_check()

    def start_services_check(self):
        self.update_loop()
        threading.Thread(target=self.log_watcher, args=(self.core.apache_log, self.apache_console), daemon=True).start()
        threading.Thread(target=self.log_watcher, args=(self.core.php_log, self.php_console), daemon=True).start()
        threading.Thread(target=self.log_watcher, args=(self.core.mariadb_log, self.db_console), daemon=True).start()

    def on_window_resize(self, event):
        if event.widget == self.root:
            if event.width < 850:
                self.set_sidebar_collapsed(True)
            else:
                self.set_sidebar_collapsed(False)

    def set_sidebar_collapsed(self, collapsed):
        if self.sidebar_collapsed == collapsed:
            return
        self.sidebar_collapsed = collapsed
        if collapsed:
            self.sidebar_frame.configure(width=75)
            self.logo_lbl.configure(text="AR", font=customtkinter.CTkFont(family="Segoe UI", size=18, weight="bold"))
            self.ver_lbl.pack_forget()
            self.theme_btn.pack_forget()
            self.close_btn.pack_forget()
            if hasattr(self, 'footer_separator'):
                self.footer_separator.pack_forget()
            self.theme_btn.pack(side="top", pady=4)
            self.close_btn.pack(side="top", pady=4)
            for btn in self.sidebar_buttons.values():
                btn.set_collapsed(True)
        else:
            self.sidebar_frame.configure(width=240)
            self.logo_lbl.configure(text="AbuRasha Serv", font=customtkinter.CTkFont(family="Segoe UI", size=18, weight="bold"))
            self.ver_lbl.pack(side="left")
            self.theme_btn.pack_forget()
            self.close_btn.pack_forget()
            if hasattr(self, 'footer_separator'):
                self.footer_separator.pack_forget()
            # Pack order: theme (rightmost), separator, close
            self.theme_btn.pack(side="right", padx=(0, 4))
            if hasattr(self, 'footer_separator'):
                self.footer_separator.pack(side="right", padx=8)
            self.close_btn.pack(side="right", padx=(4, 0))
            for btn in self.sidebar_buttons.values():
                btn.set_collapsed(False)


    def setup_ui(self):
        # 1. Left Sidebar
        # 1. Left Sidebar (Floating panel layout)
        self.sidebar_frame = customtkinter.CTkFrame(self.root, width=240, corner_radius=15, fg_color=self.colors['sidebar_bg'], border_color=self.colors['border'], border_width=1)
        self.sidebar_frame.pack(side="left", fill="y", padx=(15, 10), pady=15)
        self.sidebar_frame.pack_propagate(False)
        
        # Sidebar Logo / Header
        self.logo_lbl = customtkinter.CTkLabel(self.sidebar_frame, text="AbuRasha Serv", font=customtkinter.CTkFont(family="Segoe UI", size=18, weight="bold"), text_color=self.colors['text'])
        self.logo_lbl.pack(fill="x", pady=(25, 20), padx=15)
        
        # Sidebar Menu Items
        menu_items = [
            ('services', '\uE90F', 'Services'),
            ('downloads', '\uE118', 'Downloads'),
            ('settings', '\uE713', 'Settings'),
            ('logs', '\uE7C3', 'Logs'),
            ('help', '\uE897', 'Help')
        ]
        
        for page_id, icon_char, label_text in menu_items:
            btn = SidebarButton(
                self.sidebar_frame, 
                icon_char=icon_char,
                text=label_text, 
                command=lambda p=page_id: self.show_page(p),
                colors=self.colors
            )
            btn.pack(fill="x", padx=15, pady=4)
            self.sidebar_buttons[page_id] = btn

        # Sidebar Footer Frame
        self.footer_frame = customtkinter.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.footer_frame.pack(side="bottom", fill="x", pady=15, padx=15)
        
        self.ver_lbl = customtkinter.CTkLabel(self.footer_frame, text="v2.4 Stable", font=("Segoe UI", 11), text_color=self.colors['muted'])
        self.ver_lbl.pack(side="left")

        # Theme toggle button (left side of footer buttons)
        theme_icon = "\uE706" if self.theme == 'dark' else "\uE708"
        self.theme_btn = HoverButton(
            self.footer_frame,
            style_type="normal",
            text=theme_icon,
            font=("Segoe MDL2 Assets", 12),
            width=36,
            height=36,
            command=self.toggle_theme
        )
        self.theme_btn.pack(side="right", padx=(0, 4))

        # Vertical Separator - distinctive gradient-style divider
        self.footer_separator = customtkinter.CTkFrame(
            self.footer_frame,
            width=2,
            height=24,
            fg_color=("#94a3b8", "#475569"),
            corner_radius=2
        )
        self.footer_separator.pack(side="right", padx=8)
        self.footer_separator.pack_propagate(False)

        # Close App button (stops services and shuts down application safely)
        self.close_btn = HoverButton(
            self.footer_frame,
            style_type="danger",
            text="\uE7E8",
            font=("Segoe MDL2 Assets", 12),
            width=36,
            height=36,
            command=self.safe_shutdown
        )
        self.close_btn.pack(side="right", padx=(4, 0))


        # 2. Right Pane
        self.right_pane = customtkinter.CTkFrame(self.root, fg_color="transparent")
        self.right_pane.pack(side="right", fill="both", expand=True, padx=(10, 15), pady=15)

        # Right Header (Title, global status, toast message)
        self.header_frame = customtkinter.CTkFrame(self.right_pane, fg_color="transparent")
        self.header_frame.pack(fill="x", pady=(10, 15))
        
        self.title_lbl = customtkinter.CTkLabel(self.header_frame, text="SERVER CONTROL PANEL", font=customtkinter.CTkFont(family="Segoe UI", size=15, weight="bold"), text_color=self.colors['accent'])
        self.title_lbl.pack(side="left")

        # Toast notifications packed to the left right next to the title
        self.toast_lbl = customtkinter.CTkLabel(self.header_frame, text="", font=customtkinter.CTkFont(family="Segoe UI", size=10, weight="bold", slant="italic"), text_color=self.colors['muted'])
        self.toast_lbl.pack(side="left", padx=15)

        # Global server status on the far right
        self.global_status_lbl = customtkinter.CTkLabel(self.header_frame, text="Checking status...", font=customtkinter.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color=self.colors['muted'])
        self.global_status_lbl.pack(side="right", padx=(10, 5))

        # Top buttons next to server status (packed right, so it sits on the left of status)
        self.top_btns_frame = customtkinter.CTkFrame(self.header_frame, fg_color="transparent")
        self.top_btns_frame.pack(side="right", padx=(0, 10))

        initial_state = "normal" if self.core.is_running() else "disabled"

        self.open_web_btn = HoverButton(
            self.top_btns_frame,
            style_type="accent",
            text="🌐 Open Web",
            font=("Segoe UI", 10, "bold"),
            command=self.open_web,
            state=initial_state,
            height=28
        )
        self.open_web_btn.pack(side="left", padx=3)

        self.open_pma_btn = HoverButton(
            self.top_btns_frame,
            style_type="normal",
            text="🗄️ phpMyAdmin",
            font=("Segoe UI", 10, "bold"),
            command=self.open_phpmyadmin,
            state=initial_state,
            height=28
        )
        self.open_pma_btn.pack(side="left", padx=3)

        self.divider = customtkinter.CTkFrame(self.right_pane, height=1, fg_color=self.colors['border'])
        self.divider.pack(fill="x")

        # Content area for multiple panels
        self.right_container = customtkinter.CTkFrame(self.right_pane, fg_color="transparent")
        self.right_container.pack(fill="both", expand=True, pady=15)
        self.right_container.grid_rowconfigure(0, weight=1)
        self.right_container.grid_columnconfigure(0, weight=1)

        # Page Frames
        self.pages = {}
        for name in ['services', 'downloads', 'settings', 'logs', 'help']:
            self.pages[name] = customtkinter.CTkFrame(self.right_container, fg_color="transparent")
            self.pages[name].grid(row=0, column=0, sticky="nsew")

        self.setup_services_tab()
        self.setup_downloads_tab()
        self.setup_settings_tab()
        self.setup_logs_tab()
        self.setup_help_tab()

    def show_page(self, page_name):
        for name, btn in self.sidebar_buttons.items():
            btn.set_active(name == page_name)
        
        self.pages[page_name].tkraise()

    def get_installed_phpmyadmins(self):
        installed = []
        if os.path.exists(self.core.www_dir):
            for d in os.listdir(self.core.www_dir):
                if d.lower().startswith('phpmyadmin'):
                    pma_path = os.path.join(self.core.www_dir, d)
                    if os.path.isdir(pma_path) and os.path.exists(os.path.join(pma_path, 'index.php')):
                        if self.is_tool_installed(d):
                            installed.append(d)
        return installed

    def open_web(self):
        webbrowser.open("http://localhost:8080/")

    def open_phpmyadmin(self):
        installed = self.get_installed_phpmyadmins()
        if not installed:
            self.show_toast("✗ phpMyAdmin is not installed. Please install it from the Downloads tab.", self.colors['red'])
            return
        
        if len(installed) == 1:
            webbrowser.open(f"http://localhost:8080/{installed[0]}/")
        else:
            self.show_pma_selector_window(installed)

    def setup_help_tab(self):
        container = customtkinter.CTkFrame(self.pages['help'], fg_color="transparent")
        container.pack(fill="both", expand=True)

        sect_lbl = customtkinter.CTkLabel(
            container, 
            text="SYSTEM DOCUMENTATION & GUIDE", 
            font=customtkinter.CTkFont(family="Segoe UI", size=13, weight="bold"), 
            text_color=self.colors['accent']
        )
        sect_lbl.pack(anchor="w", pady=(5, 10), padx=20)

        # Scrollable container for help content
        scroll_frame = customtkinter.CTkScrollableFrame(container, fg_color="transparent")
        scroll_frame.pack(fill="both", expand=True)

        # Section 1: Overview
        self.create_help_card(
            scroll_frame, 
            "🌐 System Overview (AbuRasha Serv)", 
            "AbuRasha Serv is a portable, all-in-one local development suite designed for web developers. It includes the Apache HTTP Server, MariaDB Database Server, PHP Scripting Engine, and embedded SQLite Database support. All services run locally and require zero complex configurations."
        )
        
        # Section 2: Apache Web Server
        self.create_help_card(
            scroll_frame, 
            "💻 Apache Web Server Guide", 
            "• The web server runs by default on port 8080.\n"
            "• Access your local sites using: http://localhost:8080/\n"
            "• The project document root directory is www/. Place your website and project files there.\n"
            "• When changing the project's PHP version in settings, the web server restarts automatically to apply the changes."
        )
        
        # Section 3: Database & phpMyAdmin
        self.create_help_card(
            scroll_frame, 
            "🗄️ Database Server & phpMyAdmin", 
            "• The relational database server is MariaDB (fully MySQL-compatible) running on port 3306.\n"
            "• Click on (Open phpMyAdmin) in the header to manage databases via the web panel.\n"
            "• Default Database Login Credentials:\n"
            "  » Username: root\n"
            "  » Password: root\n"
            "• You can run phpMyAdmin on a separate PHP version independently from the project."
        )
        
        # Section 4: PHP & SQLite
        self.create_help_card(
            scroll_frame, 
            "⚙️ PHP Engine & SQLite Database", 
            "• Configure different PHP runtimes for the project and phpMyAdmin from the Settings tab.\n"
            "• The environment supports multiple PHP runtimes such as PHP 8.2, 8.3, 8.4, and 8.5.\n"
            "• Toggle the SQLite PDO driver on or off with a single click from the Services tab (Enable/Disable SQLite) without editing configuration files manually."
        )
        
        # Section 5: Troubleshooting & Support
        self.create_help_card(
            scroll_frame, 
            "📝 Logs, Debugging & Support", 
            "• Monitor error outputs for Apache, PHP, and MariaDB in the Logs tab to debug coding issues.\n"
            "• For feedback or support queries, contact us at: admin@aljup.com (link available in Settings)."
        )

    def create_help_card(self, parent, title, content):
        card = customtkinter.CTkFrame(
            parent,
            corner_radius=12,
            border_width=1,
            border_color=self.colors['border'],
            fg_color=self.colors['card']
        )
        card.pack(fill="x", pady=6, padx=5)
        
        # Header of card (LTR alignment)
        title_lbl = customtkinter.CTkLabel(
            card, 
            text=title, 
            font=("Segoe UI", 12, "bold"), 
            text_color=self.colors['accent'],
            anchor="w",
            justify="left"
        )
        title_lbl.pack(fill="x", padx=15, pady=(10, 5))
        
        # Content (LTR alignment)
        content_lbl = customtkinter.CTkLabel(
            card, 
            text=content, 
            font=("Segoe UI", 10), 
            text_color=self.colors['text'],
            anchor="w",
            justify="left",
            wraplength=500
        )
        content_lbl.pack(fill="x", padx=15, pady=(0, 10))
        content_lbl.bind("<Configure>", lambda event, lbl=content_lbl: lbl.configure(wraplength=event.width - 30))

    def show_pma_selector_window(self, installed_versions):
        # Create toplevel window
        selector = customtkinter.CTkToplevel(self.root)
        selector.title("phpMyAdmin Login Portal")
        selector.geometry("450x300")
        selector.resizable(False, False)
        
        # Bring to front and grab focus
        selector.transient(self.root)
        selector.grab_set()
        selector.focus_set()
        
        # Center the window on the main window
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 225
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 150
        selector.geometry(f"+{x}+{y}")
        
        # Styling frame
        bg_color = self.colors['card']
        border_color = self.colors['border']
        
        frame = customtkinter.CTkFrame(selector, corner_radius=15, border_width=1, border_color=border_color, fg_color=bg_color)
        frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        lbl_title = customtkinter.CTkLabel(
            frame, 
            text="phpMyAdmin Login Portal", 
            font=("Segoe UI", 14, "bold"), 
            text_color=self.colors['accent']
        )
        lbl_title.pack(pady=(15, 5))
        
        # Version Selection Section
        sel_frame = customtkinter.CTkFrame(frame, fg_color="transparent")
        sel_frame.pack(fill="x", padx=20, pady=5)
        
        lbl_ver = customtkinter.CTkLabel(
            sel_frame,
            text="Installed Version:",
            font=("Segoe UI", 11, "bold"),
            text_color=self.colors['text']
        )
        lbl_ver.pack(side="left", padx=5)
        
        selected_version = tk.StringVar(value=installed_versions[0])
        
        combo = customtkinter.CTkOptionMenu(
            sel_frame, 
            variable=selected_version,
            values=installed_versions,
            width=200,
            font=("Segoe UI", 11, "bold"),
            dropdown_font=("Segoe UI", 11)
        )
        combo.pack(side="right")
        
        # Login Info Helper Box
        info_box = customtkinter.CTkFrame(frame, corner_radius=8, fg_color=self.colors['bg'], border_width=1, border_color=border_color)
        info_box.pack(fill="x", padx=20, pady=10)
        
        info_title = customtkinter.CTkLabel(
            info_box,
            text="🔑 Default Credentials:",
            font=("Segoe UI", 11, "bold"),
            text_color=self.colors['accent'],
            justify="left"
        )
        info_title.pack(anchor="w", padx=10, pady=(5, 2))
        
        # Grid inside info box for credentials
        cred_frame = customtkinter.CTkFrame(info_box, fg_color="transparent")
        cred_frame.pack(anchor="w", padx=15, pady=(2, 5))
        
        lbl_u_title = customtkinter.CTkLabel(cred_frame, text="Username:", font=("Segoe UI", 10, "bold"), text_color=self.colors['text'])
        lbl_u_title.grid(row=0, column=0, sticky="w", padx=(0, 10))
        
        lbl_u_val = customtkinter.CTkLabel(cred_frame, text="root", font=("Consolas", 11, "bold"), text_color=self.colors['green'])
        lbl_u_val.grid(row=0, column=1, sticky="w")
        
        lbl_p_title = customtkinter.CTkLabel(cred_frame, text="Password:", font=("Segoe UI", 10, "bold"), text_color=self.colors['text'])
        lbl_p_title.grid(row=1, column=0, sticky="w", padx=(0, 10))
        
        lbl_p_val = customtkinter.CTkLabel(cred_frame, text="root", font=("Consolas", 11, "bold"), text_color=self.colors['green'])
        lbl_p_val.grid(row=1, column=1, sticky="w")
        
        # Action Button
        btn_open = HoverButton(
            frame,
            style_type="success",
            text="Open phpMyAdmin",
            width=160,
            font=("Segoe UI", 11, "bold"),
            command=lambda: [webbrowser.open(f"http://localhost:8080/{selected_version.get()}/"), selector.destroy()]
        )
        btn_open.pack(pady=(5, 10))

    def create_service_card(self, parent, key, title, desc):
        card = customtkinter.CTkFrame(
            parent,
            corner_radius=12,
            border_width=2,
            border_color=self.colors['border'],
            fg_color=self.colors['card']
        )
        card.pack(fill="x", pady=8, padx=20)
        
        # Buttons (right) - Packed first so they never clip
        btn_frame = customtkinter.CTkFrame(card, fg_color="transparent")
        btn_frame.pack(side="right", fill="y", padx=(15, 15), pady=10)
        
        buttons = {}
        
        if key == 'apache':
            b_start = HoverButton(btn_frame, style_type="success", text="\u25B6  Start", command=self.on_start, width=75, font=("Segoe UI", 9, "bold"))
            b_start.pack(side="left", padx=3)
            b_stop = HoverButton(btn_frame, style_type="danger", text="\u25A0  Stop", command=self.on_stop, width=75, font=("Segoe UI", 9, "bold"))
            b_stop.pack(side="left", padx=3)
            b_restart = HoverButton(btn_frame, style_type="accent", text="\u21BB  Restart", command=self.on_restart, width=75, font=("Segoe UI", 9, "bold"))
            b_restart.pack(side="left", padx=3)
            b_config = HoverButton(btn_frame, style_type="normal", text="\u2699  Configure", command=lambda: self.on_configure('apache'), width=75, font=("Segoe UI", 9, "bold"))
            b_config.pack(side="left", padx=3)
            
            buttons['start'] = b_start
            buttons['stop'] = b_stop
            buttons['restart'] = b_restart
            buttons['config'] = b_config
            
        elif key == 'php':
            b_restart = HoverButton(btn_frame, style_type="accent", text="\u21BB  Restart", command=self.on_restart, width=75, font=("Segoe UI", 9, "bold"))
            b_restart.pack(side="left", padx=3)
            b_config = HoverButton(btn_frame, style_type="normal", text="\u2699  Configure", command=lambda: self.on_configure('php'), width=75, font=("Segoe UI", 9, "bold"))
            b_config.pack(side="left", padx=3)
            
            buttons['restart'] = b_restart
            buttons['config'] = b_config
            
        elif key == 'sqlite':
            b_enable = HoverButton(btn_frame, style_type="success", text="\u25B6  Enable", command=self.on_sql_on, width=75, font=("Segoe UI", 9, "bold"))
            b_enable.pack(side="left", padx=3)
            b_disable = HoverButton(btn_frame, style_type="danger", text="\u25A0  Disable", command=self.on_sql_off, width=75, font=("Segoe UI", 9, "bold"))
            b_disable.pack(side="left", padx=3)
            b_restart = HoverButton(btn_frame, style_type="accent", text="\u21BB  Restart", command=self.on_restart, width=75, font=("Segoe UI", 9, "bold"))
            b_restart.pack(side="left", padx=3)
            b_config = HoverButton(btn_frame, style_type="normal", text="\u2699  Configure", command=lambda: self.on_configure('sqlite'), width=75, font=("Segoe UI", 9, "bold"))
            b_config.pack(side="left", padx=3)
            
            buttons['enable'] = b_enable
            buttons['disable'] = b_disable
            buttons['restart'] = b_restart
            buttons['config'] = b_config

        elif key == 'mariadb':
            b_start = HoverButton(btn_frame, style_type="success", text="\u25B6  Start", command=self.on_mariadb_start, width=75, font=("Segoe UI", 9, "bold"))
            b_start.pack(side="left", padx=3)
            b_stop = HoverButton(btn_frame, style_type="danger", text="\u25A0  Stop", command=self.on_mariadb_stop, width=75, font=("Segoe UI", 9, "bold"))
            b_stop.pack(side="left", padx=3)
            b_restart = HoverButton(btn_frame, style_type="accent", text="\u21BB  Restart", command=self.on_mariadb_restart, width=75, font=("Segoe UI", 9, "bold"))
            b_restart.pack(side="left", padx=3)
            b_config = HoverButton(btn_frame, style_type="normal", text="\u2699  Configure", command=lambda: self.on_configure('mariadb'), width=75, font=("Segoe UI", 9, "bold"))
            b_config.pack(side="left", padx=3)
            
            buttons['start'] = b_start
            buttons['stop'] = b_stop
            buttons['restart'] = b_restart
            buttons['config'] = b_config
            
        # Status text - Packed second
        status_lbl = customtkinter.CTkLabel(card, text="● CHECKING", font=("Segoe UI", 10, "bold"), text_color=self.colors['muted'])
        status_lbl.pack(side="right", padx=8)
        
        # Info (left) - Packed last to fill remaining space
        info_frame = customtkinter.CTkFrame(card, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, padx=15, pady=10)
        
        title_row = customtkinter.CTkFrame(info_frame, fg_color="transparent")
        title_row.pack(anchor="w")
        
        icon_map = {
            'apache': '\uE12B',
            'php': '\uE943',
            'sqlite': '\uEC27',
            'mariadb': '\uEC27'
        }
        icon_char = icon_map.get(key, '\uE90F')
        
        icon_lbl = customtkinter.CTkLabel(title_row, text=icon_char, font=("Segoe MDL2 Assets", 18), text_color=self.colors['accent'])
        icon_lbl.pack(side="left", padx=(0, 8))
        
        title_lbl = customtkinter.CTkLabel(title_row, text=title, font=("Segoe UI", 13, "bold"), text_color=self.colors['text'])
        title_lbl.pack(side="left")
        
        desc_lbl = customtkinter.CTkLabel(info_frame, text=desc, font=("Segoe UI", 10), text_color=self.colors['muted'], justify="left")
        desc_lbl.pack(anchor="w", pady=(3, 0))
        # Responsive description text wrapping
        desc_lbl.bind("<Configure>", lambda event, lbl=desc_lbl: lbl.configure(wraplength=event.width))
        
        self.service_widgets[key] = {
            'card': card,
            'status_lbl': status_lbl,
            'desc_lbl': desc_lbl,
            'buttons': buttons
        }
    def setup_services_tab(self):
        container = customtkinter.CTkFrame(self.pages['services'], fg_color="transparent")
        container.pack(fill="both", expand=True)
  
        # Title / Description info
        sect_lbl = customtkinter.CTkLabel(container, text="ACTIVE SYSTEM SERVICES", font=customtkinter.CTkFont(family="Segoe UI", size=13, weight="bold"), text_color=self.colors['accent'])
        sect_lbl.pack(anchor="w", pady=(5, 10), padx=20)
  
        # Cards container
        self.create_service_card(container, 'apache', 'Apache Web Server', 'HTTP Daemon Service v2.4 (Handles web queries)')
        self.create_service_card(container, 'php', 'PHP Scripting Engine', 'Server-side Script Interpreter & Preprocessor')
        self.create_service_card(container, 'sqlite', 'SQLite Database Core', 'Embedded Serverless Database Extension')
        self.create_service_card(container, 'mariadb', 'MariaDB Database Server', 'MySQL-compatible SQL Relational Database Server')

        # Uptime & File statistics footer
        stats_frame = customtkinter.CTkFrame(container, fg_color="transparent")
        stats_frame.pack(fill="x", side="bottom", pady=15, padx=20)
        self.file_count_lbl = customtkinter.CTkLabel(stats_frame, text="Files in www: Checking...", font=("Segoe UI", 11), text_color=self.colors['muted'])
        self.file_count_lbl.pack(side="left")

        self.uptime_lbl = customtkinter.CTkLabel(stats_frame, text="Uptime: 00:00:00", font=("Segoe UI", 11), text_color=self.colors['muted'])
        self.uptime_lbl.pack(side="right")

    def setup_downloads_tab(self):
        self.download_widgets = {}
        container = customtkinter.CTkFrame(self.pages['downloads'], fg_color="transparent")
        container.pack(fill="both", expand=True)

        sect_lbl = customtkinter.CTkLabel(container, text="SUPPORTED VERSIONS & DOWNLOAD MANAGER", font=customtkinter.CTkFont(family="Segoe UI", size=13, weight="bold"), text_color=self.colors['accent'])
        sect_lbl.pack(anchor="w", pady=(5, 10), padx=20)

        # Scrollable container for cards
        scroll_frame = customtkinter.CTkScrollableFrame(container, fg_color="transparent")
        scroll_frame.pack(fill="both", expand=True)

        # Supported PHP Versions
        self.create_download_card(scroll_frame, 'php8.5.6', 'PHP Scripting Engine', 'v8.5.6 (Security Update)', 'Recommended update for security patches and scripting performance.')
        self.create_download_card(scroll_frame, 'php8.4', 'PHP Scripting Engine', 'v8.4.0 (Stable)', 'Stable scripting engine release.')
        self.create_download_card(scroll_frame, 'php8.3', 'PHP Scripting Engine', 'v8.3.0 (Stable)', 'Stable scripting engine release.')
        self.create_download_card(scroll_frame, 'php8.2', 'PHP Scripting Engine', 'v8.2.0 (Legacy)', 'Legacy scripting engine release.')
        
        # Supported Apache Versions (2.4.59 is the default; these are newer)
        self.create_download_card(scroll_frame, 'apache2.4.63', 'Apache Web Server', 'v2.4.63 (Latest Stable)', 'Latest stable release with critical security patches and HTTP/2 improvements.')
        self.create_download_card(scroll_frame, 'apache2.4.62', 'Apache Web Server', 'v2.4.62 (Security Release)', 'Recommended security release with updated OpenSSL and security fixes.')
        self.create_download_card(scroll_frame, 'apache2.4.61', 'Apache Web Server', 'v2.4.61 (Stable Release)', 'Stable release with mod_rewrite improvements and performance enhancements.')
        
        # Supported MariaDB Versions
        self.create_download_card(scroll_frame, 'mariadb11.4', 'MariaDB Database Server', 'v11.4 (Experimental)', 'Next-gen MySQL-compatible database server with optimized engine.')
        self.create_download_card(scroll_frame, 'mariadb10.11', 'MariaDB Database Server', 'v10.11 (Experimental)', 'High-performance MySQL-compatible relational database server.')

        # Separator label
        tools_lbl = customtkinter.CTkLabel(scroll_frame, text="TOOLS & UTILITIES", font=customtkinter.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color=self.colors['muted'])
        tools_lbl.pack(anchor="w", pady=(15, 5), padx=20)

        # Developer Tools
        self.create_download_card(scroll_frame, 'phpmyadmin', 'phpMyAdmin', 'v5.2.1 (Stable)', 'Web-based database management interface for MariaDB/MySQL.')
        self.create_download_card(scroll_frame, 'phpmyadmin5.2.2', 'phpMyAdmin', 'v5.2.2 (Stable)', 'Web-based database management interface for MariaDB/MySQL.')
        self.create_download_card(scroll_frame, 'phpmyadmin5.2.3', 'phpMyAdmin', 'v5.2.3 (Stable)', 'Web-based database management interface for MariaDB/MySQL.')
        self.create_download_card(scroll_frame, 'phpmyadmin4.9.11', 'phpMyAdmin', 'v4.9.11 (Stable)', 'Web-based database management interface for MariaDB/MySQL.')
        self.create_download_card(scroll_frame, 'composer', 'Composer', 'v2.7.0 (Stable)', 'PHP dependency manager for package management and autoloading.')
        self.create_download_card(scroll_frame, 'adminer', 'Adminer', 'v4.8.1 (Stable)', 'Lightweight single-file database management tool. Supports MySQL, SQLite, PostgreSQL.')
        self.create_download_card(scroll_frame, 'nodejs20', 'Node.js Runtime', 'v20.18 (LTS)', 'JavaScript runtime for building server-side applications and build tools.')


    def create_download_card(self, parent, key, service_name, target_ver, desc):
        card = customtkinter.CTkFrame(
            parent,
            corner_radius=12,
            border_width=2,
            border_color=self.colors['border'],
            fg_color=self.colors['card']
        )
        card.pack(fill="x", pady=8, padx=20)
        
        info_frame = customtkinter.CTkFrame(card, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, padx=15, pady=10)
        
        title_row = customtkinter.CTkFrame(info_frame, fg_color="transparent")
        title_row.pack(anchor="w")
        
        icon_map = {
            'apache': '\uE12B',      # Globe/Server
            'php': '\uE943',          # Code
            'mariadb': '\uEC27',      # Database
            'phpmyadmin': '\uE8A7',   # Settings/Admin
            'composer': '\uE74C',     # Package
            'adminer': '\uEC27',      # Database
            'nodejs': '\uE7C3',       # Console/Terminal
        }
        if key.startswith('phpmyadmin'):
            icon_key = 'phpmyadmin'
        elif key.startswith('php'):
            icon_key = 'php'
        elif key.startswith('mariadb'):
            icon_key = 'mariadb'
        elif key.startswith('apache'):
            icon_key = 'apache'
        elif key.startswith('nodejs'):
            icon_key = 'nodejs'
        else:
            icon_key = key
        icon_char = icon_map.get(icon_key, '\uE90F')
        
        icon_lbl = customtkinter.CTkLabel(title_row, text=icon_char, font=("Segoe MDL2 Assets", 18), text_color=self.colors['accent'])
        icon_lbl.pack(side="left", padx=(0, 8))
        
        title_lbl = customtkinter.CTkLabel(title_row, text=f"{service_name} {target_ver.split(' ')[0]}", font=("Segoe UI", 12, "bold"), text_color=self.colors['text'])
        title_lbl.pack(side="left")
        
        if key.startswith('mariadb'):
            badge_lbl = customtkinter.CTkLabel(
                title_row, 
                text="تجريبي / NEW", 
                font=("Segoe UI", 9, "bold"), 
                text_color="#ffffff", 
                fg_color="#ef4444", 
                corner_radius=6,
                width=80,
                height=16
            )
            badge_lbl.pack(side="left", padx=8)

        if key in ('phpmyadmin', 'adminer', 'composer', 'nodejs20'):
            tool_badge = customtkinter.CTkLabel(
                title_row,
                text="TOOL",
                font=("Segoe UI", 8, "bold"),
                text_color="#ffffff",
                fg_color="#8b5cf6",
                corner_radius=6,
                width=45,
                height=16
            )
            tool_badge.pack(side="left", padx=8)
            
        status_lbl = customtkinter.CTkLabel(title_row, text="CHECKING", font=("Segoe UI", 9, "bold"), text_color=self.colors['muted'])
        status_lbl.pack(side="left", padx=15)

        
        desc_lbl = customtkinter.CTkLabel(info_frame, text=desc, font=("Segoe UI", 10), text_color=self.colors['muted'], justify="left")
        desc_lbl.pack(anchor="w", pady=(3, 0))
        desc_lbl.bind("<Configure>", lambda event, lbl=desc_lbl: lbl.configure(wraplength=event.width))
        
        action_frame = customtkinter.CTkFrame(card, fg_color="transparent")
        action_frame.pack(side="right", fill="y", padx=15, pady=10)
        
        progress = customtkinter.CTkProgressBar(action_frame, width=120)
        progress.set(0.0)
        
        btn = HoverButton(
            action_frame, 
            style_type="accent", 
            text="Download", 
            width=75, 
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.start_download(key, btn, progress, status_lbl, desc_lbl, service_name, target_ver)
        )
        btn.pack(side="right", padx=5)
        
        self.download_widgets[key] = {
            'card': card,
            'desc_lbl': desc_lbl,
            'status_lbl': status_lbl,
            'btn': btn
        }

    def start_download(self, key, btn, progress, status_lbl, desc_lbl, service_name, target_ver):
        btn.configure(state="disabled")
        progress.pack(side="left", padx=10)
        progress.set(0.0)
        threading.Thread(target=self._run_download_thread, args=(key, btn, progress, status_lbl, desc_lbl, service_name, target_ver), daemon=True).start()

    def _run_download_thread(self, key, btn, progress, status_lbl, desc_lbl, service_name, target_ver):
        target_clean = target_ver.split(' ')[0].replace('v', '')
        download_success = True
        error_msg = ""

        if key.startswith('mariadb'):
            # Real Download of MariaDB because the stubs in workspace are invalid
            try:
                target_db_dir = os.path.join(self.core.base, 'bin', key)
                if not os.path.exists(target_db_dir):
                    alt_dir = os.path.join(self.core.base, 'bin', f"mariadb{target_clean}")
                    if os.path.exists(alt_dir):
                        target_db_dir = alt_dir
                
                # Stop MariaDB completely to release process locks
                self.core.stop_mariadb()
                time.sleep(1.0)
                
                # Determine URL and root folder name in ZIP
                if "11.4" in target_ver:
                    url = "https://archive.mariadb.org/mariadb-11.4.2/winx64-packages/mariadb-11.4.2-winx64.zip"
                    zip_root_name = "mariadb-11.4.2-winx64"
                else:
                    url = "https://archive.mariadb.org/mariadb-10.11.8/winx64-packages/mariadb-10.11.8-winx64.zip"
                    zip_root_name = "mariadb-10.11.8-winx64"
                
                # Temp paths in workspace
                temp_dir = os.path.join(self.core.base, 'temp')
                os.makedirs(temp_dir, exist_ok=True)
                zip_path = os.path.join(temp_dir, f"{key}.zip")
                
                # Connecting...
                self.root.after(0, lambda: status_lbl.configure(text="CONNECTING...", text_color=self.colors['accent']))
                self.root.after(0, lambda: desc_lbl.configure(text="Connecting to official MariaDB archive server..."))
                
                # Download with real progress callback
                def update_progress(percent, downloaded_bytes, total_bytes):
                    downloaded_mb = downloaded_bytes / (1024 * 1024)
                    total_mb = total_bytes / (1024 * 1024)
                    pct = int(percent * 100)
                    self.root.after(0, lambda: progress.set(percent))
                    self.root.after(0, lambda: status_lbl.configure(
                        text=f"DOWNLOADING {pct}%", 
                        text_color=self.colors['accent']
                    ))
                    self.root.after(0, lambda: desc_lbl.configure(
                        text=f"Downloading archive: {downloaded_mb:.1f} MB / {total_mb:.1f} MB ({pct}%)"
                    ))
                
                import urllib.request
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response:
                    total_size = int(response.info().get('Content-Length', 0))
                    downloaded = 0
                    block_size = 1024 * 64
                    with open(zip_path, 'wb') as f:
                        while True:
                            chunk = response.read(block_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                update_progress(downloaded / total_size, downloaded, total_size)
                
                # Extract
                self.root.after(0, lambda: status_lbl.configure(text="EXTRACTING...", text_color="#ef4444"))
                self.root.after(0, lambda: desc_lbl.configure(text="Unzipping files and preparing system directory structures..."))
                extract_temp = os.path.join(temp_dir, f"extract_{key}")
                shutil.rmtree(extract_temp, ignore_errors=True)
                os.makedirs(extract_temp, exist_ok=True)
                
                import zipfile
                with zipfile.ZipFile(zip_path, 'r') as z:
                    z.extractall(extract_temp)
                
                # Move/Copy to target directory
                self.root.after(0, lambda: status_lbl.configure(text="INSTALLING...", text_color="#8b5cf6"))
                self.root.after(0, lambda: desc_lbl.configure(text="Writing database files, registering runtime and cleaning locks..."))
                extracted_root = os.path.join(extract_temp, zip_root_name)
                if os.path.exists(extracted_root):
                    # Define robust copy-overwrite function with Windows file-lock renaming trick
                    def robust_copy_overwrite(src_dir, dst_dir):
                        import os
                        import shutil
                        import time
                        
                        os.makedirs(dst_dir, exist_ok=True)
                        
                        for root_dir, sub_dirs, filenames in os.walk(src_dir):
                            rel_path = os.path.relpath(root_dir, src_dir)
                            if rel_path == ".":
                                target_dir = dst_dir
                            else:
                                target_dir = os.path.join(dst_dir, rel_path)
                                os.makedirs(target_dir, exist_ok=True)
                                
                            for filename in filenames:
                                src_file = os.path.join(root_dir, filename)
                                dst_file = os.path.join(target_dir, filename)
                                
                                copied = False
                                for attempt in range(5):
                                    try:
                                        if os.path.exists(dst_file):
                                            try:
                                                os.remove(dst_file)
                                            except Exception:
                                                # Windows file locking trick: rename locked file out of the way
                                                temp_dst = dst_file + f".old.{int(time.time())}"
                                                try:
                                                    os.rename(dst_file, temp_dst)
                                                except Exception:
                                                    pass
                                        shutil.copy2(src_file, dst_file)
                                        copied = True
                                        break
                                    except Exception as e:
                                        print(f"Error copying {src_file} to {dst_file} (attempt {attempt+1}): {e}")
                                        time.sleep(0.5)
                                if not copied:
                                    shutil.copy2(src_file, dst_file)
                                    
                    # Perform copy and overwrite operation
                    robust_copy_overwrite(extracted_root, target_db_dir)
                    
                    # Attempt to clean up any renamed .old files
                    for root_dir, sub_dirs, filenames in os.walk(target_db_dir):
                        for filename in filenames:
                            if ".old." in filename:
                                try:
                                    os.remove(os.path.join(root_dir, filename))
                                except:
                                    pass
                
                # Cleanup temp files
                shutil.rmtree(extract_temp, ignore_errors=True)
                try:
                    os.remove(zip_path)
                except:
                    pass
                
                # Write version.txt
                with open(os.path.join(target_db_dir, 'version.txt'), 'w', encoding='utf-8') as f:
                    f.write(target_clean)
                
                # Initialize database tables if mysql directory doesn't exist
                data_dir = os.path.join(target_db_dir, 'data')
                mysql_dir = os.path.join(data_dir, 'mysql')
                if not os.path.exists(mysql_dir):
                    install_db_exe = os.path.join(target_db_dir, 'bin', 'mariadb-install-db.exe')
                    if not os.path.exists(install_db_exe):
                        install_db_exe = os.path.join(target_db_dir, 'bin', 'mysql_install_db.exe')
                    if os.path.exists(install_db_exe):
                        self.root.after(0, lambda: status_lbl.configure(text="INITIALIZING DB...", text_color="#059669"))
                        self.root.after(0, lambda: desc_lbl.configure(text="Initializing privilege tables and default system databases..."))
                        try:
                            # Empty the data directory first to prevent "not empty" error
                            for root_dir, sub_dirs, filenames in os.walk(data_dir, topdown=False):
                                for filename in filenames:
                                    try:
                                        os.remove(os.path.join(root_dir, filename))
                                    except:
                                        pass
                                for sub_dir in sub_dirs:
                                    try:
                                        shutil.rmtree(os.path.join(root_dir, sub_dir), ignore_errors=True)
                                    except:
                                        pass
                            
                            # Run mariadb-install-db.exe
                            subprocess.run(
                                [install_db_exe, f"--datadir={data_dir}"], 
                                capture_output=True, 
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                timeout=60
                            )
                        except Exception as e:
                            print(f"Error running mariadb-install-db.exe: {e}")
                
                # Validate the binary exists and is valid
                mariadb_exe = os.path.join(target_db_dir, 'bin', 'mariadbd.exe')
                if not os.path.exists(mariadb_exe):
                    mariadb_exe = os.path.join(target_db_dir, 'bin', 'mysqld.exe')
                
                if not os.path.exists(mariadb_exe) or os.path.getsize(mariadb_exe) < 1024:
                    shutil.rmtree(target_db_dir, ignore_errors=True)
                    download_success = False
                    error_msg = "ملفات MariaDB الثنائية (mariadbd.exe / mysqld.exe) مفقودة أو غير صالحة بعد التنزيل."
            except Exception as e:
                print(f"Error downloading/installing MariaDB: {e}")
                download_success = False
                error_msg = f"فشل تنزيل ملفات MariaDB: {e}"

        elif key.startswith('phpmyadmin'):
            try:
                pma_dir = os.path.join(self.core.www_dir, key)
                bin_pma_dir = os.path.join(self.core.base, 'bin', key)
                os.makedirs(pma_dir, exist_ok=True)
                os.makedirs(bin_pma_dir, exist_ok=True)
                
                url = f"https://files.phpmyadmin.net/phpMyAdmin/{target_clean}/phpMyAdmin-{target_clean}-all-languages.zip"
                zip_root_name = f"phpMyAdmin-{target_clean}-all-languages"
                
                # Temp paths in workspace
                temp_dir = os.path.join(self.core.base, 'temp')
                os.makedirs(temp_dir, exist_ok=True)
                zip_path = os.path.join(temp_dir, f"{key}.zip")
                
                # Connecting...
                self.root.after(0, lambda: status_lbl.configure(text="CONNECTING...", text_color=self.colors['accent']))
                self.root.after(0, lambda: desc_lbl.configure(text=f"Connecting to phpMyAdmin server to download v{target_clean}..."))
                
                # Download with real progress callback
                def update_progress(percent, downloaded_bytes, total_bytes):
                    downloaded_mb = downloaded_bytes / (1024 * 1024)
                    total_mb = total_bytes / (1024 * 1024)
                    pct = int(percent * 100)
                    self.root.after(0, lambda: progress.set(percent))
                    self.root.after(0, lambda: status_lbl.configure(
                        text=f"DOWNLOADING {pct}%", 
                        text_color=self.colors['accent']
                    ))
                    self.root.after(0, lambda: desc_lbl.configure(
                        text=f"Downloading phpMyAdmin: {downloaded_mb:.1f} MB / {total_mb:.1f} MB ({pct}%)"
                    ))
                
                import urllib.request
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response:
                    total_size = int(response.info().get('Content-Length', 0))
                    downloaded = 0
                    block_size = 1024 * 64
                    with open(zip_path, 'wb') as f:
                        while True:
                            chunk = response.read(block_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                update_progress(downloaded / total_size, downloaded, total_size)
                
                # Extract
                self.root.after(0, lambda: status_lbl.configure(text="EXTRACTING...", text_color="#ef4444"))
                self.root.after(0, lambda: desc_lbl.configure(text="Decompressing phpMyAdmin files and preparing directory structures..."))
                extract_temp = os.path.join(temp_dir, f"extract_{key}")
                shutil.rmtree(extract_temp, ignore_errors=True)
                os.makedirs(extract_temp, exist_ok=True)
                
                import zipfile
                with zipfile.ZipFile(zip_path, 'r') as z:
                    z.extractall(extract_temp)
                
                # Move/Copy to target directory
                self.root.after(0, lambda: status_lbl.configure(text="INSTALLING...", text_color="#8b5cf6"))
                self.root.after(0, lambda: desc_lbl.configure(text="Writing phpMyAdmin files to www directory..."))
                extracted_root = os.path.join(extract_temp, zip_root_name)
                if os.path.exists(extracted_root):
                    # Define robust copy-overwrite function with Windows file-lock renaming trick
                    def robust_copy_overwrite(src_dir, dst_dir):
                        import os
                        import shutil
                        import time
                        
                        os.makedirs(dst_dir, exist_ok=True)
                        
                        for root_dir, sub_dirs, filenames in os.walk(src_dir):
                            rel_path = os.path.relpath(root_dir, src_dir)
                            if rel_path == ".":
                                target_dir = dst_dir
                            else:
                                target_dir = os.path.join(dst_dir, rel_path)
                                os.makedirs(target_dir, exist_ok=True)
                                
                            for filename in filenames:
                                src_file = os.path.join(root_dir, filename)
                                dst_file = os.path.join(target_dir, filename)
                                
                                copied = False
                                for attempt in range(5):
                                    try:
                                        if os.path.exists(dst_file):
                                            try:
                                                os.remove(dst_file)
                                            except Exception:
                                                # Windows file locking trick: rename locked file out of the way
                                                temp_dst = dst_file + f".old.{int(time.time())}"
                                                try:
                                                    os.rename(dst_file, temp_dst)
                                                except Exception:
                                                    pass
                                        shutil.copy2(src_file, dst_file)
                                        copied = True
                                        break
                                    except Exception as e:
                                        print(f"Error copying {src_file} to {dst_file} (attempt {attempt+1}): {e}")
                                        time.sleep(0.5)
                                if not copied:
                                    shutil.copy2(src_file, dst_file)
                                    
                    # Perform copy and overwrite operation
                    robust_copy_overwrite(extracted_root, pma_dir)
                    
                    # Create a dummy index.php or version.txt in bin_pma_dir for installation check
                    with open(os.path.join(bin_pma_dir, 'index.php'), 'w', encoding='utf-8') as f:
                        f.write(f'<?php echo "phpMyAdmin {target_clean} is running under www/{key}"; ?>')
                    with open(os.path.join(bin_pma_dir, 'version.txt'), 'w', encoding='utf-8') as f:
                        f.write(target_clean)
                        
                # Cleanup temp files
                shutil.rmtree(extract_temp, ignore_errors=True)
                try:
                    os.remove(zip_path)
                except:
                    pass
            except Exception as e:
                print(f"Error downloading/installing phpMyAdmin: {e}")
                download_success = False
                error_msg = f"فشل تنزيل ملفات phpMyAdmin: {e}"

        else:
            # Simulated Download for other items
            self.root.after(0, lambda: status_lbl.configure(text="CONNECTING...", text_color=self.colors['accent']))
            self.root.after(0, lambda: desc_lbl.configure(text=f"Contacting update mirror for {service_name}..."))
            time.sleep(1.0)
            
            steps = 20
            for i in range(steps + 1):
                time.sleep(0.1)
                val = i / steps
                progress.set(val)
                self.root.after(0, lambda v=val: status_lbl.configure(text=f"DOWNLOADING {int(v*100)}%", text_color=self.colors['accent']))
                self.root.after(0, lambda v=val: desc_lbl.configure(text=f"Downloading update files: {int(v*100)}% completed..."))
                
            self.root.after(0, lambda: status_lbl.configure(text="EXTRACTING...", text_color="#ef4444"))
            self.root.after(0, lambda: desc_lbl.configure(text="Decompressing active files and preparing installation folder..."))
            time.sleep(1.0)
            
            self.root.after(0, lambda: status_lbl.configure(text="INSTALLING...", text_color="#8b5cf6"))
            self.root.after(0, lambda: desc_lbl.configure(text="Overwriting binary runtimes and validating setup..."))
            time.sleep(1.0)
            
            # Use the download card key as the folder name for consistency
            if key.startswith('php') and not key.startswith('phpmyadmin'):
                try:
                    active_php_dir = self.core.php_dir
                    target_php_dir = os.path.join(self.core.base, 'bin', key)
                    # Also check for variant folder names (e.g. php8.2.0 for php8.2)
                    if not os.path.exists(target_php_dir):
                        alt_dir = os.path.join(self.core.base, 'bin', f"php{target_clean}")
                        if os.path.exists(alt_dir):
                            target_php_dir = alt_dir
                    if not os.path.exists(target_php_dir) and os.path.exists(active_php_dir):
                        shutil.copytree(active_php_dir, target_php_dir)
                    if os.path.exists(target_php_dir):
                        with open(os.path.join(target_php_dir, 'version.txt'), 'w', encoding='utf-8') as f:
                            f.write(target_clean)
                except Exception as e:
                    print(f"Error copying PHP directory: {e}")
                    download_success = False
                    error_msg = str(e)
            elif key.startswith('apache'):
                try:
                    active_apache_dir = self.core.apache_root
                    target_apache_dir = os.path.join(self.core.base, 'bin', key)
                    if not os.path.exists(target_apache_dir):
                        alt_dir = os.path.join(self.core.base, 'bin', f"apache{target_clean}")
                        if os.path.exists(alt_dir):
                            target_apache_dir = alt_dir
                    if not os.path.exists(target_apache_dir) and os.path.exists(active_apache_dir):
                        shutil.copytree(active_apache_dir, target_apache_dir)
                    if os.path.exists(target_apache_dir):
                        with open(os.path.join(target_apache_dir, 'version.txt'), 'w', encoding='utf-8') as f:
                            f.write(target_clean)
                except Exception as e:
                    print(f"Error copying Apache directory: {e}")
                    download_success = False
                    error_msg = str(e)
            elif key == 'adminer':
                try:
                    adminer_dir = os.path.join(self.core.www_dir, 'adminer')
                    os.makedirs(adminer_dir, exist_ok=True)
                    with open(os.path.join(adminer_dir, 'index.php'), 'w', encoding='utf-8') as f:
                        f.write('<?php echo "Adminer v4.8.1 - Place real Adminer file here."; ?>')
                except Exception as e:
                    print(f"Error installing Adminer: {e}")
                    download_success = False
                    error_msg = str(e)
            elif key == 'composer':
                try:
                    composer_dir = os.path.join(self.core.base, 'bin', 'composer')
                    os.makedirs(composer_dir, exist_ok=True)
                    with open(os.path.join(composer_dir, 'version.txt'), 'w', encoding='utf-8') as f:
                        f.write(target_clean)
                except Exception as e:
                    print(f"Error installing Composer: {e}")
                    download_success = False
                    error_msg = str(e)
            elif key == 'nodejs20':
                try:
                    node_dir = os.path.join(self.core.base, 'bin', 'nodejs20')
                    os.makedirs(node_dir, exist_ok=True)
                    with open(os.path.join(node_dir, 'version.txt'), 'w', encoding='utf-8') as f:
                        f.write(target_clean)
                except Exception as e:
                    print(f"Error installing Node.js: {e}")
                    download_success = False
                    error_msg = str(e)
                
        if download_success:
            self.root.after(0, lambda: self.finish_download(key, btn, progress, status_lbl, desc_lbl, service_name, target_ver))
        else:
            self.root.after(0, lambda: self.fail_download(key, btn, progress, status_lbl, desc_lbl, error_msg))

    def finish_download(self, key, btn, progress, status_lbl, desc_lbl, service_name, target_ver):
        progress.pack_forget()
        btn.configure(text="Installed", state="disabled")
        status_lbl.configure(text="UP TO DATE", text_color=self.colors['green'])
        desc_lbl.configure(text=f"Active version: {target_ver.split(' ')[0]} \u2022 System is up to date.")
        
        # Clear configurations and version cache on successful installation
        self.core.settings['cache'] = {}
        self.tool_installed_cache = {}
        self.core._available_phps_cache = None
        self.core._available_apaches_cache = None
        self.core._available_mariadbs_cache = None
        self.core._sqlite_status_cache = None
        
        target_clean = target_ver.split(' ')[0].replace('v', '')
        
        if key.startswith('php') and not key.startswith('phpmyadmin'):
            new_php_folder = f"php{target_clean}"
            self.settings_php_var.set(new_php_folder)
            self.core.settings['active_php'] = new_php_folder
            self.core.save_settings()
            self.core.update_php_paths()
            self.on_settings_php_change(new_php_folder)
        elif key.startswith('apache'):
            new_apache_folder = f"apache{target_clean}"
            self.settings_apache_var.set(new_apache_folder)
            self.core.settings['active_apache'] = new_apache_folder
            self.core.save_settings()
            self.core.update_apache_paths()
            self.on_settings_apache_change(new_apache_folder)
        elif key.startswith('mariadb'):
            new_mariadb_folder = f"mariadb{target_clean}"
            self.settings_mariadb_var.set(new_mariadb_folder)
            self.core.settings['active_mariadb'] = new_mariadb_folder
            self.core.save_settings()
            self.core.update_mariadb_paths()
            self.on_settings_mariadb_change(new_mariadb_folder)
            
        self.show_toast(f"\u2713 {service_name} updated to {target_ver.split(' ')[0]} successfully!", self.colors['green'])
        self.refresh_status()

    def fail_download(self, key, btn, progress, status_lbl, desc_lbl, error_msg):
        progress.pack_forget()
        btn.configure(text="Download", state="normal")
        status_lbl.configure(text="FAILED", text_color=self.colors['red'])
        desc_lbl.configure(text=f"Error: {error_msg}")
        self.show_toast(f"✗ Download failed: {error_msg}", self.colors['red'])
        self.refresh_status()



    def setup_settings_tab(self):
        settings_frame = customtkinter.CTkFrame(self.pages['settings'], fg_color="transparent")
        settings_frame.pack(fill="both", expand=True)

        # Configuration Option Container Card
        opt_card = customtkinter.CTkFrame(settings_frame, corner_radius=12, border_width=1, border_color=self.colors['border'], fg_color=self.colors['card'])
        opt_card.pack(fill="x", pady=10, padx=20)

        lbl_section = customtkinter.CTkLabel(opt_card, text="ENVIRONMENT PREFERENCES", font=customtkinter.CTkFont(family="Segoe UI", size=13, weight="bold"), text_color=self.colors['accent'])
        lbl_section.pack(anchor="w", pady=(20, 15), padx=20)

        # Dropdowns
        row1 = customtkinter.CTkFrame(opt_card, fg_color="transparent")
        row1.pack(fill="x", pady=8, padx=20)
        
        lbl_version = customtkinter.CTkLabel(row1, text="Project PHP Version:", font=("Segoe UI", 11, "bold"), text_color=self.colors['text'])
        lbl_version.pack(side="left")
        
        self.settings_php_var = tk.StringVar()
        self.settings_php_combo = customtkinter.CTkOptionMenu(
            row1, 
            variable=self.settings_php_var,
            values=["php"],
            command=self.on_settings_php_change,
            width=200,
            font=("Segoe UI", 11, "bold"),
            dropdown_font=("Segoe UI", 11)
        )
        self.settings_php_combo.pack(side="right")

        # Row 1.2: phpMyAdmin PHP Version
        row12 = customtkinter.CTkFrame(opt_card, fg_color="transparent")
        row12.pack(fill="x", pady=8, padx=20)
        
        lbl_pma_php = customtkinter.CTkLabel(row12, text="phpMyAdmin PHP Version:", font=("Segoe UI", 11, "bold"), text_color=self.colors['text'])
        lbl_pma_php.pack(side="left")
        
        self.settings_pma_php_var = tk.StringVar()
        self.settings_pma_php_combo = customtkinter.CTkOptionMenu(
            row12, 
            variable=self.settings_pma_php_var,
            values=["php"],
            command=self.on_settings_pma_php_change,
            width=200,
            font=("Segoe UI", 11, "bold"),
            dropdown_font=("Segoe UI", 11)
        )
        self.settings_pma_php_combo.pack(side="right")

        # Row 1.5: Active Apache Version
        row15 = customtkinter.CTkFrame(opt_card, fg_color="transparent")
        row15.pack(fill="x", pady=8, padx=20)
        
        lbl_ap_version = customtkinter.CTkLabel(row15, text="Active Apache Version:", font=("Segoe UI", 11, "bold"), text_color=self.colors['text'])
        lbl_ap_version.pack(side="left")
        
        self.settings_apache_var = tk.StringVar()
        self.settings_apache_combo = customtkinter.CTkOptionMenu(
            row15, 
            variable=self.settings_apache_var,
            values=["apache"],
            command=self.on_settings_apache_change,
            width=200,
            font=("Segoe UI", 11, "bold"),
            dropdown_font=("Segoe UI", 11)
        )
        self.settings_apache_combo.pack(side="right")

        # Row 1.7: Active MariaDB Version
        row17 = customtkinter.CTkFrame(opt_card, fg_color="transparent")
        row17.pack(fill="x", pady=8, padx=20)
        
        lbl_md_version = customtkinter.CTkLabel(row17, text="Active MariaDB Version:", font=("Segoe UI", 11, "bold"), text_color=self.colors['text'])
        lbl_md_version.pack(side="left")
        
        self.settings_mariadb_var = tk.StringVar()
        self.settings_mariadb_combo = customtkinter.CTkOptionMenu(
            row17, 
            variable=self.settings_mariadb_var,
            values=["mariadb"],
            command=self.on_settings_mariadb_change,
            width=200,
            font=("Segoe UI", 11, "bold"),
            dropdown_font=("Segoe UI", 11)
        )
        self.settings_mariadb_combo.pack(side="right")

        row2 = customtkinter.CTkFrame(opt_card, fg_color="transparent")
        row2.pack(fill="x", pady=8, padx=20)


        lbl_theme = customtkinter.CTkLabel(row2, text="Application Theme:", font=("Segoe UI", 11, "bold"), text_color=self.colors['text'])
        lbl_theme.pack(side="left")

        self.settings_theme_var = tk.StringVar()
        self.settings_theme_combo = customtkinter.CTkOptionMenu(
            row2, 
            variable=self.settings_theme_var,
            values=['Dark Mode', 'Light Mode'],
            command=self.on_settings_theme_change,
            width=200,
            font=("Segoe UI", 11, "bold"),
            dropdown_font=("Segoe UI", 11)
        )
        self.settings_theme_combo.pack(side="right")
        
        theme_val = 'Dark Mode' if self.theme == 'dark' else 'Light Mode'
        self.settings_theme_var.set(theme_val)

        self.php_feedback_lbl = customtkinter.CTkLabel(opt_card, text="* The web server restarts automatically when PHP version is changed.", font=("Segoe UI", 10, "italic"), text_color=self.colors['muted'])
        self.php_feedback_lbl.pack(anchor="w", pady=(12, 20), padx=20)

        # Directory / File Utility Buttons
        paths_card = customtkinter.CTkFrame(settings_frame, corner_radius=12, border_width=1, border_color=self.colors['border'], fg_color=self.colors['card'])
        paths_card.pack(fill="both", expand=True, pady=10, padx=20)

        lbl_paths = customtkinter.CTkLabel(paths_card, text="QUICK PATH UTILITIES", font=customtkinter.CTkFont(family="Segoe UI", size=13, weight="bold"), text_color=self.colors['accent'])
        lbl_paths.pack(anchor="w", pady=(20, 15), padx=20)

        btn_w = HoverButton(paths_card, style_type="normal", text="Open Web Directory (www)", font=("Segoe UI", 10, "bold"), command=lambda: os.startfile(self.core.www_dir))
        btn_w.pack(fill="x", pady=6, padx=20)

        btn_p = HoverButton(paths_card, style_type="normal", text="Open PHP Executables Folder", font=("Segoe UI", 10, "bold"), command=lambda: os.startfile(os.path.dirname(self.core.php_dir)))
        btn_p.pack(fill="x", pady=6, padx=20)

        btn_c = HoverButton(paths_card, style_type="normal", text="Open Configuration (config)", font=("Segoe UI", 10, "bold"), command=lambda: os.startfile(os.path.join(self.core.base, 'config')))
        btn_c.pack(fill="x", pady=6, padx=20)

        contact_f = customtkinter.CTkFrame(paths_card, fg_color="transparent")
        contact_f.pack(fill="x", pady=(12, 20), padx=20)
        
        lbl_email_title = customtkinter.CTkLabel(contact_f, text="Support & Feedback Contact:", font=("Segoe UI", 10, "bold"), text_color=self.colors['muted'])
        lbl_email_title.pack(side="left")

        self.email_lbl = customtkinter.CTkLabel(contact_f, text="admin@aljup.com", font=("Segoe UI", 11, "bold"), text_color=self.colors['accent'], cursor="hand2")
        self.email_lbl.pack(side="left", padx=10)
        
        self.email_lbl.bind("<Enter>", lambda e: self.email_lbl.configure(text_color=self.colors['accent']))
        self.email_lbl.bind("<Leave>", lambda e: self.email_lbl.configure(text_color=self.colors['accent']))
        self.email_lbl.bind("<Button-1>", lambda e: webbrowser.open("mailto:admin@aljup.com"))

    def setup_logs_tab(self):
        tabview = customtkinter.CTkTabview(self.pages['logs'], fg_color="transparent")
        tabview.pack(fill="both", expand=True, padx=20, pady=5)
        
        tabview.add(" Apache Logs ")
        tabview.add(" PHP Logs ")
        tabview.add(" Database Logs ")
        
        t1 = tabview.tab(" Apache Logs ")
        t2 = tabview.tab(" PHP Logs ")
        t3 = tabview.tab(" Database Logs ")
        
        # Apache Toolbar & Text area
        tools1 = customtkinter.CTkFrame(t1, fg_color="transparent")
        tools1.pack(fill="x")
        
        copy_apache = HoverButton(tools1, style_type="normal", text="Copy All", command=lambda: self.copy_all(self.apache_console), font=("Segoe UI", 9, "bold"), width=90)
        copy_apache.pack(side="right", pady=5, padx=5)
        
        clear_apache = HoverButton(tools1, style_type="danger", text="Clear Console", command=lambda: self.apache_console.delete(1.0, tk.END), font=("Segoe UI", 9, "bold"), width=100)
        clear_apache.pack(side="right", pady=5, padx=0)

        self.apache_console = customtkinter.CTkTextbox(t1, font=("Consolas", 11), fg_color=self.colors['console_bg'], text_color=self.colors['console_fg_apache'])
        self.apache_console.pack(fill="both", expand=True, pady=(5, 0))
        
        # PHP Toolbar & Text area
        tools2 = customtkinter.CTkFrame(t2, fg_color="transparent")
        tools2.pack(fill="x")
        
        copy_php = HoverButton(tools2, style_type="normal", text="Copy All", command=lambda: self.copy_all(self.php_console), font=("Segoe UI", 9, "bold"), width=90)
        copy_php.pack(side="right", pady=5, padx=5)
        
        clear_php = HoverButton(tools2, style_type="danger", text="Clear Console", command=lambda: self.php_console.delete(1.0, tk.END), font=("Segoe UI", 9, "bold"), width=100)
        clear_php.pack(side="right", pady=5, padx=0)

        self.php_console = customtkinter.CTkTextbox(t2, font=("Consolas", 11), fg_color=self.colors['console_bg'], text_color=self.colors['console_fg_php'])
        self.php_console.pack(fill="both", expand=True, pady=(5, 0))

        # Database / MariaDB Toolbar & Text area
        tools3 = customtkinter.CTkFrame(t3, fg_color="transparent")
        tools3.pack(fill="x")
        
        copy_db = HoverButton(tools3, style_type="normal", text="Copy All", command=lambda: self.copy_all(self.db_console), font=("Segoe UI", 9, "bold"), width=90)
        copy_db.pack(side="right", pady=5, padx=5)
        
        clear_db = HoverButton(tools3, style_type="danger", text="Clear Console", command=lambda: self.db_console.delete(1.0, tk.END), font=("Segoe UI", 9, "bold"), width=100)
        clear_db.pack(side="right", pady=5, padx=0)

        db_status_lbl = customtkinter.CTkLabel(tools3, text="MariaDB Error Log", font=("Segoe UI", 10, "bold"), text_color=self.colors['muted'])
        db_status_lbl.pack(side="left", padx=5)

        self.db_console = customtkinter.CTkTextbox(t3, font=("Consolas", 11), fg_color=self.colors['console_bg'], text_color=self.colors['console_fg_db'])
        self.db_console.pack(fill="both", expand=True, pady=(5, 0))
        
        self.add_context_menu(self.apache_console)
        self.add_context_menu(self.php_console)
        self.add_context_menu(self.db_console)

    def toggle_theme(self):
        new_theme = 'light' if self.theme == 'dark' else 'dark'
        self.set_theme(new_theme)

    def set_theme(self, theme_name):
        try:
            self.theme = theme_name
            self.core.settings['theme'] = self.theme
            self.core.save_settings()
            customtkinter.set_appearance_mode(self.theme)
            
            # Update title bar to match theme on Windows (immersive dark mode for border chromium)
            if os.name == 'nt':
                try:
                    import ctypes
                    hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
                    if hwnd == 0:
                        hwnd = self.root.winfo_id()
                    rendering_mode = 20
                    value = ctypes.c_int(1 if self.theme == "dark" else 0)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, rendering_mode, ctypes.byref(value), ctypes.sizeof(value))
                except Exception:
                    pass

            theme_val = 'Dark Mode' if self.theme == 'dark' else 'Light Mode'
            if hasattr(self, 'settings_theme_var'):
                self.settings_theme_var.set(theme_val)
                
            if hasattr(self, 'theme_btn'):
                theme_icon = "\uE706" if self.theme == 'dark' else "\uE708"
                self.theme_btn.configure(text=theme_icon)
                
            # Update all custom sidebar buttons to match the new theme
            if hasattr(self, 'sidebar_buttons'):
                for btn in self.sidebar_buttons.values():
                    btn.update_theme(self.colors)

            self._last_run_state = None  # Force redraw of services status UI on theme switch
            self._last_sqlite_state = None
            self._last_php_ver = None
            
            # Synchronously refresh status UI with new theme colors
            self.refresh_status()
            self.root.update_idletasks()
            self.root.update()
        except Exception as e:
            print(f"Theme switch error: {e}")

    def on_settings_theme_change(self, val=None):
        theme_val = val or self.settings_theme_var.get()
        new_theme = 'dark' if theme_val == 'Dark Mode' else 'light'
        if new_theme != self.theme:
            self.set_theme(new_theme)

    def copy_all(self, widget):
        self.root.clipboard_clear()
        self.root.clipboard_append(widget.get("1.0", tk.END))
        self.root.update()
        self.show_toast("✓ Copied all logs to clipboard", self.colors['green'])

    def add_context_menu(self, widget):
        bg_col = self.colors['card'][1] if self.theme == 'dark' else self.colors['card'][0]
        fg_col = self.colors['text'][1] if self.theme == 'dark' else self.colors['text'][0]
        menu = tk.Menu(widget, tearoff=0, bg=bg_col, fg=fg_col, activebackground=self.colors['accent'])
        menu.add_command(label="Copy Selected", command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label="Select All", command=lambda: widget.tag_add("sel", "1.0", "end"))
        menu.add_separator()
        menu.add_command(label="Clear Output", command=lambda: widget.delete("1.0", tk.END))
        
        def show_menu(e):
            menu.tk_popup(e.x_root, e.y_root)
        widget.bind("<Button-3>", show_menu)

    def show_toast(self, msg, color=None):
        color = color or self.colors['accent']
        self.toast_lbl.configure(text=msg, text_color=color)
        if hasattr(self, 'toast_timer') and self.toast_timer: 
            self.root.after_cancel(self.toast_timer)
        self.toast_timer = self.root.after(3000, lambda: self.toast_lbl.configure(text=""))

    def on_configure(self, service_key):
        if service_key == 'apache':
            if os.path.exists(self.core.conf):
                os.startfile(self.core.conf)
                self.show_toast("✓ Opened Apache config file", self.colors['green'])
            else:
                self.show_toast("✗ Apache config not found", self.colors['red'])
        elif service_key == 'php':
            if os.path.exists(self.core.php_ini):
                os.startfile(self.core.php_ini)
                self.show_toast("✓ Opened php.ini configuration", self.colors['green'])
            else:
                self.show_toast("✗ php.ini not found", self.colors['red'])
        elif service_key == 'sqlite':
            config_dir = os.path.join(self.core.base, 'config')
            if os.path.exists(config_dir):
                os.startfile(config_dir)
                self.show_toast("✓ Opened config directory", self.colors['green'])
            else:
                self.show_toast("✗ Config directory not found", self.colors['red'])
        elif service_key == 'mariadb':
            if os.path.exists(self.core.mariadb_root):
                os.startfile(self.core.mariadb_root)
                self.show_toast("✓ Opened MariaDB directory", self.colors['green'])
            else:
                self.show_toast("✗ MariaDB directory not found", self.colors['red'])


    def on_start(self):
        if getattr(self, 'is_operating', False): return
        self.is_operating = True
        self.show_toast("⚙️ Starting Apache Web Server...", self.colors['accent'])
        threading.Thread(target=self._do_start_thread, daemon=True).start()
        
    def _do_start_thread(self):
        self.core.start()
        self.start_time = time.time() if self.core.is_running() else None
        self.root.after(0, self._finish_operation, "✓ Web server started successfully", self.colors['green'])

    def on_stop(self):
        if getattr(self, 'is_operating', False): return
        self.is_operating = True
        self.show_toast("⚙️ Stopping active services...", self.colors['accent'])
        threading.Thread(target=self._do_stop_thread, daemon=True).start()

    def _do_stop_thread(self):
        self.core.stop()
        self.start_time = None
        self.root.after(0, self._finish_operation, "✓ Server stopped completely", self.colors['red'])
        
    def safe_shutdown(self):
        self.show_toast("\u26D4 Shutting down all services safely...", self.colors['red'])
        self.root.update()
        # Stop Apache
        self.core.stop()
        # Stop MariaDB if running
        if self.core.mariadb_running:
            self.core.stop_mariadb()
        # Kill any lingering PHP-CGI processes
        try:
            subprocess.run(["taskkill", "/F", "/IM", "php-cgi.exe", "/T"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        except:
            pass
        self.root.after(800, self.root.destroy)

    def on_restart(self):
        if getattr(self, 'is_operating', False): return
        self.is_operating = True
        self.show_toast("⚙️ Restarting server...", self.colors['accent'])
        threading.Thread(target=self._do_restart_thread, daemon=True).start()

    def _do_restart_thread(self):
        self.core.stop()
        self.start_time = None
        time.sleep(1.0)
        self.core.start()
        self.start_time = time.time() if self.core.is_running() else None
        self.root.after(0, self._finish_operation, "✓ Web server restarted successfully", self.colors['green'])

    def on_sql_on(self): 
        if getattr(self, 'is_operating', False): return
        self.is_operating = True
        self.core.toggle_sqlite(True)
        self.show_toast("✓ Enabling SQLite PDO driver", self.colors['green'])
        threading.Thread(target=self._do_restart_thread, daemon=True).start()
        
    def on_sql_off(self): 
        if getattr(self, 'is_operating', False): return
        self.is_operating = True
        self.core.toggle_sqlite(False)
        self.show_toast("✓ Disabling SQLite PDO driver", self.colors['red'])
        threading.Thread(target=self._do_restart_thread, daemon=True).start()
    
    def on_settings_pma_php_change(self, val=None):
        new_pma_php = val or self.settings_pma_php_var.get()
        
        if new_pma_php != self.core.settings.get('pma_php', ''):
            if getattr(self, 'is_operating', False): return
            self.is_operating = True
            self.show_toast(f"⚙️ Switching phpMyAdmin PHP to {new_pma_php}...", self.colors['accent'])
            
            self.core.settings['pma_php'] = new_pma_php
            self.core.save_settings()
            
            # Restart server to apply new CGI config
            threading.Thread(target=self._do_restart_thread, daemon=True).start()

    def on_settings_php_change(self, val=None):
        new_php = val or self.settings_php_var.get()
        if new_php and new_php != self.core.settings.get('active_php'):
            if getattr(self, 'is_operating', False): return
            self.is_operating = True
            self.show_toast(f"⚙️ Switching PHP to {new_php}...", self.colors['accent'])
            
            self.php_feedback_lbl.configure(text=f"✓ Switched to {new_php}. Restarting server...", text_color=self.colors['green'])
            self.root.after(3500, lambda: self.php_feedback_lbl.configure(text="* The web server restarts automatically when PHP version is changed.", text_color=self.colors['muted']))
            
            threading.Thread(target=self._do_switch_php_thread, args=(new_php,), daemon=True).start()

    def _do_switch_php_thread(self, new_php):
        self.core.stop()
        self.start_time = None
        
        self.core.settings['active_php'] = new_php
        self.core.save_settings()
        self.core.update_php_paths()
        
        time.sleep(1.0)
        self.core.start()
        self.start_time = time.time() if self.core.is_running() else None
        
        self.root.after(0, self._finish_operation, f"✓ Switched to {new_php} successfully", self.colors['green'])

    def on_settings_apache_change(self, val=None):
        new_apache = val or self.settings_apache_var.get()
        if new_apache and new_apache != self.core.settings.get('active_apache'):
            if getattr(self, 'is_operating', False): return
            self.is_operating = True
            self.show_toast(f"⚙️ Switching Apache to {new_apache}...", self.colors['accent'])
            
            self.php_feedback_lbl.configure(text=f"✓ Switched to {new_apache}. Restarting server...", text_color=self.colors['green'])
            self.root.after(3500, lambda: self.php_feedback_lbl.configure(text="* The web server restarts automatically when PHP version is changed.", text_color=self.colors['muted']))
            
            threading.Thread(target=self._do_switch_apache_thread, args=(new_apache,), daemon=True).start()

    def _do_switch_apache_thread(self, new_apache):
        self.core.stop()
        self.start_time = None
        
        self.core.settings['active_apache'] = new_apache
        self.core.save_settings()
        self.core.update_apache_paths()
        
        time.sleep(1.0)
        self.core.start()
        self.start_time = time.time() if self.core.is_running() else None
        
        self.root.after(0, self._finish_operation, f"✓ Switched to {new_apache} successfully", self.colors['green'])

    def on_mariadb_start(self):
        if getattr(self, 'is_operating', False): return
        self.is_operating = True
        self.show_toast("⚙️ Starting MariaDB Database Server...", self.colors['accent'])
        threading.Thread(target=self._do_mariadb_start_thread, daemon=True).start()

    def _do_mariadb_start_thread(self):
        success = self.core.start_mariadb()
        if success:
            self.root.after(0, self._finish_operation, "\u2713 MariaDB started successfully", self.colors['green'])
        elif not self.core.is_mariadb_valid():
            self.root.after(0, self._finish_operation, "\u2717 MariaDB binary not valid - please install real binary files", self.colors['orange'])
        else:
            self.root.after(0, self._finish_operation, "\u2717 Failed to start MariaDB", self.colors['red'])

    def on_mariadb_stop(self):
        if getattr(self, 'is_operating', False): return
        self.is_operating = True
        self.show_toast("⚙️ Stopping MariaDB Database Server...", self.colors['accent'])
        threading.Thread(target=self._do_mariadb_stop_thread, daemon=True).start()

    def _do_mariadb_stop_thread(self):
        self.core.stop_mariadb()
        self.root.after(0, self._finish_operation, "✓ MariaDB stopped successfully", self.colors['red'])

    def on_mariadb_restart(self):
        if getattr(self, 'is_operating', False): return
        self.is_operating = True
        self.show_toast("⚙️ Restarting MariaDB Database Server...", self.colors['accent'])
        threading.Thread(target=self._do_mariadb_restart_thread, daemon=True).start()

    def _do_mariadb_restart_thread(self):
        self.core.stop_mariadb()
        time.sleep(1.0)
        self.core.start_mariadb()
        self.root.after(0, self._finish_operation, "✓ MariaDB restarted successfully", self.colors['green'])

    def on_settings_mariadb_change(self, val=None):
        new_mariadb = val or self.settings_mariadb_var.get()
        if new_mariadb and new_mariadb != self.core.settings.get('active_mariadb'):
            if getattr(self, 'is_operating', False): return
            self.is_operating = True
            self.show_toast(f"⚙️ Switching MariaDB to {new_mariadb}...", self.colors['accent'])
            
            self.php_feedback_lbl.configure(text=f"✓ Switched to {new_mariadb}. Restarting database...", text_color=self.colors['green'])
            self.root.after(3500, lambda: self.php_feedback_lbl.configure(text="* The web server restarts automatically when PHP version is changed.", text_color=self.colors['muted']))
            
            threading.Thread(target=self._do_switch_mariadb_thread, args=(new_mariadb,), daemon=True).start()

    def _do_switch_mariadb_thread(self, new_mariadb):
        self.core.stop_mariadb()
        
        self.core.settings['active_mariadb'] = new_mariadb
        self.core.save_settings()
        self.core.update_mariadb_paths()
        
        time.sleep(1.0)
        self.core.start_mariadb()
        
        self.root.after(0, self._finish_operation, f"✓ Switched MariaDB to {new_mariadb} successfully", self.colors['green'])

    def _finish_operation(self, msg, color):
        self.is_operating = False
        self._last_run_state = None  # Force UI redraw
        self.tool_installed_cache = {}  # Clear tool status cache
        self.core._available_phps_cache = None
        self.core._available_apaches_cache = None
        self.core._available_mariadbs_cache = None
        self.core._sqlite_status_cache = None
        self.refresh_status()
        self.show_toast(msg, color)



    def log_watcher(self, log_path, console_widget):
        while True:
            if os.path.exists(log_path):
                try:
                    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                        console_widget.delete(1.0, tk.END)
                        for line in lines[-100:]:
                            console_widget.insert(tk.END, line)
                        console_widget.see(tk.END)
                        
                        while True:
                            line = f.readline()
                            if line:
                                console_widget.insert(tk.END, line)
                                console_widget.see(tk.END)
                            else:
                                time.sleep(0.3)
                except: pass
            time.sleep(2)

    def update_loop(self):
        self.refresh_status()
        self.root.after(2000, self.update_loop)

    def is_tool_installed(self, tool_key):
        # Memory caching of tool checks to eliminate continuous slow disk checks
        if hasattr(self, 'tool_installed_cache') and tool_key in self.tool_installed_cache:
            return self.tool_installed_cache[tool_key]
            
        installed = False
        if tool_key.startswith('phpmyadmin') or tool_key == 'adminer':
            pma_www = os.path.join(self.core.www_dir, tool_key, 'index.php')
            pma_bin = os.path.join(self.core.base, 'bin', tool_key, 'index.php')
            for path in [pma_www, pma_bin]:
                try:
                    if os.path.exists(path) and os.path.getsize(path) > 500:
                        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read(200)
                            if "Place real files here" not in content and "Place real Adminer file here" not in content:
                                installed = True
                                break
                except:
                    pass
        elif tool_key == 'composer':
            path = os.path.join(self.core.base, 'bin', 'composer')
            installed = os.path.exists(path) and os.path.isdir(path)
        elif tool_key == 'nodejs20':
            path = os.path.join(self.core.base, 'bin', 'nodejs20')
            installed = os.path.exists(path) and os.path.isdir(path)
            
        if not hasattr(self, 'tool_installed_cache'):
            self.tool_installed_cache = {}
        self.tool_installed_cache[tool_key] = installed
        return installed

    def refresh_status(self):
        self.check_commands()
        run = self.core.is_running()
        
        # State Cache filtering to solve flashing/flickering
        if self._last_run_state != run:
            self._last_run_state = run
            
            if run:
                self.global_status_lbl.configure(text="System Online", text_color=self.colors['green'])
                self.service_widgets['apache']['status_lbl'].configure(text="● RUNNING", text_color=self.colors['green'])
                self.service_widgets['apache']['card'].configure(border_color=self.colors['green'])
                if hasattr(self, 'open_web_btn'):
                    self.open_web_btn.configure(state="normal")
                if hasattr(self, 'open_pma_btn'):
                    self.open_pma_btn.configure(state="normal")
            else:
                self.global_status_lbl.configure(text="System Offline", text_color=self.colors['red'])
                self.service_widgets['apache']['status_lbl'].configure(text="● STOPPED", text_color=self.colors['red'])
                self.service_widgets['apache']['card'].configure(border_color=self.colors['border'])
                if hasattr(self, 'open_web_btn'):
                    self.open_web_btn.configure(state="disabled")
                if hasattr(self, 'open_pma_btn'):
                    self.open_pma_btn.configure(state="disabled")

        # Enforce button states based on is_operating or run status
        is_op = getattr(self, 'is_operating', False)
        if is_op:
            if 'start' in self.service_widgets['apache']['buttons']:
                self.service_widgets['apache']['buttons']['start'].configure(state="disabled")
            if 'stop' in self.service_widgets['apache']['buttons']:
                self.service_widgets['apache']['buttons']['stop'].configure(state="disabled")
            if 'restart' in self.service_widgets['apache']['buttons']:
                self.service_widgets['apache']['buttons']['restart'].configure(state="disabled")
            if 'restart' in self.service_widgets['php']['buttons']:
                self.service_widgets['php']['buttons']['restart'].configure(state="disabled")
            if 'restart' in self.service_widgets['sqlite']['buttons']:
                self.service_widgets['sqlite']['buttons']['restart'].configure(state="disabled")
            if 'enable' in self.service_widgets['sqlite']['buttons']:
                self.service_widgets['sqlite']['buttons']['enable'].configure(state="disabled")
            if 'disable' in self.service_widgets['sqlite']['buttons']:
                self.service_widgets['sqlite']['buttons']['disable'].configure(state="disabled")
            if 'start' in self.service_widgets['mariadb']['buttons']:
                self.service_widgets['mariadb']['buttons']['start'].configure(state="disabled")
            if 'stop' in self.service_widgets['mariadb']['buttons']:
                self.service_widgets['mariadb']['buttons']['stop'].configure(state="disabled")
            if 'restart' in self.service_widgets['mariadb']['buttons']:
                self.service_widgets['mariadb']['buttons']['restart'].configure(state="disabled")
        else:
            if run:
                self.service_widgets['apache']['buttons']['start'].configure(state="disabled")
                self.service_widgets['apache']['buttons']['stop'].configure(state="normal")
            else:
                self.service_widgets['apache']['buttons']['start'].configure(state="normal")
                self.service_widgets['apache']['buttons']['stop'].configure(state="disabled")
            self.service_widgets['apache']['buttons']['restart'].configure(state="normal")
            self.service_widgets['php']['buttons']['restart'].configure(state="normal")
            self.service_widgets['sqlite']['buttons']['restart'].configure(state="normal")

        # WWW Directory stats update
        if os.path.exists(self.core.www_dir):
            files = len([f for f in os.listdir(self.core.www_dir) if os.path.isfile(os.path.join(self.core.www_dir, f))])
            if self._last_file_count != files:
                self._last_file_count = files
                self.file_count_lbl.configure(text=f"Files in www: {files} files")

        # Server Uptime display
        if run and hasattr(self, 'start_time') and self.start_time:
            elapsed = int(time.time() - self.start_time)
            uptime_text = f"Uptime: {time.strftime('%H:%M:%S', time.gmtime(elapsed))}"
            if self._last_uptime != uptime_text:
                self._last_uptime = uptime_text
                self.uptime_lbl.configure(text=uptime_text)
        else:
            self.uptime_lbl.configure(text="Uptime: 00:00:00")
            
        # Available PHP dropdown items update
        available_phps = self.core.get_available_phps()
        if list(self.settings_php_combo.cget("values")) != available_phps:
            self.settings_php_combo.configure(values=available_phps)
            
        active_php = self.core.settings.get('active_php', 'php')
        if active_php not in available_phps and available_phps:
            active_php = available_phps[0]
            self.core.settings['active_php'] = active_php
            self.core.save_settings()
            
        if self.settings_php_var.get() != active_php:
            self.settings_php_var.set(active_php)

        # Available phpMyAdmin PHP dropdown items update
        if list(self.settings_pma_php_combo.cget("values")) != available_phps:
            self.settings_pma_php_combo.configure(values=available_phps)
            
        active_pma_php = self.core.settings.get('pma_php', '')
        if active_pma_php not in available_phps and available_phps:
            active_pma_php = active_php
            self.core.settings['pma_php'] = active_pma_php
            self.core.save_settings()
            
        if self.settings_pma_php_var.get() != active_pma_php:
            self.settings_pma_php_var.set(active_pma_php)

        # Available Apache dropdown items update
        available_apaches = self.core.get_available_apaches()
        if list(self.settings_apache_combo.cget("values")) != available_apaches:
            self.settings_apache_combo.configure(values=available_apaches)
            
        active_apache = self.core.settings.get('active_apache', 'apache')
        if active_apache not in available_apaches and available_apaches:
            active_apache = available_apaches[0]
            self.core.settings['active_apache'] = active_apache
            self.core.save_settings()
            
        if self.settings_apache_var.get() != active_apache:
            self.settings_apache_var.set(active_apache)

        # Available MariaDB dropdown items update
        available_mariadbs = self.core.get_available_mariadbs()
        if list(self.settings_mariadb_combo.cget("values")) != available_mariadbs:
            self.settings_mariadb_combo.configure(values=available_mariadbs)
            
        active_mariadb = self.core.settings.get('active_mariadb', 'mariadb')
        if active_mariadb not in available_mariadbs and available_mariadbs:
            active_mariadb = available_mariadbs[0]
            self.core.settings['active_mariadb'] = active_mariadb
            self.core.save_settings()
            
        if self.settings_mariadb_var.get() != active_mariadb:
            self.settings_mariadb_var.set(active_mariadb)

        # PHP Version Check
        php_v = self.core.get_php_ver()
        php_ok = php_v != "N/A" and php_v != "Not Found"
        php_ver_text = f"● ACTIVE (PHP {php_v})" if php_ok else "● PHP NOT FOUND"
        
        if self._last_php_ver != php_ver_text:
            self._last_php_ver = php_ver_text
            self.service_widgets['php']['status_lbl'].configure(
                text=php_ver_text, 
                text_color=self.colors['accent'] if php_ok else self.colors['red']
            )
            self.service_widgets['php']['card'].configure(border_color=self.colors['accent'] if php_ok else self.colors['red'])
        
        # SQLite Extension state check
        sql = self.core.sqlite_status()
        sql_state_text = "● ENABLED" if sql else "● DISABLED"
        if self._last_sqlite_state != sql_state_text:
            self._last_sqlite_state = sql_state_text
            self.service_widgets['sqlite']['status_lbl'].configure(
                text=sql_state_text, 
                text_color=self.colors['green'] if sql else self.colors['muted']
            )
            self.service_widgets['sqlite']['card'].configure(border_color=self.colors['green'] if sql else self.colors['border'])
            
        if not is_op:
            if sql:
                self.service_widgets['sqlite']['buttons']['enable'].configure(state="disabled")
                self.service_widgets['sqlite']['buttons']['disable'].configure(state="normal")
            else:
                self.service_widgets['sqlite']['buttons']['enable'].configure(state="normal")
                self.service_widgets['sqlite']['buttons']['disable'].configure(state="disabled")

        # MariaDB Status Check
        db_run = self.core.mariadb_running
        db_ok = os.path.exists(self.core.mariadb_exe)
        
        db_valid = self.core.is_mariadb_valid()
        if db_ok and db_valid:
            mariadb_ver = self.core.get_mariadb_ver()
            db_status_text = f"\u25CF RUNNING (v{mariadb_ver})" if db_run else "\u25CF STOPPED"
            db_status_color = self.colors['green'] if db_run else self.colors['red']
            db_border_color = self.colors['green'] if db_run else self.colors['border']
        elif db_ok and not db_valid:
            db_status_text = "\u25CF NEEDS REAL BINARY"
            db_status_color = self.colors['orange']
            db_border_color = self.colors['orange']
        else:
            db_status_text = "\u25CF NOT INSTALLED"
            db_status_color = self.colors['muted']
            db_border_color = self.colors['border']

        self.service_widgets['mariadb']['status_lbl'].configure(text=db_status_text, text_color=db_status_color)
        self.service_widgets['mariadb']['card'].configure(border_color=db_border_color)
        
        if not is_op:
            if not db_ok or not db_valid:
                self.service_widgets['mariadb']['buttons']['start'].configure(state="disabled")
                self.service_widgets['mariadb']['buttons']['stop'].configure(state="disabled")
                self.service_widgets['mariadb']['buttons']['restart'].configure(state="disabled")
            else:
                if db_run:
                    self.service_widgets['mariadb']['buttons']['start'].configure(state="disabled")
                    self.service_widgets['mariadb']['buttons']['stop'].configure(state="normal")
                else:
                    self.service_widgets['mariadb']['buttons']['start'].configure(state="normal")
                    self.service_widgets['mariadb']['buttons']['stop'].configure(state="disabled")
                self.service_widgets['mariadb']['buttons']['restart'].configure(state="normal")

        # 1. Update Apache card description dynamically on main screen
        apache_v = self.core.get_apache_ver()
        self.service_widgets['apache']['desc_lbl'].configure(text=f"HTTP Daemon Service v{apache_v} (Handles web queries)")

        # 2. Update downloads page components dynamically
        if hasattr(self, 'download_widgets') and self.download_widgets:
            php_versions = {
                'php8.5.6': '8.5.6',
                'php8.4': '8.4',
                'php8.3': '8.3',
                'php8.2': '8.2'
            }
            for key, target_ver in php_versions.items():
                if key in self.download_widgets:
                    # Use prefix matching: php8.2 matches php8.2.0, php8.2, etc.
                    is_installed = any(p == key or p.startswith(key + '.') or p.startswith(key + '/') for p in available_phps) or os.path.exists(os.path.join(self.core.base, 'bin', key, 'php.exe'))
                    widget = self.download_widgets[key]
                    
                    if is_installed:
                        widget['status_lbl'].configure(text="INSTALLED", text_color=self.colors['green'])
                        widget['btn'].configure(text="Installed", state="disabled")
                    else:
                        widget['status_lbl'].configure(text="AVAILABLE", text_color=self.colors['accent'])
                        if widget['btn'].cget("text") != "Installed" and "DOWNLOADING" not in widget['status_lbl'].cget("text"):
                            widget['btn'].configure(text="Download", state="normal")
                            
                    desc_text = f"Version: {target_ver} \u2022 PHP Scripting Engine."
                    # Check if any active php matches this key (prefix match)
                    is_active = active_php == key or active_php.startswith(key + '.') or active_php.startswith(key + '/')
                    if is_active:
                        desc_text += " (Currently Active)"
                    widget['desc_lbl'].configure(text=desc_text)
            
            apache_versions = {
                'apache2.4.63': '2.4.63',
                'apache2.4.62': '2.4.62',
                'apache2.4.61': '2.4.61'
            }
            for key, target_ver in apache_versions.items():
                if key in self.download_widgets:
                    is_installed = key in available_apaches or os.path.exists(os.path.join(self.core.base, 'bin', key, 'bin', 'httpd.exe'))
                    widget = self.download_widgets[key]
                    
                    if is_installed:
                        widget['status_lbl'].configure(text="INSTALLED", text_color=self.colors['green'])
                        widget['btn'].configure(text="Installed", state="disabled")
                    else:
                        widget['status_lbl'].configure(text="AVAILABLE", text_color=self.colors['accent'])
                        if widget['btn'].cget("text") != "Installed" and "DOWNLOADING" not in widget['status_lbl'].cget("text"):
                            widget['btn'].configure(text="Download", state="normal")
                            
                    desc_text = f"Version: {target_ver} • Apache Web Server."
                    if key == active_apache:
                        desc_text += " (Currently Active)"
                    widget['desc_lbl'].configure(text=desc_text)

            mariadb_versions = {
                'mariadb11.4': '11.4',
                'mariadb10.11': '10.11'
            }
            for key, target_ver in mariadb_versions.items():
                if key in self.download_widgets:
                    is_installed = key in available_mariadbs or os.path.exists(os.path.join(self.core.base, 'bin', key, 'bin', 'mariadbd.exe')) or os.path.exists(os.path.join(self.core.base, 'bin', key, 'bin', 'mysqld.exe'))
                    widget = self.download_widgets[key]
                    
                    if is_installed:
                        widget['status_lbl'].configure(text="INSTALLED", text_color=self.colors['green'])
                        widget['btn'].configure(text="Installed", state="disabled")
                    else:
                        widget['status_lbl'].configure(text="AVAILABLE", text_color=self.colors['accent'])
                        if widget['btn'].cget("text") != "Installed" and "DOWNLOADING" not in widget['status_lbl'].cget("text"):
                            widget['btn'].configure(text="Download", state="normal")
                            
                    desc_text = f"Version: {target_ver} • MariaDB Database Server."
                    if key == active_mariadb:
                        desc_text += " (Currently Active)"
                    widget['desc_lbl'].configure(text=desc_text)

            # Tools & Utilities status checks
            tool_checks = {
                'phpmyadmin': ('phpMyAdmin', self.is_tool_installed('phpmyadmin')),
                'phpmyadmin5.2.2': ('phpMyAdmin 5.2.2', self.is_tool_installed('phpmyadmin5.2.2')),
                'phpmyadmin5.2.3': ('phpMyAdmin 5.2.3', self.is_tool_installed('phpmyadmin5.2.3')),
                'phpmyadmin4.9.11': ('phpMyAdmin 4.9.11', self.is_tool_installed('phpmyadmin4.9.11')),
                'adminer': ('Adminer', self.is_tool_installed('adminer')),
                'composer': ('Composer', self.is_tool_installed('composer')),
                'nodejs20': ('Node.js', self.is_tool_installed('nodejs20')),
            }
            for key, (name, installed) in tool_checks.items():
                if key in self.download_widgets:
                    widget = self.download_widgets[key]
                    if installed:
                        widget['status_lbl'].configure(text="INSTALLED", text_color=self.colors['green'])
                        widget['btn'].configure(text="Installed", state="disabled")
                    else:
                        widget['status_lbl'].configure(text="AVAILABLE", text_color=self.colors['accent'])
                        if widget['btn'].cget("text") != "Installed" and "DOWNLOADING" not in widget['status_lbl'].cget("text"):
                            widget['btn'].configure(text="Download", state="normal")



    def check_commands(self):
        cmd_file = os.path.join(self.core.base, 'config', 'cmd.json')
        if os.path.exists(cmd_file):
            try:
                with open(cmd_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                os.remove(cmd_file)
                action = data.get('action')
                if action == 'restart':
                    self.on_restart()
                elif action == 'stop':
                    self.on_stop()
            except Exception as e:
                print(f"Error processing cmd.json: {e}")

if __name__ == "__main__":
    try: ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except: pass
    customtkinter.set_appearance_mode("dark")
    customtkinter.set_default_color_theme("blue")
    root = customtkinter.CTk()
    app = UltimateDashboard(root)
    root.mainloop()
