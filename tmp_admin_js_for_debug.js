
let adminHtmlEditor, adminCssEditor;

function initAdminEditors() {
    const htmlTextarea = document.getElementById('target-html');
    const cssTextarea = document.getElementById('target-css');
    
    if (htmlTextarea) {
        adminHtmlEditor = CodeMirror.fromTextArea(htmlTextarea, {
            mode: 'htmlmixed', theme: 'dracula', lineNumbers: true, tabSize: 2
        });
    }
    if (cssTextarea) {
        adminCssEditor = CodeMirror.fromTextArea(cssTextarea, {
            mode: 'css', theme: 'dracula', lineNumbers: true, tabSize: 2
        });
    }
}

// Challenge type toggle
document.querySelectorAll('.type-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.type-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const type = btn.dataset.type;
        document.getElementById('challenge-type').value = type;
        document.getElementById('image-fields').style.display = type === 'image' ? 'block' : 'none';
        document.getElementById('html-fields').style.display = type === 'html' ? 'block' : 'none';
    });
});

// Create challenge form
document.getElementById('create-challenge-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData();
    formData.append('challenge_type', document.getElementById('challenge-type').value);
    formData.append('title', document.getElementById('title').value);
    formData.append('difficulty', document.getElementById('difficulty').value);
    formData.append('time_limit', document.getElementById('time-limit').value);
    formData.append('description', document.getElementById('description').value);
    
    if (document.getElementById('challenge-type').value === 'image') {
        const file = document.getElementById('target-image').files[0];
        if (file) formData.append('target_image', file);
        else { showToast('Please select an image', 'error'); return; }
    } else {
        formData.append('target_html', adminHtmlEditor ? adminHtmlEditor.getValue() : '');
        formData.append('target_css', adminCssEditor ? adminCssEditor.getValue() : '');
        formData.append('html_locked', document.getElementById('html-locked').checked);
    }
    
    const res = await fetch('/admin/create_challenge', {method: 'POST', body: formData});
    const data = await res.json();
    if (data.success) {
        showToast(`Room created! Code: ${data.room_code}`, 'success');
        setTimeout(() => location.reload(), 1500);
    } else {
        showToast(data.error || 'Error creating challenge', 'error');
    }
});

// Image preview
document.getElementById('target-image')?.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = (event) => {
            document.getElementById('image-preview').innerHTML = `<img src="${event.target.result}" style="max-width:100%;max-height:150px;border-radius:8px;">`;
        };
        reader.readAsDataURL(file);
    }
});

// Preview HTML challenge
document.getElementById('preview-target')?.addEventListener('click', () => {
    const html = adminHtmlEditor ? adminHtmlEditor.getValue() : '';
    const css = adminCssEditor ? adminCssEditor.getValue() : '';
    const previewDiv = document.getElementById('html-preview');
    const iframe = document.getElementById('preview-iframe');
    previewDiv.style.display = 'block';
    iframe.srcdoc = `<!DOCTYPE html><html><head><style>${css}</style></head><body>${html}</body></html>`;
});

// Room actions
window.roomAction = async (button, roomId, action) => {
    if (button && button.disabled === false) {
        button.disabled = true;
        button.dataset.originalText = button.innerHTML;
        button.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    }

    try {
        const res = await fetch(`/admin/room/${roomId}/action`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action})
        });
        if (res.ok) {
            showToast(`${action} command sent`, 'success');
            setTimeout(() => location.reload(), 900);
        } else {
            showToast(`Failed to ${action} room`, 'error');
        }
    } catch (error) {
        showToast(`Network error: ${error.message}`, 'error');
    } finally {
        if (button) {
            button.disabled = false;
            button.innerHTML = button.dataset.originalText || button.innerHTML;
        }
    }
};

// Delete room
window.deleteRoom = async (button, roomId) => {
    const confirmed = await showConfirm('Delete this room? All data will be lost.', 'Delete room');
    if (!confirmed) return;
    if (button) button.disabled = true;
    const res = await fetch(`/admin/room/${roomId}/delete`, {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'}
    });
    const data = await res.json();
    if (res.ok && data.success) {
        showToast('Room deleted', 'success');
        setTimeout(() => location.reload(), 900);
    } else {
        showToast(data.error || 'Failed to delete room', 'error');
        if (button) button.disabled = false;
    }
};

