/**
 * Engine console session save/load (.wks JSON under drive/…/session).
 *
 * Schema (format_version 1):
 * {
 *   "format_version": 1,
 *   "kind": "nos_engine_console_workspace",
 *   "saved_at": "<ISO8601>",
 *   "terminal": { "main_html", "split_html", "command_history" },
 *   "workspace": { "active_execution_id", "documents": [ ... ] }
 * }
 * Execution-only snapshot (.out) uses kind "nos_engine_console_output" with only "workspace" filled.
 */
(function() {
    'use strict';

    var _lastSaveFilename = null;

    function defaultFilename() {
        var d = new Date();
        var pad = function(n) { return String(n).padStart(2, '0'); };
        return 'session-' + d.getFullYear() +
            pad(d.getMonth() + 1) + pad(d.getDate()) + '-' +
            pad(d.getHours()) + pad(d.getMinutes()) + pad(d.getSeconds()) + '.wks';
    }

    function buildSessionPayload() {
        var HC = window.HytheraConsole;
        var terminal = HC && typeof HC.serializeTerminalForSession === 'function'
            ? HC.serializeTerminalForSession()
            : { main_html: '', split_html: '', command_history: [] };
        var workspace = typeof window.__workspaceExportSession === 'function'
            ? window.__workspaceExportSession()
            : { documents: [], active_execution_id: null };
        return {
            format_version: 1,
            kind: 'nos_engine_console_workspace',
            saved_at: new Date().toISOString(),
            terminal: terminal,
            workspace: workspace
        };
    }

    function buildOutputOnlyPayload() {
        var workspace = typeof window.__workspaceExportSession === 'function'
            ? window.__workspaceExportSession()
            : { documents: [], active_execution_id: null };
        return {
            format_version: 1,
            kind: 'nos_engine_console_output',
            saved_at: new Date().toISOString(),
            workspace: workspace
        };
    }

    function validateLoadedSession(obj) {
        if (!obj || typeof obj !== 'object') return false;
        if (obj.format_version === 1) return true;
        if (obj.kind === 'nos_engine_console_workspace' || obj.kind === 'nos_engine_console_session') return true;
        return false;
    }

    function applySessionPayload(obj) {
        if (!validateLoadedSession(obj)) {
            window.alert('Invalid or unsupported workspace session file (.wks).');
            return;
        }
        var HC = window.HytheraConsole;
        if (HC && typeof HC.restoreTerminalFromSession === 'function') {
            HC.restoreTerminalFromSession(obj.terminal || {});
        }
        if (typeof window.__workspaceImportSession === 'function') {
            window.__workspaceImportSession(obj.workspace || { documents: [] });
        }
        if (typeof window.showTab === 'function') {
            window.showTab('console');
        }
        if (typeof window.closeAllMenus === 'function') {
            window.closeAllMenus();
        }
        if (HC && typeof HC.addSystemMessage === 'function') {
            HC.addSystemMessage('Workspace session restored.', 'info');
        }
    }

    function applyOutputPayload(obj) {
        if (!obj || typeof obj !== 'object') return;
        if (obj.kind !== 'nos_engine_console_output' && obj.format_version !== 1) {
            window.alert('Invalid execution output snapshot (.out).');
            return;
        }
        var ws = obj.workspace || { documents: [] };
        if (typeof window.__workspaceAppendOutputDocuments === 'function') {
            window.__workspaceAppendOutputDocuments(ws);
        } else if (typeof window.__workspaceImportSession === 'function') {
            window.__workspaceImportSession(ws);
        }
        if (typeof window.showTab === 'function') {
            window.showTab('workspace');
        }
        if (typeof window.closeAllMenus === 'function') {
            window.closeAllMenus();
        }
        var HC = window.HytheraConsole;
        if (HC && typeof HC.addSystemMessage === 'function') {
            HC.addSystemMessage('Execution output opened in workspace.', 'info');
        }
    }

    function postSave(filename, payload, executionOutput) {
        var body = { filename: filename, session: payload };
        if (executionOutput != null) {
            body.execution_output = executionOutput;
        }
        return fetch('/api/console/user-session/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify(body)
        }).then(function(r) {
            return r.json().then(function(data) {
                if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
                return data;
            });
        });
    }

    function saveSession(filename) {
        var payload = buildSessionPayload();
        var outOnly = buildOutputOnlyPayload();
        var name = (filename || '').trim() || defaultFilename();
        return postSave(name, payload, outOnly).then(function(data) {
            _lastSaveFilename = data.filename || name;
            if (window.explorerPanel && typeof window.explorerPanel.invalidateSessionsTreeCache === 'function') {
                window.explorerPanel.invalidateSessionsTreeCache();
            }
            var HC = window.HytheraConsole;
            if (HC && typeof HC.addSystemMessage === 'function') {
                var paths = data.paths || {};
                var msg = 'Workspace session saved';
                if (paths.wks && paths.out) {
                    msg += ': ' + paths.wks + ' + ' + paths.out;
                } else {
                    msg += ': ' + (data.path || name);
                }
                HC.addSystemMessage(msg, 'success');
            }
            return data;
        });
    }

    function loadSessionFromPath(absPath) {
        if (!absPath) return Promise.reject(new Error('No path'));
        return fetch('/api/console/user-session/read?path=' + encodeURIComponent(absPath), {
            credentials: 'same-origin'
        }).then(function(r) {
            return r.json().then(function(data) {
                if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
                if (data.file_kind === 'output' && data.output) {
                    applyOutputPayload(data.output);
                    return data;
                }
                if (!data.session) throw new Error('Empty session');
                applySessionPayload(data.session);
                return data;
            });
        });
    }

    window.__nosBuildSessionPayload = buildSessionPayload;
    window.__nosBuildOutputOnlyPayload = buildOutputOnlyPayload;
    window.__nosApplySessionPayload = applySessionPayload;
    window.__nosApplyOutputPayload = applyOutputPayload;
    window.__nosSaveConsoleSession = saveSession;
    window.__nosLoadConsoleSessionFromPath = loadSessionFromPath;

    document.addEventListener('DOMContentLoaded', function() {
        var saveBtn = document.getElementById('menu-save');
        if (saveBtn) {
            saveBtn.addEventListener('click', function() {
                var name = _lastSaveFilename || defaultFilename();
                saveSession(name).catch(function(err) {
                    console.error(err);
                    window.alert('Save failed: ' + (err && err.message ? err.message : String(err)));
                });
                if (typeof window.closeAllMenus === 'function') window.closeAllMenus();
            });
        }
        var saveAsBtn = document.getElementById('menu-save-as');
        if (saveAsBtn) {
            saveAsBtn.addEventListener('click', function() {
                var suggested = _lastSaveFilename || defaultFilename();
                var name = window.prompt('Workspace session file name (.wks)', suggested);
                if (name === null) {
                    if (typeof window.closeAllMenus === 'function') window.closeAllMenus();
                    return;
                }
                name = name.trim() || defaultFilename();
                saveSession(name).catch(function(err) {
                    console.error(err);
                    window.alert('Save failed: ' + (err && err.message ? err.message : String(err)));
                });
                if (typeof window.closeAllMenus === 'function') window.closeAllMenus();
            });
        }
        var histMenu = document.getElementById('menu-history');
        if (histMenu) {
            histMenu.addEventListener('click', function() {
                if (typeof window.showTab === 'function') window.showTab('history');
                if (typeof window.closeAllMenus === 'function') window.closeAllMenus();
                if (window.__execHistory && typeof window.__execHistory.load === 'function') {
                    window.__execHistory.load();
                }
            });
        }
    });
})();
