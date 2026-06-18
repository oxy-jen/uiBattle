// Global toast notification system
function applyGlobalTheme(theme) {
    const selectedTheme = theme === 'light' ? 'light' : 'dark';
    document.documentElement.dataset.theme = selectedTheme;
    document.body.dataset.theme = selectedTheme;

    const adminRoot = document.getElementById('admin-root');
    if (adminRoot) adminRoot.dataset.adminTheme = selectedTheme;

    document.querySelectorAll('#global-theme-toggle, #admin-theme-toggle').forEach((toggle) => {
        const icon = toggle.querySelector('i');
        const label = toggle.querySelector('span');
        if (icon) icon.className = selectedTheme === 'light' ? 'fas fa-sun' : 'fas fa-moon';
        if (label) label.textContent = selectedTheme === 'light' ? 'Light' : 'Dark';
        toggle.setAttribute('aria-label', `Switch to ${selectedTheme === 'light' ? 'dark' : 'light'} mode`);
    });

    try {
        localStorage.setItem('uiBattleTheme', selectedTheme);
    } catch (e) {}
}

function getSavedGlobalTheme() {
    try {
        return localStorage.getItem('uiBattleTheme') || localStorage.getItem('uiBattleAdminTheme') || 'dark';
    } catch (e) {
        return 'dark';
    }
}

applyGlobalTheme(getSavedGlobalTheme());

document.addEventListener('DOMContentLoaded', () => {
    applyGlobalTheme(getSavedGlobalTheme());
    initProfileSitePermissions();
    initSiteMenus();
    document.querySelectorAll('#global-theme-toggle, #admin-theme-toggle').forEach((toggle) => {
        toggle.addEventListener('click', () => {
            const currentTheme = document.documentElement.dataset.theme || 'dark';
            applyGlobalTheme(currentTheme === 'dark' ? 'light' : 'dark');
        });
    });
});

