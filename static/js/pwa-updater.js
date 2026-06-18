(function () {
    const VERSION_URL = '/pwa/version.json';
    const HEALTH_URL = '/pwa/health';
    const SW_URL = '/service-worker.js';
    const CLIENT_ID_KEY = 'uibaPwaClientId';
    const ACTIVE_VERSION_KEY = 'uibaPwaActiveVersion';
    const LATER_VERSION_KEY = 'uibaPwaLaterVersion';
    const LATER_AT_KEY = 'uibaPwaLaterAt';
    const PENDING_VERSION_KEY = 'uibaPwaPendingVersion';
    const LAST_CHECK_KEY = 'uibaPwaLastCheckAt';
    const INSTALL_DISMISSED_KEY = 'uibaPwaInstallDismissedAt';
    const DEFAULT_CHECK_INTERVAL = 15 * 60 * 1000;
    const INSTALL_DISMISS_MS = 7 * 24 * 60 * 60 * 1000;
    const UPDATE_SNOOZE_MS = 12 * 60 * 60 * 1000;

    let registration = null;
    let latestRelease = null;
    let updatePanel = null;
    let installPanel = null;
    let statusPanel = null;
    let statusButton = null;
    let installPromptEvent = null;
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
            id = (window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`).replace(/[^a-zA-Z0-9-]/g, '');
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
        const laterAt = Number(storageGet(LATER_AT_KEY, '0'));
        if (storageGet(LATER_VERSION_KEY) === release.version && Date.now() - laterAt < UPDATE_SNOOZE_MS) return false;
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

    function isHomePage() {
        return window.location.pathname === '/' || document.querySelector('.home-page');
    }

    function isInstalledDisplayMode() {
        return window.matchMedia?.('(display-mode: standalone)').matches || window.navigator.standalone === true;
    }

    function redirectStandaloneHomeToApp() {
        if (!isInstalledDisplayMode()) return;
        if (window.location.pathname === '/') {
            window.location.replace('/app');
        }
    }

    function installDismissedRecently() {
        const dismissedAt = Number(storageGet(INSTALL_DISMISSED_KEY, '0'));
        return dismissedAt && Date.now() - dismissedAt < INSTALL_DISMISS_MS;
    }

    function syncInstallButtons() {
        const canInstall = Boolean(installPromptEvent) && !isInstalledDisplayMode();
        document.querySelectorAll('[data-pwa-install]').forEach((button) => {
            button.hidden = !canInstall;
            button.disabled = !canInstall;
            if (!button.dataset.pwaInstallBound) {
                button.dataset.pwaInstallBound = 'true';
                button.addEventListener('click', installApp);
            }
        });
    }

    function ensureInstallPanel() {
        if (installPanel) return installPanel;
        installPanel = document.createElement('section');
        installPanel.className = 'pwa-install-panel';
        installPanel.setAttribute('role', 'dialog');
        installPanel.setAttribute('aria-live', 'polite');
        installPanel.hidden = true;
        document.body.appendChild(installPanel);
        return installPanel;
    }

    function showInstallPanel() {
        if (!installPromptEvent || !isHomePage() || isInstalledDisplayMode() || installDismissedRecently()) return;
        const panel = ensureInstallPanel();
        panel.innerHTML = `
            <div class="pwa-install-head">
                <div>
                    <span class="pwa-install-kicker"><i class="fas fa-desktop"></i> Desktop app</span>
                    <h3>Install UI Battle Arena</h3>
                </div>
                <button class="pwa-install-close" type="button" aria-label="Dismiss install prompt">
                    <i class="fas fa-times"></i>
                </button>
            </div>
            <p class="pwa-install-copy">Add the arena to your desktop for a faster app-style launch, background updates, and release notes after deployments.</p>
            <div class="pwa-install-actions">
                <button class="pwa-install-later" type="button">Later</button>
                <button class="pwa-install-now" type="button"><i class="fas fa-download"></i> Install app</button>
            </div>
        `;
        panel.hidden = false;
        requestAnimationFrame(() => panel.classList.add('is-visible'));
        panel.querySelector('.pwa-install-close')?.addEventListener('click', dismissInstallPrompt);
        panel.querySelector('.pwa-install-later')?.addEventListener('click', dismissInstallPrompt);
        panel.querySelector('.pwa-install-now')?.addEventListener('click', installApp);
    }

    function hideInstallPanel() {
        if (!installPanel) return;
        installPanel.classList.remove('is-visible');
        setTimeout(() => {
            if (installPanel) installPanel.hidden = true;
        }, 220);
    }

    function dismissInstallPrompt() {
        storageSet(INSTALL_DISMISSED_KEY, String(Date.now()));
        hideInstallPanel();
    }

    async function installApp() {
        if (!installPromptEvent) return;
        const promptEvent = installPromptEvent;
        installPromptEvent = null;
        hideInstallPanel();
        syncInstallButtons();
        try {
            await promptEvent.prompt();
            const choice = await promptEvent.userChoice;
            if (choice?.outcome === 'accepted') {
                storageRemove(INSTALL_DISMISSED_KEY);
                if (window.showToast) showToast('UI Battle Arena is installing.', 'success');
            } else {
                dismissInstallPrompt();
            }
        } catch (error) {
            if (window.showToast) showToast('Install prompt is unavailable in this browser right now.', 'warning');
        }
    }

    function showUpdatePanel(release) {
        latestRelease = release;
        const panel = ensurePanel();
        const releaseTitle = release.release_name || release.version || '';
        const releaseDescription = release.release_description || 'A new version is ready. The app has been improved and can refresh when you choose.';
        const backupWarning = release.backup_warning || 'Before updating, back up anything important and save active work.';
        panel.innerHTML = `
            <div class="pwa-update-head">
                <div>
                    <span class="pwa-update-kicker">Update available</span>
                    <h3>${escapeText(releaseTitle)}</h3>
                </div>
                <button class="pwa-update-close" type="button" aria-label="Dismiss update for now">
                    <i class="fas fa-times"></i>
                </button>
            </div>
            <p class="pwa-update-copy">${escapeText(releaseDescription)}</p>
            <p class="pwa-update-copy"><strong>Back up first:</strong> ${escapeText(backupWarning)}</p>
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

    function ensureStatusButton() {
        if (statusButton || !isInstalledDisplayMode()) return statusButton;
        statusButton = document.createElement('button');
        statusButton.className = 'pwa-app-status-btn';
        statusButton.type = 'button';
        statusButton.innerHTML = '<i class="fas fa-cloud-arrow-down"></i><span>Updates</span>';
        statusButton.setAttribute('aria-label', 'Open app update status');
        statusButton.addEventListener('click', showStatusPanel);
        document.body.appendChild(statusButton);
        return statusButton;
    }

    function ensureStatusPanel() {
        if (statusPanel) return statusPanel;
        statusPanel = document.createElement('section');
        statusPanel.className = 'pwa-status-panel';
        statusPanel.setAttribute('role', 'dialog');
        statusPanel.hidden = true;
        document.body.appendChild(statusPanel);
        return statusPanel;
    }

    function showStatusPanel() {
        const panel = ensureStatusPanel();
        const active = escapeText(currentVersion() || 'Installed');
        const latest = escapeText(latestRelease?.version || active);
        const released = escapeText(latestRelease?.released_at || 'Latest deployed release');
        panel.innerHTML = `
            <div class="pwa-install-head">
                <div>
                    <span class="pwa-install-kicker"><i class="fas fa-desktop"></i> App version</span>
                    <h3>UI Battle Arena</h3>
                </div>
                <button class="pwa-install-close" type="button" aria-label="Close update status">
                    <i class="fas fa-times"></i>
                </button>
            </div>
            <div class="pwa-status-body">
                <div><span>Current</span><strong>${active}</strong></div>
                <div><span>Latest</span><strong>${latest}</strong></div>
                <p>${released}</p>
            </div>
            <div class="pwa-install-actions">
                <button class="pwa-install-later" type="button">Close</button>
                <button class="pwa-install-now" type="button"><i class="fas fa-rotate"></i> Check for updates</button>
            </div>
        `;
        panel.hidden = false;
        requestAnimationFrame(() => panel.classList.add('is-visible'));
        panel.querySelector('.pwa-install-close')?.addEventListener('click', hideStatusPanel);
        panel.querySelector('.pwa-install-later')?.addEventListener('click', hideStatusPanel);
        panel.querySelector('.pwa-install-now')?.addEventListener('click', async () => {
            panel.querySelector('.pwa-install-now').disabled = true;
            await checkForUpdates(true, true);
            hideStatusPanel();
        });
    }

    function hideStatusPanel() {
        if (!statusPanel) return;
        statusPanel.classList.remove('is-visible');
        setTimeout(() => {
            if (statusPanel) statusPanel.hidden = true;
        }, 220);
    }

    function dismissUpdate() {
        if (latestRelease?.version) storageSet(LATER_VERSION_KEY, latestRelease.version);
        storageSet(LATER_AT_KEY, String(Date.now()));
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
        const backupWarning = latestRelease.backup_warning || 'Before updating, back up anything important and save active work.';
        if (!window.confirm(`Update to ${latestRelease.release_name || latestRelease.version}?\n\n${backupWarning}`)) return;
        storageSet(PENDING_VERSION_KEY, latestRelease.version);
        storageRemove(LATER_VERSION_KEY);
        storageRemove(LATER_AT_KEY);
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

    async function checkForUpdates(force = false, userInitiated = false) {
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
            } else if (userInitiated && window.showToast) {
                showToast('You are already on the latest version.', 'success');
            }
        } catch (error) {
            if (userInitiated && window.showToast) showToast('Could not check for updates. Try again when you are online.', 'error');
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
            ensureStatusButton();
        } catch (error) {
            // PWA support is a progressive enhancement.
        }
    }

    window.addEventListener('beforeinstallprompt', (event) => {
        event.preventDefault();
        installPromptEvent = event;
        syncInstallButtons();
        setTimeout(showInstallPanel, 900);
    });

    window.addEventListener('appinstalled', () => {
        installPromptEvent = null;
        storageRemove(INSTALL_DISMISSED_KEY);
        hideInstallPanel();
        syncInstallButtons();
        if (window.showToast) showToast('UI Battle Arena installed. Future updates will appear here.', 'success');
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            redirectStandaloneHomeToApp();
            syncInstallButtons();
            initPwaUpdater();
        });
    } else {
        redirectStandaloneHomeToApp();
        syncInstallButtons();
        initPwaUpdater();
    }
})();