// Kick player
window.kickPlayer = async (button, roomId, username) => {
    if (typeof button !== 'object') {
        username = roomId;
        roomId = button;
        button = null;
    }
    if (!username || username === 'Empty') return;
    const confirmed = await showConfirm(`Kick ${username} from the room?`, 'Kick user');
    if (!confirmed) return;
    if (button) button.disabled = true;
    const res = await fetch('/admin/kick', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({room_id: roomId, username: username})
    });
    const data = await res.json();
    if (res.ok && data.success) {
        showToast(`${username} kicked`, 'warning');
        setTimeout(() => location.reload(), 900);
    } else {
        showToast(data.error || 'Failed to kick player', 'error');
        if (button) button.disabled = false;
    }
};

// Delete challenge
window.deleteChallenge = async (challengeId, challengeTitle) => {
    const confirmed = await showConfirm(`Delete challenge "${challengeTitle}"? This will mark the challenge as inactive.`, 'Delete challenge');
    if (!confirmed) return;
    
    const res = await fetch(`/admin/challenge/${challengeId}/delete`, {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'}
    });
    const data = await res.json();
    if (data.success) {
        showToast(`Challenge "${challengeTitle}" deleted`, 'success');
        setTimeout(() => location.reload(), 1000);
    } else {
        showToast(data.error || 'Failed to delete challenge', 'error');
    }
};

// Restore challenge
window.restoreChallenge = async (challengeId) => {
    const confirmed = await showConfirm('Restore this challenge?', 'Restore challenge');
    if (!confirmed) return;
    
    const res = await fetch(`/admin/challenge/${challengeId}/restore`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'}
    });
    const data = await res.json();
    if (data.success) {
        showToast('Challenge restored', 'success');
        setTimeout(() => location.reload(), 1000);
    }
};

// View challenge details
window.viewChallengeDetails = async (challengeId) => {
    const modal = document.getElementById('challenge-details-modal');
    const modalBody = document.getElementById('challenge-modal-body');
    const modalTitle = document.getElementById('challenge-modal-title');
    
    modal.style.display = 'flex';
    modalBody.innerHTML = '<div class="loading">Loading...</div>';
    
    const res = await fetch(`/admin/challenge/${challengeId}/details`);
    const data = await res.json();
    
    if (data.success) {
        modalTitle.textContent = data.title;
        modalBody.innerHTML = `
            <div class="detail-card"><span class="detail-label">Type</span><span class="detail-value">${data.challenge_type.toUpperCase()}</span></div>
            <div class="detail-card"><span class="detail-label">Difficulty</span><span class="detail-value">${data.difficulty}</span></div>
            <div class="detail-card"><span class="detail-label">Time Limit</span><span class="detail-value">${data.time_limit}s</span></div>
            <div class="detail-card"><span class="detail-label">Description</span><span class="detail-value">${data.description || 'No description'}</span></div>
            ${data.challenge_type === 'image' ? 
                `<div class="detail-card"><span class="detail-label">Target Image</span><div><img src="${data.target_image_url}" style="max-width:100%; border-radius:8px;"></div></div>` : 
                `<div class="detail-card"><span class="detail-label">HTML Locked</span><span class="detail-value">${data.html_locked ? 'Yes' : 'No'}</span></div>
                 <div class="code-preview"><strong>Target HTML:</strong><pre><code>${escapeHtml(data.target_html || 'No HTML')}</code></pre></div>
                 <div class="code-preview"><strong>Target CSS:</strong><pre><code>${escapeHtml(data.target_css || 'No CSS')}</code></pre></div>`
            }
        `;
    }
};

// Delete user
window.deleteUser = async (userId, username) => {
    const confirmed = await showConfirm(`Delete user "${username}"? This cannot be undone!`, 'Delete user');
    if (!confirmed) return;
    
    const res = await fetch(`/admin/user/${userId}/delete`, {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'}
    });
    const data = await res.json();
    if (data.success) {
        showToast(`User ${username} deleted`, 'success');
        setTimeout(() => location.reload(), 1000);
    } else {
        showToast(data.error || 'Failed to delete user', 'error');
    }
};

