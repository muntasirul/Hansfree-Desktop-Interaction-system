/**
 * background.js — Extension Service Worker (fixed)
 *
 * Fixes:
 *  1. activeTabId is always refreshed from Chrome before every command
 *     so "new tab" then "search" correctly targets the NEW tab
 *  2. onUpdated fires for ALL tabs (not just activeTabId) so new tabs
 *     get numbered as soon as they finish loading
 *  3. new_tab now waits for the tab to be created, then updates activeTabId
 *     immediately so subsequent commands land on the right tab
 */

const WS_URL = 'ws://localhost:9765';
const RECONNECT_DELAY_MS = 2000;

let ws = null;
let connected = false;

// Always query Chrome for the real active tab — never trust a stale variable
async function getActiveTabId() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    return tab?.id ?? null;
}

// ── WebSocket connection ───────────────────────────────────────────────────

function connect() {
    try {
        ws = new WebSocket(WS_URL);
    } catch (e) {
        scheduleReconnect();
        return;
    }

    ws.onopen = () => {
        connected = true;
        console.log('[WebMode] Connected to Python server');
        sendToPython({ type: 'extension_connected', version: '1.0.0' });
        updateIcon(true);
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handlePythonMessage(msg);
        } catch (e) {
            console.error('[WebMode] Bad message from Python:', e);
        }
    };

    ws.onclose = () => {
        connected = false;
        updateIcon(false);
        scheduleReconnect();
    };

    ws.onerror = () => {
        connected = false;
        ws?.close();
    };
}

function scheduleReconnect() {
    setTimeout(connect, RECONNECT_DELAY_MS);
}

function sendToPython(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(data));
    }
}

// ── Handle commands from Python ───────────────────────────────────────────

async function handlePythonMessage(msg) {
    // Always get the REAL current tab fresh from Chrome
    const tabId = await getActiveTabId();
    if (!tabId) return;

    switch (msg.action) {

        case 'activate':
            await chrome.storage.local.set({ webmode_active: true });
            await sendToContent(tabId, { action: 'activate' });
            break;

        case 'deactivate':
            await chrome.storage.local.set({ webmode_active: false });
            await sendToContent(tabId, { action: 'deactivate' });
            break;

        case 'rescan':
            await sendToContent(tabId, { action: 'rescan' });
            break;

        case 'click':
            await sendToContent(tabId, { action: 'click', num: msg.num });
            break;

        case 'type':
            await sendToContent(tabId, { action: 'type', text: msg.text });
            break;

        case 'clear':
            await sendToContent(tabId, { action: 'clear' });
            break;

        case 'enter':
            await sendToContent(tabId, { action: 'enter' });
            break;

        case 'scroll':
            await sendToContent(tabId, { action: 'scroll', direction: msg.direction });
            break;

        case 'navigate':
            switch (msg.cmd) {
                case 'back':
                    await chrome.tabs.goBack(tabId);
                    break;
                case 'forward':
                    await chrome.tabs.goForward(tabId);
                    break;
                case 'refresh':
                    await chrome.tabs.reload(tabId);
                    break;

                case 'new_tab':
                    // Create tab, wait for it to be active, THEN tell Python
                    const newTab = await chrome.tabs.create({ active: true });
                    // Chrome sets it active immediately — confirm with a query
                    await chrome.tabs.update(newTab.id, { active: true });
                    sendToPython({ type: 'new_tab_opened', tabId: newTab.id });
                    break;

                case 'next_tab':
                    const tabs = await chrome.tabs.query({ currentWindow: true });
                    const cur = tabs.findIndex(t => t.active);
                    const nxt = tabs[(cur + 1) % tabs.length];
                    if (nxt) await chrome.tabs.update(nxt.id, { active: true });
                    break;
                case 'prev_tab':
                    const tabs2 = await chrome.tabs.query({ currentWindow: true });
                    const cur2 = tabs2.findIndex(t => t.active);
                    const prv = tabs2[(cur2 - 1 + tabs2.length) % tabs2.length];
                    if (prv) await chrome.tabs.update(prv.id, { active: true });
                    break;
                case 'close_tab':
                    await chrome.tabs.remove(tabId);
                    sendToPython({ type: 'tab_closed' });
                    break;

                case 'top':
                case 'bottom':
                    await sendToContent(tabId, { action: 'navigate', cmd: msg.cmd });
                    break;
            }
            break;

        case 'open_url':
            // Always open in the CURRENT active tab (which is correct after new_tab)
            await chrome.tabs.update(tabId, { url: msg.url });
            sendToPython({ type: 'navigating_to', url: msg.url });
            break;

        case 'get_url':
            const tab = await chrome.tabs.get(tabId);
            sendToPython({ type: 'current_url', url: tab.url, title: tab.title });
            break;

        case 'media_toggle':
            await sendToContent(tabId, { action: 'media_toggle' });
            break;

        case 'media_mute':
            await sendToContent(tabId, { action: 'media_mute' });
            break;

        case 'media_vol':
            await sendToContent(tabId, { action: 'media_vol', direction: msg.direction });
            break;

        case 'media_fullscreen':
            await sendToContent(tabId, { action: 'media_fullscreen' });
            break;

        case 'media_reveal':
            await sendToContent(tabId, { action: 'media_reveal' });
            break;

        case 'ping':
            sendToPython({ type: 'pong', connected: true });
            break;
    }
}

