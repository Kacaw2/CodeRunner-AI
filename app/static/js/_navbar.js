/**
 * Navbar authentication and role-based display logic
 * Separated from HTML to maintain clean static JS
 */
(function () {
    // DOM elements
    const nav = document.querySelector('.site-nav');
    const guestBox = document.getElementById('nav-auth-guest');
    const userBox = document.getElementById('nav-auth-user');
    const dashLink = document.getElementById('nav-dashboard');
    const signout = document.getElementById('nav-signout');
    const teacherTools = document.getElementById('nav-teacher-tools');
    const submissionsLink = document.getElementById('nav-submissions');
    const myQuizzesLink = document.getElementById('nav-myquizzes'); 

    const mobileMenuToggle = document.querySelector('.site-nav__menu-toggle');
    const mobileMenuDropdown = document.getElementById('site-nav-mobile-dropdown');

    const dashLinkMobile = document.getElementById('nav-dashboard-mobile');
    const teacherToolsMobile = document.getElementById('nav-teacher-tools-mobile');
    const submissionsLinkMobile = document.getElementById('nav-submissions-mobile');
    const myQuizzesLinkMobile = document.getElementById('nav-myquizzes-mobile');

    const loginMobile = document.getElementById('nav-login-mobile');
    const signupMobile = document.getElementById('nav-signup-mobile');
    const signoutMobile = document.getElementById('nav-signout-mobile');

    // Get URLs from data attributes (set by Jinja2)
    const URLS = {
        login: nav?.dataset.loginUrl || '/auth/login',
        teacherDashboard: nav?.dataset.teacherDashboard || '/teacher/profile',
        studentDashboard: nav?.dataset.studentDashboard || '/student/profile'
    };

    /**
     * Safely get authentication token from storage
     */
    function getTokenSafe() {
        try {
            if (window.__auth && typeof window.__auth.getToken === 'function') {
                return window.__auth.getToken();
            }
        } catch (_) { }
        
        try { 
            return localStorage.getItem('token'); 
        } catch (_) { 
            return null; 
        }
    }

    /**
     * Safely clear authentication token
     */
    function clearTokenSafe() {
        try {
            if (window.__auth && typeof window.__auth.clearToken === 'function') {
                window.__auth.clearToken(); 
                return;
            }
        } catch (_) { }
        
        try { 
            localStorage.removeItem('token'); 
        } catch (_) { }
    }

    /**
     * Parse JWT token to extract payload
     */
    function parseJwt(token) {
        try { 
            return JSON.parse(atob(token.split('.')[1])); 
        } catch (_) { 
            return null; 
        }
    }

    /**
     * Render navbar based on authentication token
     */
    function renderByToken() {
        const token = getTokenSafe();
        
        if (token) {
            // User is logged in
            userBox && userBox.classList.remove('is-hidden');
            guestBox && guestBox.classList.add('is-hidden');

            const payload = parseJwt(token) || {};
            const role = payload.role || payload.user_role;

            // Set profile link based on role
            if (dashLink) {
                dashLink.href = role === 'teacher' 
                    ? URLS.teacherDashboard 
                    : URLS.studentDashboard;
            }
            if (dashLinkMobile) {
                dashLinkMobile.href = role === 'teacher'
                    ? URLS.teacherDashboard
                    : URLS.studentDashboard;
            }

            // Show/hide role-specific elements
            if (role === 'teacher') {
                // Teacher: show teacher tools, hide submissions
                teacherTools && teacherTools.classList.remove('is-hidden');
                submissionsLink && submissionsLink.classList.add('is-hidden');
                myQuizzesLink && myQuizzesLink.classList.add('is-hidden');

                teacherToolsMobile && teacherToolsMobile.classList.remove('is-hidden');
                submissionsLinkMobile && submissionsLinkMobile.classList.add('is-hidden');
                myQuizzesLinkMobile && myQuizzesLinkMobile.classList.add('is-hidden');
            } else {
                // Student: hide teacher tools, show submissions
                teacherTools && teacherTools.classList.add('is-hidden');
                submissionsLink && submissionsLink.classList.remove('is-hidden');
                myQuizzesLink && myQuizzesLink.classList.remove('is-hidden');

                teacherToolsMobile && teacherToolsMobile.classList.add('is-hidden');
                submissionsLinkMobile && submissionsLinkMobile.classList.remove('is-hidden');
                myQuizzesLinkMobile && myQuizzesLinkMobile.classList.remove('is-hidden');
            }

            // Mobile auth links：hide when login
            if (loginMobile)  loginMobile.classList.add('is-hidden');
            if (signupMobile) signupMobile.classList.add('is-hidden');
            if (signoutMobile) signoutMobile.classList.remove('is-hidden');
        } else {
            // User is not logged in
            userBox && userBox.classList.add('is-hidden');
            guestBox && guestBox.classList.remove('is-hidden');
            teacherTools && teacherTools.classList.add('is-hidden');
            submissionsLink && submissionsLink.classList.add('is-hidden');
            myQuizzesLink && myQuizzesLink.classList.add('is-hidden');

            teacherToolsMobile && teacherToolsMobile.classList.add('is-hidden');
            submissionsLinkMobile && submissionsLinkMobile.classList.add('is-hidden');
            myQuizzesLinkMobile && myQuizzesLinkMobile.classList.add('is-hidden');

            if (loginMobile)  loginMobile.classList.remove('is-hidden');
            if (signupMobile) signupMobile.classList.remove('is-hidden');
            if (signoutMobile) signoutMobile.classList.add('is-hidden');

            if (dashLinkMobile) {
                dashLinkMobile.href = URLS.login;   // 未登录时，点击跳去登录页
            }
        }
    }

    /**
     * Handle sign out
     */
    function handleSignOut(e) {
        e.preventDefault();
        clearTokenSafe();
        renderByToken();
        window.location.assign(URLS.login);
    }

    // Initial render
    renderByToken();

    // Sign out event listener
    if (signout) {
        signout.addEventListener('click', handleSignOut);
    }
    if (signoutMobile) {
        signoutMobile.addEventListener('click', handleSignOut);
    }
    // Re-render on storage change (for multi-tab sync)
    window.addEventListener('storage', function(e) {
        if (e.key === 'token') {
            renderByToken();
        }
    });
        // ===== Mobile menu toggle =====
    function closeMobileMenu() {
        if (!mobileMenuDropdown || !mobileMenuToggle) return;
        mobileMenuDropdown.classList.add('is-hidden');
        mobileMenuDropdown.classList.remove('is-open');
        mobileMenuToggle.setAttribute('aria-expanded', 'false');
    }

    function openMobileMenu() {
        if (!mobileMenuDropdown || !mobileMenuToggle) return;
        mobileMenuDropdown.classList.remove('is-hidden');
        mobileMenuDropdown.classList.add('is-open');
        mobileMenuToggle.setAttribute('aria-expanded', 'true');
    }

    if (mobileMenuToggle && mobileMenuDropdown) {
        mobileMenuToggle.addEventListener('click', function (e) {
            e.stopPropagation();
            const isOpen = mobileMenuDropdown.classList.contains('is-open');
            if (isOpen) {
                closeMobileMenu();
            } else {
                openMobileMenu();
            }
        });

        // withdraw
        mobileMenuDropdown.addEventListener('click', function (e) {
            if (e.target.closest('.site-nav__menu-link')) {
                closeMobileMenu();
            }
        });

        // close 
        document.addEventListener('click', function (e) {
            if (!mobileMenuDropdown.contains(e.target) &&
                !mobileMenuToggle.contains(e.target)) {
                closeMobileMenu();
            }
        });
    }

    // Re-render on storage change (for multi-tab sync)
    window.addEventListener('storage', function(e) {
        if (e.key === 'token') {
            renderByToken();
        }
    });

})();
