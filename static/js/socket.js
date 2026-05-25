// Socket.IO connection - Force HTTP long-polling only (more reliable for local dev)
const socket = io({
    transports: ['polling'],  // Force polling only, no websocket
    reconnection: true,
    reconnectionAttempts: 10,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
    timeout: 20000,
    upgrade: false  // Don't try to upgrade to websocket
});
window.socket = socket;

// Track if we've already joined the room
let hasJoinedRoom = false;
let typingTimer = null;
let typingActive = false;

// Connection status handlers
socket.on('connect', () => {
    console.log('âœ… Socket connected successfully (polling mode) - ID:', socket.id);
    
    // Join room
    const config = window.ARENA_CONFIG || {};
    const roomId = document.getElementById('room-id')?.value || config.roomId;
    const username = document.getElementById('current-username')?.value || config.currentUsername;
    
    const userRole = document.getElementById('user-role')?.value || config.userRole || 'spectator';
    if (roomId && username && !hasJoinedRoom) {
        console.log(`ðŸ“¡ Joining room ${roomId} as ${username} (${userRole})`);
        hasJoinedRoom = true;
        socket.emit('join_room', {
            room_id: parseInt(roomId),
            username: username,
            user_role: userRole
        });
    }
});

socket.on('disconnect', (reason) => {
    console.log('âŒ Socket disconnected:', reason);
    hasJoinedRoom = false;
    showToast('Connection lost. Reconnecting...', 'warning');
});

socket.on('reconnect', (attemptNumber) => {
    console.log('ðŸ”„ Socket reconnected after', attemptNumber, 'attempts');
    showToast('Reconnected!', 'success');
    hasJoinedRoom = false;
    
    // Re-join the room
    const config = window.ARENA_CONFIG || {};
    const roomId = document.getElementById('room-id')?.value || config.roomId;
    const username = document.getElementById('current-username')?.value || config.currentUsername;
    const userRole = document.getElementById('user-role')?.value || config.userRole || 'spectator';
    if (roomId && username) {
        setTimeout(() => {
            socket.emit('join_room', {
                room_id: parseInt(roomId),
                username: username,
                user_role: userRole
            });
            hasJoinedRoom = true;
        }, 500);
    }
});

socket.on('connect_error', (error) => {
    console.error('âŒ Socket connection error:', error);
});

// Debug: Listen for all events
socket.onAny((event, ...args) => {
    console.log(`ðŸ”” Socket event received: ${event}`, args);
});

// Player joined/left handlers
socket.on('player_joined', (data) => {
    console.log('ðŸ‘¤ player_joined event:', data);
    showToast(`${data.username} joined the arena!`, 'info');
    if (window.ARENA_CONFIG) {
        window.ARENA_CONFIG.player1Username = data.player1 || window.ARENA_CONFIG.player1Username || '';
        window.ARENA_CONFIG.player2Username = data.player2 || window.ARENA_CONFIG.player2Username || '';
    }
    const p1El = document.getElementById('p1-username');
    const p2El = document.getElementById('p2-username');
    if (p1El && data.player1) p1El.textContent = data.player1;
    if (p2El && data.player2) p2El.textContent = data.player2;
});

socket.on('player_left', (data) => {
    console.log('ðŸ‘‹ player_left event:', data);
    showToast(`${data.username} left the arena.`, 'warning');
});

// Room joined confirmation
socket.on('room_joined', (data) => {
    console.log('âœ… Successfully joined room:', data);
    showToast(`Joined room ${data.room_id}`, 'success');
});

function setEditorPausedState(isPaused) {
    const config = window.ARENA_CONFIG || {};
    const userRole = document.getElementById('user-role')?.value || config.userRole || 'spectator';
    const challengeType = document.getElementById('challenge-type')?.value || config.challengeType;
    const htmlLocked = document.getElementById('html-locked')?.value === 'true' || config.htmlLocked === true;
    const isPlayer = userRole === 'player1' || userRole === 'player2';
    const shouldLock = isPaused || !isPlayer;

    if (window.cssEditor) window.cssEditor.setOption('readOnly', shouldLock);
    if (window.jsEditor) window.jsEditor.setOption('readOnly', shouldLock);
    if (window.htmlEditor) {
        window.htmlEditor.setOption('readOnly', shouldLock || (challengeType === 'html' && htmlLocked));
    }

    ['submit-btn', 'reset-code-btn'].forEach((id) => {
        const btn = document.getElementById(id);
        if (btn) btn.disabled = isPaused || !isPlayer;
    });
}

// Player list update
socket.on('player_list_update', (data) => {
    console.log('ðŸ‘¥ Player list update:', data);
    if (data.player1) {
        const p1El = document.getElementById('p1-username');
        if (p1El) p1El.textContent = data.player1;
    }
    if (data.player2) {
        const p2El = document.getElementById('p2-username');
        if (p2El) p2El.textContent = data.player2;
    }
});

