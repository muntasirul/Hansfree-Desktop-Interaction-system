/**
 * content.js — Web Mode Content Script (v3)
 *
 * Fixes:
 *  1. Browser UI (tabs, back, reload) handled via voice commands to Python
 *     since Chrome extensions cannot label native browser chrome
 *  2. Scroll-stable badges — reposition on scroll without full rescan
 *  3. Better click: tries multiple strategies (click, mousedown/up, dispatch)
 *  4. Pause/Play detection for media elements (video/audio)
 *  5. Labels media controls specifically so pause/play are always numbered
 */

(() => {
    'use strict';

    let labelElements = [];
    let targetElements = [];
    let isActive = false;
    let container = null;
    let mutationTimer = null;
    let scrollTimer = null;
    let isTypingMode = false;
    let typingTarget = null;

    // ── Selectors — media controls included explicitly ────────────────────────
    const CLICKABLE_SELECTORS = [
        'a[href]',
        'button',
        'input:not([type="hidden"])',
        'select',
        'textarea',
        '[role="button"]',
        '[role="link"]',
        '[role="menuitem"]',
        '[role="tab"]',
        '[role="checkbox"]',
        '[role="radio"]',
        '[role="combobox"]',
        '[role="option"]',
        '[role="slider"]',
        '[onclick]',
        '[tabindex]:not([tabindex="-1"])',
        'summary',
        // YouTube / media specific
        '.ytp-play-button',
        '.ytp-mute-button',
        '.ytp-fullscreen-button',
        '.ytp-settings-button',
        'video',
        'audio',
        '[data-testid]',
        '[aria-label]',
    ].join(',');

    // ── Styles ────────────────────────────────────────────────────────────────
    function injectStyles() {
        if (document.getElementById('__wm_styles__')) return;
        const s = document.createElement('style');
        s.id = '__wm_styles__';
        s.textContent = `
      #__wm_container__ {
        position: fixed; top:0; left:0;
        width:0; height:0;
        z-index: 2147483647;
        pointer-events: none;
      }
      .wm-badge {
        position: fixed;
        min-width: 20px; height: 20px;
        padding: 0 4px;
        background: #0d1117;
        color: #00d4ff;
        border: 1.5px solid #00d4ff;
        border-radius: 3px;
        font-family: 'Courier New', monospace;
        font-size: 11px; font-weight: 700;
        line-height: 18px; text-align: center;
        pointer-events: none;
        box-shadow: 0 0 8px rgba(0,212,255,.55), 0 1px 3px rgba(0,0,0,.8);
        z-index: 2147483647;
        white-space: nowrap; user-select: none;
      }
      .wm-badge.wm-input {
        background:#0d1a0d; color:#00ff88; border-color:#00ff88;
        box-shadow: 0 0 8px rgba(0,255,136,.55), 0 1px 3px rgba(0,0,0,.8);
      }
      .wm-badge.wm-link {
        background:#1a0d2e; color:#cc88ff; border-color:#cc88ff;
        box-shadow: 0 0 8px rgba(204,136,255,.55), 0 1px 3px rgba(0,0,0,.8);
      }
      .wm-badge.wm-media {
        background:#1a1a00; color:#ffdd00; border-color:#ffdd00;
        box-shadow: 0 0 8px rgba(255,220,0,.55), 0 1px 3px rgba(0,0,0,.8);
      }
      .wm-badge.wm-highlight {
        background:#ff6600 !important; color:#fff !important;
        border-color:#ff9900 !important;
        box-shadow: 0 0 16px rgba(255,102,0,.9) !important;
        transform: scale(1.3);
      }
      /* Browser UI hint bar — shown at TOP of page */
      #__wm_topbar__ {
        position: fixed; top:0; left:0; right:0; height:36px;
        background: rgba(8,12,18,.95);
        border-bottom: 1.5px solid #00d4ff;
        display: flex; align-items: center;
        padding: 0 12px; gap: 10px;
        font-family: 'Courier New', monospace; font-size: 11px;
        color: #00d4ff; pointer-events: none;
        z-index: 2147483646;
        backdrop-filter: blur(6px);
      }
      .wm-nav-hint {
        background: #0d1a0d; color: #00ff88;
        border: 1px solid #00ff88; border-radius: 3px;
        padding: 1px 7px; font-size: 10px; font-weight: 700;
      }
      /* Status bar at bottom */
      #__wm_statusbar__ {
        position: fixed; bottom:0; left:0; right:0; height:28px;
        background: rgba(8,12,18,.93);
        border-top: 1px solid #00d4ff;
        display: flex; align-items: center;
        padding: 0 12px; gap: 10px;
        font-family: 'Courier New', monospace; font-size: 11px;
        color: #00d4ff; pointer-events: none;
        z-index: 2147483646; backdrop-filter: blur(6px);
      }
      #__wm_pulse__ {
        width:7px; height:7px; border-radius:50%;
        background:#00ff88;
        animation: wm-pulse 1.2s ease-in-out infinite;
        flex-shrink:0;
      }
      @keyframes wm-pulse {
        0%,100%{opacity:1;transform:scale(1)}
        50%{opacity:.4;transform:scale(.75)}
      }
    `;
        document.head.appendChild(s);
    }

    // ── Activate / Deactivate ─────────────────────────────────────────────────

    function activate() {
        injectStyles();
        createContainer();
        if (!isActive) {
            isActive = true;
            observeMutations();
            observeScroll();
            showBars();
        }
        scan();
        notifyPython({ type: 'activated', url: location.href, title: document.title });
    }

    function deactivate() {
        isActive = false;
        clearBadges();
        removeBars();
        if (observer) { observer.disconnect(); observer = null; }
        notifyPython({ type: 'deactivated' });
    }

    function createContainer() {
        if (container && document.contains(container)) return;
        container = document.createElement('div');
        container.id = '__wm_container__';
        document.documentElement.appendChild(container);
    }

    // ── Scan ──────────────────────────────────────────────────────────────────

    function scan() {
        clearBadges();
        createContainer();

        const seen = new Set();
        // Use a Set to deduplicate overlapping selectors
        const allNodes = new Set(document.querySelectorAll(CLICKABLE_SELECTORS));
        let idx = 1;

        allNodes.forEach(el => {
            if (seen.has(el)) return;
            if (!isVisible(el)) return;
            seen.add(el);

            const rect = el.getBoundingClientRect();
            if (rect.width < 4 || rect.height < 4) return;

            const badge = document.createElement('div');
            badge.className = 'wm-badge ' + getBadgeClass(el);
            badge.textContent = String(idx);

            // Position badge just ABOVE the element so it doesn't cover content.
            // If too close to top edge, place it just below the element instead.
            const bLeft = Math.min(Math.max(rect.left, 2), window.innerWidth - 28);
            let bTop;
            if (rect.top > 22) {
                bTop = rect.top - 20;   // above element
            } else {
                bTop = rect.bottom + 2; // below element if near top of screen
            }
            bTop = Math.min(bTop, window.innerHeight - 22);
            badge.style.left = bLeft + 'px';
            badge.style.top = bTop + 'px';

            container.appendChild(badge);
            targetElements.push(el);
            labelElements.push(badge);
            idx++;
        });

        updateStatus(`${targetElements.length} elements labeled`);

        notifyPython({
            type: 'scan_complete',
            count: targetElements.length,
            url: location.href,
            title: document.title,
            elements: targetElements.map((el, i) => ({
                index: i + 1,
                tag: el.tagName.toLowerCase(),
                type: el.type || '',
                text: getLabel(el),
                isInput: isInputEl(el),
                isMedia: isMediaEl(el),
            }))
        });
    }

    function clearBadges() {
        if (container) container.innerHTML = '';
        labelElements = [];
        targetElements = [];
    }

    // Reposition badges without re-querying DOM (fast, called on scroll)
    function repositionBadges() {
        targetElements.forEach((el, i) => {
            const badge = labelElements[i];
            if (!badge) return;
            const rect = el.getBoundingClientRect();
            if (!isVisible(el) || rect.width < 4) {
                badge.style.display = 'none';
                return;
            }
            badge.style.display = '';
            const rLeft = Math.min(Math.max(rect.left, 2), window.innerWidth - 28);
            let rTop;
            if (rect.top > 22) {
                rTop = rect.top - 20;
            } else {
                rTop = rect.bottom + 2;
            }
            rTop = Math.min(rTop, window.innerHeight - 22);
            badge.style.left = rLeft + 'px';
            badge.style.top = rTop + 'px';
        });
    }

    // ── Click ─────────────────────────────────────────────────────────────────

    function clickElement(num) {
        const idx = parseInt(num, 10) - 1;
        if (idx < 0 || idx >= targetElements.length) {
            notifyPython({ type: 'error', message: `No element #${num}` });
            updateStatus(`⚠ No element #${num} — try "rescan"`);
            return;
        }

        const el = targetElements[idx];
        const badge = labelElements[idx];

        // Flash
        badge.classList.add('wm-highlight');
        setTimeout(() => badge.classList.remove('wm-highlight'), 500);

        el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

        // ── Media element (video/audio) — toggle play/pause directly ──────────
        if (el.tagName === 'VIDEO' || el.tagName === 'AUDIO') {
            if (el.paused) { el.play(); updateStatus('▶ Playing media'); }
            else { el.pause(); updateStatus('⏸ Paused media'); }
            notifyPython({ type: 'media_toggled', paused: el.paused });
            return;
        }

        // ── Input element — enter typing mode ─────────────────────────────────
        if (isInputEl(el)) {
            el.focus();
            isTypingMode = true;
            typingTarget = el;
            updateStatus(`⌨ Speak to type into: ${getLabel(el).slice(0, 40)}`);
            notifyPython({ type: 'typing_mode_entered', element: getLabel(el) });
            return;
        }

        // ── Regular element — try multiple click strategies ────────────────────
        el.focus();
        try { el.click(); } catch (_) { }

        // Fallback: dispatch mouse events (needed for React/Vue apps)
        try {
            const center = {
                clientX: el.getBoundingClientRect().left + el.offsetWidth / 2,
                clientY: el.getBoundingClientRect().top + el.offsetHeight / 2,
                bubbles: true, cancelable: true
            };
            el.dispatchEvent(new MouseEvent('mousedown', center));
            el.dispatchEvent(new MouseEvent('mouseup', center));
            el.dispatchEvent(new MouseEvent('click', center));
        } catch (_) { }

        updateStatus(`✓ Clicked #${num}: ${getLabel(el).slice(0, 40)}`);
        notifyPython({ type: 'clicked', element: getLabel(el) });
        setTimeout(() => { if (isActive) scan(); }, 900);
    }

    // ── Type ──────────────────────────────────────────────────────────────────

    function typeText(text) {
        const el = typingTarget || document.activeElement;
        if (!el) return;

        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            el.focus();
            const proto = el.tagName === 'INPUT'
                ? window.HTMLInputElement.prototype
                : window.HTMLTextAreaElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            if (setter) {
                setter.call(el, el.value + text);
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            } else {
                el.value += text;
            }
        } else if (el.isContentEditable) {
            document.execCommand('insertText', false, text);
        }

        updateStatus(`⌨ Typed: "${text.slice(0, 40)}"`);
        notifyPython({ type: 'typed', text });
    }

    function clearInput() {
        const el = typingTarget || document.activeElement;
        if (!el) return;
        const setter = Object.getOwnPropertyDescriptor(
            el.tagName === 'TEXTAREA'
                ? window.HTMLTextAreaElement.prototype
                : window.HTMLInputElement.prototype,
            'value'
        )?.set;
        if (setter) { setter.call(el, ''); el.dispatchEvent(new Event('input', { bubbles: true })); }
        else if (el.value !== undefined) el.value = '';
    }

    function pressEnter() {
        const el = typingTarget || document.activeElement;
        if (el) {
            ['keydown', 'keypress', 'keyup'].forEach(t =>
                el.dispatchEvent(new KeyboardEvent(t, {
                    key: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true
                }))
            );
            el.closest('form')?.requestSubmit?.();
        }
        isTypingMode = false;
        typingTarget = null;
        updateStatus('↩ Enter pressed');
        setTimeout(() => { if (isActive) scan(); }, 1000);
        notifyPython({ type: 'enter_pressed' });
    }

    // ── Media control helpers (called from Python via voice) ──────────────────

    function toggleMedia() {
        // Strategy 1: Direct JS API — works even when controls are hidden
        const media = [...document.querySelectorAll('video, audio')]
            .find(m => m.readyState > 0);

        if (media) {
            if (media.paused) {
                media.play();
                updateStatus('▶ Playing');
                notifyPython({ type: 'media_toggled', paused: false });
            } else {
                media.pause();
                updateStatus('⏸ Paused');
                notifyPython({ type: 'media_toggled', paused: true });
            }
            return;
        }

        // Strategy 2: Spacebar on the page body (YouTube keyboard shortcut)
        // Works as fallback if video element is inside an iframe
        const target = document.activeElement || document.body;
        target.dispatchEvent(new KeyboardEvent('keydown', {
            key: ' ', keyCode: 32, which: 32, bubbles: true, cancelable: true
        }));
        updateStatus('⏸ Space pressed (pause/play)');
        notifyPython({ type: 'media_toggled', paused: null });
    }

    // Reveal hidden player controls temporarily, then hide again
    function revealControls() {
        const video = document.querySelector('video');
        if (!video) return;
        // Move mouse over the video center to trigger controls reveal
        const rect = video.getBoundingClientRect();
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        video.dispatchEvent(new MouseEvent('mousemove', {
            clientX: cx, clientY: cy, bubbles: true
        }));
        // Also dispatch on parent (YouTube wraps video in a div)
        video.parentElement?.dispatchEvent(new MouseEvent('mousemove', {
            clientX: cx, clientY: cy, bubbles: true
        }));
    }

    function adjustVol(dir) {
        const media = document.querySelector('video, audio');
        if (!media) return;
        media.volume = Math.min(1, Math.max(0, media.volume + (dir === 'up' ? 0.1 : -0.1)));
        updateStatus();
    }

    function toggleFullscreen() {
        const media = document.querySelector('video');
        if (!media) return;
        if (document.fullscreenElement) document.exitFullscreen();
        else media.requestFullscreen?.();
    }

    function adjustVol(dir) {
        const media = document.querySelector('video, audio');
        if (media) {
            media.volume = Math.min(1, Math.max(0, media.volume + (dir === 'up' ? 0.1 : -0.1)));
            updateStatus('Volume: ' + Math.round(media.volume * 100) + '%');
            return;
        }
        // Fallback: arrow keys (YouTube volume shortcut)
        const key = dir === 'up' ? 'ArrowUp' : 'ArrowDown';
        document.body.dispatchEvent(new KeyboardEvent('keydown', {
            key, bubbles: true, cancelable: true
        }));
    }

    function toggleFullscreen() {
        const media = document.querySelector('video');
        if (!media) return;
        if (document.fullscreenElement) document.exitFullscreen();
        else if (media.requestFullscreen) media.requestFullscreen();
    }

    function muteMedia() {
        // Direct JS mute — works even when controls are hidden
        const media = document.querySelector('video, audio');
        if (media) {
            media.muted = !media.muted;
            updateStatus(media.muted ? '🔇 Muted' : '🔊 Unmuted');
            notifyPython({ type: 'media_muted', muted: media.muted });
            return;
        }
        // Fallback: M key (YouTube mute shortcut)
        document.body.dispatchEvent(new KeyboardEvent('keydown', {
            key: 'm', keyCode: 77, bubbles: true
        }));
    }

    // ── Scroll ────────────────────────────────────────────────────────────────

    function scroll(direction, amount = 350) {
        const dirs = {
            down: [0, amount], up: [0, -amount],
            right: [amount, 0], left: [-amount, 0],
            top: [0, -9999999], bottom: [0, 9999999],
        };
        const [x, y] = dirs[direction] || [0, amount];
        window.scrollBy({ left: x, top: y, behavior: 'smooth' });
        updateStatus(`↕ Scrolled ${direction}`);
        notifyPython({ type: 'scrolled', direction });
    }

    function navigate(cmd) {
        if (cmd === 'top') window.scrollTo({ top: 0, behavior: 'smooth' });
        if (cmd === 'bottom') window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
    }

    // ── Mutation + Scroll observers ───────────────────────────────────────────

    let observer = null;

    function observeMutations() {
        if (observer) return;
        observer = new MutationObserver(() => {
            clearTimeout(mutationTimer);
            mutationTimer = setTimeout(() => { if (isActive) scan(); }, 800);
        });
        observer.observe(document.documentElement, { childList: true, subtree: true });
    }

    function observeScroll() {
        window.addEventListener('scroll', () => {
            // Fast reposition on every scroll frame
            repositionBadges();
            // Full rescan after scroll settles
            clearTimeout(scrollTimer);
            scrollTimer = setTimeout(() => { if (isActive) scan(); }, 500);
        }, { passive: true });
    }

    // ── Top bar (browser UI hints) + Status bar ───────────────────────────────

    function showBars() {
        // Top bar — explains browser UI voice commands
        if (!document.getElementById('__wm_topbar__')) {
            const top = document.createElement('div');
            top.id = '__wm_topbar__';
            top.innerHTML = `
        <span style="color:#00d4ff;font-weight:700;">BROWSER CONTROLS (voice):</span>
        <span class="wm-nav-hint">say "go back"</span>
        <span class="wm-nav-hint">say "go forward"</span>
        <span class="wm-nav-hint">say "refresh"</span>
        <span class="wm-nav-hint">say "new tab"</span>
        <span class="wm-nav-hint">say "close tab"</span>
        <span style="margin-left:auto;color:#30363d;font-size:10px;">
          browser buttons not labelable — use voice
        </span>
      `;
            document.documentElement.appendChild(top);
        }

        // Bottom status bar
        if (!document.getElementById('__wm_statusbar__')) {
            const bar = document.createElement('div');
            bar.id = '__wm_statusbar__';
            bar.innerHTML = `
        <div id="__wm_pulse__"></div>
        <span style="color:#00d4ff;font-weight:700;letter-spacing:.5px;">WEB MODE</span>
        <span id="__wm_status_text__" style="color:#8b949e;">Scanning...</span>
        <span style="margin-left:auto;color:#30363d;font-size:10px;">
          number=click · scroll down · pause · mute · go back
        </span>
      `;
            document.documentElement.appendChild(bar);
        }
    }

    function removeBars() {
        ['__wm_topbar__', '__wm_statusbar__'].forEach(id => {
            document.getElementById(id)?.remove();
        });
    }

    function updateStatus(text) {
        const el = document.getElementById('__wm_status_text__');
        if (el) el.textContent = text;
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    function isVisible(el) {
        try {
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            if (style.display === 'none') return false;
            if (style.visibility === 'hidden') return false;
            if (parseFloat(style.opacity) < 0.05) return false;
            if (rect.width === 0 && rect.height === 0) return false;
            return rect.bottom > 0 && rect.right > 0
                && rect.top < window.innerHeight
                && rect.left < window.innerWidth;
        } catch { return false; }
    }

    function isInputEl(el) {
        const tag = el.tagName.toLowerCase();
        const type = (el.type || '').toLowerCase();
        const nonTyping = ['submit', 'button', 'reset', 'image', 'checkbox', 'radio', 'file', 'color', 'range'];
        return tag === 'textarea'
            || (tag === 'input' && !nonTyping.includes(type))
            || el.isContentEditable === true;
    }

    function isMediaEl(el) {
        return el.tagName === 'VIDEO' || el.tagName === 'AUDIO';
    }

    function getBadgeClass(el) {
        if (isMediaEl(el)) return 'wm-media';
        if (isInputEl(el)) return 'wm-input';
        if (el.tagName.toLowerCase() === 'a') return 'wm-link';
        return '';
    }

    function getLabel(el) {
        return (
            el.getAttribute('aria-label') ||
            el.getAttribute('title') ||
            el.getAttribute('placeholder') ||
            el.getAttribute('alt') ||
            el.textContent?.trim().slice(0, 50) ||
            el.tagName.toLowerCase()
        );
    }

    // ── Python comms ──────────────────────────────────────────────────────────

    function notifyPython(data) {
        try { chrome.runtime.sendMessage({ source: 'content', ...data }); } catch (_) { }
    }

    // ── Message listener ──────────────────────────────────────────────────────

    chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
        if (msg.target !== 'content') return;
        switch (msg.action) {
            case 'activate': activate(); break;
            case 'deactivate': deactivate(); break;
            case 'rescan': scan(); break;
            case 'click': clickElement(msg.num); break;
            case 'type': typeText(msg.text); break;
            case 'clear': clearInput(); break;
            case 'enter': pressEnter(); break;
            case 'scroll': scroll(msg.direction); break;
            case 'navigate': navigate(msg.cmd); break;
            case 'media_toggle': toggleMedia(); break;
            case 'media_mute': muteMedia(); break;
            case 'ping': sendResponse({ ok: true, active: isActive }); return;
        }
        sendResponse({ ok: true });
        return true;
    });

    // ── Auto-activate on load ─────────────────────────────────────────────────

    chrome.storage.local.get('webmode_active', (result) => {
        if (!result.webmode_active) return;
        if (document.readyState === 'complete') activate();
        else window.addEventListener('load', activate, { once: true });
    });

})();