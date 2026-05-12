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

// Track if we've already joined the room
let hasJoinedRoom = false;

// Connection status handlers
socket.on('connect', () => {
    console.log('✅ Socket connected successfully (polling mode) - ID:', socket.id);
    
    // Join room
    const roomId = document.getElementById('room-id')?.value;
    const username = document.getElementById('current-username')?.value;
    
    if (roomId && username && !hasJoinedRoom) {
        console.log(`📡 Joining room ${roomId} as ${username}`);
        hasJoinedRoom = true;
        socket.emit('join_room', {
            room_id: parseInt(roomId),
            username: username
        });
    }
});

socket.on('disconnect', (reason) => {
    console.log('❌ Socket disconnected:', reason);
    hasJoinedRoom = false;
    showToast('Connection lost. Reconnecting...', 'warning');
});

socket.on('reconnect', (attemptNumber) => {
    console.log('🔄 Socket reconnected after', attemptNumber, 'attempts');
    showToast('Reconnected!', 'success');
    hasJoinedRoom = false;
    
    // Re-join the room
    const roomId = document.getElementById('room-id')?.value;
    const username = document.getElementById('current-username')?.value;
    if (roomId && username) {
        setTimeout(() => {
            socket.emit('join_room', {
                room_id: parseInt(roomId),
                username: username
            });
            hasJoinedRoom = true;
        }, 500);
    }
});

socket.on('connect_error', (error) => {
    console.error('❌ Socket connection error:', error);
});

// Debug: Listen for all events
socket.onAny((event, ...args) => {
    console.log(`🔔 Socket event received: ${event}`, args);
});

// Player joined/left handlers
socket.on('player_joined', (data) => {
    console.log('👤 player_joined event:', data);
    showToast(`${data.username} joined the arena!`, 'info');
});

socket.on('player_left', (data) => {
    console.log('👋 player_left event:', data);
    showToast(`${data.username} left the arena.`, 'warning');
});

// Room joined confirmation
socket.on('room_joined', (data) => {
    console.log('✅ Successfully joined room:', data);
    showToast(`Joined room ${data.room_id}`, 'success');
});

// Player list update
socket.on('player_list_update', (data) => {
    console.log('👥 Player list update:', data);
    if (data.player1) {
        const p1El = document.getElementById('p1-username');
        if (p1El) p1El.textContent = data.player1;
    }
    if (data.player2) {
        const p2El = document.getElementById('p2-username');
        if (p2El) p2El.textContent = data.player2;
    }
});

// Challenge Started - CRITICAL
socket.on('challenge_started', function(data) {
    console.log('🏁🏁🏁 CHALLENGE STARTED EVENT RECEIVED! 🏁🏁🏁');
    console.log('Data received:', data);
    
    // Unlock editors based on challenge type and lock state
    const challengeType = document.getElementById('challenge-type')?.value;
    const htmlLocked = document.getElementById('html-locked')?.value === 'true';
    const userRole = document.getElementById('user-role')?.value;
    
    showToast(`Challenge started! ${data.time_limit}s on the clock!`, 'success');
    
    // Hide the overlay
    const overlay = document.getElementById('editor-overlay');
    if (overlay) {
        overlay.classList.add('hidden');
        console.log('✅ Overlay hidden');
    }
    
    // Update room status
    const statusPill = document.getElementById('room-status');
    if (statusPill) {
        statusPill.textContent = 'LIVE';
        statusPill.style.background = 'rgba(0,255,136,0.2)';
        statusPill.style.color = 'var(--success)';
    }
    
    // Enable editors if not spectator
    if (userRole !== 'spectator') {
        if (window.cssEditor) {
            window.cssEditor.setOption('readOnly', false);
            console.log('✅ CSS editor unlocked');
        }
        if (window.jsEditor) {
            window.jsEditor.setOption('readOnly', false);
            console.log('✅ JS editor unlocked');
        }
        
        if (!(challengeType === 'html' && htmlLocked)) {
            if (window.htmlEditor) {
                window.htmlEditor.setOption('readOnly', false);
                console.log('✅ HTML editor unlocked');
            }
        }
    }
    
    // Enable submit button
    const submitBtn = document.getElementById('submit-btn');
    if (submitBtn) {
        submitBtn.disabled = false;
    }
});

// Progress update - opponent only
socket.on('progress_update', (data) => {
    console.log('📊 progress_update:', data);
    const currentUser = document.getElementById('current-username')?.value;
    if (data.username === currentUser) return;
    
    const p1Name = document.getElementById('p1-username-data')?.value;
    const p2Name = document.getElementById('p2-username-data')?.value;
    
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
    console.log('📊 leaderboard_update:', data);
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
    console.log('💬 chat_message:', data);
    appendChatMessage(data.username, data.message, data.is_system);
});

