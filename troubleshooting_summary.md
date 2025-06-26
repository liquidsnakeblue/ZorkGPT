# ZorkGPT Viewer Status Troubleshooting Summary

This document summarizes the troubleshooting steps taken to resolve the incorrect status indicator on the ZorkGPT web viewer.

## Initial Problem

The ZorkGPT viewer at `https://zorkgpt.schuyler.ai/` showed a red (stale) status light, while the local version at `http://localhost:10000/zork_viewer.html` showed a green (connected) status. This indicated that the public-facing frontend was not receiving fresh data from the backend.

## Troubleshooting Steps

### 1. Client-Side Caching (Incorrect)

*   **Hypothesis:** The browser was caching the `state.json` file, preventing it from fetching the latest version.
*   **Attempted Fix:** Modified `zork_viewer.html` to add `{ cache: 'no-cache' }` to the `fetch` request for `state.json`.
*   **Result:** The issue persisted, indicating the problem was not client-side caching.

### 2. Server-Side Caching (Incorrect)

*   **Hypothesis:** The Caddy server was sending aggressive caching headers, causing the browser to cache the `state.json` file.
*   **Attempted Fix:** Added a `header` directive to the Caddyfile to send `Cache-Control: no-cache` headers for `state.json`.
*   **Result:** The issue persisted. This was an incorrect approach because the `header` directive doesn't override headers from the `reverse_proxy` backend.

### 3. Caddy Rewrite Rule (Incorrect)

*   **Hypothesis:** A broad `rewrite / /zork_viewer.html` rule in the Caddyfile was incorrectly rewriting all requests, including `/state.json`, to the main HTML page.
*   **Attempted Fix:** Changed the rewrite rule to be more specific (`@root path /` and `rewrite @root /zork_viewer.html`) to only rewrite requests for the root path.
*   **Result:** The issue persisted. While the rewrite rule was a potential issue, it was not the root cause.

### 4. Backend Connectivity (Correct)

*   **Hypothesis:** The Caddy server was unable to connect to the backend Python server running on port 10000.
*   **Evidence:** Caddy logs showed the error `dial tcp 192.168.65.254:10000: connect: connection refused`.
*   **Root Cause:** The `start_viewer.py` script, which runs the simple Python web server, was not running or had crashed. This meant there was no service listening on port 10000 for Caddy to connect to.
*   **Resolution:** The `start_viewer.py` script was started, resolving the "connection refused" error and allowing Caddy to successfully proxy requests to the backend. This fixed the stale status issue.

## Conclusion

The root cause was a network connectivity issue between the Caddy reverse proxy and the backend Python server, not a caching or URL rewrite problem. The Caddy error logs were essential in diagnosing the problem correctly.
