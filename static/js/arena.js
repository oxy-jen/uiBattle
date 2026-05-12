// Arena-specific JavaScript
let htmlEditor, cssEditor, jsEditor;
let currentTab = 'html';
let diffCheckInterval = null;
let sliderActive = false;
let sliderPercent = 50;

// Get DOM elements safely
function getElement(id) {
    return document.getElementById(id);
}

// Get configuration from hidden inputs
const ROOM_ID = parseInt(getElement('room-id')?.value || '0');
const ROOM_CODE = getElement('room-code')?.value || '';
const CURRENT_USERNAME = getElement('current-username')?.value || '';
const USER_ROLE = getElement('user-role')?.value || '';
const CHALLENGE_TYPE = getElement('challenge-type')?.value || 'image';
const HTML_LOCKED = getElement('html-locked')?.value === 'true';
const TIME_LIMIT = parseInt(getElement('challenge-time-limit')?.value || '120');
const TARGET_IMAGE_URL = getElement('target-image-url')?.value || '';
const TARGET_HTML_RAW = getElement('target-html-data')?.value || '';
const TARGET_CSS_RAW = getElement('target-css-data')?.value || '';

// Parse target HTML/CSS (handle JSON escaping)
let TARGET_HTML = TARGET_HTML_RAW;
let TARGET_CSS = TARGET_CSS_RAW;
try {
    if (TARGET_HTML_RAW && TARGET_HTML_RAW.startsWith('"')) {
        TARGET_HTML = JSON.parse(TARGET_HTML_RAW);
    }
    if (TARGET_CSS_RAW && TARGET_CSS_RAW.startsWith('"')) {
        TARGET_CSS = JSON.parse(TARGET_CSS_RAW);
    }
} catch(e) {}

// Initialize CodeMirror editors
function initEditors() {
    const htmlEditorElem = getElement('html-editor');
    const cssEditorElem = getElement('css-editor');
    const jsEditorElem = getElement('js-editor');
    
    if (!htmlEditorElem) return;
    
    htmlEditor = CodeMirror(htmlEditorElem, {
        mode: 'htmlmixed',
        theme: 'dracula',
        lineNumbers: true,
        tabSize: 2,
        indentWithTabs: false,
        lineWrapping: false,
        autoCloseBrackets: true,
        matchBrackets: true,
        extraKeys: { "Tab": "indentMore", "Shift-Tab": "indentLess" }
    });
    
    cssEditor = CodeMirror(cssEditorElem, {
        mode: 'css',
        theme: 'dracula',
        lineNumbers: true,
        tabSize: 2,
        indentWithTabs: false,
        lineWrapping: false,
        autoCloseBrackets: true,
        matchBrackets: true
    });
    
    jsEditor = CodeMirror(jsEditorElem, {
        mode: 'javascript',
        theme: 'dracula',
        lineNumbers: true,
        tabSize: 2,
        indentWithTabs: false,
        lineWrapping: false,
        autoCloseBrackets: true,
        matchBrackets: true
    });
    
    // Set initial content based on challenge type
    if (CHALLENGE_TYPE === 'html') {
        if (TARGET_HTML) htmlEditor.setValue(TARGET_HTML);
        if (HTML_LOCKED) {
            htmlEditor.setOption('readOnly', true);
            const htmlTab = document.querySelector('[data-tab="html"]');
            if (htmlTab) htmlTab.innerHTML = '🔒 HTML';
        }
        cssEditor.setValue('');
        jsEditor.setValue('');
        // Switch to CSS tab by default
        switchTab('css');
    } else {
        htmlEditor.setValue('');
        cssEditor.setValue('');
        jsEditor.setValue('');
        switchTab('html');
    }
    
    // Restore from localStorage
    const savedHtml = getFromLocal(`arena_${ROOM_ID}_${CURRENT_USERNAME}_html`);
    const savedCss = getFromLocal(`arena_${ROOM_ID}_${CURRENT_USERNAME}_css`);
    const savedJs = getFromLocal(`arena_${ROOM_ID}_${CURRENT_USERNAME}_js`);
    
    if (savedHtml && (!HTML_LOCKED || CHALLENGE_TYPE !== 'html')) htmlEditor.setValue(savedHtml);
    if (savedCss) cssEditor.setValue(savedCss);
    if (savedJs) jsEditor.setValue(savedJs);
    
    // Add change listeners
    htmlEditor.on('change', debounce(() => {
        updatePreview();
        saveToLocal();
    }, 300));
    
    cssEditor.on('change', debounce(() => {
        updatePreview();
        saveToLocal();
    }, 300));
    
    jsEditor.on('change', debounce(() => {
        updatePreview();
        saveToLocal();
    }, 300));
    
    // Cursor position display
    htmlEditor.on('cursorActivity', updateCursorPosition);
    cssEditor.on('cursorActivity', updateCursorPosition);
    jsEditor.on('cursorActivity', updateCursorPosition);
    
    // Initially lock editors until challenge starts
    const isSpectator = USER_ROLE === 'spectator';
    const isWaiting = getElement('room-status')?.textContent === 'WAITING';
    
    if (isSpectator || isWaiting) {
        htmlEditor.setOption('readOnly', true);
        cssEditor.setOption('readOnly', true);
        jsEditor.setOption('readOnly', true);
    }
}

