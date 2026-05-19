// app/static/js/auth.js
/**
 * Authentication utility functions for client-side token management
 */

/**
 * Save JWT token to localStorage
 * @param {string} token - JWT token from server
 */
export function saveToken(token) {
  if (!token) {
    return;
  }
  localStorage.setItem('token', token);
}

/**
 * Get JWT token from localStorage
 * @returns {string|null} JWT token or null if not found
 */
export function getToken() {
  return localStorage.getItem('token');
}

/**
 * Remove JWT token from localStorage (logout)
 */
export function clearToken() {
  localStorage.removeItem('token');
}

/**
 * Check if user is authenticated
 * @returns {boolean} true if token exists
 */
export function isAuthenticated() {
  return !!getToken();
}

/**
 * Make authenticated API request
 * @param {string} url - API endpoint
 * @param {object} options - Fetch options
 * @returns {Promise<Response>} Fetch response
 */
export async function authenticatedFetch(url, options = {}) {
  const token = getToken();
  
  if (!token) {
    throw new Error('No authentication token found');
  }
  
  const headers = {
    ...options.headers,
    'Authorization': `Bearer ${token}`
  };
  
  return fetch(url, { ...options, headers });
}

/**
 * Decode JWT token (without verification - for client-side info only)
 * @param {string} token - JWT token
 * @returns {object|null} Decoded payload or null if invalid
 */
export function decodeToken(token) {
  if (!token) return null;
  
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    
    const payload = parts[1];
    const decoded = JSON.parse(atob(payload));
    return decoded;
  } catch (err) {
    return null;
  }
}

/**
 * Check if token is expired
 * @param {string} token - JWT token
 * @returns {boolean} true if token is expired
 */
export function isTokenExpired(token) {
  const decoded = decodeToken(token);
  if (!decoded || !decoded.exp) return true;
  
  const now = Math.floor(Date.now() / 1000);
  return decoded.exp < now;
}

/**
 * Get current user info from token
 * @returns {object|null} User info or null if not authenticated
 */
export function getCurrentUser() {
  const token = getToken();
  if (!token) return null;
  
  if (isTokenExpired(token)) {
    clearToken();
    return null;
  }
  
  const decoded = decodeToken(token);
  return decoded ? {
    id: decoded.user_id,
    username: decoded.username,
    role: decoded.role
  } : null;
}

/**
 * Redirect to login if not authenticated
 * @param {string} returnUrl - URL to return to after login
 */
export function requireAuth(returnUrl = null) {
  if (!isAuthenticated()) {
    const next = returnUrl || window.location.pathname;
    window.location.href = `/auth/login?next=${encodeURIComponent(next)}`;
    return false;
  }
  return true;
}
