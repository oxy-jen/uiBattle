(function () {
    const VERSION_URL = '/pwa/version.json';
    const HEALTH_URL = '/pwa/health';
    const SW_URL = '/service-worker.js';
    const CLIENT_ID_KEY = 'uibaPwaClientId';
    const ACTIVE_VERSION_KEY = 'uibaPwaActiveVersion';
    const LATER_VERSION_KEY = 'uibaPwaLaterVersion';
    const PENDING_VERSION_KEY = 'uibaPwaPendingVersion';
    const LAST_CHECK_KEY = 'uibaPwaLastCheckAt';
    const DEFAULT_CHECK_INTERVAL = 15 * 60 * 1000;

    let registration = null;
    let latestRelease = null;
    let updatePanel = null;
    let controllerReloading = false;

    function supportsPwaUpdates() {
        return 'serviceWorker' in navigator && window.isSecureContext;
    }

    function storageGet(key, fallback = '') {
        try {
            return localStorage.getItem(key) || fallback;
        } catch (error) {
            return fallback;
        }
    }

    function storageSet(key, value) {
        try {
            localStorage.setItem(key, value);
        } catch (error) {}
    }

    function storageRemove(key) {
        try {
            localStorage.removeItem(key);
        } catch (error) {}
    }

    function clientId() {
        let id = storageGet(CLIENT_ID_KEY);
        if (!id) {
            id = (crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`).replace(/[^a-zA-Z0-9-]/g, '');
            storageSet(CLIENT_ID_KEY, id);
        }
        return id;
    }

    function rolloutBucket(id) {
        let hash = 0;
        for (let i = 0; i < id.length; i += 1) {
            hash = ((hash << 5) - hash + id.charCodeAt(i)) | 0;
        }
        return Math.abs(hash) % 100;
    }

    function isInRollout(release) {
        const percent = Number(release?.rollout_percent ?? 100);
        return percent >= 100 || rolloutBucket(clientId()) < Math.max(0, Math.min(100, percent));
    }

    async function fetchRelease() {
        const response = await fetch(`${VERSION_URL}?t=${Date.now()}`, {
            cache: 'no-store',
            headers: {'Accept': 'application/json'}
        });
        if (!response.ok) throw new Error(`Version check failed: ${response.status}`);
        return response.json();
    }

    function currentVersion() {
        return storageGet(ACTIVE_VERSION_KEY);
    }

    function shouldShowUpdate(release) {
        if (!release?.version || !isInRollout(release)) return false;
        if (storageGet(LATER_VERSION_KEY) === release.version) return false;
        return currentVersion() && currentVersion() !== release.version;
    }

    function markCurrentVersion(release) {
        if (release?.version && !currentVersion()) {
            storageSet(ACTIVE_VERSION_KEY, release.version);
        }
    }

    function changelogHtml(changelog) {
        const groups = Array.isArray(changelog) ? changelog : [];
        if (!groups.length) {
            return '<div class="pwa-update-empty">No release notes were provided for this update.</div>';
        }
        return groups.map((group) => {
            const title = escapeText(group.type || 'Updates');
            const items = Array.isArray(group.items) ? group.items : [];
            return `
                <section class="pwa-update-change-group">
                    <h4>${title}</h4>
                    <ul>
                        ${items.map((item) => `<li>${escapeText(item)}</li>`).join('')}
                    </ul>
                </section>
            `;
        }).join('');
    }

    function escapeText(value) {
        const div = document.createElement('div');
        div.textContent = String(value || '');
        return div.innerHTML;
    }

    function ensurePanel() {
        if (updatePanel) return updatePanel;
        updatePanel = document.createElement('section');
        updatePanel.className = 'pwa-update-panel';
        updatePanel.setAttribute('role', 'status');
        updatePanel.setAttribute('aria-live', 'polite');
        updatePanel.hidden = true;
        document.body.appendChild(updatePanel);
        return updatePanel;
    }

    function showUpdatePanel(release) {
        latestRelease = release;
        const panel = ensurePanel();
        panel.innerHTML = `
            <div class="pwa-update-head">
                <div>
                    <span class="pwa-update-kicker">Update available</span>
                    <h3>UI Battle Arena ${escapeText(release.version || '')}</h3>
                </div>
                <button class="pwa-update-close" type="button" aria-label="Dismiss update for now">
                    <i class="fas fa-times"></i>
                </button>
            </div>
            <p class="pwa-update-copy">A new version is ready. The app has been improved and can refresh safely when you choose.</p>
            <div class="pwa-update-changelog" aria-label="What's new">
                <strong>What's new</strong>
                ${changelogHtml(release.changelog)}
            </div>
            <div class="pwa-update-actions">
                <button class="pwa-update-later" type="button">Later</button>
                <button class="pwa-update-now" type="button"><i class="fas fa-rotate"></i> Update now</button>
            </div>
        `;
        panel.hidden = false;
        requestAnimationFrame(() => panel.classList.add('is-visible'));
        panel.querySelector('.pwa-update-close')?.addEventListener('click', dismissUpdate);
        panel.querySelector('.pwa-update-later')?.addEventListener('click', dismissUpdate);
        panel.querySelector('.pwa-update-now')?.addEventListener('click', activateUpdate);
    }

    function dismissUpdate() {
        if (latestRelease?.version) storageSet(LATER_VERSION_KEY, latestRelease.version);
        hidePanel();
    }

    function hidePanel() {
        if (!updatePanel) return;
        updatePanel.classList.remove('is-visible');
        setTimeout(() => {
            if (updatePanel) updatePanel.hidden = true;
        }, 220);
    }

    async function clearPwaCaches() {
        if (!window.caches?.keys) return;
        const names = await caches.keys();
        await Promise.all(
            names
                .filter((name) => name.startsWith('uiba-pwa'))
                .map((name) => caches.delete(name))
        );
    }

    async function activateUpdate() {
        if (!latestRelease?.version) return;
        storageSet(PENDING_VERSION_KEY, latestRelease.version);
        storageRemove(LATER_VERSION_KEY);
        hidePanel();
        if (window.showToast) showToast('Updating UI Battle Arena...', 'info');

        try {
            await clearPwaCaches();
            await registration?.update?.();
            const waitingWorker = registration?.waiting || registration?.installing;
            if (waitingWorker) {
                waitingWorker.postMessage({type: 'UIBA_ACTIVATE_UPDATE'});
            } else if (navigator.serviceWorker.controller) {
                navigator.serviceWorker.controller.postMessage({type: 'UIBA_CLEAR_CACHES'});
                window.location.reload();
            } else {
                window.location.reload();
            }
            setTimeout(() => {
                if (!controllerReloading) window.location.reload();
            }, 1600);
        } catch (error) {
            storageRemove(PENDING_VERSION_KEY);
            if (window.showToast) showToast('Update could not start. Keep using this version and try again later.', 'error');
        }
    }

    async function rollbackIfHealthCheckFails() {
        const pendingVersion = storageGet(PENDING_VERSION_KEY);
        if (!pendingVersion) return;
        try {
            const response = await fetch(`${HEALTH_URL}?t=${Date.now()}`, {cache: 'no-store'});
            const health = await response.json();
            if (!response.ok || !health.ok) throw new Error('Health check failed');
            storageSet(ACTIVE_VERSION_KEY, health.version || pendingVersion);
            storageRemove(PENDING_VERSION_KEY);
            if (window.showToast) showToast('App updated successfully.', 'success');
        } catch (error) {
            storageRemove(PENDING_VERSION_KEY);
            await clearPwaCaches();
            const regs = await navigator.serviceWorker.getRegistrations();
            await Promise.all(regs.map((reg) => reg.unregister()));
            if (window.showToast) showToast('Update rollback started. Reloading stable network copy.', 'warning');
            setTimeout(() => window.location.reload(), 800);
        }
    }

    function listenForWorker(reg) {
        reg.addEventListener('updatefound', () => {
            const worker = reg.installing;
            if (!worker) return;
            worker.addEventListener('statechange', () => {
                if (worker.state === 'installed' && navigator.serviceWorker.controller && latestRelease && shouldShowUpdate(latestRelease)) {
                    showUpdatePanel(latestRelease);
                }
            });
        });
    }

    async function checkForUpdates(force = false) {
        if (!supportsPwaUpdates()) return;
        const now = Date.now();
        const interval = Number(latestRelease?.update_check_interval_ms || DEFAULT_CHECK_INTERVAL);
        const lastCheck = Number(storageGet(LAST_CHECK_KEY, '0'));
        if (!force && now - lastCheck < interval) return;
        storageSet(LAST_CHECK_KEY, String(now));

        try {
            const release = await fetchRelease();
            latestRelease = release;
            markCurrentVersion(release);
            await registration?.update?.();
            if (shouldShowUpdate(release)) {
                showUpdatePanel(release);
            }
        } catch (error) {
            // Update checks must never interrupt the app.
        }
    }

    async function initPwaUpdater() {
        if (!supportsPwaUpdates()) return;
        try {
            registration = await navigator.serviceWorker.register(SW_URL, {scope: '/'});
            listenForWorker(registration);
            navigator.serviceWorker.addEventListener('controllerchange', () => {
                if (controllerReloading) return;
                controllerReloading = true;
                window.location.reload();
            });
            await rollbackIfHealthCheckFails();
            await checkForUpdates(true);
            setInterval(() => checkForUpdates(false), DEFAULT_CHECK_INTERVAL);
            document.addEventListener('visibilitychange', () => {
                if (!document.hidden) checkForUpdates(false);
            });
            window.addEventListener('online', () => checkForUpdates(true));
        } catch (error) {
            // PWA support is a progressive enhancement.
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPwaUpdater);
    } else {
        initPwaUpdater();
    }
})();