function updateCursorPosition() {
    let editor, pos, mode;
    if (currentTab === 'html') {
        editor = htmlEditor;
        mode = 'HTML';
    } else if (currentTab === 'css') {
        editor = cssEditor;
        mode = 'CSS';
    } else {
        editor = jsEditor;
        mode = 'JS';
    }
    
    if (editor) {
        pos = editor.getCursor();
        const statusBar = getElement('cursor-position');
        if (statusBar) {
            statusBar.textContent = `Ln ${pos.line + 1}, Col ${pos.ch + 1}`;
        }
        const modeSpan = getElement('editor-mode');
        if (modeSpan) modeSpan.textContent = mode;
    }
}

function updatePreview() {
    const html = htmlEditor.getValue();
    const css = cssEditor.getValue();
    const js = jsEditor.getValue();
    
    const doc = `<!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>${css}</style>
    </head>
    <body>
        ${html}
        <script>${js}<\/script>
    </body>
    </html>`;
    
    const outputFrame = getElement('output-frame');
    if (outputFrame) {
        outputFrame.srcdoc = doc;
    }
}

function saveToLocal() {
    if (!HTML_LOCKED || CHALLENGE_TYPE !== 'html') {
        saveToLocal(`arena_${ROOM_ID}_${CURRENT_USERNAME}_html`, htmlEditor.getValue());
    }
    saveToLocal(`arena_${ROOM_ID}_${CURRENT_USERNAME}_css`, cssEditor.getValue());
    saveToLocal(`arena_${ROOM_ID}_${CURRENT_USERNAME}_js`, jsEditor.getValue());
}

