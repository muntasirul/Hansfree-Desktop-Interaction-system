/**
 * popup.js — Extension Popup Script
 * Shows connection status and active state.
 */

const dot = document.getElementById('statusDot');
const text = document.getElementById('statusText');

// Ask background if WS is connected
chrome.runtime.sendMessage({ action: 'ping', target: 'background' }, (response) => {
    if (chrome.runtime.lastError || !response) {
        dot.classList.remove('connected');
        text.innerHTML = '<strong>Disconnected</strong> — start python main.py';
        return;
    }

    if (response.connected) {
        dot.classList.add('connected');
        text.innerHTML = '<strong>Connected</strong> to Python server';
    } else {
        dot.classList.remove('connected');
        text.innerHTML = '<strong>Waiting</strong> for Python server...';
    }
});