// Toggle admin role
window.toggleAdminRole = async (userId, username) => {
    const row = document.querySelector(`tr[data-user-id='${userId}']`);
    const currentRole = row?.dataset.role || 'player';
    const action = currentRole === 'admin' ? 'demote' : 'promote';
    const confirmMessage = currentRole === 'admin'
        ? `Remove admin role from ${username}?`
        : `Promote ${username} to admin?`;
    const confirmed = await showConfirm(confirmMessage, 'Change role');
    if (!confirmed) return;
    const res = await fetch(`/admin/user/${userId}/role`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: action})
    });
    const data = await res.json();
    if (res.ok && data.success) {
        showToast(`Role updated for ${username}`, 'success');
        setTimeout(() => location.reload(), 900);
    } else {
        showToast(data.error || 'Failed to update role', 'error');
    }
};

// Reset player stats
window.resetPlayerStats = async (userId, username) => {
    const confirmed = await showConfirm(`Reset all stats for ${username}?`, 'Reset stats');
    if (!confirmed) return;
    
    const res = await fetch(`/admin/user/${userId}/reset-stats`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'}
    });
    try {
        const res = await fetch(`/admin/user/${userId}/matches`);
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        const data = await res.json();

        if (data && data.success && Array.isArray(data.matches) && data.matches.length) {
            modalBody.innerHTML = `
                <table class="data-table">
                    <thead><tr><th>Date</th><th>Challenge</th><th>Accuracy</th><th>Result</th></tr></thead>
                    <tbody>
                        ${data.matches.map(m => `<tr>
                            <td>${m.date}</td>
                            <td>${m.challenge}</td>
                            <td>${m.accuracy}%</td>
                            <td>${m.result}</td>
                        </tr>`).join('')}
                    </tbody>
                </table>
            `;
        } else {
            modalBody.innerHTML = '<p class="no-data">No matches found for this player.</p>';
        }
    } catch (err) {
        modalBody.innerHTML = `<p class="error">Error loading matches: ${err.message}</p>`;
        if (typeof showToast === 'function') showToast('Error loading matches', 'error');
        console.error('viewPlayerMatches error:', err);
    }
        const data = await res.json();

        if (data && data.success) {
            modalTitle.textContent = `${data.username}'s Stats`;
            modalBody.innerHTML = `
                <div class="detail-card"><span class="detail-label">Username</span><span class="detail-value">${data.username}</span></div>
                <div class="detail-card"><span class="detail-label">Role</span><span class="detail-value">${data.role || 'player'}</span></div>
                <div class="detail-card"><span class="detail-label">Matches</span><span class="detail-value">${data.matches_played ?? 0}</span></div>
                <div class="detail-card"><span class="detail-label">Best Accuracy</span><span class="detail-value">${data.best_accuracy ?? 0}%</span></div>
                <div class="detail-card"><span class="detail-label">Total Wins</span><span class="detail-value">${data.total_wins ?? 0}</span></div>
                <div class="detail-card"><span class="detail-label">Win Rate</span><span class="detail-value">${data.win_rate ?? 0}%</span></div>
                <div class="detail-card"><span class="detail-label">Member Since</span><span class="detail-value">${data.joined_date ?? 'Unknown'}</span></div>
            `;
        } else {
            modalTitle.textContent = 'Profile';
            modalBody.innerHTML = `<p class="error">${data?.error || 'Failed to load profile'}</p>`;
            if (typeof showToast === 'function') showToast(data?.error || 'Failed to load profile', 'error');
        }
    } catch (err) {
        modalTitle.textContent = 'Profile';
        modalBody.innerHTML = `<p class="error">Error loading profile: ${err.message}</p>`;
        if (typeof showToast === 'function') showToast('Error loading profile', 'error');
        console.error('viewPlayerProfile error:', err);
    }
};

// View player matches
window.viewPlayerMatches = async (userId, username) => {
    const modal = document.getElementById('player-stats-modal');
    const modalBody = document.getElementById('modal-body');
    const modalTitle = document.getElementById('modal-player-name');
    
    modal.style.display = 'flex';
    modalBody.innerHTML = '<div class="loading">Loading...</div>';
    modalTitle.textContent = `${username}'s Matches`;
    
    const res = await fetch(`/admin/user/${userId}/matches`);
    const data = await res.json();
    
    if (data.success && data.matches.length) {
        modalBody.innerHTML = `
            <table class="data-table">
                <thead><tr><th>Date</th><th>Challenge</th><th>Accuracy</th><th>Result</th></tr></thead>
                <tbody>
                    ${data.matches.map(m => `<tr>
                        <td>${m.date}</td>
                        <td>${m.challenge}</td>
                        <td class="${m.accuracy >= 80 ? 'high' : m.accuracy >= 50 ? 'mid' : 'low'}">${m.accuracy}%</td>
                        <td>${m.is_winner ? '<i class="fas fa-trophy"></i> Win' : '<i class="fas fa-times-circle"></i> Loss'}</td>
                    </tr>`).join('')}
                </tbody>
            </table>
        `;
    } else {
        modalBody.innerHTML = '<p>No matches found.</p>';
    }
};