function appendChatMessage(username, message, isSystem = false) {
    const container = document.getElementById('chat-messages');
    if (!container) return;
    
    const msgDiv = document.createElement('div');
    msgDiv.className = 'chat-message';
    if (isSystem) {
        msgDiv.innerHTML = `<span class="chat-system">📢 ${message}</span>`;
    } else {
        msgDiv.innerHTML = `<span class="chat-username">${escapeHtml(username)}:</span> <span class="chat-text">${escapeHtml(message)}</span>`;
    }
    container.appendChild(msgDiv);
    container.scrollTop = container.scrollHeight;
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
});

// Challenge paused
socket.on('challenge_paused', (data) => {
    console.log('⏸️ challenge_paused:', data);
    showToast('Challenge paused by admin', 'warning');
    const statusPill = document.getElementById('room-status');
    if (statusPill) {
        statusPill.textContent = 'PAUSED';
        statusPill.style.background = 'rgba(255,170,0,0.2)';
        statusPill.style.color = 'var(--warning)';
    }
});

// Challenge resumed
socket.on('challenge_resumed', () => {
    console.log('▶️ challenge_resumed');
    showToast('Challenge resumed!', 'success');
    const statusPill = document.getElementById('room-status');
    if (statusPill) {
        statusPill.textContent = 'LIVE';
        statusPill.style.background = 'rgba(0,255,136,0.2)';
        statusPill.style.color = 'var(--success)';
    }
});

// Challenge ended
socket.on('challenge_ended', (data) => {
    console.log('🏁 challenge_ended:', data);
    showToast("Time's up! Calculating final score...", 'warning');
    
    if (window.htmlEditor) window.htmlEditor.setOption('readOnly', true);
    if (window.cssEditor) window.cssEditor.setOption('readOnly', true);
    if (window.jsEditor) window.jsEditor.setOption('readOnly', true);
    
    const overlay = document.getElementById('editor-overlay');
    if (overlay) {
        overlay.classList.remove('hidden');
        const overlaySpan = overlay.querySelector('.overlay-content span');
        if (overlaySpan) overlaySpan.textContent = '🏁 Challenge ended!';
    }
    
    if (window.runDiffCheck) {
        window.runDiffCheck().then(() => {
            setTimeout(() => {
                window.location.href = `/results/${data.room_id}`;
            }, 3000);
        });
    }
});

// System announcement
socket.on('system_announcement', (data) => {
    console.log('📢 system_announcement:', data);
    showToast(`📢 ${data.message}`, 'info');
    appendChatMessage('ADMIN', data.message, true);
});

// Kicked
socket.on('kicked', (data) => {
    console.log('👢 kicked:', data);
    showToast(data.message || 'You were removed by the admin.', 'error');
    setTimeout(() => {
        window.location.href = '/dashboard';
    }, 2000);
});

// Player forfeit
socket.on('player_forfeit', (data) => {
    console.log('🏳️ player_forfeit:', data);
    showToast(`${data.username} forfeited!`, 'warning');
});

// Camera frame
socket.on('cam_frame', (data) => {
    const currentUser = document.getElementById('current-username')?.value;
    if (data.username === currentUser) return;
    
    const p1Name = document.getElementById('p1-username-data')?.value;
    const p2Name = document.getElementById('p2-username-data')?.value;
    
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

// Send chat message
function sendChatMessage() {
    const input = document.getElementById('chat-input');
    const message = input?.value.trim();
    if (!message) return;
    
    const roomId = document.getElementById('room-id')?.value;
    const username = document.getElementById('current-username')?.value;
    
    socket.emit('chat_message', {
        room_id: parseInt(roomId),
        username: username,
        message: message
    });
    
    input.value = '';
}

// Manual status check button
window.checkChallengeStatus = function() {
    const roomId = document.getElementById('room-id')?.value;
    if (roomId && socket) {
        console.log('Manual status check requested');
        socket.emit('check_challenge_status', { room_id: parseInt(roomId) });
        showToast('Checking challenge status...', 'info');
    }
};

// Setup chat input handler
document.addEventListener('DOMContentLoaded', () => {
    console.log('📄 DOM Content Loaded');
    
    const sendBtn = document.getElementById('send-chat');
    const chatInput = document.getElementById('chat-input');
    
    if (sendBtn) {
        sendBtn.addEventListener('click', sendChatMessage);
    }
    if (chatInput) {
        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendChatMessage();
        });
    }
    
    const shareBtn = document.getElementById('share-btn');
    if (shareBtn) {
        shareBtn.addEventListener('click', () => {
            const roomId = document.getElementById('room-id')?.value;
            if (roomId) {
                navigator.clipboard.writeText(`${window.location.origin}/arena/${roomId}`);
                showToast('Room link copied!', 'success');
            }
        });
    }
    
    const leaveBtn = document.getElementById('leave-room-btn');
    if (leaveBtn) {
        leaveBtn.addEventListener('click', () => {
            if (confirm('Leave this room?')) {
                const roomId = document.getElementById('room-id')?.value;
                const username = document.getElementById('current-username')?.value;
                socket.emit('leave_room', {
                    room_id: parseInt(roomId),
                    username: username
                });
                window.location.href = '/dashboard';
            }
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
        console.log('✅ Status check button added');
    }
}, 1000);