// Tab switching
function switchTab(tab) {
    currentTab = tab;
    
    const htmlEditorDiv = getElement('html-editor');
    const cssEditorDiv = getElement('css-editor');
    const jsEditorDiv = getElement('js-editor');
    const tabs = document.querySelectorAll('.tab-btn');
    
    if (htmlEditorDiv) htmlEditorDiv.style.display = tab === 'html' ? 'block' : 'none';
    if (cssEditorDiv) cssEditorDiv.style.display = tab === 'css' ? 'block' : 'none';
    if (jsEditorDiv) jsEditorDiv.style.display = tab === 'js' ? 'block' : 'none';
    
    tabs.forEach(btn => {
        if (btn.dataset.tab === tab) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    
    // Refresh CodeMirror
    if (tab === 'html' && htmlEditor) htmlEditor.refresh();
    if (tab === 'css' && cssEditor) cssEditor.refresh();
    if (tab === 'js' && jsEditor) jsEditor.refresh();
    
    updateCursorPosition();
}

// Initialize target based on challenge type
function initTarget() {
    const targetImg = getElement('target-image');
    const targetFrame = getElement('target-frame');
    
    if (CHALLENGE_TYPE === 'html') {
        if (targetImg) targetImg.style.display = 'none';
        if (targetFrame) {
            targetFrame.style.display = 'block';
            const targetDoc = `<!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>${TARGET_CSS || ''}</style>
            </head>
            <body>
                ${TARGET_HTML || ''}
            </body>
            </html>`;
            targetFrame.srcdoc = targetDoc;
        }
        const typeLabel = getElement('target-type-label');
        if (typeLabel) typeLabel.textContent = 'HTML Target';
    } else {
        if (targetFrame) targetFrame.style.display = 'none';
        if (targetImg && TARGET_IMAGE_URL) {
            targetImg.style.display = 'block';
            targetImg.src = TARGET_IMAGE_URL;
        }
        const typeLabel = getElement('target-type-label');
        if (typeLabel) typeLabel.textContent = 'Image Target';
    }
}

// Diff check system
async function runDiffCheck() {
    const btn = getElement('submit-btn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';
    }
    
    try {
        const W = 400, H = 300;
        
        // Screenshot player's output
        const outputFrame = getElement('output-frame');
        if (!outputFrame) throw new Error('Output frame not found');
        
        const outputFrameDoc = outputFrame.contentDocument || outputFrame.contentWindow.document;
        const outputCanvas = await html2canvas(outputFrameDoc.body, {
            width: W, height: H, scale: 1,
            backgroundColor: '#ffffff',
            useCORS: true,
            logging: false
        });
        
        // Get target canvas
        const targetCanvas = document.createElement('canvas');
        targetCanvas.width = W;
        targetCanvas.height = H;
        const tCtx = targetCanvas.getContext('2d');
        tCtx.fillStyle = '#ffffff';
        tCtx.fillRect(0, 0, W, H);
        
        if (CHALLENGE_TYPE === 'image') {
            const targetImg = getElement('target-image');
            if (targetImg && targetImg.complete && targetImg.naturalWidth > 0) {
                tCtx.drawImage(targetImg, 0, 0, W, H);
            }
        } else {
            const targetFrame = getElement('target-frame');
            if (targetFrame) {
                const targetFrameDoc = targetFrame.contentDocument || targetFrame.contentWindow.document;
                const tFrameCanvas = await html2canvas(targetFrameDoc.body, {
                    width: W, height: H, scale: 1,
                    backgroundColor: '#ffffff',
                    useCORS: true,
                    logging: false
                });
                tCtx.drawImage(tFrameCanvas, 0, 0, W, H);
            }
        }
        
        // Run pixelmatch
        const outData = outputCanvas.getContext('2d').getImageData(0, 0, W, H);
        const tgtData = targetCanvas.getContext('2d').getImageData(0, 0, W, H);
        
        const diffCanvas = getElement('diff-canvas');
        if (diffCanvas) {
            diffCanvas.width = W;
            diffCanvas.height = H;
            const dCtx = diffCanvas.getContext('2d');
            const diffImgData = dCtx.createImageData(W, H);
            
            const mismatched = pixelmatch(
                outData.data, tgtData.data, diffImgData.data,
                W, H, { threshold: 0.1, includeAA: true }
            );
            
            dCtx.putImageData(diffImgData, 0, 0);
            
            // Calculate accuracy
            const total = W * H;
            const accuracy = parseFloat((((total - mismatched) / total) * 100).toFixed(1));
            
            // Update UI
            updateMyProgressBar(accuracy);
            updateAccuracyBadge(accuracy);
            
            // Populate slider canvases
            populateSliderCanvases(outputCanvas, targetCanvas);
            
            // Save submission
            await fetch('/submission/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    room_id: ROOM_ID,
                    challenge_id: null,
                    html_code: htmlEditor.getValue(),
                    css_code: cssEditor.getValue(),
                    js_code: jsEditor.getValue(),
                    accuracy: accuracy
                })
            });
            
            // Broadcast accuracy
            if (window.socket) {
                socket.emit('progress_update', {
                    room_id: ROOM_ID,
                    username: CURRENT_USERNAME,
                    accuracy: accuracy
                });
            }
            
            showToast(`Score: ${accuracy}% match`, accuracy >= 80 ? 'success' : 'info');
            return accuracy;
        }
    } catch (err) {
        console.error('Diff failed:', err);
        showToast('Comparison failed. Try again.', 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-check-circle"></i> SUBMIT & CHECK';
        }
    }
    return 0;
}