function initSiteMenus() {
    const menus = Array.from(document.querySelectorAll('[data-site-menu]'));
    if (!menus.length) return;

    const closeMenu = (menu) => {
        const panel = menu.querySelector('[data-site-menu-panel]');
        const toggle = menu.querySelector('[data-site-menu-toggle]');
        if (!panel || !toggle) return;
        panel.hidden = true;
        toggle.setAttribute('aria-expanded', 'false');
    };

    const closeAllMenus = (except = null) => {
        menus.forEach((menu) => {
            if (menu !== except) closeMenu(menu);
        });
    };

    menus.forEach((menu) => {
        const toggle = menu.querySelector('[data-site-menu-toggle]');
        const panel = menu.querySelector('[data-site-menu-panel]');
        if (!toggle || !panel) return;

        toggle.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            const nextOpen = panel.hidden;
            closeAllMenus(menu);
            panel.hidden = !nextOpen;
            toggle.setAttribute('aria-expanded', String(nextOpen));
        });
    });

    document.addEventListener('click', (event) => {
        if (!event.target.closest('[data-site-menu]')) closeAllMenus();
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') closeAllMenus();
    });
}

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <div class="toast-content">
            <i class="fas ${type === 'success' ? 'fa-check-circle' : type === 'error' ? 'fa-exclamation-circle' : type === 'warning' ? 'fa-triangle-exclamation' : 'fa-info-circle'}"></i>
            <span>${message}</span>
        </div>
    `;
    document.body.appendChild(toast);
    const visibleToasts = document.querySelectorAll('.toast');
    toast.style.setProperty('--toast-offset', `${Math.max(0, visibleToasts.length - 1) * 74}px`);
    
    setTimeout(() => {
        toast.classList.add('show');
    }, 10);
    
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}


function initRoomInviteNotifications() {
    if (!window.CURRENT_PROFILE || !window.io || window.roomInviteSocket) return;
    try {
        window.roomInviteSocket = window.io({
            reconnection: true,
            reconnectionAttempts: 5,
            timeout: 20000
        });
        window.roomInviteSocket.on('room_invite', (data) => {
            const title = data.challenge_title || 'New match invite';
            const message = data.message || `You are invited to join ${title}.`;
            showToast(`${message} Click to join.`, 'info');
            const toast = document.querySelector('.toast:last-child');
            if (toast && data.invite_url) {
                toast.style.pointerEvents = 'auto';
                toast.style.cursor = 'pointer';
                toast.addEventListener('click', () => { window.location.href = data.invite_url; }, {once: true});
            }
        });
        window.roomInviteSocket.on('maintenance_notice', (data) => {
            const when = data?.maintenance_at ? ` Maintenance: ${data.maintenance_at}.` : '';
            const release = data?.release_at ? ` Release: ${data.release_at}.` : '';
            const releaseName = data?.release_name || data?.release_version;
            const releaseText = releaseName ? ` Update: ${releaseName}.` : '';
            showToast(`${data?.title || 'Scheduled maintenance'}: ${data?.message || ''}${when}${release}${releaseText}`, 'warning');
        });
    } catch (e) {}
}

// Add toast styles
if (!document.getElementById('global-ui-styles')) {
    const toastStyles = document.createElement('style');
    toastStyles.id = 'global-ui-styles';
    toastStyles.textContent = `
    .toast {
        position: fixed;
        top: calc(18px + env(safe-area-inset-top, 0px) + var(--toast-offset, 0px));
        left: 50%;
        right: auto;
        bottom: auto;
        width: min(460px, calc(100vw - 28px));
        z-index: 2147483000 !important;
        opacity: 0;
        transform: translate(-50%, -18px);
        transition: all 0.3s ease;
        pointer-events: none;
    }
    .confirm-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.7);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 2147483001 !important;
        padding: 18px;
    }
    .confirm-box {
        width: min(420px, 90%);
        max-height: calc(100dvh - 36px);
        overflow: auto;
        background: var(--bg-panel);
        border: 1px solid var(--border-default);
        border-radius: 8px;
        padding: 24px;
        box-shadow: 0 25px 70px rgba(0,0,0,0.3);
        color: white;
    }
    .confirm-box h4 {
        margin: 0 0 12px;
        font-size: 1.1rem;
        color: var(--neon-cyan);
    }
    .confirm-box p { margin: 0 0 20px; color: var(--text-secondary); }
    .confirm-box label {
        display: grid;
        gap: 8px;
        margin-bottom: 16px;
        color: var(--text-secondary);
        font-weight: 700;
    }
    .confirm-box input,
    .confirm-box textarea {
        width: 100%;
        background: var(--bg-secondary);
        border: 1px solid var(--border-default);
        border-radius: 8px;
        color: var(--text-primary);
        padding: 11px 12px;
        font: inherit;
    }
    .confirm-box textarea {
        min-height: 110px;
        resize: vertical;
    }
    .confirm-actions { display: flex; justify-content: flex-end; gap: 12px; }
    .confirm-actions button {
        min-width: 100px;
        padding: 10px 14px;
        border-radius: 10px;
        border: none;
        cursor: pointer;
        font-weight: 700;
    }
    .confirm-actions .confirm-yes { background: var(--success); color: var(--bg-primary); }
    .confirm-actions .confirm-no { background: var(--bg-secondary); color: white; }
    .toast.show {
        opacity: 1;
        transform: translate(-50%, 0);
    }
    .toast-content {
        background: var(--bg-panel);
        border-radius: 12px;
        padding: 12px 20px;
        display: flex;
        align-items: center;
        gap: 12px;
        border-left: 3px solid;
        box-shadow: 0 4px 15px rgba(0,0,0,0.3);
    }
    .toast-success .toast-content { border-left-color: var(--success); }
    .toast-error .toast-content { border-left-color: var(--danger); }
    .toast-warning .toast-content { border-left-color: var(--warning); }
    .toast-info .toast-content { border-left-color: var(--neon-cyan); }
    `;
    document.head.appendChild(toastStyles);
}

function showConfirm(message, title = 'Confirm action') {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'confirm-overlay';
        overlay.innerHTML = `
            <div class="confirm-box">
                <h4>${title}</h4>
                <p>${message}</p>
                <div class="confirm-actions">
                    <button class="confirm-no">Cancel</button>
                    <button class="confirm-yes">Confirm</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        const cleanup = (result) => {
            resolve(result);
            overlay.remove();
        };

        overlay.querySelector('.confirm-no').addEventListener('click', () => cleanup(false));
        overlay.querySelector('.confirm-yes').addEventListener('click', () => cleanup(true));
        overlay.addEventListener('click', (event) => {
            if (event.target === overlay) cleanup(false);
        });
    });
}

