/**
 * engine_console_v2 — Live worker telemetry (CPU / RAM) from Socket.IO `execution_log`
 * events where event === 'system_metric' (worker process sampling).
 *
 * Depends: Chart.js (global Chart), HytheraConsole.state.socket (console-socket.js).
 */
(function () {
    'use strict';

    var MAX_POINTS = 120;
    var charts = { cpu: null, ram: null };
    var labels = [];
    var cpuData = [];
    var ramMbData = [];
    var lastExecutionId = null;
    var sampleCount = 0;

    function $(id) {
        return document.getElementById(id);
    }

    function formatTimeShort() {
        var d = new Date();
        return (
            String(d.getHours()).padStart(2, '0') +
            ':' +
            String(d.getMinutes()).padStart(2, '0') +
            ':' +
            String(d.getSeconds()).padStart(2, '0')
        );
    }

    function readCssVar(name, fallback) {
        var v = getComputedStyle(document.documentElement).getPropertyValue(name);
        v = (v || '').trim();
        return v || fallback;
    }

    function resetSeries() {
        labels = [];
        cpuData = [];
        ramMbData = [];
        sampleCount = 0;
        if (charts.cpu) {
            charts.cpu.data.labels = [];
            charts.cpu.data.datasets[0].data = [];
            charts.cpu.update('none');
        }
        if (charts.ram) {
            charts.ram.data.labels = [];
            charts.ram.data.datasets[0].data = [];
            charts.ram.update('none');
        }
        var elN = $('v2-metrics-samples');
        if (elN) elN.textContent = '0';
    }

    function pushPoint(cpu, ramMb) {
        var t = formatTimeShort();
        labels.push(t);
        cpuData.push(cpu);
        ramMbData.push(ramMb);
        if (labels.length > MAX_POINTS) {
            labels.shift();
            cpuData.shift();
            ramMbData.shift();
        }
        sampleCount += 1;
        if (charts.cpu) {
            charts.cpu.data.labels = labels.slice();
            charts.cpu.data.datasets[0].data = cpuData.slice();
            charts.cpu.update('none');
        }
        if (charts.ram) {
            charts.ram.data.labels = labels.slice();
            charts.ram.data.datasets[0].data = ramMbData.slice();
            charts.ram.update('none');
        }
        var elN = $('v2-metrics-samples');
        if (elN) elN.textContent = String(sampleCount);
        var elCpu = $('v2-metrics-cpu-now');
        var elRam = $('v2-metrics-ram-now');
        if (elCpu) elCpu.textContent = cpu != null ? cpu.toFixed(1) + ' %' : '—';
        if (elRam) elRam.textContent = ramMb != null ? ramMb.toFixed(1) + ' MB' : '—';
    }

    function onExecutionLog(data) {
        if (!data || data.event !== 'system_metric') return;
        var eid = data.execution_id || '';
        if (eid && eid !== lastExecutionId) {
            lastExecutionId = eid;
            resetSeries();
            var elId = $('v2-metrics-exec-id');
            if (elId) {
                elId.textContent = eid.length > 42 ? eid.slice(0, 20) + '…' + eid.slice(-12) : eid;
                elId.title = eid;
            }
        }
        var cpu = parseFloat(data.cpu_percent);
        if (isNaN(cpu)) cpu = null;
        var ramB = data.ram_bytes;
        if (typeof ramB === 'string') ramB = parseInt(ramB, 10);
        if (typeof ramB !== 'number' || isNaN(ramB)) ramB = null;
        var ramMb = ramB != null ? ramB / (1024 * 1024) : null;
        if (cpu != null || ramMb != null) {
            pushPoint(cpu != null ? Math.min(100, Math.max(0, cpu)) : 0, ramMb != null ? ramMb : 0);
        }
    }

    function initCharts() {
        if (typeof Chart === 'undefined') {
            console.warn('[metrics] Chart.js not loaded');
            return;
        }
        var fg = readCssVar('--term-fg', '#c6d0e3');
        var grid = readCssVar('--term-border', 'rgba(255,255,255,0.08)');
        var muted = readCssVar('--log-debug', '#6c7086');
        var cpuColor = readCssVar('--log-info', '#89b4fa');
        var ramColor = '#c4a7e7';

        var commonOpts = {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(12, 15, 20, 0.92)',
                    titleColor: fg,
                    bodyColor: fg,
                    borderColor: grid,
                    borderWidth: 1,
                    padding: 10,
                    displayColors: true
                }
            },
            scales: {
                x: {
                    grid: { color: grid, drawBorder: false },
                    ticks: {
                        color: muted,
                        maxRotation: 0,
                        autoSkip: true,
                        maxTicksLimit: 8,
                        font: { size: 10 }
                    }
                },
                y: {
                    grid: { color: grid, drawBorder: false },
                    ticks: { color: muted, font: { size: 10 } }
                }
            }
        };

        var cpuCanvas = $('v2-metrics-chart-cpu');
        var ramCanvas = $('v2-metrics-chart-ram');
        if (!cpuCanvas || !ramCanvas) return;

        charts.cpu = new Chart(cpuCanvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'CPU %',
                        data: [],
                        borderColor: cpuColor,
                        backgroundColor: 'rgba(137, 180, 250, 0.14)',
                        fill: true,
                        tension: 0.22,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        borderWidth: 2
                    }
                ]
            },
            options: Object.assign({}, commonOpts, {
                scales: {
                    x: commonOpts.scales.x,
                    y: Object.assign({}, commonOpts.scales.y, {
                        min: 0,
                        max: 100,
                        title: { display: true, text: '%', color: muted, font: { size: 10 } }
                    })
                }
            })
        });

        charts.ram = new Chart(ramCanvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'RAM',
                        data: [],
                        borderColor: ramColor,
                        backgroundColor: 'rgba(196, 167, 231, 0.12)',
                        fill: true,
                        tension: 0.22,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        borderWidth: 2
                    }
                ]
            },
            options: Object.assign({}, commonOpts, {
                scales: {
                    x: commonOpts.scales.x,
                    y: Object.assign({}, commonOpts.scales.y, {
                        min: 0,
                        title: { display: true, text: 'MB', color: muted, font: { size: 10 } }
                    })
                }
            })
        });
    }

    function bindSocket() {
        var HC = window.HytheraConsole;
        if (!HC || !HC.state || !HC.state.socket) {
            setTimeout(bindSocket, 100);
            return;
        }
        var socket = HC.state.socket;
        if (socket.__nosMetricsBound) return;
        socket.__nosMetricsBound = true;
        socket.on('execution_log', onExecutionLog);
        var status = $('v2-metrics-socket-status');
        if (status) {
            status.textContent = socket.connected ? 'Connected' : 'Waiting…';
            socket.on('connect', function () {
                status.textContent = 'Connected';
            });
            socket.on('disconnect', function () {
                status.textContent = 'Disconnected';
            });
        }
    }

    function wireUi() {
        var btn = $('v2-metrics-clear');
        if (btn) {
            btn.addEventListener('click', function () {
                resetSeries();
                lastExecutionId = null;
                var elId = $('v2-metrics-exec-id');
                if (elId) {
                    elId.textContent = '—';
                    elId.removeAttribute('title');
                }
            });
        }
    }

    function resizeCharts() {
        if (charts.cpu) charts.cpu.resize();
        if (charts.ram) charts.ram.resize();
    }

    function boot() {
        wireUi();
        initCharts();
        bindSocket();
        document.querySelectorAll('.panel-tabs--bottom button[data-tab="metrics"]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                setTimeout(resizeCharts, 80);
            });
        });
        window.addEventListener('resize', resizeCharts);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
