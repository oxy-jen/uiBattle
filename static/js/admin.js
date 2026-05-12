// Admin panel specific JavaScript

// Initialize CodeMirror editors for HTML challenge creation
let adminHtmlEditor, adminCssEditor;

function initAdminEditors() {
    const htmlTextarea = document.getElementById('target-html');
    const cssTextarea = document.getElementById('target-css');
    
    if (htmlTextarea) {
        adminHtmlEditor = CodeMirror.fromTextArea(htmlTextarea, {
            mode: 'htmlmixed',
            theme: 'dracula',
            lineNumbers: true,
            tabSize: 2,
            lineWrapping: true,
            autoCloseBrackets: true,
            matchBrackets: true
        });
    }
    
    if (cssTextarea) {
        adminCssEditor = CodeMirror.fromTextArea(cssTextarea, {
            mode: 'css',
            theme: 'dracula',
            lineNumbers: true,
            tabSize: 2,
            lineWrapping: true,
            autoCloseBrackets: true,
            matchBrackets: true
        });
    }
}

// Challenge type toggle with live preview
function initChallengeTypeToggle() {
    const typeBtns = document.querySelectorAll('.type-btn');
    const imageFields = document.getElementById('image-fields');
    const htmlFields = document.getElementById('html-fields');
    const challengeTypeInput = document.getElementById('challenge-type');
    
    if (!typeBtns.length) return;
    
    typeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            typeBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            const type = btn.dataset.type;
            if (challengeTypeInput) challengeTypeInput.value = type;
            
            if (imageFields) imageFields.style.display = type === 'image' ? 'block' : 'none';
            if (htmlFields) htmlFields.style.display = type === 'html' ? 'block' : 'none';
        });
    });
}

// Image preview on upload
function initImagePreview() {
    const imageInput = document.getElementById('target-image');
    const previewDiv = document.getElementById('image-preview');
    
    if (imageInput && previewDiv) {
        imageInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = (event) => {
                    previewDiv.innerHTML = `<img src="${event.target.result}" style="max-width:100%; max-height:200px; border-radius:8px; margin-top:10px;">`;
                };
                reader.readAsDataURL(file);
            } else {
                previewDiv.innerHTML = '';
            }
        });
    }
}

// Preview HTML challenge
function initHtmlPreview() {
    const previewBtn = document.getElementById('preview-target');
    const previewDiv = document.getElementById('html-preview');
    const previewIframe = document.getElementById('preview-iframe');
    
    if (previewBtn && previewDiv && previewIframe) {
        previewBtn.addEventListener('click', () => {
            const html = adminHtmlEditor ? adminHtmlEditor.getValue() : '';
            const css = adminCssEditor ? adminCssEditor.getValue() : '';
            
            previewDiv.style.display = 'block';
            previewIframe.srcdoc = `<!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>${css}</style>
            </head>
            <body>
                ${html}
            </body>
            </html>`;
        });
    }
}

// Room action handlers with real-time feedback
function initRoomActions() {
    window.roomAction = async (roomId, action) => {
        const button = event?.target;
        const originalText = button?.innerHTML;
        
        if (button) {
            button.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
            button.disabled = true;
        }
        
        try {
            const response = await fetch(`/admin/room/${roomId}/action`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action })
            });
            
            const data = await response.json();
            
            if (data.success) {
                showToast(`${action} command sent successfully`, 'success');
                setTimeout(() => location.reload(), 1000);
            } else {
                showToast(`Failed to ${action} room`, 'error');
            }
        } catch (error) {
            showToast(`Error: ${error.message}`, 'error');
        } finally {
            if (button) {
                button.innerHTML = originalText;
                button.disabled = false;
            }
        }
    };
}

// Kick player handler
function initKickPlayer() {
    window.kickPlayer = async (roomId, username) => {
        if (!confirm(`Kick ${username} from the room?`)) return;
        
        try {
            const response = await fetch('/admin/kick', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ room_id: roomId, username: username })
            });
            
            if (response.ok) {
                showToast(`${username} has been kicked`, 'warning');
                setTimeout(() => location.reload(), 1000);
            }
        } catch (error) {
            showToast('Failed to kick player', 'error');
        }
    };
}

// Broadcast message handler
function initBroadcast() {
    window.broadcastMessage = async () => {
        const messageTextarea = document.getElementById('broadcast-message');
        const message = messageTextarea?.value.trim();
        
        if (!message) {
            showToast('Enter a message to broadcast', 'warning');
            return;
        }
        
        try {
            const response = await fetch('/admin/broadcast', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message })
            });
            
            if (response.ok) {
                showToast('Broadcast sent to all rooms', 'success');
                if (messageTextarea) messageTextarea.value = '';
            }
        } catch (error) {
            showToast('Failed to broadcast', 'error');
        }
    };
}

// Delete challenge handler
function initDeleteChallenge() {
    window.deleteChallenge = async (challengeId) => {
        if (!confirm('Delete this challenge? This action cannot be undone.')) return;
        
        try {
            const response = await fetch(`/admin/challenge/${challengeId}/delete`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                showToast('Challenge deleted', 'success');
                setTimeout(() => location.reload(), 1000);
            }
        } catch (error) {
            showToast('Failed to delete challenge', 'error');
        }
    };
}