socket.on('spectator_list_update', (data) => {
    console.log('ðŸ‘€ spectator_list_update:', data);
    const countEl = document.getElementById('spectator-count');
    const listEl = document.getElementById('spectator-list');
    if (countEl) countEl.textContent = data.count;
    if (!listEl) return;

    if (!data.spectators || data.spectators.length === 0) {
        listEl.innerHTML = '<div class="spectator-placeholder">No spectators yet</div>';
        return;
    }

    listEl.innerHTML = data.spectators.map((name) => `
        <div class="spectator-item">
            <i class="fas fa-eye"></i> ${escapeHtml(name)}
        </div>
    `).join('');
});

socket.on('presence_update', (data) => {
    const list = document.getElementById('online-users-list');
    if (!list) return;
    const users = Array.isArray(data?.users) ? data.users : [];
    if (!users.length) {
        list.innerHTML = '<div class="spectator-placeholder">No one online yet</div>';
        return;
    }

    list.innerHTML = users.map((user) => `
        <div class="online-user">
            <span class="online-dot"></span>
            <span>${escapeHtml(user.username)}</span>
            <small>${escapeHtml(user.role || 'spectator')}</small>
        </div>
    `).join('');
});

// Challenge Started - CRITICAL
socket.on('challenge_started', function(data) {
    console.log('ðŸðŸðŸ CHALLENGE STARTED EVENT RECEIVED! ðŸðŸðŸ');
    console.log('Data received:', data);
    
    // Unlock editors based on challenge type and lock state
    const config = window.ARENA_CONFIG || {};
    const challengeType = document.getElementById('challenge-type')?.value || config.challengeType;
    const htmlLocked = document.getElementById('html-locked')?.value === 'true' || config.htmlLocked === true;
    const userRole = document.getElementById('user-role')?.value || config.userRole;
    
    showToast(`Challenge started! ${data.time_limit}s on the clock!`, 'success');
    
    // Hide the overlay
    const overlay = document.getElementById('editor-overlay');
    if (overlay) {
        overlay.classList.add('hidden');
        console.log('âœ… Overlay hidden');
    }
    
    // Update room status
    const statusPill = document.getElementById('room-status');
    if (statusPill) {
        statusPill.textContent = 'LIVE';
        statusPill.style.background = 'rgba(0,255,136,0.2)';
        statusPill.style.color = 'var(--success)';
    }
    
    // Enable editors only for active players. Admin and spectators observe read-only.
    const isPlayer = userRole === 'player1' || userRole === 'player2';
    if (isPlayer) {
        if (window.cssEditor) {
            window.cssEditor.setOption('readOnly', false);
            console.log('âœ… CSS editor unlocked');
        }
        if (window.jsEditor) {
            window.jsEditor.setOption('readOnly', false);
            console.log('âœ… JS editor unlocked');
        }
        
        if (!(challengeType === 'html' && htmlLocked)) {
            if (window.htmlEditor) {
                window.htmlEditor.setOption('readOnly', false);
                console.log('âœ… HTML editor unlocked');
            }
        }
    }
    
    // Enable submit button
    const submitBtn = document.getElementById('submit-btn');
    if (submitBtn) {
        submitBtn.disabled = !isPlayer;
    }

    setEditorPausedState(false);

    if (window.setArenaMatchRunning) {
        window.setArenaMatchRunning(true);
    }
});

// Progress update - opponent only
socket.on('progress_update', (data) => {
    console.log('ðŸ“Š progress_update:', data);
    const currentUser = document.getElementById('current-username')?.value || window.ARENA_CONFIG?.currentUsername;
    if (data.username === currentUser) return;
    
    const p1Name = document.getElementById('p1-username-data')?.value || window.ARENA_CONFIG?.player1Username;
    const p2Name = document.getElementById('p2-username-data')?.value || window.ARENA_CONFIG?.player2Username;
    
    let barId, labelId;
    if (data.username === p1Name) {
        barId = 'p1-progress-fill';
        labelId = 'p1-accuracy-label';
    } else if (data.username === p2Name) {
        barId = 'p2-progress-fill';
        labelId = 'p2-accuracy-label';
    } else {
        return;
    }
    
    const bar = document.getElementById(barId);
    const label = document.getElementById(labelId);
    
    if (bar) bar.style.width = data.accuracy + '%';
    if (label) {
        label.textContent = data.accuracy + '%';
        label.classList.add('flash-update');
        setTimeout(() => label.classList.remove('flash-update'), 600);
    }
});