// ── Content script helper ─────────────────────────────────────────────────

async function sendToContent(tabId, msg) {
    try {
        return await chrome.tabs.sendMessage(tabId, { target: 'content', ...msg });
    } catch (e) {
        // Content script not injected yet (new tab, chrome:// page, etc.) — inject it
        try {
            await chrome.scripting.executeScript({
                target: { tabId },
                files: ['content.js'],
            });
            // Small delay so the script initialises
            await new Promise(r => setTimeout(r, 150));
            return await chrome.tabs.sendMessage(tabId, { target: 'content', ...msg });
        } catch (e2) {
            console.warn('[WebMode] Could not reach content script in tab', tabId, e2.message);
        }
    }
}

// ── Relay content → Python ────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender) => {
    if (msg.source === 'content') {
        sendToPython(msg);
    }
});

// ── Tab events ────────────────────────────────────────────────────────────

// User switched to a different tab
chrome.tabs.onActivated.addListener(async ({ tabId }) => {
    try {
        const tab = await chrome.tabs.get(tabId);
        sendToPython({ type: 'tab_changed', url: tab.url, title: tab.title });
    } catch (_) { }

    // Re-activate web mode labels in the newly focused tab
    const { webmode_active } = await chrome.storage.local.get('webmode_active');
    if (webmode_active) {
        // Small delay so the page is ready
        setTimeout(() => sendToContent(tabId, { action: 'activate' }), 300);
    }
});

// Page finished loading — re-scan regardless of which tab it is
// This is the key fix: we do NOT check tabId === activeTabId
// because new tabs are active but our cached value may lag
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
    if (changeInfo.status !== 'complete') return;

    // Skip internal Chrome pages
    if (!tab.url || tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://')) {
        return;
    }

    sendToPython({ type: 'page_loaded', url: tab.url, title: tab.title });

    const { webmode_active } = await chrome.storage.local.get('webmode_active');
    if (webmode_active) {
        // Wait for page JS to settle, then inject labels
        setTimeout(() => sendToContent(tabId, { action: 'activate' }), 600);
    }
});

// ── Extension icon ────────────────────────────────────────────────────────

function updateIcon(isConnected) {
    chrome.action.setBadgeText({ text: isConnected ? 'ON' : '' });
    chrome.action.setBadgeBackgroundColor({
        color: isConnected ? '#00d4ff' : '#f85149'
    });
}

// ── Boot ──────────────────────────────────────────────────────────────────

connect();