function updateMyProgressBar(accuracy) {
    const isP1 = USER_ROLE === 'player1';
    const barId = isP1 ? 'p1-progress-fill' : 'p2-progress-fill';
    const lblId = isP1 ? 'p1-accuracy-label' : 'p2-accuracy-label';
    
    const bar = getElement(barId);
    const label = getElement(lblId);
    
    if (bar) bar.style.width = accuracy + '%';
    if (label) {
        label.textContent = accuracy + '%';
        label.classList.add('flash-update');
        setTimeout(() => label.classList.remove('flash-update'), 600);
    }
}

function updateAccuracyBadge(accuracy) {
    const badge = getElement('accuracy-badge');
    if (badge) {
        badge.textContent = accuracy + '% MATCH';
        badge.className = accuracy >= 80 ? 'badge-success' : 
                         accuracy >= 50 ? 'badge-warning' : 'badge-danger';
    }
}

// Slider diff functions
function initSlider() {
    const container = getElement('slider-diff-container');
    const divider = getElement('slider-divider');
    const rightWrap = getElement('slider-right-wrapper');
    
    if (!container || !divider) return;
    
    divider.addEventListener('mousedown', (e) => {
        sliderActive = true;
        e.preventDefault();
    });
    
    document.addEventListener('mousemove', (e) => {
        if (!sliderActive) return;
        const rect = container.getBoundingClientRect();
        let x = e.clientX - rect.left;
        x = Math.max(0, Math.min(x, rect.width));
        sliderPercent = (x / rect.width) * 100;
        updateSliderPosition(sliderPercent);
    });
    
    document.addEventListener('mouseup', () => {
        sliderActive = false;
    });
    
    // Touch support
    divider.addEventListener('touchstart', (e) => {
        sliderActive = true;
        e.preventDefault();
    });
    
    document.addEventListener('touchmove', (e) => {
        if (!sliderActive) return;
        const rect = container.getBoundingClientRect();
        let x = e.touches[0].clientX - rect.left;
        x = Math.max(0, Math.min(x, rect.width));
        sliderPercent = (x / rect.width) * 100;
        updateSliderPosition(sliderPercent);
    });
    
    document.addEventListener('touchend', () => {
        sliderActive = false;
    });
}

function updateSliderPosition(percent) {
    const divider = getElement('slider-divider');
    const rightWrap = getElement('slider-right-wrapper');
    const leftTint = getElement('slider-output-tint');
    
    if (divider) divider.style.left = percent + '%';
    if (rightWrap) rightWrap.style.width = (100 - percent) + '%';
    if (leftTint) leftTint.style.width = percent + '%';
}

function populateSliderCanvases(outputCanvas, targetCanvas) {
    const sliderOut = getElement('slider-output-canvas');
    const sliderTgt = getElement('slider-target-canvas');
    
    if (sliderOut) {
        sliderOut.width = outputCanvas.width;
        sliderOut.height = outputCanvas.height;
        sliderOut.getContext('2d').drawImage(outputCanvas, 0, 0);
    }
    
    if (sliderTgt) {
        sliderTgt.width = targetCanvas.width;
        sliderTgt.height = targetCanvas.height;
        sliderTgt.getContext('2d').drawImage(targetCanvas, 0, 0);
    }
    
    updateSliderPosition(50);
}

// Diff view toggle
function initDiffToggle() {
    const pixelBtn = document.querySelector('[data-view="pixel"]');
    const sliderBtn = document.querySelector('[data-view="slider"]');
    const diffCanvas = getElement('diff-canvas');
    const sliderContainer = getElement('slider-diff-container');
    
    if (pixelBtn) {
        pixelBtn.addEventListener('click', () => {
            if (diffCanvas) diffCanvas.style.display = 'block';
            if (sliderContainer) sliderContainer.style.display = 'none';
            pixelBtn.classList.add('active');
            if (sliderBtn) sliderBtn.classList.remove('active');
        });
    }
    
    if (sliderBtn) {
        sliderBtn.addEventListener('click', () => {
            if (diffCanvas) diffCanvas.style.display = 'none';
            if (sliderContainer) sliderContainer.style.display = 'block';
            sliderBtn.classList.add('active');
            if (pixelBtn) pixelBtn.classList.remove('active');
            initSlider();
        });
    }
}