// Broadcast
window.broadcastMessage = async () => {
    const message = document.getElementById('broadcast-message').value;
    const roomId = document.getElementById('broadcast-room-id').value;
    if (!message) { showToast('Enter a message', 'warning'); return; }
    
    const socket = io();
    socket.emit('broadcast_message', {message: message, room_id: roomId || null});
    showToast('Broadcast sent', 'success');
    document.getElementById('broadcast-message').value = '';
};

window.broadcastToAll = async () => {
    const message = document.getElementById('broadcast-message').value;
    if (!message) { showToast('Enter a message', 'warning'); return; }
    
    const socket = io();
    socket.emit('broadcast_message', {message: message, room_id: null});
    showToast('Broadcast sent to all rooms', 'success');
    document.getElementById('broadcast-message').value = '';
};

// Export data
window.exportData = async () => {
    const res = await fetch('/admin/export-data');
    const data = await res.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ui-battle-arena-export-${new Date().toISOString()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Data exported', 'success');
};

// Filter functions
function filterPlayers() {
    const search = document.getElementById('player-search')?.value.toLowerCase() || '';
    const filter = document.getElementById('player-filter')?.value || 'all';
    const rows = document.querySelectorAll('#players-tbody tr');
    
    rows.forEach(row => {
        const username = row.querySelector('.username-cell')?.textContent.toLowerCase() || '';
        const role = row.dataset.role || '';
        let show = true;
        if (search && !username.includes(search)) show = false;
        if (filter !== 'all' && role !== filter) show = false;
        row.style.display = show ? '' : 'none';
    });
}

function filterRooms() {
    const search = document.getElementById('room-search')?.value.toLowerCase() || '';
    const filter = document.getElementById('room-filter')?.value || 'all';
    const rows = document.querySelectorAll('#rooms-tbody tr');
    
    rows.forEach(row => {
        const code = row.querySelector('.room-code-cell')?.textContent.toLowerCase() || '';
        const status = row.dataset.status || '';
        let show = true;
        if (search && !code.includes(search)) show = false;
        if (filter !== 'all' && status !== filter) show = false;
        row.style.display = show ? '' : 'none';
    });
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

window.refreshRooms = () => location.reload();
window.refreshPlayers = () => location.reload();
window.closeModal = () => document.getElementById('player-stats-modal').style.display = 'none';
window.closeChallengeModal = () => document.getElementById('challenge-details-modal').style.display = 'none';

// Close modals on outside click
document.getElementById('player-stats-modal')?.addEventListener('click', (e) => {
    if (e.target === document.getElementById('player-stats-modal')) closeModal();
});
document.getElementById('challenge-details-modal')?.addEventListener('click', (e) => {
    if (e.target === document.getElementById('challenge-details-modal')) closeChallengeModal();
});

// Navigation (only intercept internal section links)
document.querySelectorAll('.sidebar-nav a').forEach(link => {
    link.addEventListener('click', (e) => {
        const href = link.getAttribute('href');
        const section = link.dataset.section;
        // If this is an in-page navigation (href="#" or has data-section), handle via JS
        if (href === '#' || section) {
            e.preventDefault();
            document.querySelectorAll('.sidebar-nav a').forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            document.querySelectorAll('.admin-section').forEach(s => s.classList.remove('active'));
            const target = document.getElementById(`section-${section}`);
            if (target) target.classList.add('active');
        }
        // Otherwise allow the link to navigate normally (external/admin pages)
    });
});

// Event listeners for search/filter
document.getElementById('player-search')?.addEventListener('input', filterPlayers);
document.getElementById('player-filter')?.addEventListener('change', filterPlayers);
document.getElementById('room-search')?.addEventListener('input', filterRooms);
document.getElementById('room-filter')?.addEventListener('change', filterRooms);

initAdminEditors();
