<?php
declare(strict_types=1);

// Configuration paths
$baseDir = dirname(__DIR__);
$settingsFile = $baseDir . '/config/settings.json';
$cmdFile = $baseDir . '/config/cmd.json';

// Load settings
$settings = [];
if (is_file($settingsFile)) {
    $settings = json_decode(file_get_contents($settingsFile), true) ?: [];
}

$activePhp = $settings['active_php'] ?? 'php';
$activeApache = $settings['active_apache'] ?? 'apache';
$activeMariadb = $settings['active_mariadb'] ?? 'mariadb';
$pmaPhp = $settings['pma_php'] ?? $activePhp;

$phpIniFile = $baseDir . '/bin/' . $activePhp . '/php.ini';
$apacheLogFile = $baseDir . '/bin/' . $activeApache . '/logs/error.log';
$phpLogFile = $baseDir . '/bin/' . $activePhp . '/logs/php_error.log';

$message = '';
$messageType = 'success';

// Handle SQLite status
$sqliteEnabled = false;
if (is_file($phpIniFile)) {
    $iniContent = file_get_contents($phpIniFile);
    $sqliteEnabled = (preg_match('/^\s*extension\s*=\s*php_pdo_sqlite\.dll/im', $iniContent) === 1);
}

// Process POST actions
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (isset($_POST['action'])) {
        $action = $_POST['action'];
        if (in_array($action, ['restart', 'stop'], true)) {
            file_put_contents($cmdFile, json_encode([
                'action' => $action,
                'timestamp' => time()
            ]));
            $message = "Server command '" . strtoupper($action) . "' sent successfully. Reloading...";
        }
    }
    
    if (isset($_POST['switch_php'])) {
        $newPhp = $_POST['switch_php'];
        $settings['active_php'] = $newPhp;
        file_put_contents($settingsFile, json_encode($settings, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
        file_put_contents($cmdFile, json_encode(['action' => 'restart', 'timestamp' => time()]));
        $activePhp = $newPhp;
        $message = "PHP Version switched to $newPhp. Restarting services...";
    }

    if (isset($_POST['switch_pma_php'])) {
        $newPmaPhp = $_POST['switch_pma_php'];
        $settings['pma_php'] = $newPmaPhp;
        file_put_contents($settingsFile, json_encode($settings, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
        file_put_contents($cmdFile, json_encode(['action' => 'restart', 'timestamp' => time()]));
        $pmaPhp = $newPmaPhp;
        $message = "phpMyAdmin PHP Version switched to $newPmaPhp. Restarting services...";
    }

    if (isset($_POST['switch_apache'])) {
        $newApache = $_POST['switch_apache'];
        $settings['active_apache'] = $newApache;
        file_put_contents($settingsFile, json_encode($settings, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
        file_put_contents($cmdFile, json_encode(['action' => 'restart', 'timestamp' => time()]));
        $activeApache = $newApache;
        $message = "Apache Version switched to $newApache. Restarting services...";
    }

    if (isset($_POST['switch_mariadb'])) {
        $newMariadb = $_POST['switch_mariadb'];
        $settings['active_mariadb'] = $newMariadb;
        file_put_contents($settingsFile, json_encode($settings, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
        file_put_contents($cmdFile, json_encode(['action' => 'restart', 'timestamp' => time()]));
        $activeMariadb = $newMariadb;
        $message = "MariaDB Version switched to $newMariadb. Restarting services...";
    }

    if (isset($_POST['toggle_sqlite_btn'])) {
        $enable = $_POST['toggle_sqlite_btn'] === '1';
        if (is_file($phpIniFile)) {
            $lines = file($phpIniFile);
            $newLines = [];
            foreach ($lines as $line) {
                if (stripos($line, 'extension=php_pdo_sqlite.dll') !== false) {
                    $newLines[] = $enable ? "extension=php_pdo_sqlite.dll\n" : ";extension=php_pdo_sqlite.dll\n";
                } else {
                    $newLines[] = $line;
                }
            }
            file_put_contents($phpIniFile, implode('', $newLines));
            file_put_contents($cmdFile, json_encode(['action' => 'restart', 'timestamp' => time()]));
            $sqliteEnabled = $enable;
            $message = "SQLite PDO extension " . ($enable ? 'ENABLED' : 'DISABLED') . ". Restarting services...";
        }
    }

    if (isset($_POST['clear_logs'])) {
        $logType = $_POST['clear_logs'];
        if ($logType === 'apache') {
            if (is_file($apacheLogFile)) {
                file_put_contents($apacheLogFile, '');
                $message = "Apache error log cleared successfully.";
            } else {
                $message = "Apache error log file not found.";
            }
        } elseif ($logType === 'php') {
            if (is_file($phpLogFile)) {
                file_put_contents($phpLogFile, '');
                $message = "PHP error log cleared successfully.";
            } else {
                $message = "PHP error log file not found.";
            }
        } else {
            if (is_file($apacheLogFile)) file_put_contents($apacheLogFile, '');
            if (is_file($phpLogFile)) file_put_contents($phpLogFile, '');
            $message = "All system logs cleared successfully.";
        }
    }
}

// Scan directories for versions
$binDir = $baseDir . '/bin';
$phps = [];
$apaches = [];
$mariadbs = [];
$pmaInstalled = false;
$pmaFolder = '';

if (is_dir($binDir)) {
    foreach (scandir($binDir) as $d) {
        if ($d === '.' || $d === '..') continue;
        $dPath = $binDir . '/' . $d;
        if (is_dir($dPath)) {
            if (str_starts_with($d, 'php') && !str_starts_with($d, 'phpmyadmin') && is_file($dPath . '/php.exe')) {
                $phps[] = $d;
            } elseif (str_starts_with($d, 'apache') && is_file($dPath . '/bin/httpd.exe')) {
                $apaches[] = $d;
            } elseif (str_starts_with($d, 'mariadb') && (is_file($dPath . '/bin/mariadbd.exe') || is_file($dPath . '/bin/mysqld.exe'))) {
                $mariadbs[] = $d;
            }
        }
    }
}

// Check for phpmyadmin folder
foreach (scandir(__DIR__) as $d) {
    if (str_starts_with(strtolower($d), 'phpmyadmin') && is_dir(__DIR__ . '/' . $d) && is_file(__DIR__ . '/' . $d . '/index.php')) {
        $pmaInstalled = true;
        $pmaFolder = $d;
        break;
    }
}

// Function to read logs
function getLogTail(string $path, int $linesCount = 30): string {
    if (!is_file($path)) {
        return "Log file not found.";
    }
    $data = file_get_contents($path);
    if ($data === false) {
        return "Failed to read log file.";
    }
    $lines = explode("\n", trim($data));
    $sliced = array_slice($lines, -$linesCount);
    return implode("\n", array_map('htmlspecialchars', $sliced));
}

$apacheLogs = getLogTail($apacheLogFile);
$phpLogs = getLogTail($phpLogFile);
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ARWP - Web Panel</title>
    <link href="https://fonts.googleapis.com/css2?family=Source+Sans+Pro:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --sidebar-width: 250px;
            --topbar-height: 50px;
            
            /* CWP Classic colors */
            --cwp-dark: #2f3542;
            --cwp-darker: #21252f;
            --cwp-light: #f1f2f6;
            --cwp-white: #ffffff;
            --cwp-text: #2f3542;
            --cwp-border: #dcdde1;
            
            --cwp-blue: #2980b9;
            --cwp-green: #2ecc71;
            --cwp-red: #e74c3c;
            --cwp-orange: #e67e22;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Source Sans Pro', sans-serif;
            background-color: var(--cwp-light);
            color: var(--cwp-text);
            display: flex;
            min-height: 100vh;
        }

        /* Sidebar styling */
        .sidebar {
            width: var(--sidebar-width);
            background-color: var(--cwp-darker);
            color: #a4b0be;
            position: fixed;
            top: 0;
            bottom: 0;
            left: 0;
            display: flex;
            flex-direction: column;
            z-index: 100;
        }

        .sidebar-brand {
            height: var(--topbar-height);
            display: flex;
            align-items: center;
            padding: 0 20px;
            background-color: #1e222b;
            color: #fff;
            font-weight: 700;
            font-size: 18px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }

        .sidebar-brand span {
            color: var(--cwp-blue);
            margin-right: 4px;
        }

        .sidebar-menu {
            list-style: none;
            padding: 15px 0;
        }

        .sidebar-menu li a {
            display: flex;
            align-items: center;
            padding: 12px 20px;
            color: #ced6e0;
            text-decoration: none;
            font-size: 13px;
            font-weight: 600;
            transition: all 0.2s ease;
            border-left: 3px solid transparent;
        }

        .sidebar-menu li a:hover, .sidebar-menu li.active a {
            background-color: rgba(255, 255, 255, 0.05);
            color: #fff;
            border-left-color: var(--cwp-blue);
        }

        .sidebar-menu li a .icon {
            margin-right: 12px;
            font-size: 16px;
            width: 20px;
            text-align: center;
        }

        /* Main Content container */
        .main-wrapper {
            margin-left: var(--sidebar-width);
            width: calc(100% - var(--sidebar-width));
            display: flex;
            flex-direction: column;
        }

        /* Topbar styling */
        .topbar {
            height: var(--topbar-height);
            background-color: var(--cwp-white);
            border-bottom: 1px solid var(--cwp-border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 30px;
            position: sticky;
            top: 0;
            z-index: 90;
        }

        .topbar-stats {
            display: flex;
            gap: 20px;
            font-size: 12px;
            color: #747d8c;
            font-weight: 600;
        }

        .topbar-stats span strong {
            color: var(--cwp-text);
        }

        .topbar-actions {
            display: flex;
            gap: 10px;
        }

        /* Content block */
        .content-body {
            padding: 30px;
            flex: 1;
        }

        .page-title {
            font-size: 22px;
            font-weight: 600;
            margin-bottom: 5px;
            color: #2f3542;
        }

        .page-subtitle {
            font-size: 12px;
            color: #747d8c;
            margin-bottom: 25px;
        }

        /* Alert styling */
        .alert-bar {
            background-color: var(--cwp-blue);
            color: white;
            padding: 12px 20px;
            border-radius: 4px;
            margin-bottom: 25px;
            font-size: 13px;
            font-weight: 600;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        /* Grid layouts */
        .dashboard-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 30px;
        }

        @media (max-width: 992px) {
            .dashboard-grid {
                grid-template-columns: 1fr;
            }
        }

        /* Card panels */
        .cwp-card {
            background-color: var(--cwp-white);
            border: 1px solid var(--cwp-border);
            border-radius: 4px;
            margin-bottom: 30px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
        }

        .cwp-card-header {
            padding: 15px 20px;
            border-bottom: 1px solid var(--cwp-border);
            font-size: 14px;
            font-weight: 700;
            color: #1e222b;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .cwp-card-body {
            padding: 20px;
        }

        /* Form Controls */
        .control-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #f1f2f6;
        }

        .control-row:last-child {
            border-bottom: none;
        }

        .control-info {
            display: flex;
            flex-direction: column;
        }

        .control-label {
            font-size: 13px;
            font-weight: 700;
            color: #2f3542;
        }

        .control-desc {
            font-size: 11px;
            color: #747d8c;
            margin-top: 2px;
        }

        select {
            background-color: #fff;
            color: var(--cwp-text);
            border: 1px solid var(--cwp-border);
            padding: 6px 12px;
            border-radius: 4px;
            font-family: inherit;
            font-size: 12px;
            font-weight: 600;
            outline: none;
            width: 160px;
            cursor: pointer;
        }

        select:focus {
            border-color: var(--cwp-blue);
        }

        /* Buttons */
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 7px 15px;
            font-size: 12px;
            font-weight: 700;
            border-radius: 4px;
            border: 1px solid transparent;
            cursor: pointer;
            transition: all 0.1s ease-in-out;
            text-decoration: none;
            font-family: inherit;
        }

        .btn-blue {
            background-color: var(--cwp-blue);
            color: white;
        }

        .btn-blue:hover {
            background-color: #2471a3;
        }

        .btn-green {
            background-color: var(--cwp-green);
            color: white;
        }

        .btn-green:hover {
            background-color: #27ae60;
        }

        .btn-red {
            background-color: var(--cwp-red);
            color: white;
        }

        .btn-red:hover {
            background-color: #c0392b;
        }

        .btn-gray {
            background-color: #e2e8f0;
            color: var(--cwp-text);
            border-color: var(--cwp-border);
        }

        .btn-gray:hover {
            background-color: #cbd5e1;
        }

        /* Badges */
        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 3px 8px;
            font-size: 10px;
            font-weight: 700;
            border-radius: 3px;
        }

        .pill-green {
            background-color: rgba(46, 204, 113, 0.15);
            color: var(--cwp-green);
            border: 1px solid rgba(46, 204, 113, 0.3);
        }

        .pill-red {
            background-color: rgba(231, 76, 60, 0.15);
            color: var(--cwp-red);
            border: 1px solid rgba(231, 76, 60, 0.3);
        }

        /* Console */
        .console-logs {
            background-color: #1e222b;
            border: 1px solid #111;
            padding: 12px;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 11px;
            color: #f1f2f6;
            height: 220px;
            overflow-y: auto;
            white-space: pre-wrap;
            border-radius: 3px;
        }

        .tab-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }

        .tab-btn {
            background: #e2e8f0;
            border: 1px solid var(--cwp-border);
            border-bottom: none;
            padding: 6px 14px;
            font-size: 11px;
            font-weight: 700;
            color: #57606f;
            cursor: pointer;
            border-radius: 3px 3px 0 0;
            font-family: inherit;
        }

        .tab-btn.active {
            background: #1e222b;
            color: #fff;
            border-color: #1e222b;
        }

        /* Quick Tools Links */
        .list-group {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .list-group-item {
            background-color: #fff;
            border: 1px solid var(--cwp-border);
            padding: 12px 15px;
            border-radius: 4px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            text-decoration: none;
            color: var(--cwp-text);
            transition: all 0.2s ease;
        }

        .list-group-item:hover {
            border-color: var(--cwp-blue);
            background-color: #fafafa;
        }

        .list-item-title {
            font-size: 12px;
            font-weight: 700;
        }

        .list-item-desc {
            font-size: 10px;
            color: #747d8c;
            margin-top: 1px;
        }

        .list-badge {
            background-color: var(--cwp-dark);
            color: #fff;
            font-size: 9px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 3px;
        }
    </style>
</head>
<body>

<!-- Left Sidebar -->
<nav class="sidebar">
    <div class="sidebar-brand">
        <span>AbuRasha</span> Serv Panel
    </div>
    <ul class="sidebar-menu">
        <li class="active">
            <a href="adminserver.php">
                <span class="icon">💻</span> Dashboard
            </a>
        </li>
        <?php if ($pmaInstalled): ?>
            <li>
                <a href="/<?= htmlspecialchars($pmaFolder) ?>/" target="_blank">
                    <span class="icon">🗄️</span> phpMyAdmin
                </a>
            </li>
        <?php endif; ?>
        <li>
            <a href="index.php">
                <span class="icon">🌐</span> Portal Home
            </a>
        </li>
    </ul>
</nav>

<!-- Main Wrapper -->
<div class="main-wrapper">
    <!-- Top Header Navigation -->
    <div class="topbar">
        <div class="topbar-stats">
            <span>Server: <strong style="color: var(--cwp-green)">Online</strong></span>
            <span>OS: <strong>Windows (Portable)</strong></span>
            <span>Web Server: <strong><?= htmlspecialchars($activeApache) ?></strong></span>
        </div>
        <div class="topbar-actions">
            <a href="index.php" class="btn btn-gray">Portal Index</a>
        </div>
    </div>

    <!-- Main Page Content Body -->
    <div class="content-body">
        <h2 class="page-title">AbuRasha Web Panel</h2>
        <div class="page-subtitle">Manage local server runtimes, switch PHP versions, and check logs</div>

        <?php if ($message): ?>
            <div class="alert-bar">
                <span><?= htmlspecialchars($message) ?></span>
                <span style="cursor: pointer;" onclick="this.parentElement.style.display='none'">✕</span>
            </div>
        <?php endif; ?>

        <div class="dashboard-grid">
            <!-- Left Panel -->
            <main>
                <div class="cwp-card">
                    <div class="cwp-card-header">
                        Server Configuration Switcher
                    </div>
                    <div class="cwp-card-body">
                        <!-- Switch PHP Version -->
                        <div class="control-row">
                            <div class="control-info">
                                <span class="control-label">Project PHP Version</span>
                                <span class="control-desc">Select active PHP runtime used for project web queries.</span>
                            </div>
                            <div>
                                <form method="POST">
                                    <select name="switch_php" onchange="submitServerForm(this.form)">
                                        <?php foreach ($phps as $php): ?>
                                            <option value="<?= htmlspecialchars($php) ?>" <?= $php === $activePhp ? 'selected' : '' ?>>
                                                <?= htmlspecialchars($php) ?>
                                            </option>
                                        <?php endforeach; ?>
                                    </select>
                                </form>
                            </div>
                        </div>

                        <!-- Switch phpMyAdmin PHP version -->
                        <div class="control-row">
                            <div class="control-info">
                                <span class="control-label">phpMyAdmin PHP Version</span>
                                <span class="control-desc">Select independent PHP runtime for database manager page.</span>
                            </div>
                            <div>
                                <form method="POST">
                                    <select name="switch_pma_php" onchange="submitServerForm(this.form)">
                                        <?php foreach ($phps as $php): ?>
                                            <option value="<?= htmlspecialchars($php) ?>" <?= $php === $pmaPhp ? 'selected' : '' ?>>
                                                <?= htmlspecialchars($php) ?>
                                            </option>
                                        <?php endforeach; ?>
                                    </select>
                                </form>
                            </div>
                        </div>

                        <!-- Switch Apache version -->
                        <div class="control-row">
                            <div class="control-info">
                                <span class="control-label">Apache Web Server Version</span>
                                <span class="control-desc">Select active HTTP daemon version.</span>
                            </div>
                            <div>
                                <form method="POST">
                                    <select name="switch_apache" onchange="submitServerForm(this.form)">
                                        <?php foreach ($apaches as $apache): ?>
                                            <option value="<?= htmlspecialchars($apache) ?>" <?= $apache === $activeApache ? 'selected' : '' ?>>
                                                <?= htmlspecialchars($apache) ?>
                                            </option>
                                        <?php endforeach; ?>
                                    </select>
                                </form>
                            </div>
                        </div>

                        <!-- Switch MariaDB version -->
                        <div class="control-row">
                            <div class="control-info">
                                <span class="control-label">MariaDB Database Version</span>
                                <span class="control-desc">Select active SQL database client version.</span>
                            </div>
                            <div>
                                <form method="POST">
                                    <select name="switch_mariadb" onchange="submitServerForm(this.form)">
                                        <?php foreach ($mariadbs as $db): ?>
                                            <option value="<?= htmlspecialchars($db) ?>" <?= $db === $activeMariadb ? 'selected' : '' ?>>
                                                <?= htmlspecialchars($db) ?>
                                            </option>
                                        <?php endforeach; ?>
                                    </select>
                                </form>
                            </div>
                        </div>

                        <!-- Toggle SQLite PDO Extension -->
                        <div class="control-row">
                            <div class="control-info">
                                <span class="control-label">SQLite3 PDO Extension</span>
                                <span class="control-desc">Toggle serverless database module in active php.ini.</span>
                            </div>
                            <div>
                                <form method="POST">
                                    <input type="hidden" name="toggle_sqlite_btn" value="<?= $sqliteEnabled ? '0' : '1' ?>">
                                    <button type="submit" class="btn <?= $sqliteEnabled ? 'btn-red' : 'btn-blue' ?>">
                                        <?= $sqliteEnabled ? 'Disable SQLite' : 'Enable SQLite' ?>
                                    </button>
                                </form>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Log Viewer -->
                <div class="cwp-card">
                    <div class="cwp-card-header" style="border-bottom: none; padding-bottom: 0;">
                        System logs
                    </div>
                    <div style="padding: 10px 20px 20px 20px;">
                        <div class="tab-header">
                            <div style="display: flex; gap: 4px;">
                                <button class="tab-btn active" onclick="switchLog('apache')">Apache Error Log</button>
                                <button class="tab-btn" onclick="switchLog('php')">PHP Error Log</button>
                            </div>
                            <form method="POST" style="margin: 0; display: inline-flex; align-items: center;">
                                <input type="hidden" name="clear_logs" id="clear_log_type" value="apache">
                                <button type="submit" class="btn btn-red" style="padding: 4px 10px; font-size: 11px; display: inline-flex; align-items: center; gap: 4px;">
                                    <span>🗑️</span> Clear Logs
                                </button>
                            </form>
                        </div>
                        <div id="apache_log_box" class="console-logs"><?= $apacheLogs ?></div>
                        <div id="php_log_box" class="console-logs" style="display:none; color: #ffaf40;"><?= $phpLogs ?></div>
                    </div>
                </div>
            </main>

            <!-- Sidebar Controls -->
            <aside>
                <div class="cwp-card">
                    <div class="cwp-card-header">
                        Server Controls
                    </div>
                    <div class="cwp-card-body">
                        <div style="margin-bottom: 20px; font-size: 13px;">
                            <span>General Status: </span>
                            <span class="status-pill pill-green">ONLINE</span>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 10px;">
                            <form method="POST" style="width: 100%;">
                                <input type="hidden" name="action" value="restart">
                                <button type="submit" class="btn btn-blue" style="width: 100%;">Reboot Server</button>
                            </form>
                            <form method="POST" style="width: 100%;">
                                <input type="hidden" name="action" value="stop">
                                <button type="submit" class="btn btn-red" style="width: 100%;">Stop Services</button>
                            </form>
                        </div>
                    </div>
                </div>

                <div class="cwp-card">
                    <div class="cwp-card-header">
                        Quick Shortcuts
                    </div>
                    <div class="cwp-card-body" style="padding: 15px;">
                        <div class="list-group">
                            <?php if ($pmaInstalled): ?>
                                <a href="/<?= htmlspecialchars($pmaFolder) ?>/" class="list-group-item" target="_blank">
                                    <div>
                                        <div class="list-item-title">phpMyAdmin</div>
                                        <div class="list-item-desc">Web portal for databases.</div>
                                    </div>
                                    <span class="list-badge">Database Portal</span>
                                </a>
                            <?php endif; ?>
                            <a href="index.php" class="list-group-item">
                                <div>
                                    <div class="list-item-title">Portal Index</div>
                                    <div class="list-item-desc">Go back to project root view.</div>
                                </div>
                            </a>
                        </div>
                    </div>
                </div>
            </aside>
        </div>
    </div>
</div>

<script>
    function switchLog(type) {
        const btnApache = document.querySelectorAll('.tab-btn')[0];
        const btnPhp = document.querySelectorAll('.tab-btn')[1];
        const boxApache = document.getElementById('apache_log_box');
        const boxPhp = document.getElementById('php_log_box');

        if (type === 'apache') {
            btnApache.classList.add('active');
            btnPhp.classList.remove('active');
            boxApache.style.display = 'block';
            boxPhp.style.display = 'none';
        } else {
            btnApache.classList.remove('active');
            btnPhp.classList.add('active');
            boxApache.style.display = 'none';
            boxPhp.style.display = 'block';
        }

        const clearTypeInput = document.getElementById('clear_log_type');
        if (clearTypeInput) {
            clearTypeInput.value = type;
        }
    }

    function submitServerForm(form) {
        if (typeof form.requestSubmit === 'function') {
            form.requestSubmit();
        } else {
            form.dispatchEvent(new Event('submit', {cancelable: true, bubbles: true}));
            form.submit();
        }
    }

    function showOverlay(isStop) {
        let overlay = document.getElementById('restart-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'restart-overlay';
            overlay.style.position = 'fixed';
            overlay.style.top = '0';
            overlay.style.left = '0';
            overlay.style.width = '100vw';
            overlay.style.height = '100vh';
            overlay.style.backgroundColor = 'rgba(33, 37, 47, 0.95)';
            overlay.style.color = '#ffffff';
            overlay.style.display = 'flex';
            overlay.style.flexDirection = 'column';
            overlay.style.justifyContent = 'center';
            overlay.style.alignItems = 'center';
            overlay.style.zIndex = '9999';
            overlay.style.fontFamily = "'Source Sans Pro', sans-serif";
            
            const content = document.createElement('div');
            content.style.textAlign = 'center';
            content.style.padding = '30px';
            content.style.borderRadius = '8px';
            content.style.backgroundColor = '#2f3542';
            content.style.border = '1px solid #dcdde1';
            content.style.boxShadow = '0 10px 25px rgba(0,0,0,0.3)';
            content.style.maxWidth = '450px';
            content.style.width = '90%';

            const spinner = document.createElement('div');
            spinner.id = 'overlay-spinner';
            spinner.style.border = '4px solid rgba(255,255,255,0.1)';
            spinner.style.width = '50px';
            spinner.style.height = '50px';
            spinner.style.borderRadius = '50%';
            spinner.style.borderLeftColor = '#2980b9';
            spinner.style.animation = 'spin 1s linear infinite';
            spinner.style.margin = '0 auto 20px auto';
            
            const style = document.createElement('style');
            style.innerHTML = `
                @keyframes spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }
            `;
            document.head.appendChild(style);

            const title = document.createElement('h2');
            title.id = 'overlay-title';
            title.style.fontSize = '20px';
            title.style.marginBottom = '10px';
            title.style.fontWeight = '600';

            const desc = document.createElement('p');
            desc.id = 'overlay-desc';
            desc.style.fontSize = '13px';
            desc.style.color = '#a4b0be';

            content.appendChild(spinner);
            content.appendChild(title);
            content.appendChild(desc);
            overlay.appendChild(content);
            document.body.appendChild(overlay);
        }

        document.getElementById('overlay-title').innerText = isStop ? 'Stopping Server Services...' : 'Rebooting Server Services...';
        document.getElementById('overlay-desc').innerText = isStop ? 'Apache and database services are shutting down. The panel will go offline.' : 'Runtimes are restarting. Please wait while we reconnect to the panel...';
        
        const spinnerElement = document.getElementById('overlay-spinner');
        if (isStop) {
            spinnerElement.style.display = 'none';
        } else {
            spinnerElement.style.display = 'block';
        }
        overlay.style.display = 'flex';
    }

    function pingServer() {
        fetch(window.location.pathname + '?ping=' + Date.now(), {
            method: 'GET',
            mode: 'same-origin',
            credentials: 'omit',
            cache: 'no-store'
        })
        .then(response => {
            if (response.ok) {
                window.location.href = window.location.pathname;
            } else {
                setTimeout(pingServer, 750);
            }
        })
        .catch(err => {
            setTimeout(pingServer, 750);
        });
    }

    document.addEventListener('submit', function(e) {
        const form = e.target;
        const isClearLogs = form.querySelector('[name="clear_logs"]');
        if (isClearLogs) {
            return;
        }

        e.preventDefault();
        
        const actionInput = form.querySelector('[name="action"]');
        const isStop = actionInput && actionInput.value === 'stop';

        showOverlay(isStop);

        const formData = new FormData(form);
        fetch(window.location.href, {
            method: 'POST',
            body: formData
        }).catch(err => {
            // expected network failure on restart
        });

        if (isStop) {
            return;
        }

        setTimeout(pingServer, 1000);
    });

    // Auto scroll to logs bottom
    document.getElementById('apache_log_box').scrollTop = document.getElementById('apache_log_box').scrollHeight;
    document.getElementById('php_log_box').scrollTop = document.getElementById('php_log_box').scrollHeight;
</script>
</body>
</html>
