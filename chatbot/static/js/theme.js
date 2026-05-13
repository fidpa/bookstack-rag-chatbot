// KnowledgeBot Theme Manager
(function() {
    'use strict';
    
    // Constants
    const THEME_KEY = 'knowledgebot-theme';
    const THEME_LIGHT = 'light';
    const THEME_DARK = 'dark';
    
    // Get stored theme or detect system preference
    function getPreferredTheme() {
        const stored = localStorage.getItem(THEME_KEY);
        if (stored) {
            return stored;
        }
        
        // Check system preference
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return THEME_DARK;
        }
        
        return THEME_LIGHT;
    }
    
    // Apply theme to document
    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem(THEME_KEY, theme);
        
        // Update toggle button state
        const toggle = document.getElementById('themeToggle');
        if (toggle) {
            toggle.setAttribute('data-theme', theme);
        }
    }
    
    // Toggle between themes
    function toggleTheme() {
        const currentTheme = document.documentElement.getAttribute('data-theme') || THEME_LIGHT;
        const newTheme = currentTheme === THEME_LIGHT ? THEME_DARK : THEME_LIGHT;
        applyTheme(newTheme);
    }
    
    // Initialize theme on page load
    function initTheme() {
        const theme = getPreferredTheme();
        applyTheme(theme);
        
        // Add click handler to toggle button
        const toggle = document.getElementById('themeToggle');
        if (toggle) {
            toggle.addEventListener('click', toggleTheme);
        }
        
        // Listen for system theme changes
        if (window.matchMedia) {
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
                // Only auto-switch if user hasn't manually set a preference
                if (!localStorage.getItem(THEME_KEY)) {
                    applyTheme(e.matches ? THEME_DARK : THEME_LIGHT);
                }
            });
        }
    }
    
    // Run when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initTheme);
    } else {
        initTheme();
    }
})();