// Camera setup
async function setupCamera() {
    const camFeed = getElement('cam-feed');
    const camPlaceholder = getElement('cam-placeholder');
    const recBadge = getElement('rec-badge');
    const enableBtn = getElement('enable-cam-btn');
    
    if (!camFeed) return;
    
    async function enableCamera() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
            camFeed.srcObject = stream;
            if (camPlaceholder) camPlaceholder.style.display = 'none';
            if (recBadge) recBadge.style.display = 'inline-flex';
            camFeed.style.display = 'block';
            
            // Broadcast frames
            const canvas = document.createElement('canvas');
            canvas.width = 160;
            canvas.height = 120;
            const ctx = canvas.getContext('2d');
            
            setInterval(() => {
                if (camFeed.readyState >= camFeed.HAVE_ENOUGH_DATA) {
                    ctx.drawImage(camFeed, 0, 0, 160, 120);
                    if (window.socket) {
                        socket.emit('cam_frame', {
                            room_id: ROOM_ID,
                            username: CURRENT_USERNAME,
                            frame_data: canvas.toDataURL('image/jpeg', 0.3)
                        });
                    }
                }
            }, 2000);
        } catch (err) {
            console.error('Camera error:', err);
            showToast('Could not access camera', 'error');
        }
    }
    
    if (enableBtn) {
        enableBtn.addEventListener('click', enableCamera);
    } else {
        enableCamera();
    }
}

// Reset code
function resetCode() {
    if (confirm('Reset your code? This cannot be undone.')) {
        if (CHALLENGE_TYPE === 'html' && HTML_LOCKED) {
            // Only reset CSS and JS
            cssEditor.setValue('');
            jsEditor.setValue('');
            showToast('CSS and JS reset. HTML structure preserved.', 'info');
        } else {
            htmlEditor.setValue('');
            cssEditor.setValue('');
            jsEditor.setValue('');
            showToast('Code reset', 'info');
        }
        updatePreview();
    }
}

// Forfeit
function forfeit() {
    if (confirm('Forfeit the match? This will end your participation.')) {
        if (window.socket) {
            socket.emit('forfeit', {
                room_id: ROOM_ID,
                username: CURRENT_USERNAME
            });
        }
        window.location.href = '/dashboard';
    }
}

// Code preview for admin (every 5 seconds)
function startCodePreview() {
    if (USER_ROLE !== 'spectator' && USER_ROLE !== 'admin') {
        setInterval(() => {
            const html = htmlEditor.getValue();
            const css = cssEditor.getValue();
            const js = jsEditor.getValue();
            const compiled = `<!DOCTYPE html><html><head><style>${css}</style></head><body>${html}<script>${js}<\/script></body></html>`;
            
            if (window.socket) {
                socket.emit('code_preview', {
                    room_id: ROOM_ID,
                    username: CURRENT_USERNAME,
                    compiled_html: compiled
                });
            }
        }, 5000);
    }
}

// Collapse editor
function initCollapseEditor() {
    const collapseBtn = getElement('collapse-editor-btn');
    const editorPanel = getElement('editor-panel');
    
    if (collapseBtn && editorPanel) {
        collapseBtn.addEventListener('click', () => {
            editorPanel.classList.toggle('collapsed');
            if (editorPanel.classList.contains('collapsed')) {
                collapseBtn.innerHTML = '<i class="fas fa-chevron-right"></i> Expand Editor';
            } else {
                collapseBtn.innerHTML = '<i class="fas fa-chevron-left"></i> Collapse Editor';
            }
            // Refresh CodeMirror
            if (htmlEditor) htmlEditor.refresh();
            if (cssEditor) cssEditor.refresh();
            if (jsEditor) jsEditor.refresh();
        });
    }
}

