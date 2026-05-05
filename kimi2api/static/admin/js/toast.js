/**
 * Toast 浮动消息提示组件
 * 替代原生 alert/confirm，提供 Vue 风格的悬浮提示
 */
const Toast = (() => {
    let container = null;
    const ICONS = {
        success: '✓',
        error: '✕',
        warning: '!',
        info: 'i',
    };

    function ensureContainer() {
        if (!container) {
            container = document.createElement('div');
            container.className = 'toast-container';
            document.body.appendChild(container);
        }
        return container;
    }

    function show(message, type = 'info', options = {}) {
        const {
            title = '',
            duration = 3500,
            closable = true,
        } = options;

        const c = ensureContainer();
        const el = document.createElement('div');
        el.className = `toast toast-${type}`;
        el.innerHTML = `
            <div class="toast-icon">${ICONS[type] || ICONS.info}</div>
            <div class="toast-body">
                ${title ? `<div class="toast-title">${escapeHtml(title)}</div>` : ''}
                <div class="toast-message">${escapeHtml(message)}</div>
            </div>
            ${closable ? '<button class="toast-close" type="button">×</button>' : ''}
            ${duration > 0 ? `<div class="toast-progress" style="width:100%"></div>` : ''}
        `;

        c.appendChild(el);

        // 入场动画
        requestAnimationFrame(() => {
            el.classList.add('show');
        });

        // 进度条动画
        const progress = el.querySelector('.toast-progress');
        if (progress && duration > 0) {
            requestAnimationFrame(() => {
                progress.style.transitionDuration = `${duration}ms`;
                progress.style.width = '0%';
            });
        }

        // 关闭按钮
        const closeBtn = el.querySelector('.toast-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => dismiss(el));
        }

        // 自动关闭
        let timer = null;
        if (duration > 0) {
            timer = setTimeout(() => dismiss(el), duration);
        }

        // 悬停暂停
        el.addEventListener('mouseenter', () => {
            if (timer) {
                clearTimeout(timer);
                timer = null;
            }
            if (progress) {
                progress.style.transitionDuration = '0ms';
                const current = getComputedStyle(progress).width;
                progress.style.width = current;
            }
        });

        el.addEventListener('mouseleave', () => {
            if (duration > 0) {
                const remaining = (parseFloat(getComputedStyle(progress).width) / parseFloat(getComputedStyle(progress).maxWidth || el.offsetWidth)) * duration;
                progress.style.transitionDuration = `${Math.max(remaining, 500)}ms`;
                progress.style.width = '0%';
                timer = setTimeout(() => dismiss(el), Math.max(remaining, 500));
            }
        });

        return el;
    }

    function dismiss(el) {
        if (!el || el.classList.contains('leaving')) return;
        el.classList.remove('show');
        el.classList.add('leaving');
        el.addEventListener('transitionend', () => el.remove(), { once: true });
        // 安全兜底
        setTimeout(() => { if (el.parentNode) el.remove(); }, 400);
    }

    function success(message, options = {}) {
        return show(message, 'success', options);
    }

    function error(message, options = {}) {
        return show(message, 'error', { duration: 5000, ...options });
    }

    function warning(message, options = {}) {
        return show(message, 'warning', { duration: 4000, ...options });
    }

    function info(message, options = {}) {
        return show(message, 'info', options);
    }

    /**
     * 替代 confirm() 的确认对话框
     * 返回 Promise<boolean>
     */
    function confirm(message, options = {}) {
        const {
            title = '确认操作',
            confirmText = '确定',
            cancelText = '取消',
            type = 'warning',
        } = options;

        return new Promise(resolve => {
            const backdrop = document.createElement('div');
            backdrop.className = 'toast-confirm-backdrop';
            backdrop.innerHTML = `
                <div class="toast-confirm-card">
                    <div class="toast-confirm-title">${escapeHtml(title)}</div>
                    <div class="toast-confirm-message">${escapeHtml(message)}</div>
                    <div class="toast-confirm-actions">
                        <button class="ghost" data-action="cancel">${escapeHtml(cancelText)}</button>
                        <button class="${type === 'danger' ? 'danger' : 'primary'}" data-action="confirm">${escapeHtml(confirmText)}</button>
                    </div>
                </div>
            `;

            document.body.appendChild(backdrop);

            const handleClick = (e) => {
                const action = e.target.dataset.action;
                if (!action) return;
                backdrop.remove();
                resolve(action === 'confirm');
            };

            backdrop.addEventListener('click', (e) => {
                if (e.target === backdrop) {
                    backdrop.remove();
                    resolve(false);
                }
            });

            backdrop.querySelector('.toast-confirm-actions').addEventListener('click', handleClick);
        });
    }

    function escapeHtml(value) {
        return String(value ?? '')
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#39;');
    }

    return { show, success, error, warning, info, confirm, dismiss };
})();
