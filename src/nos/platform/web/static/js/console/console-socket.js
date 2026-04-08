/**
 * Hythera Console - Socket.IO Event Handlers
 * 
 * This file handles all Socket.IO communication:
 * - Connection initialization
 * - Event listeners (socket.on)
 * - Event emitters (socket.emit)
 * 
 * Depends on console-app.js which exposes window.HytheraConsole
 */

'use strict';

(function() {
    'use strict';

    /**
     * Initialize Socket.IO connection and event handlers
     * This function is called when DOM is ready
     */
    function initSocket() {
        // Get reference to console API
        const Console = window.HytheraConsole;
        if (!Console) {
            console.error('HytheraConsole not found. Make sure console-app.js is loaded first.');
            return;
        }

        const state = Console.state;
        const dom = Console.dom;

        // Close existing connection
        if (state.socket) {
            state.socket.disconnect();
        }

        // Create new connection
        state.socket = io({
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionAttempts: 50
        });

        // Track first connection error to avoid spamming the same message on every retry
        let connectionErrorLogged = false;

        // ------------------------------------
        // Connection Events
        // ------------------------------------

        state.socket.on('connect', () => {
            connectionErrorLogged = false;
            Console.updateConnectionStatus(true);
            Console.createPrompt();
        });

        state.socket.on('disconnect', (reason) => {
            Console.updateConnectionStatus(false);
            if (state.currentPrompt) {
                state.currentPrompt.remove();
                state.currentPrompt = null;
            }
            Console.addSystemMessage(`Disconnected: ${reason}`, 'warning');
        });

        state.socket.on('connect_error', (error) => {
            if (!connectionErrorLogged) {
                connectionErrorLogged = true;
                Console.addSystemMessage(`Connection error: ${error.message}. Retrying up to 10 times…`, 'error');
            }
        });

        state.socket.on('reconnect_failed', () => {
            state.socket.disconnect();
            state.socket.removeAllListeners();
            Console.updateConnectionStatus(false);
            if (state.currentPrompt) {
                state.currentPrompt.remove();
                state.currentPrompt = null;
            }
            Console.addSystemMessage('Connection closed after maximum retries. Use Connect from the Console menu to try again.', 'warning');
            Console.createPrompt();
        });

        // ------------------------------------
        // Execution Events
        // ------------------------------------

        /**
         * Listen for execution logs from node/workflow execution.
         * Track currentExecutionId from any event that carries execution_id,
         * so that Ctrl+C works regardless of how the execution was started
         * (Terminal command or Engine Console form).
         */
        state.socket.on('execution_log', (data) => {
            // Set execution_id as soon as we see one (start of any execution)
            if (data.execution_id && !state.currentExecutionId) {
                state.currentExecutionId = data.execution_id;
            }
            // Clear on end events (event field values from NodeEndEvent / WorkflowExecutionResultEvent)
            const endEvents = ['Node end', 'workflow_execution_result', 'node_end', 'error'];
            if (endEvents.includes(data.event)) {
                state.currentExecutionId = null;
            }
            Console.addLogEntry(data);
        });

        /**
         * Listen for console output from command execution
         * This handles command results, progress, errors, etc.
         */
        state.socket.on('console_output', (data) => {
            // Handle clear command
            if (data.type === 'clear') {
                Console.handleClear();
                return;
            }
            
            const targetOutput = data.target === 'output';
            const typeMap = {
                'info': 'info',
                'success': 'success',
                'error': 'error',
                'warning': 'error'
            };
            const outputType = typeMap[data.type] || 'info';
            const format = data.format || 'text';
            
            // Track execution_id for Ctrl+C stop command (terminal only)
            if (!targetOutput && format === 'progress' && data.data && data.data.execution_id) {
                state.currentExecutionId = data.data.execution_id;
            }
            
            if (format !== 'progress') {
                Console.clearProgressIndicators();
                if (data.type === 'success' || data.type === 'error') {
                    state.currentExecutionId = null;
                }
            }
            
            // Final node/workflow result: open a Workspace tab (document) — not the Terminal stream.
            if (targetOutput && Console.renderOutputPanel) {
                Console.renderOutputPanel(data.message, outputType, format, data.data);
                if (typeof Console.addSystemMessage === 'function') {
                    Console.addSystemMessage('Result opened in Workspace.', 'info');
                }
                if (state.connected && !state.currentPrompt) {
                    Console.createPrompt();
                }
                setTimeout(() => {
                    if (window.__execHistory) window.__execHistory.load();
                }, 700);
                return;
            }
            
            // Check for create/open command success - load code into editor
            if (data.type === 'success' && data.data && data.data.action) {
                const action = data.data.action;
                if ((action === 'create_node' || action === 'create_workflow' ||
                     action === 'open_node' || action === 'open_workflow') && data.data.content) {
                    Console.loadCreatedCodeIntoEditor(data.data);
                }
            }

            if (data.data && data.data.action === 'save') {
                if (data.data.success) {
                    window.dispatchEvent(new CustomEvent('code-save-success'));
                } else {
                    window.dispatchEvent(new CustomEvent('code-save-error'));
                }
            }
            
            Console.renderConsoleOutput(data.message, outputType, format, data.data);
            
            if (format !== 'progress' && state.connected && !state.currentPrompt) {
                Console.createPrompt();
            }
        });

        /**
         * Listen for execution requests (bidirectional communication)
         * Handles interactive forms for node/workflow configuration
         */
        state.socket.on('execution_request', (data) => {
            try {
                const eventType = (data && data.event_type) || '';
                const requestData = (data && data.data) || {};
                const requestId = (data && data.request_id) || '';

                if (eventType === 'form_input' || requestData.form_type === 'node_input' || requestData.form_type === 'workflow_initial_state') {
                    const formPayload = {
                        request_id: requestId,
                        title: requestData.title || `Configure ${data.node_id || data.workflow_id || 'Execution'}`,
                        node_id: data.node_id,
                        workflow_id: data.workflow_id,
                        execution_id: data.execution_id,
                        state: requestData.state || { label: 'State', fields: [] },
                        params: requestData.params || { label: 'Parameters', fields: [] }
                    };
                    Console.appendFormToLogEntry(requestId, formPayload);
                } else {
                    Console.addLogEntry({
                        event: 'execution_request',
                        level: 'warning',
                        message: `Server requests: ${eventType}`,
                        request_id: requestId,
                        data: requestData
                    });
                }
            } catch (err) {
                console.error('execution_request handler error:', err);
                const msg = (err && err.message) ? String(err.message) : String(err);
                if (Console.addLogEntry) {
                    Console.addLogEntry({
                        event: 'execution_request',
                        level: 'error',
                        message: 'Form could not be rendered: ' + msg,
                        request_id: (data && data.request_id) || '',
                        data: (data && data.data) || {}
                    });
                }
            }
        });
    }

    /**
     * Handle reconnection request
     */
    function handleReconnect() {
        initSocket();
    }

    // ------------------------------------
    // Initialization
    // ------------------------------------

    function init() {
        // Listen for reconnect event from menu
        window.addEventListener('console-reconnect', handleReconnect);
        window.addEventListener('menu-reconnect', handleReconnect);

        // Listen for Ctrl+C to cancel reconnection retries when disconnected
        window.addEventListener('console-cancel-reconnect', function() {
            const Console = window.HytheraConsole;
            if (!Console || !Console.state || !Console.state.socket) return;
            const state = Console.state;
            if (state.socket.connected) return;
            state.socket.disconnect();
            state.socket.removeAllListeners();
            Console.updateConnectionStatus(false);
            if (state.currentPrompt) {
                state.currentPrompt.remove();
                state.currentPrompt = null;
            }
            Console.addSystemMessage('Connection retries cancelled. Use Connect from the Console menu to try again.', 'warning');
            Console.createPrompt();
        });

        // Initialize Socket.IO connection
        initSocket();
    }

    // Start when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
