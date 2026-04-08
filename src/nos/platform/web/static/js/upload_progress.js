/**
 * upload_progress.js - Upload files via HTTP with progress bar.
 * Used by engine console form: upload file fields first, then send form_data via Socket.IO.
 *
 * Usage:
 *   var result = await window.UploadProgress.uploadWithProgress('/api/upload/temp', formData, { progressContainer: element });
 *   // result.uploads = [{ upload_id, filename, size }, ...]
 */

(function (global) {
    'use strict';

    function createProgressBar(container) {
        var wrap = document.createElement('div');
        wrap.style.cssText = 'margin:0.35rem 0;background:#1a1a1a;border:1px solid #333;border-radius:2px;overflow:hidden;';
        var bar = document.createElement('div');
        bar.style.cssText = 'height:6px;background:#4ec9b0;width:0%;transition:width 0.15s;';
        var text = document.createElement('div');
        text.style.cssText = 'font-size:0.8rem;color:#858585;padding:0.2rem 0.35rem;';
        text.textContent = '0%';
        wrap.appendChild(bar);
        wrap.appendChild(text);
        if (container && container.appendChild) {
            container.appendChild(wrap);
        }
        return {
            wrap: wrap,
            bar: bar,
            text: text,
            setProgress: function (pct, msg) {
                pct = Math.min(100, Math.max(0, pct));
                this.bar.style.width = pct + '%';
                this.text.textContent = msg != null ? msg : (Math.round(pct) + '%');
            },
            remove: function () {
                if (this.wrap && this.wrap.parentNode) {
                    this.wrap.parentNode.removeChild(this.wrap);
                }
            }
        };
    }

    /**
     * Upload files via XHR with progress. Returns Promise<{ success, uploads, error }>.
     * @param {string} url - e.g. '/api/upload/temp'
     * @param {FormData} formData - FormData with 'file' or 'files' (and optional max_size_mb, accept)
     * @param {Object} options - { progressContainer: HTMLElement }
     */
    function uploadWithProgress(url, formData, options) {
        options = options || {};
        var progressContainer = options.progressContainer || null;
        var progress = createProgressBar(progressContainer);

        return new Promise(function (resolve, reject) {
            var xhr = new XMLHttpRequest();
            var baseUrl = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
            var fullUrl = (url.indexOf('http') === 0) ? url : (baseUrl + url);

            xhr.upload.addEventListener('progress', function (e) {
                if (e.lengthComputable) {
                    var pct = (e.loaded / e.total) * 100;
                    progress.setProgress(pct, Math.round(pct) + '%');
                } else {
                    progress.setProgress(50, 'Uploading...');
                }
            });

            xhr.addEventListener('load', function () {
                progress.setProgress(100, 'Done');
                setTimeout(function () {
                    progress.remove();
                }, 400);
                var json = null;
                try {
                    json = JSON.parse(xhr.responseText || '{}');
                } catch (err) {
                    resolve({ success: false, error: 'Invalid response', uploads: [] });
                    return;
                }
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve({
                        success: true,
                        uploads: json.uploads || [],
                        error: json.error || null
                    });
                } else {
                    resolve({
                        success: false,
                        error: json.error || xhr.statusText || 'Upload failed',
                        uploads: json.uploads || []
                    });
                }
            });

            xhr.addEventListener('error', function () {
                progress.remove();
                resolve({ success: false, error: 'Network error', uploads: [] });
            });

            xhr.addEventListener('abort', function () {
                progress.remove();
                resolve({ success: false, error: 'Aborted', uploads: [] });
            });

            xhr.open('POST', fullUrl);
            xhr.send(formData);
        });
    }

    global.UploadProgress = {
        uploadWithProgress: uploadWithProgress,
        createProgressBar: createProgressBar
    };
})(typeof window !== 'undefined' ? window : this);