// Admin controls
function initAdminControls() {
    if (USER_ROLE !== 'admin') return;
    
    const pauseBtn = getElement('admin-pause');
    const resumeBtn = getElement('admin-resume');
    const addTimeBtn = getElement('admin-addtime');
    const endBtn = getElement('admin-end');
    
    if (pauseBtn) {
        pauseBtn.addEventListener('click', () => {
            socket.emit('pause_challenge', { room_id: ROOM_ID });
        });
    }
    
    if (resumeBtn) {
        resumeBtn.addEventListener('click', () => {
            socket.emit('resume_challenge', { room_id: ROOM_ID });
        });
    }
    
    if (addTimeBtn) {
        addTimeBtn.addEventListener('click', () => {
            socket.emit('add_time', { room_id: ROOM_ID, seconds: 30 });
        });
    }
    
    if (endBtn) {
        endBtn.addEventListener('click', () => {
            if (confirm('End this challenge?')) {
                socket.emit('end_challenge', { room_id: ROOM_ID });
            }
        });
    }
}

// Initialize all arena features
document.addEventListener('DOMContentLoaded', () => {
    initEditors();
    initTarget();
    initDiffToggle();
    setupCamera();
    initCollapseEditor();
    initAdminControls();
    startCodePreview();
    
    // Tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            switchTab(btn.dataset.tab);
        });
    });
    
    // Submit button
    const submitBtn = getElement('submit-btn');
    if (submitBtn) {
        submitBtn.addEventListener('click', runDiffCheck);
    }
    
    // Reset button
    const resetBtn = getElement('reset-code-btn');
    if (resetBtn) {
        resetBtn.addEventListener('click', resetCode);
    }
    
    // Forfeit button
    const forfeitBtn = getElement('forfeit-btn');
    if (forfeitBtn) {
        forfeitBtn.addEventListener('click', forfeit);
    }
    
    // Refresh output
    const refreshBtn = getElement('refresh-output');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', updatePreview);
    }
    
    // Initial preview
    updatePreview();
});


// Add this function to arena.js - Poll for challenge status every 2 seconds
let statusPollingInterval = null;

function startStatusPolling() {
    const roomId = document.getElementById('room-id')?.value;
    if (!roomId) return;
    
    console.log('🔄 Starting status polling for room', roomId);
    
    if (statusPollingInterval) {
        clearInterval(statusPollingInterval);
    }
    
    statusPollingInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/challenge-status/${roomId}`);
            const data = await response.json();
            
            if (data.status === 'running') {
                console.log('🏁 Polling detected challenge started!');
                
                // Stop polling once started
                if (statusPollingInterval) {
                    clearInterval(statusPollingInterval);
                    statusPollingInterval = null;
                }
                
                // Hide the overlay
                const overlay = document.getElementById('editor-overlay');
                if (overlay) overlay.classList.add('hidden');
                
                // Update room status
                const statusPill = document.getElementById('room-status');
                if (statusPill) {
                    statusPill.textContent = 'LIVE';
                    statusPill.style.background = 'rgba(0,255,136,0.2)';
                    statusPill.style.color = 'var(--success)';
                }
                
                // Enable editors
                const userRole = document.getElementById('user-role')?.value;
                if (userRole !== 'spectator') {
                    if (window.cssEditor) window.cssEditor.setOption('readOnly', false);
                    if (window.jsEditor) window.jsEditor.setOption('readOnly', false);
                    
                    const challengeType = document.getElementById('challenge-type')?.value;
                    const htmlLocked = document.getElementById('html-locked')?.value === 'true';
                    if (!(challengeType === 'html' && htmlLocked)) {
                        if (window.htmlEditor) window.htmlEditor.setOption('readOnly', false);
                    }
                }
                
                // Enable submit button
                const submitBtn = document.getElementById('submit-btn');
                if (submitBtn) submitBtn.disabled = false;
                
                showToast(`Challenge started! ${data.time_limit}s on the clock!`, 'success');
                
                // Also try to emit a socket event to confirm
                if (socket) {
                    socket.emit('check_challenge_status', { room_id: parseInt(roomId) });
                }
            }
        } catch (err) {
            console.error('Status poll error:', err);
        }
    }, 2000);
}

// Start polling when page loads
document.addEventListener('DOMContentLoaded', () => {
    console.log('📄 DOM loaded, starting status polling');
    startStatusPolling();
});


// Expose functions globally
window.runDiffCheck = runDiffCheck;
window.htmlEditor = () => htmlEditor;
window.cssEditor = () => cssEditor;
window.jsEditor = () => jsEditor;
window.switchTab = switchTab;