// Leaderboard update
socket.on('leaderboard_update', (data) => {
    console.log('ðŸ“Š leaderboard_update:', data);
    renderLeaderboard(data.players);
});

function renderLeaderboard(players) {
    const container = document.getElementById('leaderboard-list');
    if (!container) return;
    
    if (!players || players.length === 0) {
        container.innerHTML = '<p class="muted">No scores yet.</p>';
        return;
    }
    
    container.innerHTML = '';
    players.forEach(p => {
        const rankColor = p.rank === 1 ? 'var(--neon-gold)' : 
                         p.rank === 2 ? 'var(--neon-silver)' : 
                         p.rank === 3 ? 'var(--neon-bronze)' : 'var(--text-primary)';
        const accColor = p.accuracy >= 80 ? 'var(--success)' : 
                        p.accuracy >= 50 ? 'var(--warning)' : 'var(--danger)';
        
        const row = document.createElement('div');
        row.className = 'lb-row';
        row.innerHTML = `
            <span class="lb-rank" style="color:${rankColor}">${p.rank}</span>
            <div class="lb-avatar">${p.username[0].toUpperCase()}</div>
            <span class="lb-name">${p.username}</span>
            <span class="lb-score" style="color:${accColor}">${p.accuracy}%</span>
        `;
        container.appendChild(row);
    });
}

// Chat message handler
socket.on('chat_message', (data) => {
    console.log('ðŸ’¬ chat_message:', data);
    appendChatMessage(data.username, data.message, data.is_system, data.timestamp, data);
});

socket.on('chat_history', (data) => {
    const container = document.getElementById('chat-messages');
    if (!container) return;
    container.innerHTML = '';
    const messages = Array.isArray(data?.messages) ? data.messages : [];
    if (!messages.length) {
        const empty = document.createElement('div');
        empty.className = 'chat-empty';
        empty.textContent = 'No messages yet. Start the room chat.';
        container.appendChild(empty);
        return;
    }
    messages.forEach((message) => {
        appendChatMessage(message.username, message.message, message.is_system, message.timestamp, message);
    });
});

socket.on('chat_warning', (data) => {
    const message = data?.message || 'Please keep the chat respectful.';
    appendChatWarning(message);
    showToast(message, 'warning');
});

socket.on('chat_message_flagged', (data) => {
    markChatMessageFlagged(data?.id, data?.flag_reason || 'Flagged for admin review');
    const isAdmin = (document.getElementById('user-role')?.value || window.ARENA_CONFIG?.userRole) === 'admin';
    if (isAdmin) showToast('Chat message flagged for review', 'warning');
});

socket.on('chat_flag_notice', (data) => {
    appendChatWarning(data?.message || 'A chat message was flagged for review.');
});

socket.on('typing_update', (data) => {
    const indicator = document.getElementById('typing-indicator');
    if (!indicator) return;
    const currentUser = document.getElementById('current-username')?.value || window.ARENA_CONFIG?.currentUsername;
    const users = (Array.isArray(data?.users) ? data.users : []).filter((name) => name && name !== currentUser);
    if (!users.length) {
        indicator.textContent = '';
    } else if (users.length === 1) {
        indicator.textContent = `${users[0]} is typing...`;
    } else {
        indicator.textContent = `${users.slice(0, 2).join(', ')} are typing...`;
    }
});

socket.on('spectator_preview_state', (data) => {
    if (Array.isArray(data?.previews)) {
        data.previews.forEach((preview) => updateSpectatorPreview(preview.username, preview.compiled_html));
    }
});

socket.on('admin_preview', (data) => {
    updateSpectatorPreview(data.username, data.compiled_html);
    if (window.updateAdminPlayerCode) {
        window.updateAdminPlayerCode(data.username, data);
    }
});

socket.on('maintenance_reset', (data) => {
    showToast(data?.message || 'The arena was reset. Please log in again.', 'warning');
    setTimeout(() => {
        window.location.href = '/maintenance';
    }, 1000);
});

function appendChatMessage(username, message, isSystem = false) {
    const container = document.getElementById('chat-messages');
    if (!container) return;
    
    const msgDiv = document.createElement('div');
    msgDiv.className = 'chat-message';
    if (isSystem) {
        msgDiv.innerHTML = `<span class="chat-system">ðŸ“¢ ${message}</span>`;
    } else {
        msgDiv.innerHTML = `<span class="chat-username">${escapeHtml(username)}:</span> <span class="chat-text">${escapeHtml(message)}</span>`;
    }
    container.appendChild(msgDiv);
    container.scrollTop = container.scrollHeight;
}

