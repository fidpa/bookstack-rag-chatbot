/**
 * KnowledgeBot Loading States Utility
 * Provides consistent loading indicators across the application
 */

class LoadingStates {
    /**
     * Inline loading spinner for small elements
     */
    static inline() {
        return '<span class="loading-spinner"><i class="fas fa-circle-notch fa-spin"></i></span>';
    }
    
    /**
     * Skeleton loader for content placeholders
     */
    static skeleton(lines = 2) {
        let skeletons = '';
        for (let i = 0; i < lines; i++) {
            const isShort = i % 2 === 1;
            skeletons += `<div class="skeleton-line ${isShort ? 'short' : ''}"></div>`;
        }
        return `<div class="skeleton-loader">${skeletons}</div>`;
    }
    
    /**
     * Button loading state
     */
    static button(text = 'Wird geladen...') {
        return `<span><i class="fas fa-spinner fa-spin"></i> ${text}</span>`;
    }
    
    /**
     * Replace button content with loading state
     */
    static setButtonLoading(button, loadingText = 'Wird geladen...') {
        button.disabled = true;
        button.dataset.originalContent = button.innerHTML;
        button.innerHTML = this.button(loadingText);
    }
    
    /**
     * Restore button to original state
     */
    static resetButton(button) {
        button.disabled = false;
        if (button.dataset.originalContent) {
            button.innerHTML = button.dataset.originalContent;
            delete button.dataset.originalContent;
        }
    }
    
    /**
     * Full page loading overlay
     */
    static overlay(message = 'Lade Daten...') {
        return `
            <div class="loading-overlay">
                <div class="loading-content">
                    <i class="fas fa-spinner fa-spin fa-3x"></i>
                    <p>${message}</p>
                </div>
            </div>
        `;
    }
    
    /**
     * Message area loading state
     */
    static messageArea() {
        return `
            <div class="message-loading">
                <div class="typing-indicator">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
                <span class="loading-text">Thinking...</span>
            </div>
        `;
    }
}

// Export for use in other modules
window.LoadingStates = LoadingStates;