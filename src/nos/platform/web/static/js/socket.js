/**
 * Socket.IO client integration
 * Connects to Flask-SocketIO server
 */

(function() {
    'use strict';

    // Check if socket.io is available (loaded via CDN or npm)
    if (typeof io === 'undefined') {
        console.warn('Socket.IO client library not found. WebSocket features will be disabled.');
        return;
    }

    // Initialize Socket.IO connection
    const socket = io();

    // Connection event handlers
    socket.on('connect', function() {
        console.log('Socket.IO connected');
        updateConnectionStatus(true);
    });

    socket.on('disconnect', function() {
        console.log('Socket.IO disconnected');
        updateConnectionStatus(false);
    });

    socket.on('connect_error', function(error) {
        console.error('Socket.IO connection error:', error);
        updateConnectionStatus(false);
    });

    // Status message handler
    socket.on('status', function(data) {
        console.log('Status:', data);
        if (data.msg) {
            showNotification(data.msg, 'info');
        }
    });

    // Message handler
    socket.on('message', function(data) {
        console.log('Message received:', data);
        showNotification('New message received', 'info');
    });

    // Custom event handlers can be added here
    socket.on('user_event', function(data) {
        console.log('User event:', data);
        showNotification(`User event: ${data.type || 'unknown'}`, 'info');
    });

    // Helper function to update connection status in UI
    function updateConnectionStatus(connected) {
        const statusElement = document.getElementById('socket-status');
        if (statusElement) {
            statusElement.textContent = connected ? 'Connected' : 'Disconnected';
            statusElement.className = connected ? 'status-connected' : 'status-disconnected';
        }
    }

    // Helper function to show notifications
    function showNotification(message, type) {
        // Simple notification - can be enhanced with a toast library
        console.log(`[${type.toUpperCase()}] ${message}`);
    }

    // Expose socket instance globally for custom usage
    window.seedxSocket = socket;

    // Helper function to send messages
    window.sendSocketMessage = function(event, data) {
        if (socket.connected) {
            socket.emit(event, data);
        } else {
            console.warn('Socket not connected. Cannot send message.');
        }
    };

})();