function appendChatMessageRich(username, message, isSystem = false, timestamp = null, meta = {}) {
    const container = document.getElementById('chat-messages');
    if (!container) return;
    container.querySelector('.chat-empty')?.remove();

    const msgDiv = document.createElement('div');
    const currentUser = document.getElementById('current-username')?.value || window.ARENA_CONFIG?.currentUsername;
    const isAdmin = (document.getElementById('user-role')?.value || window.ARENA_CONFIG?.userRole) === 'admin';
    const time = timestamp ? new Date(timestamp).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : '';
    msgDiv.className = `chat-message ${isSystem ? 'system' : ''} ${username === currentUser ? 'own' : ''} ${meta?.is_flagged ? 'flagged' : ''}`;
    if (meta?.id) msgDiv.dataset.messageId = meta.id;

    if (isSystem) {
        msgDiv.innerHTML = `<span class="chat-system">${escapeHtml(message)}</span>`;
    } else {
        const flagBadge = meta?.is_flagged ? `<span class="chat-flag-badge"><i class="fas fa-flag"></i> Flagged: ${escapeHtml(meta.flag_reason || 'Needs review')}</span>` : '';
        const adminFlag = isAdmin && meta?.id ? `<button class="chat-flag-btn" type="button" title="Flag harmful message" aria-label="Flag harmful message"><i class="fas fa-flag"></i><span>Flag</span></button>` : '';
        msgDiv.innerHTML = `
            <div class="chat-meta"><span>${escapeHtml(username)}</span><small>${time}</small>${adminFlag}</div>
            ${flagBadge}
            <div class="chat-bubble">${escapeHtml(message)}</div>
        `;
        const flagBtn = msgDiv.querySelector('.chat-flag-btn');
        if (flagBtn) {
            flagBtn.addEventListener('click', () => flagChatMessage(meta.id));
        }
    }

    container.appendChild(msgDiv);
    container.scrollTop = container.scrollHeight;
}

appendChatMessage = appendChatMessageRich;

function appendChatWarning(message) {
    const container = document.getElementById('chat-messages');
    if (!container) return;
    container.querySelector('.chat-empty')?.remove();

    const msgDiv = document.createElement('div');
    msgDiv.className = 'chat-message moderation-warning';
    msgDiv.innerHTML = `
        <div class="chat-warning-icon"><i class="fas fa-triangle-exclamation"></i></div>
        <div>
            <strong>Chat notice</strong>
            <span>${escapeHtml(message)}</span>
        </div>
    `;
    container.appendChild(msgDiv);
    container.scrollTop = container.scrollHeight;
}

function flagChatMessage(messageId) {
    if (!messageId || !socket) return;
    socket.emit('flag_chat_message', {
        message_id: Number(messageId),
        reason: 'Flagged by admin as harmful'
    });
}

