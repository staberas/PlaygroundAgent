// ==UserScript==
// @name         YouTube: Hide paid content hover overlay
// @namespace    https://tampermonkey.net/
// @version      1.0.0
// @description  Hides .ytmPaidContentOverlayHost whenever it appears on hover.
// @author       you
// @match        https://www.youtube.com/*
// @run-at       document-start
// @grant        none
// ==/UserScript==

(() => {
  'use strict';

  const TARGET_CLASS = 'ytmPaidContentOverlayHost';
  const HIDE_STYLE_ID = 'tm-hide-ytm-paid-overlay-style';

  function injectHideStyle() {
    if (document.getElementById(HIDE_STYLE_ID)) return;

    const style = document.createElement('style');
    style.id = HIDE_STYLE_ID;
    style.textContent = `.${TARGET_CLASS} { display: none !important; opacity: 0 !important; visibility: hidden !important; pointer-events: none !important; }`;
    (document.head || document.documentElement).appendChild(style);
  }

  function hideExistingOverlays(root = document) {
    const overlays = root.querySelectorAll(`.${TARGET_CLASS}`);
    for (const overlay of overlays) {
      overlay.style.setProperty('display', 'none', 'important');
      overlay.style.setProperty('opacity', '0', 'important');
      overlay.style.setProperty('visibility', 'hidden', 'important');
      overlay.style.setProperty('pointer-events', 'none', 'important');
    }
  }

  function startObserver() {
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (!(node instanceof Element)) continue;

          if (node.classList?.contains(TARGET_CLASS)) {
            hideExistingOverlays(node.parentElement || node);
            continue;
          }

          if (node.querySelector) hideExistingOverlays(node);
        }
      }
    });

    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
    });
  }

  function init() {
    injectHideStyle();
    hideExistingOverlays();
    startObserver();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
