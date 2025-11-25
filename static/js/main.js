/**
 * Related Education Document Server - Main JavaScript
 */

// Utility functions
const utils = {
    /**
     * Format a date string for display
     * @param {string} dateStr - ISO date string
     * @returns {string} Formatted date
     */
    formatDate(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        });
    },

    /**
     * Debounce a function
     * @param {Function} func - Function to debounce
     * @param {number} wait - Wait time in ms
     * @returns {Function} Debounced function
     */
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },

    /**
     * Show a notification message
     * @param {string} message - Message to show
     * @param {string} type - 'success' or 'error'
     */
    showNotification(message, type = 'success') {
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.textContent = message;
        document.body.appendChild(notification);

        setTimeout(() => {
            notification.classList.add('fade-out');
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    },

    /**
     * Make an API request
     * @param {string} url - API URL
     * @param {Object} options - Fetch options
     * @returns {Promise} Response data
     */
    async apiRequest(url, options = {}) {
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json',
            },
        };

        const response = await fetch(url, { ...defaultOptions, ...options });
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(error.detail || 'Request failed');
        }

        return response.json();
    }
};

// Document management functions
const documents = {
    /**
     * Get all documents with pagination
     * @param {number} page - Page number
     * @param {number} pageSize - Items per page
     * @returns {Promise} Documents response
     */
    async getAll(page = 1, pageSize = 20) {
        return utils.apiRequest(`/api/documents?page=${page}&page_size=${pageSize}`);
    },

    /**
     * Get a single document
     * @param {string} id - Document ID
     * @returns {Promise} Document data
     */
    async get(id) {
        return utils.apiRequest(`/api/documents/${id}`);
    },

    /**
     * Update a document
     * @param {string} id - Document ID
     * @param {Object} data - Update data
     * @returns {Promise} Updated document
     */
    async update(id, data) {
        return utils.apiRequest(`/api/documents/${id}`, {
            method: 'POST',
            body: JSON.stringify(data),
        });
    },

    /**
     * Delete a document
     * @param {string} id - Document ID
     * @returns {Promise} Response
     */
    async delete(id) {
        return utils.apiRequest(`/api/documents/${id}`, {
            method: 'DELETE',
        });
    },

    /**
     * Search documents
     * @param {Object} params - Search parameters
     * @returns {Promise} Search results
     */
    async search(params) {
        const queryString = new URLSearchParams(params).toString();
        return utils.apiRequest(`/api/search?${queryString}`);
    },

    /**
     * Upload a document
     * @param {File} file - File to upload
     * @param {Function} onProgress - Progress callback
     * @returns {Promise} Uploaded document
     */
    async upload(file, onProgress) {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch('/api/documents/upload/manual', {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            throw new Error('Upload failed');
        }

        return response.json();
    }
};

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
    // Add any global initialization here
    console.log('Education Document Server initialized');
});

// Export for use in other scripts
window.EduDocs = {
    utils,
    documents
};