function showPrompt(options = {}) {
    return new Promise((resolve) => {
        const {
            title = 'Provide details',
            message = '',
            label = 'Details',
            value = '',
            placeholder = '',
            multiline = false,
            required = false,
            confirmText = 'Continue',
            cancelText = 'Cancel'
        } = options;
        const overlay = document.createElement('div');
        overlay.className = 'confirm-overlay';
        overlay.innerHTML = `
            <div class="confirm-box">
                <h4>${title}</h4>
                ${message ? `<p>${message}</p>` : ''}
                <label>
                    ${label}
                    ${multiline
                        ? `<textarea class="prompt-input" placeholder="${placeholder}">${value}</textarea>`
                        : `<input class="prompt-input" type="text" value="${value}" placeholder="${placeholder}">`}
                </label>
                <div class="confirm-actions">
                    <button class="confirm-no" type="button">${cancelText}</button>
                    <button class="confirm-yes" type="button">${confirmText}</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        const input = overlay.querySelector('.prompt-input');
        input.focus();
        input.setSelectionRange?.(input.value.length, input.value.length);

        const cleanup = (result) => {
            resolve(result);
            overlay.remove();
        };
        const submit = () => {
            const nextValue = input.value.trim();
            if (required && !nextValue) {
                showToast('This field is required', 'warning');
                input.focus();
                return;
            }
            cleanup(nextValue);
        };

        overlay.querySelector('.confirm-no').addEventListener('click', () => cleanup(null));
        overlay.querySelector('.confirm-yes').addEventListener('click', submit);
        overlay.addEventListener('click', (event) => {
            if (event.target === overlay) cleanup(null);
        });
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') cleanup(null);
            if (event.key === 'Enter' && !multiline) submit();
        });
    });
}

function initProfileSitePermissions() {
    const root = document.getElementById('profile-site-permissions');
    if (!root) return;

    const cameraState = document.getElementById('profile-camera-permission');
    const microphoneState = document.getElementById('profile-microphone-permission');
    const summary = document.getElementById('profile-media-summary');
    const requestBtn = document.getElementById('profile-request-media-btn');
    const testMicBtn = document.getElementById('profile-test-mic-btn');
    let testStream = null;

    function setState(el, state) {
        if (!el) return;
        const label = state === 'granted' ? 'Allowed' : state === 'denied' ? 'Blocked' : state === 'prompt' ? 'Ask' : 'Unknown';
        el.textContent = label;
        el.dataset.state = state || 'unknown';
    }

    async function readPermission(name) {
        if (!navigator.permissions?.query) return 'unknown';
        try {
            const status = await navigator.permissions.query({ name });
            status.onchange = updatePermissionStatus;
            return status.state;
        } catch (error) {
            return 'unknown';
        }
    }

    async function updatePermissionStatus() {
        const [camera, microphone] = await Promise.all([
            readPermission('camera'),
            readPermission('microphone')
        ]);
        setState(cameraState, camera);
        setState(microphoneState, microphone);
        if (summary) {
            if (camera === 'granted' && microphone === 'granted') {
                summary.textContent = 'Ready';
                summary.dataset.state = 'granted';
            } else if (camera === 'denied' || microphone === 'denied') {
                summary.textContent = 'Blocked';
                summary.dataset.state = 'denied';
            } else {
                summary.textContent = 'Needs allow';
                summary.dataset.state = 'prompt';
            }
        }
    }

    async function requestProfileMedia() {
        if (!navigator.mediaDevices?.getUserMedia) {
            showToast('This browser does not support camera and microphone access here.', 'error');
            return;
        }
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'user' },
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
            });
            stream.getTracks().forEach((track) => track.stop());
            showToast('Camera and microphone are allowed for this site.', 'success');
        } catch (error) {
            const message = error?.name === 'NotAllowedError'
                ? 'Permission was blocked. Open browser site settings for this page and allow camera and microphone.'
                : error?.name === 'NotFoundError'
                    ? 'No camera or microphone was found by this browser.'
                    : 'Could not enable camera and microphone from profile settings.';
            showToast(message, 'error');
        } finally {
            setTimeout(updatePermissionStatus, 250);
        }
    }

    async function testMicrophone() {
        if (!navigator.mediaDevices?.getUserMedia) {
            showToast('This browser cannot test the microphone here.', 'error');
            return;
        }
        if (testStream) {
            testStream.getTracks().forEach((track) => track.stop());
            testStream = null;
            if (testMicBtn) testMicBtn.innerHTML = '<i class="fas fa-microphone-lines"></i> Test mic';
            showToast('Microphone test stopped.', 'info');
            return;
        }
        try {
            testStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
            if (testMicBtn) testMicBtn.innerHTML = '<i class="fas fa-stop"></i> Stop mic test';
            showToast('Microphone permission works. You can stop the test now.', 'success');
        } catch (error) {
            showToast('Microphone test failed. Allow microphone in browser site settings.', 'error');
        } finally {
            setTimeout(updatePermissionStatus, 250);
        }
    }

    if (requestBtn) requestBtn.addEventListener('click', requestProfileMedia);
    if (testMicBtn) testMicBtn.addEventListener('click', testMicrophone);
    updatePermissionStatus();
}
// Format timestamp
function formatTimestamp(date) {
    return new Date(date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// Debounce function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Local storage helper
function saveToLocal(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch(e) {}
}

function getFromLocal(key, defaultValue = '') {
    try {
        return localStorage.getItem(key) || defaultValue;
    } catch(e) {
        return defaultValue;
    }
}

// Copy to clipboard
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showToast('Copied to clipboard!', 'success');
    }).catch(() => {
        showToast('Failed to copy', 'error');
    });
}

// Get URL parameters
function getUrlParam(param) {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(param);
}

// Shared profile menu used by dashboard and arena nav profile pills.
document.addEventListener('DOMContentLoaded', () => {
    const panel = document.getElementById('profile-menu-panel');
    const overlay = document.getElementById('profile-menu-overlay');
    const closeButton = document.getElementById('profile-menu-close');
    const form = document.getElementById('profile-settings-form');
    const triggers = document.querySelectorAll('[data-profile-trigger]');

    if (!form) return;

    const setOpen = (isOpen) => {
        if (!panel || !overlay) return;
        panel.hidden = !isOpen;
        overlay.hidden = !isOpen;
        triggers.forEach((trigger) => trigger.setAttribute('aria-expanded', String(isOpen)));
        if (isOpen) {
            const firstInput = document.getElementById('profile-settings-username');
            setTimeout(() => firstInput?.focus(), 50);
        }
    };

    triggers.forEach((trigger) => {
        trigger.addEventListener('click', (event) => {
            event.preventDefault();
            setOpen(panel.hidden);
        });
    });

    overlay?.addEventListener('click', () => setOpen(false));
    closeButton?.addEventListener('click', () => setOpen(false));
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') setOpen(false);
    });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const saveButton = form.querySelector('.profile-menu-save');
        const originalText = saveButton?.innerHTML;
        if (saveButton) {
            saveButton.disabled = true;
            saveButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving';
        }

        try {
            const response = await fetch('/api/profile/me', {
                method: 'POST',
                body: new FormData(form)
            });
            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(data.error || 'Could not save profile');
            }

            updateProfileChrome(data.user);
            showToast('Profile saved', 'success');
            setOpen(false);
        } catch (error) {
            showToast(error.message || 'Could not save profile', 'error');
        } finally {
            if (saveButton) {
                saveButton.disabled = false;
                saveButton.innerHTML = originalText;
            }
        }
    });

    const passwordForm = document.getElementById('password-change-form');
    passwordForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        const button = passwordForm.querySelector('button[type="submit"]');
        const originalText = button?.innerHTML;
        if (button) {
            button.disabled = true;
            button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Updating';
        }
        try {
            const response = await fetch('/api/account/password', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    current_password: document.getElementById('current-password')?.value || '',
                    new_password: document.getElementById('new-password')?.value || '',
                    confirm_password: document.getElementById('confirm-password')?.value || ''
                })
            });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || 'Could not change password');
            passwordForm.reset();
            showToast('Password changed', 'success');
        } catch (error) {
            showToast(error.message || 'Could not change password', 'error');
        } finally {
            if (button) {
                button.disabled = false;
                button.innerHTML = originalText;
            }
        }
    });

    const emailBox = document.getElementById('email-verification-box');
    const emailStatus = document.getElementById('email-verification-status');
    const sendEmailCodeBtn = document.getElementById('email-verification-send-btn');
    const confirmEmailBtn = document.getElementById('email-verification-confirm-btn');
    const emailCodeInput = document.getElementById('email-verification-code');
    function syncEmailVerification(verified) {
        if (emailBox) emailBox.dataset.verified = verified ? 'true' : 'false';
        if (emailStatus) emailStatus.textContent = verified ? 'Verified' : 'Not verified';
    }
    syncEmailVerification(emailBox?.dataset.verified === 'true');
    sendEmailCodeBtn?.addEventListener('click', async () => {
        const emailInput = document.getElementById('profile-settings-email');
        const email = emailInput?.value?.trim() || '';
        if (!email) {
            showToast('Enter your recovery email first', 'warning');
            emailInput?.focus();
            return;
        }
        try {
            const response = await fetch('/api/account/email/send-verification', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    email,
                    current_password: document.getElementById('profile-settings-current-password')?.value || ''
                })
            });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || 'Could not send verification code');
            showToast('Verification code sent. Check your inbox and spam folder.', 'success');
            syncEmailVerification(false);
            emailCodeInput?.focus();
        } catch (error) {
            showToast(error.message || 'Could not send verification code', 'error');
        }
    });
    confirmEmailBtn?.addEventListener('click', async () => {
        try {
            const response = await fetch('/api/account/email/verify', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({code: emailCodeInput?.value || ''})
            });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || 'Could not verify email');
            syncEmailVerification(true);
            if (emailCodeInput) emailCodeInput.value = '';
            showToast('Email verified', 'success');
        } catch (error) {
            showToast(error.message || 'Could not verify email', 'error');
        }
    });

    initTwoFactorSettings();
});

function initTwoFactorSettings() {
    const box = document.getElementById('two-factor-box');
    if (!box) return;
    const setupBtn = document.getElementById('two-factor-setup-btn');
    const enableBtn = document.getElementById('two-factor-enable-btn');
    const disableBtn = document.getElementById('two-factor-disable-btn');
    const recoveryBtn = document.getElementById('two-factor-recovery-btn');
    const setupPanel = document.getElementById('two-factor-setup');
    const secretInput = document.getElementById('two-factor-secret');
    const codeInput = document.getElementById('two-factor-code');
    const currentPasswordInput = document.getElementById('two-factor-current-password');
    const status = document.getElementById('two-factor-status');
    const qrWrap = document.getElementById('two-factor-qr-wrap');
    const qrImage = document.getElementById('two-factor-qr');
    const openAppLink = document.getElementById('two-factor-open-app-link');
    const copySecretBtn = document.getElementById('two-factor-copy-secret-btn');
    const recoveryPanel = document.getElementById('two-factor-recovery');
    const recoveryGrid = document.getElementById('two-factor-recovery-grid');
    const copyRecoveryBtn = document.getElementById('two-factor-copy-recovery-btn');
    let latestRecoveryCodes = [];

    function syncState(enabled) {
        box.dataset.enabled = enabled ? 'true' : 'false';
        if (status) status.textContent = enabled ? 'Enabled' : 'Off';
        if (setupBtn) setupBtn.hidden = enabled;
        if (disableBtn) disableBtn.hidden = !enabled;
        if (recoveryBtn) recoveryBtn.hidden = !enabled;
        if (enableBtn) enableBtn.hidden = true;
        if (setupPanel) setupPanel.hidden = true;
        if (codeInput) codeInput.value = '';
    }

    function showRecoveryCodes(codes) {
        latestRecoveryCodes = Array.isArray(codes) ? codes : [];
        if (!recoveryPanel || !recoveryGrid || latestRecoveryCodes.length === 0) return;
        recoveryGrid.innerHTML = latestRecoveryCodes.map((code) => `<code>${escapeHtml(code)}</code>`).join('');
        recoveryPanel.hidden = false;
    }

    syncState(box.dataset.enabled === 'true');

    setupBtn?.addEventListener('click', async () => {
        const currentPassword = currentPasswordInput?.value || '';
        if (!currentPassword) {
            showToast('Enter your current password first', 'error');
            currentPasswordInput?.focus();
            return;
        }
        try {
            const response = await fetch('/api/account/2fa/setup', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({current_password: currentPassword})
            });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || 'Could not start two-step setup');
            if (secretInput) secretInput.value = data.secret;
            if (qrImage && data.qr_data_uri) {
                qrImage.src = data.qr_data_uri;
                if (qrWrap) qrWrap.hidden = false;
            } else if (qrWrap) {
                qrWrap.hidden = true;
                showToast('QR generation is unavailable. Use the setup key fallback.', 'warning');
            }
            if (openAppLink && data.otpauth_uri) {
                openAppLink.href = data.otpauth_uri;
                openAppLink.hidden = false;
            }
            if (setupPanel) setupPanel.hidden = false;
            if (recoveryPanel) recoveryPanel.hidden = true;
            if (enableBtn) enableBtn.hidden = false;
            codeInput?.focus();
            showToast('Scan the QR code with your authenticator, then enter its 6-digit code', 'info');
        } catch (error) {
            showToast(error.message || 'Could not start two-step setup', 'error');
        }
    });

    copySecretBtn?.addEventListener('click', async () => {
        const secret = secretInput?.value || '';
        if (!secret) return;
        try {
            await navigator.clipboard.writeText(secret);
            showToast('Setup key copied. Paste it into your authenticator app.', 'success');
        } catch (error) {
            secretInput?.select();
            showToast('Select and copy the setup key, then add it manually in your authenticator app.', 'info');
        }
    });

    openAppLink?.addEventListener('click', () => {
        showToast('If no app opens, scan the QR code or use Copy setup key. Desktop browsers often block authenticator app links.', 'info');
    });

    enableBtn?.addEventListener('click', async () => {
        try {
            const response = await fetch('/api/account/2fa/enable', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({code: codeInput?.value || ''})
            });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || 'Could not enable two-step verification');
            syncState(true);
            showRecoveryCodes(data.recovery_codes);
            showToast('Two-step verification enabled. Save your recovery codes.', 'success');
        } catch (error) {
            showToast(error.message || 'Could not enable two-step verification', 'error');
        }
    });

    recoveryBtn?.addEventListener('click', async () => {
        const currentPassword = currentPasswordInput?.value || '';
        if (!currentPassword) {
            showToast('Enter your current password first', 'error');
            currentPasswordInput?.focus();
            return;
        }
        try {
            const response = await fetch('/api/account/2fa/recovery-codes', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({current_password: currentPassword})
            });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || 'Could not create recovery codes');
            showRecoveryCodes(data.recovery_codes);
            showToast('New recovery codes created. Old codes no longer work.', 'success');
        } catch (error) {
            showToast(error.message || 'Could not create recovery codes', 'error');
        }
    });

    copyRecoveryBtn?.addEventListener('click', async () => {
        if (latestRecoveryCodes.length === 0) return;
        try {
            await navigator.clipboard.writeText(latestRecoveryCodes.join('\n'));
            showToast('Recovery codes copied', 'success');
        } catch (error) {
            showToast('Copy the visible recovery codes before leaving this page', 'info');
        }
    });

    disableBtn?.addEventListener('click', async () => {
        const currentPassword = currentPasswordInput?.value || '';
        const code = codeInput?.value || '';
        if (!currentPassword) {
            showToast('Enter your current password first', 'error');
            currentPasswordInput?.focus();
            return;
        }
        if (!code) {
            if (setupPanel) setupPanel.hidden = false;
            showToast('Enter your current 6-digit verification code', 'error');
            codeInput?.focus();
            return;
        }
        try {
            const response = await fetch('/api/account/2fa/disable', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({current_password: currentPassword, code})
            });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || 'Could not disable two-step verification');
            syncState(false);
            if (recoveryPanel) recoveryPanel.hidden = true;
            showToast('Two-step verification disabled', 'success');
        } catch (error) {
            showToast(error.message || 'Could not disable two-step verification', 'error');
        }
    });
}

function updateProfileChrome(user) {
    if (!user) return;
    const name = user.username || '';
    const avatarUrl = user.avatar_url;
    const initial = name.charAt(0).toUpperCase() || '?';

    document.querySelectorAll('[data-profile-name], [data-profile-page-name]').forEach((el) => {
        el.textContent = name;
    });

    const menuName = document.getElementById('profile-menu-name');
    if (menuName) menuName.textContent = name;

    document.querySelectorAll('[data-profile-avatar], [data-profile-page-avatar], #profile-menu-avatar').forEach((el) => {
        if (avatarUrl) {
            el.innerHTML = `<img src="${avatarUrl}" alt="${escapeHtml(name)} avatar">`;
        } else {
            el.textContent = initial;
        }
    });

    const usernameInput = document.getElementById('profile-settings-username');
    const emailInput = document.getElementById('profile-settings-email');
    const bioInput = document.getElementById('profile-settings-bio');
    const avatarInput = document.getElementById('profile-settings-avatar');
    if (usernameInput) usernameInput.value = name;
    if (emailInput) emailInput.value = user.email || '';
    const emailBox = document.getElementById('email-verification-box');
    const emailStatus = document.getElementById('email-verification-status');
    const verified = Boolean(user.email_verified);
    if (emailBox) emailBox.dataset.verified = verified ? 'true' : 'false';
    if (emailStatus) emailStatus.textContent = verified ? 'Verified' : 'Not verified';
    if (bioInput) bioInput.value = user.bio || '';
    if (avatarInput) avatarInput.value = '';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}


document.addEventListener('DOMContentLoaded', initRoomInviteNotifications);
