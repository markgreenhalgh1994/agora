/*
 * Agora Extension — background.js
 * Handles cache cleanup on startup.
 */

chrome.runtime.onInstalled.addListener(() => {
  console.log("Agora extension installed.");
});

// Clean expired cache entries on startup
chrome.runtime.onStartup.addListener(() => {
  chrome.storage.local.get(null, (items) => {
    const now = Date.now();
    const toRemove = Object.entries(items)
      .filter(([k, v]) => k.startsWith("score_") && v._expiry && v._expiry < now)
      .map(([k]) => k);
    if (toRemove.length > 0) {
      chrome.storage.local.remove(toRemove);
      console.log(`Agora: cleared ${toRemove.length} expired cache entries`);
    }
  });
});
