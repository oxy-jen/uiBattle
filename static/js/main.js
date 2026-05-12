// Global toast notification system
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <div class="toast-content">
            <i class="fas ${type === 'success' ? 'fa-check-circle' : type === 'error' ? 'fa-exclamation-circle' : 'fa-info-circle'}"></i>
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
const toastStyles = document.createElement('style');
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
    .toast-info .toast-content { border-left-color: var(--neon-cyan); }
`;
document.head.appendChild(toastStyles);

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