// Delete room handler
function initDeleteRoom() {
    window.deleteRoom = async (roomId) => {
        if (!confirm('Delete this room? All associated data will be lost.')) return;
        
        try {
            const response = await fetch(`/admin/room/${roomId}/delete`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                showToast('Room deleted', 'success');
                setTimeout(() => location.reload(), 1000);
            }
        } catch (error) {
            showToast('Failed to delete room', 'error');
        }
    };
}

// Socket.IO admin previews
function initAdminPreviews() {
    if (typeof io === 'undefined') return;
    
    const socket = io();
    
    socket.on('admin_preview', (data) => {
        console.log('Admin preview received:', data.username);
        
        if (data.username) {
            const isPlayer1 = data.username === document.querySelector('[data-p1-name]')?.dataset.p1Name;
            const iframeId = isPlayer1 ? 'admin-preview-p1' : 'admin-preview-p2';
            const iframe = document.getElementById(iframeId);
            
            if (iframe && data.compiled_html) {
                iframe.srcdoc = data.compiled_html;
            }
        }
    });
    
    // Also listen for player join/leave to update previews
    socket.on('player_joined', () => {
        // Refresh previews
    });
    
    socket.on('player_left', () => {
        // Clear previews
        const p1Iframe = document.getElementById('admin-preview-p1');
        const p2Iframe = document.getElementById('admin-preview-p2');
        if (p1Iframe) p1Iframe.srcdoc = '';
        if (p2Iframe) p2Iframe.srcdoc = '';
    });
}

// Navigation between sections
function initAdminNavigation() {
    const navLinks = document.querySelectorAll('.sidebar-nav a');
    const sections = document.querySelectorAll('.admin-section');
    
    if (!navLinks.length) return;
    
    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            
            // Update active link
            navLinks.forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            
            // Show corresponding section
            const sectionId = link.dataset.section;
            sections.forEach(section => {
                if (section.id === `section-${sectionId}`) {
                    section.classList.add('active');
                } else {
                    section.classList.remove('active');
                }
            });
        });
    });
}

// Auto-refresh room list
function initAutoRefresh() {
    let refreshInterval = null;
    const refreshBtn = document.querySelector('.refresh-btn');
    
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            location.reload();
        });
    }
    
    // Auto-refresh room list every 30 seconds
    refreshInterval = setInterval(() => {
        const activeSection = document.querySelector('.admin-section.active');
        if (activeSection && activeSection.id === 'section-rooms') {
            fetch('/room/list')
                .then(res => res.json())
                .then(data => {
                    // Update room table without full reload
                    console.log('Rooms refreshed:', data);
                })
                .catch(err => console.error('Refresh failed:', err));
        }
    }, 30000);
}

// Create challenge form handler
function initCreateChallengeForm() {
    const form = document.getElementById('create-challenge-form');
    if (!form) return;
    
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const submitBtn = form.querySelector('button[type="submit"]');
        const originalText = submitBtn?.innerHTML;
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating...';
        }
        
        const formData = new FormData();
        formData.append('challenge_type', document.getElementById('challenge-type')?.value || 'image');
        formData.append('title', document.getElementById('title')?.value || '');
        formData.append('difficulty', document.getElementById('difficulty')?.value || 'Medium');
        formData.append('time_limit', document.getElementById('time-limit')?.value || '120');
        formData.append('description', document.getElementById('description')?.value || '');
        
        const challengeType = document.getElementById('challenge-type')?.value;
        
        if (challengeType === 'image') {
            const fileInput = document.getElementById('target-image');
            if (fileInput?.files[0]) {
                formData.append('target_image', fileInput.files[0]);
            } else {
                showToast('Please select an image', 'error');
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = originalText;
                }
                return;
            }
        } else {
            const htmlValue = adminHtmlEditor ? adminHtmlEditor.getValue() : '';
            const cssValue = adminCssEditor ? adminCssEditor.getValue() : '';
            const htmlLocked = document.getElementById('html-locked')?.checked || false;
            
            formData.append('target_html', htmlValue);
            formData.append('target_css', cssValue);
            formData.append('html_locked', htmlLocked);
        }
        
        try {
            const response = await fetch('/admin/create_challenge', {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            
            if (data.success) {
                showToast(`Challenge created! Room code: ${data.room_code}`, 'success');
                setTimeout(() => location.reload(), 1500);
            } else {
                showToast(data.error || 'Failed to create challenge', 'error');
            }
        } catch (error) {
            showToast('Network error. Please try again.', 'error');
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalText;
            }
        }
    });
}

// Initialize all admin features
document.addEventListener('DOMContentLoaded', () => {
    initAdminEditors();
    initChallengeTypeToggle();
    initImagePreview();
    initHtmlPreview();
    initRoomActions();
    initKickPlayer();
    initBroadcast();
    initDeleteChallenge();
    initDeleteRoom();
    initAdminPreviews();
    initAdminNavigation();
    initAutoRefresh();
    initCreateChallengeForm();
});

// Export for global use
window.adminHtmlEditor = () => adminHtmlEditor;
window.adminCssEditor = () => adminCssEditor;