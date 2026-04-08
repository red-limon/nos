/**
 * Workspace multi-document manager: Python (CodeMirror) + execution result tabs.
 * Execution tabs: one per run (keyed by execution_id), default title "pluginId · executionId".
 */
(function() {
    'use strict';

    var docs = [];
    var activeId = null;
    var railExpanded = false;

    function genId() {
        return 'wsdoc_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    }

    function basename(p) {
        if (!p) return 'Untitled';
        var parts = p.split(/[/\\]/);
        return parts[parts.length - 1] || 'Untitled';
    }

    function docKind(d) {
        return d && d.kind === 'execution' ? 'execution' : 'python';
    }

    function truncate(s, n) {
        s = String(s || '');
        return s.length > n ? s.slice(0, n - 1) + '…' : s;
    }

    /** Map NodeExecutionResult / WorkflowExecutionResult → { format, text } for the editor. */
    function executionDataToEditorText(data) {
        if (data == null) return { format: 'json', text: '' };
        var inner = data.result != null ? data.result : data;
        var resp = inner && inner.response;
        var out = resp && resp.output;
        if (out && typeof out === 'object' && 'data' in out) {
            var fmt = String(out.output_format || 'json').toLowerCase();
            var d = out.data;
            if (fmt === 'text' || fmt === 'code' || fmt === 'html') {
                var s = typeof d === 'string' ? d : d == null ? '' : String(d);
                return { format: fmt, text: s };
            }
            try {
                return { format: fmt, text: JSON.stringify(d == null ? null : d, null, 2) };
            } catch (e) {
                return { format: fmt, text: String(d) };
            }
        }
        try {
            return { format: 'json', text: JSON.stringify(data, null, 2) };
        } catch (e2) {
            return { format: 'json', text: String(data) };
        }
    }

    function applyHtmlPreviewWorkspace(format, text) {
        var ta = document.getElementById('workspace-execution-body');
        var prev = document.getElementById('workspace-execution-html-preview');
        if (!ta || !prev) return;
        prev.innerHTML = '';
        if (format === 'html' && text) {
            var iframe = document.createElement('iframe');
            iframe.className = 'execution-result-html-iframe';
            iframe.setAttribute('sandbox', 'allow-same-origin');
            iframe.title = 'HTML preview';
            iframe.srcdoc = text;
            prev.appendChild(iframe);
            prev.hidden = false;
            ta.classList.add('execution-doc-editor--half');
        } else {
            prev.hidden = true;
            ta.classList.remove('execution-doc-editor--half');
        }
    }

    function flushEditorToDoc(doc) {
        if (!doc || docKind(doc) !== 'python' || !window.__codeEditor) return;
        doc.content = String(window.__codeEditor.value || '');
    }

    function flushExecutionToDoc(doc) {
        if (docKind(doc) !== 'execution') return;
        var ta = document.getElementById('workspace-execution-body');
        var titleIn = document.getElementById('workspace-execution-title');
        if (ta) doc.bodyText = ta.value;
        if (titleIn) doc.displayTitle = titleIn.value;
    }

    function persistActive() {
        var d = docs.find(function(x) { return x.id === activeId; });
        if (!d) return;
        if (docKind(d) === 'execution') flushExecutionToDoc(d);
        else flushEditorToDoc(d);
    }

    function setPythonChromeVisible(on) {
        document.querySelectorAll('.workspace-python-host').forEach(function(el) {
            el.hidden = !on;
            el.style.display = on ? '' : 'none';
        });
    }

    function setExecutionPaneVisible(on) {
        var ex = document.getElementById('workspace-pane-execution');
        if (ex) {
            ex.hidden = !on;
            /* console.css sets .workspace-pane--execution { display:flex } — overrides native [hidden] */
            ex.style.display = on ? '' : 'none';
        }
    }

    function showExecutionWorkspacePane(on) {
        if (on) {
            setPythonChromeVisible(false);
            setExecutionPaneVisible(true);
        } else {
            setExecutionPaneVisible(false);
            setPythonChromeVisible(false);
        }
    }

    function showPythonWorkspacePane(on) {
        if (on) {
            setExecutionPaneVisible(false);
            setPythonChromeVisible(true);
        } else {
            setPythonChromeVisible(false);
        }
    }

    function refreshShellOverlay() {
        var shell = document.getElementById('workspace-shell');
        var overlay = document.getElementById('workspace-empty-overlay');
        var header = document.getElementById('workspace-center-header');
        var hasNoDocs = docs.length === 0;
        if (!shell || !overlay) return;
        if (header) header.hidden = hasNoDocs;
        if (hasNoDocs) {
            shell.setAttribute('data-workspace-kind', 'none');
            overlay.style.display = '';
            overlay.setAttribute('aria-hidden', 'false');
            showExecutionWorkspacePane(false);
            var treeHost = document.getElementById('v2-output-json-tree');
            if (treeHost && typeof window.__renderJsonTreeIntoElement === 'function') {
                window.__renderJsonTreeIntoElement(treeHost, undefined);
            }
            return;
        }
        overlay.style.display = 'none';
        overlay.setAttribute('aria-hidden', 'true');
        var cur = docs.find(function(d) { return d.id === activeId; });
        if (!cur) return;
        if (docKind(cur) === 'execution') {
            shell.setAttribute('data-workspace-kind', 'execution');
            showExecutionWorkspacePane(true);
        } else {
            shell.setAttribute('data-workspace-kind', 'python');
            showPythonWorkspacePane(true);
            var treeHost2 = document.getElementById('v2-output-json-tree');
            if (treeHost2 && typeof window.__renderJsonTreeIntoElement === 'function') {
                window.__renderJsonTreeIntoElement(treeHost2, undefined);
            }
        }
    }

    function fillJsonInspectorText(doc) {
        var p = doc && doc.fullPayload;
        var treeHost = document.getElementById('v2-output-json-tree');
        if (treeHost && typeof window.__renderJsonTreeIntoElement === 'function') {
            window.__renderJsonTreeIntoElement(treeHost, p);
        }
        var ta = document.getElementById('workspace-json-inspector-body');
        if (ta) {
            if (p == null || p === undefined) {
                ta.value = '';
            } else {
                try {
                    ta.value = typeof p === 'object' ? JSON.stringify(p, null, 2) : String(p);
                } catch (e) {
                    ta.value = String(p);
                }
            }
        }
    }

    function applyJsonPanelOpenState(doc) {
        var layout = document.getElementById('workspace-execution-doc-layout');
        var panel = document.getElementById('workspace-json-inspector');
        var btn = document.getElementById('workspace-json-toggle-btn');
        var open = !!(doc && doc.jsonPanelOpen);
        /* Sliding JSON aside (engine_console.html); v2 uses bottom Output tab instead — no #workspace-json-inspector */
        if (layout && panel) layout.classList.toggle('workspace-json-panel-open', open);
        if (panel) panel.setAttribute('aria-hidden', open ? 'false' : 'true');
        if (btn) btn.setAttribute('aria-pressed', open ? 'true' : 'false');
    }

    function updateFormatBadgeVisibility() {
        var badge = document.getElementById('workspace-execution-format-badge');
        if (!badge) return;
        var execDocs = docs.filter(function(d) { return docKind(d) === 'execution'; });
        badge.hidden = execDocs.length === 0;
    }

    function loadExecutionIntoPane(doc) {
        var titleIn = document.getElementById('workspace-execution-title');
        var ta = document.getElementById('workspace-execution-body');
        var badge = document.getElementById('workspace-execution-format-badge');
        if (titleIn) titleIn.value = doc.displayTitle || '';
        if (ta) ta.value = doc.bodyText || '';
        if (badge) {
            badge.textContent = doc.format || '—';
            badge.title = 'Output format: ' + (doc.format || 'unknown');
        }
        applyHtmlPreviewWorkspace(doc.format, doc.bodyText);
        fillJsonInspectorText(doc);
        applyJsonPanelOpenState(doc);
    }

    function showWorkspaceTab() {
        if (typeof window.showTab === 'function') window.showTab('workspace');
    }

    function buildDocRecord(data) {
        var isWf = data.action === 'open_workflow' || data.workflow_id;
        return {
            kind: 'python',
            id: genId(),
            module_path: data.module_path,
            file_path: data.file_path,
            content: data.content,
            registration_status: data.registration_status,
            action: data.action,
            node_id: data.node_id,
            workflow_id: data.workflow_id,
            plugin_type: isWf ? 'workflow' : 'node',
            dirty: false
        };
    }

    function findByModulePath(mp) {
        if (!mp) return null;
        return docs.find(function(d) {
            return docKind(d) === 'python' && d.module_path === mp;
        });
    }

    function findByFilePath(fp) {
        if (!fp) return null;
        var norm = String(fp).replace(/\\/g, '/');
        return docs.find(function(d) {
            if (docKind(d) !== 'python' || !d.file_path) return false;
            return String(d.file_path).replace(/\\/g, '/') === norm;
        });
    }

    function findExecutionByExecId(eid) {
        return docs.find(function(d) {
            return docKind(d) === 'execution' && d.execution_id === eid;
        });
    }

    function buildLoadedDetail(doc) {
        var isWf = doc.plugin_type === 'workflow' || doc.action === 'open_workflow';
        return {
            action: doc.action || (isWf ? 'open_workflow' : 'open_node'),
            id: isWf ? doc.workflow_id : doc.node_id,
            module_path: doc.module_path,
            file_path: doc.file_path,
            registration_status: doc.registration_status
        };
    }

    function tabLabelForDoc(doc) {
        if (docKind(doc) === 'execution') {
            return truncate(doc.displayTitle || doc.plugin_id + ' · ' + doc.execution_id, 32);
        }
        return basename(doc.file_path);
    }

    function activateDocument(id, opts) {
        opts = opts || {};
        if (!opts.skipPersist) persistActive();

        var doc = docs.find(function(d) { return d.id === id; });
        if (!doc) return;

        activeId = id;

        if (docKind(doc) === 'execution') {
            loadExecutionIntoPane(doc);
            if (typeof window.__workspaceUpdateExecutionTitle === 'function') {
                window.__workspaceUpdateExecutionTitle(doc.displayTitle, doc.execution_id, doc.format);
            }
            window.dispatchEvent(new CustomEvent('code-loaded-from-console', { detail: null }));
        } else {
            if (window.__codeEditor) window.__codeEditor.value = doc.content || '';
            if (typeof window.__workspaceUpdateActiveTitle === 'function') {
                window.__workspaceUpdateActiveTitle(doc.file_path);
            }
            window.dispatchEvent(new CustomEvent('code-loaded-from-console', { detail: buildLoadedDetail(doc) }));
            window.dispatchEvent(new CustomEvent('code-editor-loaded', {
                detail: { content: doc.content || '', filePath: doc.file_path }
            }));
            if (window.explorerPanel && typeof window.explorerPanel.loadOutlineForPath === 'function') {
                window.explorerPanel.loadOutlineForPath(doc.file_path);
            }
        }

        renderDocumentChrome();
        refreshShellOverlay();
    }

    function openOrFocusPythonDocument(data) {
        if (!data) return;
        var mp = data.module_path;
        var existing = mp ? findByModulePath(mp) : null;
        if (!existing && data.file_path) {
            existing = findByFilePath(data.file_path);
        }
        persistActive();
        if (existing) {
            if (data.content != null) existing.content = data.content;
            if (data.file_path) existing.file_path = data.file_path;
            if (data.registration_status != null) existing.registration_status = data.registration_status;
            if (data.action) existing.action = data.action;
            if (data.node_id != null) existing.node_id = data.node_id;
            if (data.workflow_id != null) existing.workflow_id = data.workflow_id;
            activateDocument(existing.id, { skipPersist: true });
        } else {
            var rec = buildDocRecord(data);
            docs.push(rec);
            activateDocument(rec.id, { skipPersist: true });
        }
        showWorkspaceTab();
    }

    function openExecutionResult(spec) {
        spec = spec || {};
        var batchImport = !!spec.batchImport;
        var data = spec.data;
        var executionId = spec.executionId || (data && data.execution_id);
        if (!executionId) {
            executionId = 'run_' + genId().replace(/^wsdoc_/, '');
        }
        executionId = String(executionId);

        var pluginId = spec.pluginId || (data && (data.node_id || data.workflow_id)) || 'run';
        var execType = spec.executionType;
        if (!execType) {
            execType = (data && data.workflow_id) ? 'workflow' : 'node';
        }

        var displayTitle = spec.displayTitle || (pluginId + ' · ' + executionId);
        var parsed = executionDataToEditorText(data);
        var fullPayload = spec.fullPayload != null ? spec.fullPayload : data;

        persistActive();

        var existing = findExecutionByExecId(executionId);
        if (existing) {
            existing.displayTitle = displayTitle;
            existing.plugin_id = String(pluginId);
            existing.execution_type = execType;
            existing.format = parsed.format;
            existing.bodyText = parsed.text;
            existing.fullPayload = fullPayload;
            if (existing.jsonPanelOpen === undefined) existing.jsonPanelOpen = false;
            if (spec.outputType) existing.outputType = spec.outputType;
            if (spec.message) existing.message = spec.message;
            if (!batchImport) {
                activateDocument(existing.id, { skipPersist: true });
            }
        } else {
            var rec = {
                kind: 'execution',
                id: genId(),
                execution_id: executionId,
                plugin_id: String(pluginId),
                execution_type: execType,
                displayTitle: displayTitle,
                format: parsed.format,
                bodyText: parsed.text,
                fullPayload: fullPayload,
                outputType: spec.outputType || 'info',
                message: spec.message || '',
                jsonPanelOpen: false
            };
            docs.push(rec);
            if (!batchImport) {
                activateDocument(rec.id, { skipPersist: true });
            }
        }

        if (!batchImport) {
            showWorkspaceTab();
            if (typeof document !== 'undefined' && document.body.classList.contains('console-layout-horizontal')) {
                railExpanded = true;
            }
        }
    }

    /**
     * New blank execution document tab (editable title default "Untitled").
     */
    function openBlankExecutionDocument() {
        var executionId = 'blank_' + genId().replace(/^wsdoc_/, '');
        var minimalData = {
            execution_id: executionId,
            result: {
                response: {
                    output: {
                        output_format: 'text',
                        data: ''
                    }
                }
            }
        };
        openExecutionResult({
            executionId: executionId,
            pluginId: 'document',
            executionType: 'node',
            displayTitle: 'Untitled',
            data: minimalData,
            fullPayload: minimalData
        });
    }

    function openExecutionFromHistory(executionId, run) {
        if (!executionId) return;
        showWorkspaceTab();

        var pluginId = (run && run.plugin_id) || 'run';
        var execType = (run && run.execution_type) || 'node';
        var displayTitle = pluginId + ' · ' + executionId;

        var existing = findExecutionByExecId(executionId);
        if (existing) {
            persistActive();
            existing.displayTitle = displayTitle;
            activateDocument(existing.id, { skipPersist: true });
        } else {
            persistActive();
            var rec = {
                kind: 'execution',
                id: genId(),
                execution_id: String(executionId),
                plugin_id: String(pluginId),
                execution_type: execType,
                displayTitle: displayTitle,
                format: 'json',
                bodyText: 'Loading…',
                fullPayload: null,
                outputType: 'info',
                message: '',
                jsonPanelOpen: false
            };
            docs.push(rec);
            activateDocument(rec.id, { skipPersist: true });
        }

        fetch('/api/execution-run/result-json/' + encodeURIComponent(executionId))
            .then(function(r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function(body) {
                var d = findExecutionByExecId(executionId);
                if (!d) return;

                var runMeta = body.execution_run || run || {};
                if (runMeta.plugin_id) {
                    d.plugin_id = String(runMeta.plugin_id);
                    d.displayTitle = d.plugin_id + ' · ' + executionId;
                }

                if (body.source === 'metadata' && !body.payload) {
                    var hint = (body.read_error ? 'Read error: ' + body.read_error + '\n\n' : '') +
                        'No snapshot file for this run yet.\n\n';
                    try {
                        d.bodyText = hint + JSON.stringify(runMeta, null, 2);
                    } catch (e) {
                        d.bodyText = hint + String(runMeta);
                    }
                    d.format = 'metadata';
                    d.fullPayload = runMeta;
                } else {
                    d.fullPayload = body.payload;
                    var parsed = executionDataToEditorText(body.payload);
                    d.format = parsed.format;
                    d.bodyText = parsed.text;
                }

                if (d.id === activeId) loadExecutionIntoPane(d);
                renderDocumentChrome();
            })
            .catch(function(err) {
                var d = findExecutionByExecId(executionId);
                if (d) {
                    d.bodyText = 'Failed to load: ' + (err && err.message ? err.message : String(err));
                    d.format = 'error';
                    if (d.id === activeId) loadExecutionIntoPane(d);
                    renderDocumentChrome();
                }
            });

        if (document.body.classList.contains('console-layout-horizontal')) railExpanded = true;
    }

    function closeDocument(id, ev) {
        if (ev) {
            ev.stopPropagation();
            ev.preventDefault();
        }
        persistActive();
        var idx = docs.findIndex(function(d) { return d.id === id; });
        if (idx < 0) return;
        docs.splice(idx, 1);

        if (activeId !== id) {
            renderDocumentChrome();
            return;
        }

        if (docs.length === 0) {
            activeId = null;
            if (window.__codeEditor) window.__codeEditor.value = '';
            refreshShellOverlay();
            if (typeof window.__workspaceResetChrome === 'function') {
                window.__workspaceResetChrome();
            }
            window.dispatchEvent(new CustomEvent('code-loaded-from-console', { detail: null }));
        } else {
            var next = docs[Math.min(idx, docs.length - 1)];
            activateDocument(next.id, { skipPersist: true });
        }
        renderDocumentChrome();
    }

    function renderHorizontalTabs() {
        var bar = document.getElementById('workspace-doc-bar');
        var inner = document.getElementById('workspace-doc-bar-inner');
        if (!bar || !inner) return;

        inner.innerHTML = '';
        var tabDocs = docs.slice();
        if (tabDocs.length === 0) {
            bar.hidden = true;
            return;
        }
        bar.hidden = false;

        tabDocs.forEach(function(doc) {
            var tab = document.createElement('button');
            tab.type = 'button';
            tab.className = 'workspace-doc-tab' + (doc.id === activeId ? ' workspace-doc-tab--active' : '');
            tab.setAttribute('role', 'tab');
            tab.setAttribute('aria-selected', doc.id === activeId ? 'true' : 'false');
            tab.dataset.docId = doc.id;

            var name = document.createElement('input');
            name.type = 'text';
            name.className = 'workspace-doc-tab__name';
            name.setAttribute('spellcheck', 'false');
            name.setAttribute('autocomplete', 'off');
            name.maxLength = 160;
            name.value = (doc.displayTitle != null && String(doc.displayTitle).trim() !== '')
                ? String(doc.displayTitle)
                : tabLabelForDoc(doc);
            name.title = docKind(doc) === 'python' ? 'File name' : 'Rename tab';
            name.readOnly = docKind(doc) === 'python';
            /* Do not stopPropagation on click — the tab <button> needs the bubbled click to
             * call activateDocument when switching tabs (the input covers most of the tab). */
            name.addEventListener('mousedown', function(e) { e.stopPropagation(); });
            name.addEventListener('input', function() {
                if (docKind(doc) === 'python') return;
                doc.displayTitle = name.value;
                if (doc.id === activeId && typeof window.__workspaceUpdateExecutionTitle === 'function') {
                    window.__workspaceUpdateExecutionTitle(doc.displayTitle, doc.execution_id, doc.format);
                }
                renderRailList();
            });
            name.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    name.blur();
                }
            });

            var close = document.createElement('span');
            close.className = 'workspace-doc-tab__close';
            close.textContent = '×';
            close.title = 'Close';
            close.setAttribute('role', 'button');
            close.addEventListener('click', function(e) { closeDocument(doc.id, e); });

            tab.addEventListener('click', function(e) {
                if (e.target.closest('.workspace-doc-tab__close')) return;
                if (e.target.closest('.workspace-doc-tab__name')) {
                    if (doc.id !== activeId) {
                        activateDocument(doc.id);
                    }
                    return;
                }
                activateDocument(doc.id);
            });

            tab.appendChild(name);
            tab.appendChild(close);
            inner.appendChild(tab);
        });
    }

    function renderRailList() {
        var ul = document.getElementById('workspace-rail-doc-list');
        if (!ul) return;
        ul.innerHTML = '';
        var railDocs = docs.slice();
        if (railDocs.length === 0) {
            var empty = document.createElement('li');
            empty.className = 'workspace-rail-doc-item workspace-rail-doc-item--empty';
            empty.textContent = 'No open documents';
            ul.appendChild(empty);
            return;
        }
        railDocs.forEach(function(doc) {
            var li = document.createElement('li');
            li.className = 'workspace-rail-doc-item' + (doc.id === activeId ? ' workspace-rail-doc-item--active' : '');
            li.textContent = tabLabelForDoc(doc);
            li.title = docKind(doc) === 'execution' ? doc.execution_id : (doc.file_path || doc.module_path || '');
            li.dataset.docId = doc.id;
            li.addEventListener('click', function() {
                activateDocument(doc.id);
                showWorkspaceTab();
            });
            ul.appendChild(li);
        });
    }

    function syncRailToggle() {
        var toggle = document.getElementById('workspace-rail-toggle');
        var list = document.getElementById('workspace-rail-doc-list');
        if (!list) return;
        if (toggle) {
            toggle.setAttribute('aria-expanded', railExpanded ? 'true' : 'false');
            toggle.textContent = railExpanded ? '▼' : '▶';
        }
        list.classList.toggle('workspace-rail-doc-list--open', railExpanded);
    }

    function normalizeActiveDocForWorkspaceUi() {
        if (!activeId) return;
        var ac = docs.find(function(d) { return d.id === activeId; });
        if (ac) return;
        if (docs.length === 0) return;
        activeId = docs[docs.length - 1].id;
    }

    function renderDocumentChrome() {
        normalizeActiveDocForWorkspaceUi();
        renderHorizontalTabs();
        renderRailList();
        syncRailToggle();
        updateFormatBadgeVisibility();
    }

    function clearActiveExecutionBody() {
        var d = docs.find(function(x) { return x.id === activeId; });
        if (d && docKind(d) === 'execution') {
            d.bodyText = '';
            var ta = document.getElementById('workspace-execution-body');
            if (ta) ta.value = '';
        }
    }

    function wireExecutionPaneControls() {
        var titleIn = document.getElementById('workspace-execution-title');
        if (titleIn && !titleIn.dataset.wired) {
            titleIn.dataset.wired = '1';
            titleIn.addEventListener('input', function() {
                var d = docs.find(function(x) { return x.id === activeId; });
                if (d && docKind(d) === 'execution') {
                    d.displayTitle = titleIn.value;
                    if (typeof window.__workspaceUpdateExecutionTitle === 'function') {
                        window.__workspaceUpdateExecutionTitle(d.displayTitle, d.execution_id, d.format);
                    }
                    renderHorizontalTabs();
                    renderRailList();
                }
            });
        }

        var copyBtn = document.getElementById('workspace-execution-copy-btn');
        if (copyBtn && !copyBtn.dataset.wired) {
            copyBtn.dataset.wired = '1';
            copyBtn.addEventListener('click', function() {
                var ta = document.getElementById('workspace-execution-body');
                var t = ta ? ta.value : '';
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(t).catch(function() {});
                }
            });
        }

        var saveBtn = document.getElementById('workspace-execution-save-btn');
        if (saveBtn && !saveBtn.dataset.wired) {
            saveBtn.dataset.wired = '1';
            saveBtn.addEventListener('click', function() {
                var d = docs.find(function(x) { return x.id === activeId; });
                if (!d || docKind(d) !== 'execution') return;
                flushExecutionToDoc(d);
                var payload = d.fullPayload;
                var text;
                try {
                    text = payload != null && typeof payload === 'object'
                        ? JSON.stringify(payload, null, 2)
                        : String(d.bodyText || '');
                } catch (e) {
                    text = String(d.bodyText || '');
                }
                var ext = d.format === 'html' ? 'html' : (d.format === 'text' || d.format === 'code') ? 'txt' : 'json';
                var base = (d.displayTitle || d.execution_id || 'result').replace(/[^\w\-.\s]/g, '_').trim() || 'result';
                var blob = new Blob([text], { type: 'application/json;charset=utf-8' });
                var url = URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.href = url;
                a.download = base + '.' + ext;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            });
        }

        var jsonToggle = document.getElementById('workspace-json-toggle-btn');
        if (jsonToggle && !jsonToggle.dataset.wired) {
            jsonToggle.dataset.wired = '1';
            jsonToggle.addEventListener('click', function() {
                var d = docs.find(function(x) { return x.id === activeId; });
                if (!d || docKind(d) !== 'execution') return;
                if (d.jsonPanelOpen === undefined) d.jsonPanelOpen = false;
                d.jsonPanelOpen = !d.jsonPanelOpen;
                fillJsonInspectorText(d);
                applyJsonPanelOpenState(d);
            });
        }

        var jsonClose = document.getElementById('workspace-json-inspector-close');
        if (jsonClose && !jsonClose.dataset.wired) {
            jsonClose.dataset.wired = '1';
            jsonClose.addEventListener('click', function() {
                var d = docs.find(function(x) { return x.id === activeId; });
                if (!d || docKind(d) !== 'execution') return;
                d.jsonPanelOpen = false;
                applyJsonPanelOpenState(d);
            });
        }
    }

    function onDomReady() {
        wireExecutionPaneControls();
        var railToggle = document.getElementById('workspace-rail-toggle');
        if (railToggle) {
            railToggle.addEventListener('click', function(e) {
                e.stopPropagation();
                e.preventDefault();
                railExpanded = !railExpanded;
                syncRailToggle();
            });
        }
        updateFormatBadgeVisibility();
        refreshShellOverlay();
    }

    /**
     * Snapshot execution tabs for .nos session save.
     * Each item is the same shape as openExecutionResult() / __workspaceOpenExecutionResult()
     * (the client path used when final output is opened from the Terminal via renderOutputPanel):
     *   executionId, pluginId, executionType, displayTitle,
     *   data + fullPayload (NodeExecutionResult / WorkflowExecutionResult),
     *   outputType, message,
     * plus optional editor state: bodyText, jsonPanelOpen.
     */
    window.__workspaceExportSession = function() {
        persistActive();
        var execDocs = docs.filter(function(d) { return docKind(d) === 'execution'; });
        return {
            documents: execDocs.map(function(d) {
                var payload = d.fullPayload != null ? d.fullPayload : null;
                return {
                    executionId: d.execution_id,
                    pluginId: d.plugin_id,
                    executionType: d.execution_type,
                    displayTitle: d.displayTitle,
                    data: payload,
                    fullPayload: payload,
                    outputType: d.outputType,
                    message: d.message,
                    bodyText: d.bodyText,
                    jsonPanelOpen: !!d.jsonPanelOpen
                };
            }),
            active_execution_id: (function() {
                var ac = docs.find(function(x) { return x.id === activeId; });
                return ac && docKind(ac) === 'execution' ? ac.execution_id : null;
            })()
        };
    };

    /**
     * Restore Workspace tabs by reusing openExecutionResult() so rendering matches a live run.
     * Supports legacy snapshots with snake_case fields only.
     */
    window.__workspaceImportSession = function(ws) {
        if (!ws || !Array.isArray(ws.documents)) return;
        window.__workspaceResetAllDocuments();

        ws.documents.forEach(function(raw) {
            var payload = raw.data != null ? raw.data : raw.fullPayload;
            openExecutionResult({
                executionId: raw.executionId || raw.execution_id,
                pluginId: raw.pluginId || raw.plugin_id,
                executionType: raw.executionType || raw.execution_type,
                displayTitle: raw.displayTitle,
                data: payload,
                fullPayload: raw.fullPayload != null ? raw.fullPayload : payload,
                outputType: raw.outputType,
                message: raw.message,
                batchImport: true
            });
            var sid = String(raw.executionId || raw.execution_id || '');
            var ex = sid ? findExecutionByExecId(sid) : null;
            if (!ex && payload && payload.execution_id) {
                ex = findExecutionByExecId(String(payload.execution_id));
            }
            if (ex) {
                if (raw.bodyText != null) {
                    ex.bodyText = String(raw.bodyText);
                }
                if (raw.jsonPanelOpen != null) {
                    ex.jsonPanelOpen = !!raw.jsonPanelOpen;
                }
                if (raw.displayTitle) {
                    ex.displayTitle = String(raw.displayTitle);
                }
            }
        });

        var act = ws.active_execution_id != null ? ws.active_execution_id : ws.activeExecutionId;
        var execOnly = docs.filter(function(d) { return docKind(d) === 'execution'; });
        var target = act && execOnly.find(function(d) { return d.execution_id === act; });
        if (target) {
            activateDocument(target.id, { skipPersist: true });
        } else if (execOnly.length) {
            activateDocument(execOnly[0].id, { skipPersist: true });
        } else {
            renderDocumentChrome();
        }
        showWorkspaceTab();
        if (typeof document !== 'undefined' && document.body.classList.contains('console-layout-horizontal')) {
            railExpanded = true;
        }
    };

    /**
     * Append execution output tabs from a .out snapshot without clearing existing workspace documents.
     * Same document shape as __workspaceExportSession workspace.documents.
     */
    window.__workspaceAppendOutputDocuments = function(ws) {
        if (!ws || !Array.isArray(ws.documents)) return;
        ws.documents.forEach(function(raw) {
            var payload = raw.data != null ? raw.data : raw.fullPayload;
            openExecutionResult({
                executionId: raw.executionId || raw.execution_id,
                pluginId: raw.pluginId || raw.plugin_id,
                executionType: raw.executionType || raw.execution_type,
                displayTitle: raw.displayTitle,
                data: payload,
                fullPayload: raw.fullPayload != null ? raw.fullPayload : payload,
                outputType: raw.outputType,
                message: raw.message,
                batchImport: true
            });
            var sid = String(raw.executionId || raw.execution_id || '');
            var ex = sid ? findExecutionByExecId(sid) : null;
            if (!ex && payload && payload.execution_id) {
                ex = findExecutionByExecId(String(payload.execution_id));
            }
            if (ex) {
                if (raw.bodyText != null) ex.bodyText = String(raw.bodyText);
                if (raw.jsonPanelOpen != null) ex.jsonPanelOpen = !!raw.jsonPanelOpen;
                if (raw.displayTitle) ex.displayTitle = String(raw.displayTitle);
            }
        });
        var act = ws.active_execution_id != null ? ws.active_execution_id : ws.activeExecutionId;
        var execOnly = docs.filter(function(d) { return docKind(d) === 'execution'; });
        var target = act && execOnly.find(function(d) { return d.execution_id === act; });
        if (target) {
            activateDocument(target.id, { skipPersist: true });
        } else if (execOnly.length) {
            activateDocument(execOnly[execOnly.length - 1].id, { skipPersist: true });
        } else {
            renderDocumentChrome();
        }
        showWorkspaceTab();
        if (typeof document !== 'undefined' && document.body.classList.contains('console-layout-horizontal')) {
            railExpanded = true;
        }
    };

    window.__workspaceOpenPythonDocument = openOrFocusPythonDocument;
    window.__workspaceOpenDocument = openOrFocusPythonDocument;
    window.__workspaceOpenExecutionResult = openExecutionResult;
    window.__workspaceOpenBlankDocument = openBlankExecutionDocument;
    window.__workspaceOpenExecutionFromHistory = openExecutionFromHistory;
    window.__workspaceClearActiveExecutionBody = clearActiveExecutionBody;

    window.__workspaceResetAllDocuments = function() {
        persistActive();
        docs = [];
        activeId = null;
        railExpanded = false;
        if (window.__codeEditor) window.__codeEditor.value = '';
        var layout = document.getElementById('workspace-execution-doc-layout');
        if (layout) layout.classList.remove('workspace-json-panel-open');
        var jbtn = document.getElementById('workspace-json-toggle-btn');
        if (jbtn) jbtn.setAttribute('aria-pressed', 'false');
        refreshShellOverlay();
        renderDocumentChrome();
        window.dispatchEvent(new CustomEvent('code-loaded-from-console', { detail: null }));
        if (typeof window.__workspaceResetChrome === 'function') {
            window.__workspaceResetChrome();
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', onDomReady);
    } else {
        onDomReady();
    }
})();
