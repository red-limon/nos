/**
 * Central top split (v2): load the appropriate document surface from a small typed spec.
 * Execution output and Python source are handled in workspace-documents.js; this module
 * exposes a single entry point for callers (socket, future routes, etc.).
 */
(function() {
    'use strict';

    var KIND = {
        EXECUTION: 'execution',
        PYTHON: 'python'
    };

    /**
     * @param {{ kind: string, data?: object, spec?: object }} spec
     *   - kind === 'execution' → forwards to __workspaceOpenExecutionResult(spec.spec || spec)
     *   - kind === 'python'    → forwards to __workspaceOpenPythonDocument(spec.data)
     */
    function load(spec) {
        if (!spec || !spec.kind) return;
        if (spec.kind === KIND.EXECUTION) {
            var payload = spec.spec != null ? spec.spec : spec;
            if (typeof window.__workspaceOpenExecutionResult === 'function') {
                window.__workspaceOpenExecutionResult(payload);
            }
            return;
        }
        if (spec.kind === KIND.PYTHON) {
            var data = spec.data != null ? spec.data : spec;
            if (typeof window.__workspaceOpenPythonDocument === 'function') {
                window.__workspaceOpenPythonDocument(data);
            }
        }
    }

    window.WorkspaceDocumentStage = {
        DOCUMENT_KIND: KIND,
        load: load
    };
})();
