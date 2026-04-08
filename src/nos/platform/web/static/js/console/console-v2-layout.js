/**
 * engine_console_v2.html — IDE split layout: resizers, dock tabs, showTab regions.
 */
(function () {
    'use strict';

    if (!document.body.classList.contains('console-v2')) return;

    var origShowTab = window.showTab;

    function showTabV2(name) {
        if (!document.body.classList.contains('console-v2')) {
            return origShowTab(name);
        }
        document.querySelectorAll('.panel-tabs button[data-tab]').forEach(function (b) {
            b.classList.remove('active');
        });
        var el = document.getElementById('tab-' + name);
        if (name === 'workspace') {
            var tw = document.getElementById('tab-workspace');
            if (tw) tw.classList.add('active');
            return;
        }
        if (name === 'console' || name === 'runtime' || name === 'output' || name === 'metrics') {
            document.querySelectorAll('#tab-console, #tab-runtime, #tab-output, #tab-metrics').forEach(function (p) {
                p.classList.remove('active');
            });
            if (el) el.classList.add('active');
            document.querySelectorAll('.panel-tabs--bottom button[data-tab="' + name + '"]').forEach(function (b) {
                b.classList.add('active');
            });
            return;
        }
        if (name === 'chat-model') {
            var tc = document.getElementById('tab-chat-model');
            if (tc) tc.classList.add('active');
            document.querySelectorAll('.panel-tabs--chat button[data-tab="chat-model"]').forEach(function (b) {
                b.classList.add('active');
            });
            return;
        }
        if (name === 'history') {
            if (el) el.classList.add('active');
            return;
        }
        origShowTab(name);
    }

    window.showTab = showTabV2;

    function syncPluginsExplorerRefreshButton() {
        var refreshBtn = document.getElementById('v2-plugins-explorer-refresh');
        if (!refreshBtn) return;
        var pluginsActive = !!document.querySelector('.v2-left-tbtn.active[data-v2-left-tab="plugins"]');
        var driveActive = !!document.querySelector('.v2-left-tbtn.active[data-v2-left-tab="workspace"]');
        refreshBtn.hidden = !(pluginsActive || driveActive);
        if (driveActive) {
            refreshBtn.title = 'Reload Drive (.wks / .out under …/session)';
            refreshBtn.setAttribute('aria-label', 'Reload Drive session folder');
        } else {
            refreshBtn.title = 'Reload plugin explorer tree';
            refreshBtn.setAttribute('aria-label', 'Reload plugin explorer tree');
        }
    }

    function initPluginsExplorerRefresh() {
        var refreshBtn = document.getElementById('v2-plugins-explorer-refresh');
        if (!refreshBtn) return;
        refreshBtn.addEventListener('click', function (e) {
            e.preventDefault();
            var pluginsActive = !!document.querySelector('.v2-left-tbtn.active[data-v2-left-tab="plugins"]');
            var driveActive = !!document.querySelector('.v2-left-tbtn.active[data-v2-left-tab="workspace"]');
            if (driveActive && window.explorerPanel && typeof window.explorerPanel.loadWorkspaceDriveTree === 'function') {
                window.explorerPanel.loadWorkspaceDriveTree();
                return;
            }
            if (pluginsActive && window.explorerPanel && typeof window.explorerPanel.loadPluginsExplorerTree === 'function') {
                window.explorerPanel.loadPluginsExplorerTree();
            }
        });
        syncPluginsExplorerRefreshButton();
    }

    /**
     * Show the matching v2 left column (plugins | workspace | apps). Does not call setExplorerView — callers do that to avoid recursion loops.
     */
    function activateV2LeftDockTab(tab) {
        var btns = document.querySelectorAll('.v2-left-tbtn[data-v2-left-tab]');
        var panes = document.querySelectorAll('.v2-left-pane[data-v2-left-pane]');
        btns.forEach(function (b) {
            b.classList.toggle('active', b.getAttribute('data-v2-left-tab') === tab);
        });
        panes.forEach(function (p) {
            var on = p.getAttribute('data-v2-left-pane') === tab;
            p.classList.toggle('active', on);
            p.hidden = !on;
        });
        syncPluginsExplorerRefreshButton();
    }

    window.__nosV2ActivateLeftDockTab = activateV2LeftDockTab;

    function initLeftDockTabs() {
        var btns = document.querySelectorAll('.v2-left-tbtn[data-v2-left-tab]');
        var panes = document.querySelectorAll('.v2-left-pane[data-v2-left-pane]');
        btns.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var tab = btn.getAttribute('data-v2-left-tab');
                activateV2LeftDockTab(tab);
                if (tab === 'plugins' && window.explorerPanel && window.explorerPanel.setExplorerView) {
                    window.explorerPanel.setExplorerView('project');
                }
                if (tab === 'plugins' && window.explorerPanel && typeof window.explorerPanel.loadPluginsExplorerTree === 'function') {
                    window.explorerPanel.loadPluginsExplorerTree();
                }
                if (tab === 'workspace' && window.explorerPanel && window.explorerPanel.setExplorerView) {
                    window.explorerPanel.setExplorerView('workspace');
                }
            });
        });
        syncV2LeftDockWithExplorerView();
    }

    /** Align Project / Workspace explorer state with the active v2 left-dock tab (Drive must load sessions tree). */
    function syncV2LeftDockWithExplorerView() {
        var activeBtn = document.querySelector('.v2-left-tbtn.active[data-v2-left-tab]');
        if (!activeBtn || !window.explorerPanel || typeof window.explorerPanel.setExplorerView !== 'function') {
            return;
        }
        var tab = activeBtn.getAttribute('data-v2-left-tab');
        if (tab === 'plugins') {
            window.explorerPanel.setExplorerView('project');
        } else if (tab === 'workspace') {
            window.explorerPanel.setExplorerView('workspace');
        }
    }

    function pxVar(name, px) {
        document.documentElement.style.setProperty(name, px + 'px');
    }

    function initResizers() {
        var leftW = parseInt(localStorage.getItem('nos-v2-left-w'), 10);
        var rightW = parseInt(localStorage.getItem('nos-v2-right-w'), 10);
        var midTop = parseFloat(localStorage.getItem('nos-v2-mid-top-fr'));
        if (!isNaN(leftW) && leftW >= 160) pxVar('--v2-left-width', leftW);
        if (!isNaN(rightW) && rightW >= 220) pxVar('--v2-right-width', rightW);
        if (!isNaN(midTop) && midTop >= 0.2 && midTop <= 0.85) {
            document.documentElement.style.setProperty('--v2-center-top-fr', (midTop * 100) + '%');
            document.documentElement.style.setProperty('--v2-center-bottom-fr', ((1 - midTop) * 100) + '%');
        }

        dragResize(document.getElementById('v2-resizer-left'), 'h', function (delta) {
            var ex = document.getElementById('explorer-offcanvas');
            if (!ex) return;
            var w = ex.getBoundingClientRect().width + delta;
            w = Math.max(160, Math.min(window.innerWidth * 0.5, w));
            pxVar('--v2-left-width', w);
            localStorage.setItem('nos-v2-left-w', String(Math.round(w)));
        });

        dragResize(document.getElementById('v2-resizer-right'), 'h', function (delta) {
            var chat = document.querySelector('.console-v2-chat');
            if (!chat) return;
            var w = chat.getBoundingClientRect().width - delta;
            w = Math.max(220, Math.min(window.innerWidth * 0.55, w));
            pxVar('--v2-right-width', w);
            localStorage.setItem('nos-v2-right-w', String(Math.round(w)));
        });

        dragResize(document.getElementById('v2-resizer-middle'), 'v', function (delta) {
            var stack = document.querySelector('.v2-center-stack');
            if (!stack) return;
            var r = stack.getBoundingClientRect();
            var topEl = stack.querySelector('.v2-center-top');
            var botEl = stack.querySelector('.v2-center-bottom');
            if (!topEl || !botEl) return;
            var hTop = topEl.getBoundingClientRect().height + delta;
            var ratio = hTop / r.height;
            ratio = Math.max(0.15, Math.min(0.85, ratio));
            document.documentElement.style.setProperty('--v2-center-top-fr', (ratio * 100) + '%');
            document.documentElement.style.setProperty('--v2-center-bottom-fr', ((1 - ratio) * 100) + '%');
            localStorage.setItem('nos-v2-mid-top-fr', String(ratio));
        });
    }

    function dragResize(el, axis, onDrag) {
        if (!el || !onDrag) return;
        var dragging = false;
        el.addEventListener('mousedown', function (e) {
            dragging = true;
            el.classList.add('dragging');
            document.body.style.userSelect = 'none';
            e.preventDefault();
            var last = axis === 'v' ? e.clientY : e.clientX;
            function move(ev) {
                if (!dragging) return;
                var cur = axis === 'v' ? ev.clientY : ev.clientX;
                onDrag(cur - last);
                last = cur;
            }
            function up() {
                dragging = false;
                el.classList.remove('dragging');
                document.body.style.userSelect = '';
                document.removeEventListener('mousemove', move);
                document.removeEventListener('mouseup', up);
            }
            document.addEventListener('mousemove', move);
            document.addEventListener('mouseup', up);
        });
    }

    function initCollapseToggles() {
        var lb = document.getElementById('v2-toggle-left');
        if (lb) {
            lb.addEventListener('click', function () {
                document.body.classList.toggle('console-v2--left-collapsed');
            });
        }
        var rb = document.getElementById('v2-toggle-right');
        if (rb) {
            rb.addEventListener('click', function () {
                document.body.classList.toggle('console-v2--right-collapsed');
            });
        }
        var bb = document.getElementById('v2-toggle-bottom');
        function syncBottomCollapseToggle() {
            if (!bb) return;
            var collapsed = document.body.classList.contains('console-v2--center-bottom-collapsed');
            bb.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            bb.textContent = collapsed ? '▲' : '▼';
            bb.title = collapsed
                ? 'Expand bottom panel (Terminal / Runtime / Output / Metrics)'
                : 'Collapse bottom panel (Terminal / Runtime / Output / Metrics)';
        }
        if (bb) {
            bb.addEventListener('click', function () {
                document.body.classList.toggle('console-v2--center-bottom-collapsed');
                syncBottomCollapseToggle();
            });
            syncBottomCollapseToggle();
        }
        var exL = document.getElementById('v2-expand-left');
        if (exL) {
            exL.addEventListener('click', function () {
                document.body.classList.remove('console-v2--left-collapsed');
            });
        }
        var exR = document.getElementById('v2-expand-right');
        if (exR) {
            exR.addEventListener('click', function () {
                document.body.classList.remove('console-v2--right-collapsed');
            });
        }
    }

    function initExplorerV2Dock() {
        var ex = document.getElementById('explorer-offcanvas');
        var bd = document.getElementById('explorer-backdrop');
        if (bd) {
            bd.style.display = 'none';
            bd.style.pointerEvents = 'none';
        }
        if (ex) {
            ex.classList.add('open');
        }
        if (window.explorerPanel) {
            if (typeof window.explorerPanel.setExplorerOpenState === 'function') {
                window.explorerPanel.setExplorerOpenState(true);
            }
            if (typeof window.explorerPanel.loadPluginsExplorerTree === 'function') {
                window.explorerPanel.loadPluginsExplorerTree();
            }
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        initExplorerV2Dock();
        initLeftDockTabs();
        initPluginsExplorerRefresh();
        initResizers();
        initCollapseToggles();
        if (window.showTab) {
            window.showTab('workspace');
            window.showTab('console');
            window.showTab('chat-model');
        }
    });
})();