function markChatMessageFlagged(messageId, reason) {
    if (!messageId) return;
    const safeId = window.CSS?.escape ? CSS.escape(String(messageId)) : String(messageId).replace(/"/g, '\\"');
    const messageEl = document.querySelector(`.chat-message[data-message-id="${safeId}"]`);
    if (!messageEl) return;
    messageEl.classList.add('flagged');
    if (!messageEl.querySelector('.chat-flag-badge')) {
        const badge = document.createElement('span');
        badge.className = 'chat-flag-badge';
        badge.innerHTML = `<i class="fas fa-flag"></i> Flagged: ${escapeHtml(reason)}`;
        const bubble = messageEl.querySelector('.chat-bubble');
        if (bubble) {
            messageEl.insertBefore(badge, bubble);
        } else {
            messageEl.appendChild(badge);
        }
    }
}

// Timer tick from server
socket.on('timer_tick', (data) => {
    const remaining = data.remaining;
    const minutes = String(Math.floor(remaining / 60)).padStart(2, '0');
    const seconds = String(remaining % 60).padStart(2, '0');
    
    const timerDisplay = document.getElementById('timer-display');
    if (timerDisplay) {
        timerDisplay.textContent = `${minutes}:${seconds}`;
        if (remaining <= 10) {
            timerDisplay.classList.add('timer-danger');
        } else {
            timerDisplay.classList.remove('timer-danger');
        }
    }

    if (remaining <= 1 && window.runDiffCheck) {
        window.runDiffCheck({ silent: true, live: false, save: true, disableButton: false });
    }
});

// Challenge paused
socket.on('challenge_paused', (data = {}) => {
    console.log('â¸ï¸ challenge_paused:', data);
    showToast(data.message || 'Match paused by admin', 'warning');
    const statusPill = document.getElementById('room-status');
    if (statusPill) {
        statusPill.textContent = 'PAUSED';
        statusPill.style.background = 'rgba(255,170,0,0.2)';
        statusPill.style.color = 'var(--warning)';
    }
    if (window.setArenaMatchRunning) {
        window.setArenaMatchRunning(false);
    }
    setEditorPausedState(true);
});

// Challenge resumed
socket.on('challenge_resumed', (data = {}) => {
    console.log('â–¶ï¸ challenge_resumed', data);
    showToast('Match resumed!', 'success');
    const statusPill = document.getElementById('room-status');
    if (statusPill) {
        statusPill.textContent = 'LIVE';
        statusPill.style.background = 'rgba(0,255,136,0.2)';
        statusPill.style.color = 'var(--success)';
    }
    if (window.setArenaMatchRunning) {
        window.setArenaMatchRunning(true);
    }
    setEditorPausedState(false);
});

// Challenge ended
socket.on('challenge_ended', (data) => {
    console.log('ðŸ challenge_ended:', data);
    showToast("Time's up! Calculating final score...", 'warning');
    if (window.setArenaMatchRunning) {
        window.setArenaMatchRunning(false);
    }
    
    if (window.htmlEditor) window.htmlEditor.setOption('readOnly', true);
    if (window.cssEditor) window.cssEditor.setOption('readOnly', true);
    if (window.jsEditor) window.jsEditor.setOption('readOnly', true);
    ['submit-btn', 'reset-code-btn'].forEach((id) => {
        const btn = document.getElementById(id);
        if (btn) btn.disabled = true;
    });
    
    const overlay = document.getElementById('editor-overlay');
    if (overlay) {
        overlay.classList.remove('hidden');
        const overlaySpan = overlay.querySelector('.overlay-content span');
        if (overlaySpan) overlaySpan.textContent = 'ðŸ Challenge ended!';
    }
    
    const userRole = document.getElementById('user-role')?.value || window.ARENA_CONFIG?.userRole;
    const isPlayer = userRole === 'player1' || userRole === 'player2';
    if (window.runDiffCheck && isPlayer) {
        window.runDiffCheck({ silent: false, live: false, save: true, disableButton: false }).then(() => {
            setTimeout(() => {
                window.location.href = `/results/${data.room_id}`;
            }, 3000);
        });
    } else {
        setTimeout(() => {
            window.location.href = `/results/${data.room_id}`;
        }, 1200);
    }
});

// System announcement
socket.on('system_announcement', (data) => {
    console.log('ðŸ“¢ system_announcement:', data);
    showToast(`ðŸ“¢ ${data.message}`, 'info');
    appendChatMessage('ADMIN', data.message, true);
});

const voiceBroadcastQueue = [];
let voiceBroadcastPlaying = false;

function playNextVoiceBroadcastChunk() {
    if (voiceBroadcastPlaying || voiceBroadcastQueue.length === 0) return;
    voiceBroadcastPlaying = true;
    const audio = new Audio(voiceBroadcastQueue.shift());
    audio.onended = () => {
        voiceBroadcastPlaying = false;
        playNextVoiceBroadcastChunk();
    };
    audio.onerror = () => {
        voiceBroadcastPlaying = false;
        playNextVoiceBroadcastChunk();
    };
    audio.play().catch(() => {
        voiceBroadcastPlaying = false;
        showToast('Tap Allow Media to hear admin voice broadcasts.', 'warning');
    });
}

socket.on('voice_broadcast_start', (data = {}) => {
    const userRole = document.getElementById('user-role')?.value || window.ARENA_CONFIG?.userRole;
    if (!['player1', 'player2', 'spectator'].includes(userRole)) return;
    const name = data.username || 'Admin';
    showToast(`${name} started a voice broadcast`, 'info');
    appendChatMessage('ADMIN', `${name} started a voice broadcast`, true);
});

socket.on('voice_broadcast_chunk', (data = {}) => {
    const userRole = document.getElementById('user-role')?.value || window.ARENA_CONFIG?.userRole;
    if (!['player1', 'player2', 'spectator'].includes(userRole) || !data.chunk) return;
    voiceBroadcastQueue.push(data.chunk);
    playNextVoiceBroadcastChunk();
});

socket.on('voice_broadcast_end', (data = {}) => {
    const userRole = document.getElementById('user-role')?.value || window.ARENA_CONFIG?.userRole;
    if (!['player1', 'player2', 'spectator'].includes(userRole)) return;
    showToast('Voice broadcast ended', 'info');
});

// Kicked
socket.on('kicked', (data) => {
    console.log('ðŸ‘¢ kicked:', data);
    showToast(data.message || 'You were removed by the admin.', 'error');
    setTimeout(() => {
        window.location.href = '/dashboard';
    }, 2000);
});

socket.on('tournament_kick', (data) => {
    const message = data?.message || 'You were removed from the tournament by an admin.';
    showToast(`${message}${data?.admin_note ? ` Admin note: ${data.admin_note}` : ''}`, 'error');
});

// Player forfeit
socket.on('player_forfeit', (data) => {
    console.log('ðŸ³ï¸ player_forfeit:', data);
    showToast(`${data.username} forfeited!`, 'warning');
});

// Camera frame
socket.on('cam_frame', (data) => {
    const currentUser = document.getElementById('current-username')?.value || window.ARENA_CONFIG?.currentUsername;
    if (data.username === currentUser) return;

    const remoteCams = document.getElementById('remote-cams');
    if (remoteCams && data.username && data.frame_data) {
        remoteCams.closest('.cam-container')?.classList.add('has-remote');
        const placeholder = document.getElementById('cam-placeholder');
        if (placeholder) placeholder.style.display = 'none';
        const safeId = `remote-cam-${String(data.username).replace(/[^a-zA-Z0-9_-]/g, '-')}`;
        let item = document.getElementById(safeId);
        if (!item) {
            item = document.createElement('div');
            item.className = 'remote-cam-tile';
            item.id = safeId;
            item.innerHTML = '<img alt=""><span></span>';
            remoteCams.appendChild(item);
        }
        item.querySelector('img').src = data.frame_data;
        item.querySelector('span').textContent = data.username;
    }

    updateSpectatorCamera(data.username, data.frame_data);
    
    const p1Name = document.getElementById('p1-username-data')?.value || window.ARENA_CONFIG?.player1Username;
    const p2Name = document.getElementById('p2-username-data')?.value || window.ARENA_CONFIG?.player2Username;
    
    let pipId = null;
    if (data.username === p1Name) {
        pipId = 'opponent-cam-pip-p2';
    } else if (data.username === p2Name) {
        pipId = 'opponent-cam-pip-p1';
    }
    
    if (pipId) {
        const pip = document.getElementById(pipId);
        if (pip) {
            pip.src = data.frame_data;
            pip.style.display = 'block';
        }
    }
});

// Helper functions
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function updateSpectatorPreview(username, compiledHtml) {
    if (!username || !compiledHtml) return;
    const lists = [
        document.getElementById('spectator-preview-list'),
        document.getElementById('spectator-editor-preview-list')
    ].filter(Boolean);

    lists.forEach((list, index) => {
        const safeId = `spectator-preview-${index}-${String(username).replace(/[^a-zA-Z0-9_-]/g, '-')}`;
        let item = document.getElementById(safeId);
        if (!item) {
            item = document.createElement('div');
            item.className = 'spectator-preview-item';
            item.id = safeId;
            item.innerHTML = `
                <div class="spectator-preview-title">
                    <span></span>
                    <small>Live</small>
                </div>
                <iframe sandbox="allow-scripts allow-same-origin"></iframe>
            `;
            list.querySelector('.spectator-placeholder')?.remove();
            list.appendChild(item);
        }

        item.querySelector('span').textContent = username;
        item.querySelector('iframe').srcdoc = compiledHtml;
    });
}

function updateSpectatorCamera(username, frameData) {
    const list = document.getElementById('spectator-camera-list');
    if (!list || !username || !frameData) return;

    const safeId = `spectator-camera-${String(username).replace(/[^a-zA-Z0-9_-]/g, '-')}`;
    let item = document.getElementById(safeId);
    if (!item) {
        item = document.createElement('div');
        item.className = 'spectator-camera-tile';
        item.id = safeId;
        item.innerHTML = '<img alt=""><span></span>';
        list.querySelector('.spectator-placeholder')?.remove();
        list.appendChild(item);
    }
    item.querySelector('img').src = frameData;
    item.querySelector('span').textContent = username;
}

window.updateAdminPlayerCode = window.updateAdminPlayerCode || function () {};

// Send chat message
function sendChatMessage() {
    const input = document.getElementById('chat-input');
    const message = input?.value.trim();
    if (!message) return;
    if (window.setArenaChatOpen) window.setArenaChatOpen(true);
    if (window.activateArenaSidebarCard) window.activateArenaSidebarCard('chat');
    
    const roomId = document.getElementById('room-id')?.value || window.ARENA_CONFIG?.roomId;
    const username = document.getElementById('current-username')?.value || window.ARENA_CONFIG?.currentUsername;
    
    socket.emit('chat_message', {
        room_id: parseInt(roomId),
        username: username,
        message: message
    });
    
    input.value = '';
    document.getElementById('send-chat')?.setAttribute('disabled', 'disabled');
    emitTyping(false);
}

function emitTyping(isTyping) {
    const roomId = document.getElementById('room-id')?.value || window.ARENA_CONFIG?.roomId;
    const username = document.getElementById('current-username')?.value || window.ARENA_CONFIG?.currentUsername;
    if (!roomId || !username || !socket) return;
    if (typingActive === isTyping) return;
    typingActive = isTyping;
    socket.emit('typing', {
        room_id: parseInt(roomId),
        username: username,
        is_typing: isTyping
    });
}

// Manual status check button
window.checkChallengeStatus = function() {
    const roomId = document.getElementById('room-id')?.value || window.ARENA_CONFIG?.roomId;
    if (roomId && socket) {
        console.log('Manual status check requested');
        socket.emit('check_challenge_status', { room_id: parseInt(roomId) });
        showToast('Checking challenge status...', 'info');
    }
};

// Setup chat input handler
document.addEventListener('DOMContentLoaded', () => {
    console.log('ðŸ“„ DOM Content Loaded');
    
    const sendBtn = document.getElementById('send-chat');
    const chatInput = document.getElementById('chat-input');
    
    if (sendBtn) {
        sendBtn.addEventListener('click', () => {
            if (window.setArenaChatOpen) window.setArenaChatOpen(true);
            if (window.activateArenaSidebarCard) window.activateArenaSidebarCard('chat');
            sendChatMessage();
        });
    }
    if (chatInput) {
        const syncSendState = () => {
            if (sendBtn) sendBtn.disabled = chatInput.value.trim().length === 0;
        };
        syncSendState();
        chatInput.addEventListener('focus', () => {
            if (window.setArenaChatOpen) window.setArenaChatOpen(true);
            if (window.activateArenaSidebarCard) window.activateArenaSidebarCard('chat');
        });
        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendChatMessage();
        });
        chatInput.addEventListener('input', () => {
            emitTyping(chatInput.value.trim().length > 0);
            if (typingTimer) clearTimeout(typingTimer);
            typingTimer = setTimeout(() => emitTyping(false), 1400);
            syncSendState();
        });
        chatInput.addEventListener('blur', () => emitTyping(false));
    }
    
    const shareBtn = document.getElementById('share-btn');
    if (shareBtn && !shareBtn.dataset.shareReady) {
        shareBtn.dataset.shareReady = 'true';

        const getShareData = () => {
            const roomId = document.getElementById('room-id')?.value || window.ARENA_CONFIG?.roomId;
            const roomCode = document.getElementById('room-code')?.value || window.ARENA_CONFIG?.roomCode || '';
            const roomCodePublic = Boolean(window.ARENA_CONFIG?.roomCodePublic && roomCode);
            const roomLabel = roomCodePublic ? roomCode : `Room ${roomId}`;
            const title = window.ARENA_CONFIG?.challengeTitle || 'UI Battle Arena match';
            const playerUrl = `${window.location.origin}/arena/${roomId}?role=player`;
            const spectatorUrl = `${window.location.origin}/arena/${roomId}?role=spectator`;
            const inviteText = `Join my UI Battle Arena match ${roomLabel}: ${spectatorUrl}`;
            return { roomId, roomCode, roomCodePublic, roomLabel, title, playerUrl, spectatorUrl, inviteText };
        };

        const copyText = async (text, successMessage) => {
            try {
                if (navigator.clipboard?.writeText) {
                    await navigator.clipboard.writeText(text);
                } else {
                    throw new Error('Clipboard API unavailable');
                }
                showToast(successMessage, 'success');
            } catch (error) {
                const tempInput = document.createElement('textarea');
                tempInput.value = text;
                tempInput.setAttribute('readonly', '');
                tempInput.style.position = 'fixed';
                tempInput.style.left = '-9999px';
                document.body.appendChild(tempInput);
                tempInput.select();
                const copied = document.execCommand('copy');
                tempInput.remove();
                showToast(copied ? successMessage : text, copied ? 'success' : 'info');
            }
        };

        const openShareUrl = (url) => {
            window.open(url, '_blank', 'noopener,noreferrer,width=720,height=640');
        };

        const menu = document.createElement('div');
        menu.className = 'share-menu';
        menu.hidden = true;
        menu.innerHTML = `
            <div class="share-menu-header">
                <strong>Share Match</strong>
                <span data-share-room-code></span>
            </div>
            <button type="button" data-share-action="native"><i class="fas fa-share-alt"></i> Device Share</button>
            <button type="button" data-share-action="whatsapp"><i class="fab fa-whatsapp"></i> WhatsApp</button>
            <button type="button" data-share-action="telegram"><i class="fab fa-telegram"></i> Telegram</button>
            <button type="button" data-share-action="email"><i class="fas fa-envelope"></i> Email Invite</button>
            <button type="button" data-share-action="sms"><i class="fas fa-sms"></i> SMS</button>
            <button type="button" data-share-action="copy-spectator"><i class="fas fa-eye"></i> Copy Spectator Link</button>
            <button type="button" data-share-action="copy-player"><i class="fas fa-gamepad"></i> Copy Player Link</button>
            <button type="button" data-share-action="copy-code"><i class="fas fa-key"></i> Copy Match Room ID</button>
            <button type="button" data-share-action="copy-all"><i class="fas fa-clipboard"></i> Copy Full Invite</button>
        `;
        shareBtn.insertAdjacentElement('afterend', menu);

        const setMenuOpen = (open) => {
            const data = getShareData();
            menu.querySelector('[data-share-room-code]').textContent = data.roomCodePublic ? data.roomCode : 'Private match';
            menu.querySelector('[data-share-action="copy-code"]').hidden = !data.roomCodePublic;
            menu.hidden = !open;
            shareBtn.classList.toggle('active', open);
            shareBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
        };

        shareBtn.setAttribute('aria-haspopup', 'menu');
        shareBtn.setAttribute('aria-expanded', 'false');
        shareBtn.addEventListener('click', (event) => {
            event.stopPropagation();
            setMenuOpen(menu.hidden);
        });

        menu.addEventListener('click', async (event) => {
            const item = event.target.closest('[data-share-action]');
            if (!item) return;
            event.preventDefault();
            event.stopPropagation();

            const action = item.dataset.shareAction;
            const data = getShareData();
            const encodedText = encodeURIComponent(data.inviteText);
            const encodedUrl = encodeURIComponent(data.spectatorUrl);
            const encodedTitle = encodeURIComponent(data.title);
            const openInviteLink = async (url, fallbackText, fallbackMessage) => {
                try {
                    window.location.assign(url);
                    showToast('Opening share option...', 'info');
                } catch (error) {
                    await copyText(fallbackText, fallbackMessage);
                }
            };

            try {
                if (action === 'native') {
                    if (navigator.share) {
                        await navigator.share({ title: data.title, text: data.inviteText, url: data.spectatorUrl });
                    } else {
                        await copyText(data.inviteText, 'Device share is unavailable here. Invite copied instead!');
                    }
                }
                if (action === 'whatsapp') openShareUrl(`https://wa.me/?text=${encodedText}`);
                if (action === 'telegram') openShareUrl(`https://t.me/share/url?url=${encodedUrl}&text=${encodedTitle}`);
                if (action === 'email') {
                    await openInviteLink(
                        `mailto:?subject=${encodedTitle}&body=${encodedText}`,
                        data.inviteText,
                        'No email app opened. Invite copied instead!'
                    );
                }
                if (action === 'sms') {
                    const separator = /iPad|iPhone|iPod/.test(navigator.userAgent) ? '&' : '?';
                    await openInviteLink(
                        `sms:${separator}body=${encodedText}`,
                        data.inviteText,
                        'No SMS app opened. Invite copied instead!'
                    );
                }
                if (action === 'copy-spectator') await copyText(data.spectatorUrl, 'Spectator link copied!');
                if (action === 'copy-player') await copyText(data.playerUrl, 'Player link copied!');
                if (action === 'copy-code' && data.roomCodePublic) await copyText(data.roomCode, 'Match room ID copied!');
                if (action === 'copy-all') await copyText(data.inviteText, 'Invite copied!');
            } catch (error) {
                if (error?.name !== 'AbortError') {
                    await copyText(data.inviteText, 'Share failed. Invite copied instead!');
                }
            }

            setMenuOpen(false);
        });

        document.addEventListener('click', (event) => {
            if (!menu.hidden && !menu.contains(event.target) && event.target !== shareBtn) {
                setMenuOpen(false);
            }
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') setMenuOpen(false);
        });
    }
    
    const leaveBtn = document.getElementById('leave-room-btn');
    if (leaveBtn) {
        leaveBtn.addEventListener('click', async () => {
            const confirmed = await showConfirm('Leave this room?', 'Leave room');
            if (!confirmed) return;
            const roomId = document.getElementById('room-id')?.value || window.ARENA_CONFIG?.roomId;
            const username = document.getElementById('current-username')?.value || window.ARENA_CONFIG?.currentUsername;
            socket.emit('leave_room', {
                room_id: parseInt(roomId),
                username: username
            });
            window.location.href = '/dashboard';
        });
    }
});

// Add a check status button to the action bar if it doesn't exist
setTimeout(() => {
    const actionBar = document.querySelector('.action-bar');
    if (actionBar && !document.getElementById('check-status-btn')) {
        const checkBtn = document.createElement('button');
        checkBtn.id = 'check-status-btn';
        checkBtn.className = 'action-btn-secondary';
        checkBtn.innerHTML = '<i class="fas fa-sync-alt"></i> Check Status';
        checkBtn.onclick = checkChallengeStatus;
        actionBar.appendChild(checkBtn);
        console.log('âœ… Status check button added');
    }
}, 1000);

