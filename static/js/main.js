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
    if (document.getElementById('admin-theme-toggle')) {
        const globalToggle = document.getElementById('global-theme-toggle');
        if (globalToggle) globalToggle.hidden = true;
    }
    document.querySelectorAll('#global-theme-toggle, #admin-theme-toggle').forEach((toggle) => {
        toggle.addEventListener('click', () => {
            const currentTheme = document.documentElement.dataset.theme || 'dark';
            applyGlobalTheme(currentTheme === 'dark' ? 'light' : 'dark');
        });
    });
});

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
    
    setTimeout(() => {
        toast.classList.add('show');
    }, 10);
    
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Add toast styles
if (!document.getElementById('global-ui-styles')) {
    const toastStyles = document.createElement('style');
    toastStyles.id = 'global-ui-styles';
    toastStyles.textContent = `
    .toast {
        position: fixed;
        bottom: 20px;
        right: 20px;
        z-index: 10000;
        opacity: 0;
        transform: translateY(100%);
        transition: all 0.3s ease;
    }
    .confirm-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.7);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 11000;
    }
    .confirm-box {
        width: min(420px, 90%);
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
        transform: translateY(0);
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

    initTwoFactorSettings();
});

function initTwoFactorSettings() {
    const box = document.getElementById('two-factor-box');
    if (!box) return;
    const setupBtn = document.getElementById('two-factor-setup-btn');
    const enableBtn = document.getElementById('two-factor-enable-btn');
    const disableBtn = document.getElementById('two-factor-disable-btn');
    const setupPanel = document.getElementById('two-factor-setup');
    const secretInput = document.getElementById('two-factor-secret');
    const codeInput = document.getElementById('two-factor-code');
    const currentPasswordInput = document.getElementById('two-factor-current-password');
    const status = document.getElementById('two-factor-status');

    function syncState(enabled) {
        box.dataset.enabled = enabled ? 'true' : 'false';
        if (status) status.textContent = enabled ? 'Enabled' : 'Off';
        if (setupBtn) setupBtn.hidden = enabled;
        if (disableBtn) disableBtn.hidden = !enabled;
        if (enableBtn) enableBtn.hidden = true;
        if (setupPanel) setupPanel.hidden = true;
        if (codeInput) codeInput.value = '';
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
            if (setupPanel) setupPanel.hidden = false;
            if (enableBtn) enableBtn.hidden = false;
            codeInput?.focus();
            showToast('Add the secret key to your authenticator app', 'info');
        } catch (error) {
            showToast(error.message || 'Could not start two-step setup', 'error');
        }
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
            showToast('Two-step verification enabled', 'success');
        } catch (error) {
            showToast(error.message || 'Could not enable two-step verification', 'error');
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
    const bioInput = document.getElementById('profile-settings-bio');
    const avatarInput = document.getElementById('profile-settings-avatar');
    if (usernameInput) usernameInput.value = name;
    if (bioInput) bioInput.value = user.bio || '';
    if (avatarInput) avatarInput.value = '';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}
