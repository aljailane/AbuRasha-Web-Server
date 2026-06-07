<?php
declare(strict_types=1);

$baseDir = dirname(__DIR__);
$settingsFile = $baseDir . '/config/settings.json';

// Load settings to fetch active versions
$settings = [];
if (is_file($settingsFile)) {
    $settings = json_decode(file_get_contents($settingsFile), true) ?: [];
}

$activePhp = $settings['active_php'] ?? 'php';
$activeApache = $settings['active_apache'] ?? 'apache';
$activeMariadb = $settings['active_mariadb'] ?? 'mariadb';

// Detect phpMyAdmin folder in www directory
$pmaFolder = '';
foreach (scandir(__DIR__) as $d) {
    if (str_starts_with(strtolower($d), 'phpmyadmin') && is_dir(__DIR__ . '/' . $d) && is_file(__DIR__ . '/' . $d . '/index.php')) {
        $pmaFolder = $d;
        break;
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AbuRasha Serv Index</title>
    <link href="https://fonts.googleapis.com/css2?family=Source+Sans+Pro:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
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
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }

        /* Top header navigation bar */
        .topbar {
            height: 50px;
            background-color: var(--cwp-darker);
            color: #fff;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 30px;
        }

        .topbar-brand {
            font-weight: 700;
            font-size: 16px;
            color: #fff;
            text-decoration: none;
        }

        .topbar-brand span {
            color: var(--cwp-blue);
        }

        .topbar-stats {
            display: flex;
            gap: 20px;
            font-size: 11px;
            color: #a4b0be;
        }

        .topbar-stats span strong {
            color: #fff;
        }

        /* Main container layout */
        .main-container {
            max-width: 900px;
            width: 100%;
            margin: 60px auto;
            padding: 0 20px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        .welcome-title {
            font-size: 26px;
            font-weight: 600;
            margin-bottom: 8px;
            color: #21252f;
            text-align: center;
        }

        .welcome-subtitle {
            font-size: 13px;
            color: #747d8c;
            margin-bottom: 35px;
            text-align: center;
            max-width: 550px;
        }

        /* Dashboard content grid */
        .dashboard-wrapper {
            width: 100%;
            background-color: var(--cwp-white);
            border: 1px solid var(--cwp-border);
            border-radius: 4px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
            margin-bottom: 30px;
            overflow: hidden;
        }

        .dashboard-header {
            background-color: #fafafa;
            border-bottom: 1px solid var(--cwp-border);
            padding: 15px 20px;
            font-size: 13px;
            font-weight: 700;
            color: var(--cwp-dark);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            background-color: rgba(46, 204, 113, 0.15);
            color: var(--cwp-green);
            border: 1px solid rgba(46, 204, 113, 0.3);
            padding: 3px 8px;
            font-size: 10px;
            font-weight: 700;
            border-radius: 3px;
        }

        .dashboard-body {
            padding: 25px;
        }

        /* Systems/Versions table */
        .system-info-table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 30px;
            font-size: 13px;
        }

        .system-info-table th, .system-info-table td {
            border: 1px solid var(--cwp-border);
            padding: 10px 15px;
            text-align: left;
        }

        .system-info-table th {
            background-color: #f9f9f9;
            font-weight: 700;
            color: var(--cwp-dark);
            width: 30%;
        }

        .system-info-table td {
            color: #2f3542;
            font-weight: 600;
        }

        /* Quick Launch Links */
        .action-row {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
        }

        @media (max-width: 600px) {
            .action-row {
                grid-template-columns: 1fr;
            }
        }

        .action-btn {
            background-color: #fff;
            border: 1px solid var(--cwp-border);
            border-radius: 4px;
            padding: 20px;
            display: flex;
            align-items: center;
            text-decoration: none;
            color: var(--cwp-text);
            transition: all 0.2s ease;
        }

        .action-btn:hover {
            border-color: var(--cwp-blue);
            background-color: #fafafa;
            transform: translateY(-2px);
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05);
        }

        .action-icon {
            font-size: 32px;
            margin-right: 15px;
        }

        .action-details {
            display: flex;
            flex-direction: column;
            text-align: left;
        }

        .action-title {
            font-size: 14px;
            font-weight: 700;
            color: #1e222b;
        }

        .action-desc {
            font-size: 11px;
            color: #747d8c;
            margin-top: 3px;
        }

        /* Footer styling */
        footer {
            margin-top: auto;
            padding: 20px;
            border-top: 1px solid var(--cwp-border);
            text-align: center;
            font-size: 11px;
            color: #747d8c;
            background-color: var(--cwp-white);
        }
    </style>
</head>
<body>

<!-- Topbar Navigation -->
<div class="topbar">
    <a href="index.php" class="topbar-brand">
        <span>AbuRasha</span> Serv Index
    </a>
    <div class="topbar-stats">
        <span>Server Port: <strong>8080</strong></span>
        <span>Environment: <strong>Development</strong></span>
    </div>
</div>

<!-- Main Landing Container -->
<div class="main-container">
    <h2 class="welcome-title">Welcome to AbuRasha Serv</h2>
    <p class="welcome-subtitle">Your local development server is online and running. Use this dashboard to navigate configuration modules and manage database connections.</p>

    <!-- Dashboard widget -->
    <div class="dashboard-wrapper">
        <div class="dashboard-header">
            <span>Server Status</span>
            <span class="status-badge">ONLINE</span>
        </div>
        <div class="dashboard-body">
            <!-- Systems version specifications table -->
            <table class="system-info-table">
                <tr>
                    <th>Web Server Engine</th>
                    <td><?= htmlspecialchars($activeApache) ?></td>
                </tr>
                <tr>
                    <th>PHP Scripting Runtime</th>
                    <td><?= htmlspecialchars($activePhp) ?></td>
                </tr>
                <tr>
                    <th>MariaDB (MySQL Client)</th>
                    <td><?= htmlspecialchars($activeMariadb) ?></td>
                </tr>
            </table>

            <!-- Developer launching links -->
            <div class="action-row">
                <!-- Server Management Dashboard -->
                <a href="adminserver.php" class="action-btn">
                    <span class="action-icon">⚙️</span>
                    <span class="action-details">
                        <span class="action-title">AbuRasha Web Panel</span>
                        <span class="action-desc">Switch PHP runtimes, enable SQLite, view system error logs and reboot services.</span>
                    </span>
                </a>

                <!-- phpMyAdmin portal link -->
                <?php if ($pmaFolder): ?>
                    <a href="/<?= htmlspecialchars($pmaFolder) ?>/" class="action-btn" target="_blank">
                        <span class="action-icon">🗄️</span>
                        <span class="action-details">
                            <span class="action-title">phpMyAdmin Portal</span>
                            <span class="action-desc">Access web interface to configure MySQL/MariaDB database schemas.</span>
                        </span>
                    </a>
                <?php else: ?>
                    <div class="action-btn" style="opacity: 0.5; cursor: not-allowed;">
                        <span class="action-icon">🗄️</span>
                        <span class="action-details">
                            <span class="action-title">phpMyAdmin Missing</span>
                            <span class="action-desc" style="color: var(--cwp-red);">Please install phpMyAdmin extension from the downloads manager.</span>
                        </span>
                    </div>
                <?php endif; ?>
            </div>
        </div>
    </div>
</div>

<!-- Footer bar -->
<footer>
    &copy; 2026 AbuRasha Serv. All rights reserved. Powered by Aburasha Yemen.
</footer>

</body>
</html>
