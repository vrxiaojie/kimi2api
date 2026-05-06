/**
 * 公共工具函数
 */

function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function formatDate(value) {
    if (!value) return '-';
    const numericValue = Number(value);
    const date = new Date(numericValue > 1000000000000 ? numericValue : numericValue * 1000);
    if (Number.isNaN(date.getTime())) return '-';
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function maskToken(token) {
    if (!token) return '-';
    if (token.length <= 10) return token;
    return `${token.slice(0, 6)}...${token.slice(-4)}`;
}

async function requestJson(url, options = {}) {
    const response = await fetch(url, {
        headers: {
            'Content-Type': 'application/json',
            ...(options.headers || {}),
        },
        ...options,
    });
    const text = await response.text();
    let data = null;
    try {
        data = text ? JSON.parse(text) : null;
    } catch {
        data = { raw: text };
    }
    if (!response.ok) {
        const message = data?.error?.message || data?.error || `Request failed (${response.status})`;
        throw new Error(message);
    }
    return data;
}

async function copyText(value, successMessage) {
    if (!value) {
        Toast.warning('没有可复制的内容');
        return;
    }
    try {
        await navigator.clipboard.writeText(value);
        Toast.success(successMessage || '已复制到剪贴板');
    } catch {
        // fallback
        const textarea = document.createElement('textarea');
        textarea.value = value;
        textarea.style.cssText = 'position:fixed;left:-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        Toast.success(successMessage || '已复制到剪贴板');
    }
}

/**
 * 全局状态管理
 */
const AdminState = {
    config: {},
    accounts: [],
    models: [],
    apiKeys: [],
    activeAccountId: '',
    currentView: 'overview',
    latestCreatedKey: '',
};

/**
 * 页面视图定义
 */
const AdminViews = {
    overview: {
        eyebrow: 'Overview',
        title: '统一管理 Kimi2API 的运行配置和账号。',
        description: '概览页提供账号数量、映射、API Key 和配置状态的总览，并给出常用入口。',
    },
    accounts: {
        eyebrow: 'Accounts',
        title: '管理账号，并支持从 curl 导入 auth token。',
        description: '这里对应 CLI 里的 token 与账号管理能力，支持手动保存、从 curl 提取 auth、校验、激活和删除。',
    },
    models: {
        eyebrow: 'Models',
        title: '维护 OpenAI 模型名到 Kimi 模型名的映射。',
        description: '适合把调用方的公开模型名，映射到真实的 Kimi 模型。',
    },
    keys: {
        eyebrow: 'API Keys',
        title: '管理访问代理服务的 API Key。',
        description: '创建后的完整 Key 会保存在管理台列表中，方便后续再次复制。',
    },
    settings: {
        eyebrow: 'Settings',
        title: '调整服务监听参数和默认账号。',
        description: '这一页对应 CLI 中的 config show、set-port、set-host 等配置能力。',
    },
};
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
/**
 * 概览页面逻辑
 */
const OverviewPage = {
    els: {},

    init() {
        this.els = {
            heroEyebrow: document.getElementById('heroEyebrow'),
            heroTitle: document.getElementById('heroTitle'),
            heroDescription: document.getElementById('heroDescription'),
            statsGrid: document.getElementById('statsGrid'),
            refreshBtn: document.getElementById('refreshBtn'),
            copyConfigBtn: document.getElementById('copyConfigBtn'),
            overviewSummary: document.getElementById('overviewSummary'),
        };

        this.bindEvents();
        this.render();
    },

    bindEvents() {
        this.els.refreshBtn?.addEventListener('click', () => {
            AdminManager.loadState().catch(err => Toast.error(err.message));
        });

        this.els.copyConfigBtn?.addEventListener('click', () => {
            copyText(AdminManager.getConfigFilePath(), '已复制配置文件路径');
        });
    },

    render() {
        const current = AdminViews[AdminState.currentView] || AdminViews.overview;
        if (this.els.heroEyebrow) this.els.heroEyebrow.textContent = current.eyebrow;
        if (this.els.heroTitle) this.els.heroTitle.textContent = current.title;
        if (this.els.heroDescription) this.els.heroDescription.textContent = current.description;
        this.renderStats();
        this.renderSummary();
    },

    renderStats() {
        const hasReadyToken = AdminState.config?.kimi_token_configured;
        const stats = [
            { label: '配置文件', value: 'config.json', hint: '项目根目录持久化' },
            { label: '账号数', value: AdminState.accounts.length, hint: `活动账号: ${AdminState.activeAccountId || 'none'}` },
            { label: '模型映射', value: AdminState.models.length, hint: 'OpenAI 名称到 Kimi 名称' },
            { label: 'Token', value: hasReadyToken ? 'ready' : 'missing', hint: hasReadyToken ? '已有可用活动账号' : '先到账号页添加或导入' },
        ];
        if (this.els.statsGrid) {
            this.els.statsGrid.innerHTML = stats.map(stat => `
                <article class="stat-card">
                    <div class="label">${escapeHtml(stat.label)}</div>
                    <div class="value">${escapeHtml(stat.value)}</div>
                    <div class="subtle">${escapeHtml(stat.hint)}</div>
                </article>
            `).join('');
        }
    },

    renderSummary() {
        const config = AdminState.config || {};
        if (this.els.overviewSummary) {
            this.els.overviewSummary.textContent = `当前共有 ${AdminState.accounts.length} 个账号、${AdminState.models.length} 条模型映射、${AdminState.apiKeys.length} 个 API Key。${config.kimi_token_configured ? '代理请求已经具备可用 token。' : '还没有可用 token，建议先去账号页添加或导入。'}`;
        }
    },
};
/**
 * 账号管理页面逻辑
 */
const AccountsPage = {
    els: {},

    init() {
        this.els = {
            accountsCountPill: document.getElementById('accountsCountPill'),
            activeAccountPill: document.getElementById('activeAccountPill'),
            accountForm: document.getElementById('accountForm'),
            accountNameInput: document.getElementById('accountNameInput'),
            accountTokenInput: document.getElementById('accountTokenInput'),
            accountNotesInput: document.getElementById('accountNotesInput'),
            accountSubmitBtn: document.getElementById('accountSubmitBtn'),
            accountResetBtn: document.getElementById('accountResetBtn'),
            curlImportForm: document.getElementById('curlImportForm'),
            curlAccountNameInput: document.getElementById('curlAccountNameInput'),
            curlCommandInput: document.getElementById('curlCommandInput'),
            curlNotesInput: document.getElementById('curlNotesInput'),
            curlActivateInput: document.getElementById('curlActivateInput'),
            curlResetBtn: document.getElementById('curlResetBtn'),
            accountsList: document.getElementById('accountsList'),
            accountEditModal: document.getElementById('accountEditModal'),
            accountEditForm: document.getElementById('accountEditForm'),
            editingAccountId: document.getElementById('editingAccountId'),
            editAccountNameInput: document.getElementById('editAccountNameInput'),
            editAccountTokenInput: document.getElementById('editAccountTokenInput'),
            editAccountNotesInput: document.getElementById('editAccountNotesInput'),
            closeAccountModalBtn: document.getElementById('closeAccountModalBtn'),
            cancelAccountModalBtn: document.getElementById('cancelAccountModalBtn'),
        };

        this.bindEvents();
        this.render();
    },

    bindEvents() {
        this.els.accountForm?.addEventListener('submit', e => this.submitAccount(e));
        this.els.accountResetBtn?.addEventListener('click', () => this.resetForm());
        this.els.curlImportForm?.addEventListener('submit', e => this.submitCurlImport(e));
        this.els.curlResetBtn?.addEventListener('click', () => this.resetCurlForm());
        this.els.accountEditForm?.addEventListener('submit', e => this.submitEdit(e));
        this.els.closeAccountModalBtn?.addEventListener('click', () => this.closeModal());
        this.els.cancelAccountModalBtn?.addEventListener('click', () => this.closeModal());
        this.els.accountEditModal?.addEventListener('click', e => {
            if (e.target === this.els.accountEditModal) this.closeModal();
        });
    },

    render() {
        this.renderPills();
        this.renderList();
    },

    renderPills() {
        if (this.els.accountsCountPill) {
            this.els.accountsCountPill.textContent = `${AdminState.accounts.length} accounts`;
        }
        if (this.els.activeAccountPill) {
            this.els.activeAccountPill.textContent = AdminState.activeAccountId ? `active: ${AdminState.activeAccountId}` : 'no active account';
        }
    },

    renderList() {
        if (!this.els.accountsList) return;

        if (!AdminState.accounts.length) {
            this.els.accountsList.innerHTML = '<div class="muted-box">还没有账号。你可以在这里直接添加 token，或者粘贴浏览器复制的 curl 请求导入 auth token。</div>';
            return;
        }

        function renderValidationPill(account) {
            if (account.validation_status === 'passed') return '<span class="pill success">通过</span>';
            if (account.validation_status === 'failed') return '<span class="pill warn">失败</span>';
            if (account.validation_status === 'untested') return '<span class="pill">未验证</span>';
            return '<span class="pill">未知</span>';
        }

        this.els.accountsList.innerHTML = `
            <table class="table">
                <thead>
                    <tr>
                        <th>名称</th>
                        <th>Token</th>
                        <th>类型</th>
                        <th>状态</th>
                        <th>备注</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                    ${AdminState.accounts.map(account => `
                        <tr>
                            <td>
                                <div><strong>${escapeHtml(account.name)}</strong></div>
                                <div class="subtle">${escapeHtml(account.id)}</div>
                                <div class="subtle">${escapeHtml(account.user_id || '')}</div>
                            </td>
                            <td><span class="token">${escapeHtml(maskToken(account.token))}</span></td>
                            <td>${escapeHtml(account.auth_method || account.token_type || 'jwt')}</td>
                            <td>
                                <div class="stack">
                                    <span class="pill ${account.enabled ? 'success' : 'warn'}">${account.enabled ? 'enabled' : 'disabled'}</span>
                                    ${renderValidationPill(account)}
                                    ${AdminState.activeAccountId === account.id ? '<span class="pill accent">active</span>' : ''}
                                </div>
                                <div class="subtle" style="margin-top: 8px;">创建: ${escapeHtml(formatDate(account.created_at))}</div>
                                <div class="subtle">更新: ${escapeHtml(formatDate(account.updated_at))}</div>
                                <div class="subtle">验证时间: ${escapeHtml(formatDate(account.validated_at))}</div>
                                <div class="subtle">验证结果: ${escapeHtml(account.validation_message || '-')}</div>
                            </td>
                            <td>${escapeHtml(account.notes || '-')}</td>
                            <td>
                                <div class="row-actions">
                                    <button class="ghost" data-action="edit-account" data-id="${escapeHtml(account.id)}">编辑</button>
                                    <button class="secondary" data-action="toggle-account-enabled" data-id="${escapeHtml(account.id)}" data-enabled="${account.enabled ? 'true' : 'false'}">${account.enabled ? '禁用' : '启用'}</button>
                                    <button class="secondary" data-action="validate-account" data-id="${escapeHtml(account.id)}">验证</button>
                                    <button class="danger" data-action="delete-account" data-id="${escapeHtml(account.id)}">删除</button>
                                </div>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    },

    resetForm() {
        if (this.els.accountNameInput) this.els.accountNameInput.value = '';
        if (this.els.accountTokenInput) {
            this.els.accountTokenInput.value = '';
            this.els.accountTokenInput.placeholder = 'eyJ... 或 refresh token';
        }
        if (this.els.accountNotesInput) this.els.accountNotesInput.value = '';
        if (this.els.accountSubmitBtn) this.els.accountSubmitBtn.textContent = '新增账号';
    },

    resetCurlForm() {
        if (this.els.curlAccountNameInput) this.els.curlAccountNameInput.value = '';
        if (this.els.curlCommandInput) this.els.curlCommandInput.value = '';
        if (this.els.curlNotesInput) this.els.curlNotesInput.value = '';
        if (this.els.curlActivateInput) this.els.curlActivateInput.value = 'true';
    },

    openModal(account) {
        if (this.els.editingAccountId) this.els.editingAccountId.value = account.id;
        if (this.els.editAccountNameInput) this.els.editAccountNameInput.value = account.name || '';
        if (this.els.editAccountTokenInput) {
            this.els.editAccountTokenInput.value = '';
            this.els.editAccountTokenInput.placeholder = '留空保留当前 token，或输入新 token';
        }
        if (this.els.editAccountNotesInput) this.els.editAccountNotesInput.value = account.notes || '';
        this.els.accountEditModal?.classList.add('open');
        this.els.accountEditModal?.setAttribute('aria-hidden', 'false');
    },

    closeModal() {
        if (this.els.editingAccountId) this.els.editingAccountId.value = '';
        if (this.els.editAccountNameInput) this.els.editAccountNameInput.value = '';
        if (this.els.editAccountTokenInput) this.els.editAccountTokenInput.value = '';
        if (this.els.editAccountNotesInput) this.els.editAccountNotesInput.value = '';
        this.els.accountEditModal?.classList.remove('open');
        this.els.accountEditModal?.setAttribute('aria-hidden', 'true');
    },

    async submitAccount(event) {
        event.preventDefault();
        const payload = {
            name: this.els.accountNameInput?.value.trim(),
            token: this.els.accountTokenInput?.value.trim(),
            auth_method: 'jwt',
            notes: this.els.accountNotesInput?.value.trim(),
        };
        await requestJson('/admin/api/accounts', {
            method: 'POST',
            body: JSON.stringify({ ...payload, activate: true }),
        });
        this.resetForm();
        Toast.success('账号添加成功');
        await AdminManager.loadState();
    },

    async submitCurlImport(event) {
        event.preventDefault();
        await requestJson('/admin/api/accounts/import-curl', {
            method: 'POST',
            body: JSON.stringify({
                name: this.els.curlAccountNameInput?.value.trim(),
                curl: this.els.curlCommandInput?.value.trim(),
                notes: this.els.curlNotesInput?.value.trim(),
                activate: this.els.curlActivateInput?.value === 'true',
            }),
        });
        this.resetCurlForm();
        Toast.success('已从 curl 导入账号');
        await AdminManager.loadState();
    },

    async submitEdit(event) {
        event.preventDefault();
        const editingId = this.els.editingAccountId?.value;
        if (!editingId) { this.closeModal(); return; }
        await requestJson(`/admin/api/accounts/${editingId}`, {
            method: 'PUT',
            body: JSON.stringify({
                name: this.els.editAccountNameInput?.value.trim(),
                token: this.els.editAccountTokenInput?.value.trim(),
                auth_method: 'jwt',
                notes: this.els.editAccountNotesInput?.value.trim(),
            }),
        });
        this.closeModal();
        Toast.success('账号更新成功');
        await AdminManager.loadState();
    },

    async handleAction(action, button) {
        if (action === 'edit-account') {
            const account = AdminState.accounts.find(item => item.id === button.dataset.id);
            if (account) this.openModal(account);
            return;
        }

        if (action === 'toggle-account-enabled') {
            const enabled = button.dataset.enabled === 'true';
            await requestJson(`/admin/api/accounts/${button.dataset.id}/enabled`, {
                method: 'POST',
                body: JSON.stringify({ enabled: !enabled }),
            });
            Toast.success(enabled ? '账号已禁用' : '账号已启用');
            await AdminManager.loadState();
            return;
        }

        if (action === 'validate-account') {
            button.disabled = true;
            button.textContent = '验证中';
            await requestJson(`/admin/api/accounts/${button.dataset.id}/validate`, { method: 'POST' });
            Toast.success('账号验证完成');
            await AdminManager.loadState();
            return;
        }

        if (action === 'delete-account') {
            const confirmed = await Toast.confirm('确定删除这个账号吗？此操作不可恢复。', {
                title: '删除账号',
                confirmText: '删除',
                type: 'danger',
            });
            if (!confirmed) return;
            await requestJson(`/admin/api/accounts/${button.dataset.id}`, { method: 'DELETE' });
            this.resetForm();
            Toast.success('账号已删除');
            await AdminManager.loadState();
        }
    },
};
/**
 * 模型映射页面逻辑
 */
const ModelsPage = {
    els: {},

    init() {
        this.els = {
            modelForm: document.getElementById('modelForm'),
            openaiModelInput: document.getElementById('openaiModelInput'),
            kimiModelInput: document.getElementById('kimiModelInput'),
            modelsCountPill: document.getElementById('modelsCountPill'),
            modelsList: document.getElementById('modelsList'),
        };

        this.bindEvents();
        this.render();
    },

    bindEvents() {
        this.els.modelForm?.addEventListener('submit', e => this.submitModel(e));
    },

    render() {
        this.renderPills();
        this.renderList();
    },

    renderPills() {
        if (this.els.modelsCountPill) {
            this.els.modelsCountPill.textContent = `${AdminState.models.length} mappings`;
        }
    },

    renderList() {
        if (!this.els.modelsList) return;

        if (!AdminState.models.length) {
            this.els.modelsList.innerHTML = '<div class="muted-box">当前没有模型映射。添加一条即可开始使用。</div>';
            return;
        }

        this.els.modelsList.innerHTML = `
            <table class="table">
                <thead>
                    <tr>
                        <th>OpenAI</th>
                        <th>Kimi</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                    ${AdminState.models.map(model => `
                        <tr>
                            <td><span class="token">${escapeHtml(model.openai_model)}</span></td>
                            <td><span class="token">${escapeHtml(model.kimi_model)}</span></td>
                            <td>
                                <div class="row-actions">
                                    <button class="danger" data-action="delete-model" data-openai="${escapeHtml(model.openai_model)}">删除</button>
                                </div>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    },

    async submitModel(event) {
        event.preventDefault();
        await requestJson('/admin/api/models', {
            method: 'POST',
            body: JSON.stringify({
                openai_model: this.els.openaiModelInput?.value.trim(),
                kimi_model: this.els.kimiModelInput?.value.trim(),
            }),
        });
        if (this.els.openaiModelInput) this.els.openaiModelInput.value = '';
        if (this.els.kimiModelInput) this.els.kimiModelInput.value = '';
        Toast.success('模型映射已添加');
        await AdminManager.loadState();
    },

    async handleAction(action, button) {
        if (action === 'delete-model') {
            await requestJson(`/admin/api/models/${encodeURIComponent(button.dataset.openai)}`, { method: 'DELETE' });
            Toast.success('模型映射已删除');
            await AdminManager.loadState();
        }
    },
};
/**
 * API Key 管理页面逻辑
 */
const KeysPage = {
    els: {},

    init() {
        this.els = {
            keyForm: document.getElementById('keyForm'),
            keyNameInput: document.getElementById('keyNameInput'),
            keysCountPill: document.getElementById('keysCountPill'),
            keysList: document.getElementById('keysList'),
            latestKeyNotice: document.getElementById('latestKeyNotice'),
            latestKeyActions: document.getElementById('latestKeyActions'),
            copyLatestKeyBtn: document.getElementById('copyLatestKeyBtn'),
        };

        this.bindEvents();
        this.render();
    },

    bindEvents() {
        this.els.keyForm?.addEventListener('submit', e => this.submitKey(e));
        this.els.copyLatestKeyBtn?.addEventListener('click', () => {
            copyText(AdminState.latestCreatedKey, '已复制刚创建的 Key');
        });
    },

    render() {
        this.renderPills();
        this.renderList();
    },

    renderPills() {
        if (this.els.keysCountPill) {
            this.els.keysCountPill.textContent = `${AdminState.apiKeys.length} keys`;
        }
    },

    renderList() {
        if (!this.els.keysList) return;

        if (!AdminState.apiKeys.length) {
            this.els.keysList.innerHTML = '<div class="muted-box">当前没有 API Key。创建后会显示前缀、名称和状态。</div>';
            return;
        }

        this.els.keysList.innerHTML = `
            <table class="table">
                <thead>
                    <tr>
                        <th>完整 Key</th>
                        <th>名称</th>
                        <th>状态</th>
                        <th>创建时间</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                    ${AdminState.apiKeys.map(apiKey => `
                        <tr>
                            <td>
                                <span class="token">${escapeHtml(maskToken(apiKey.key || apiKey.prefix))}</span>
                                ${apiKey.copy_available ? '' : '<div class="subtle" style="margin-top: 8px;">旧格式 key，仅保留前缀</div>'}
                            </td>
                            <td>${escapeHtml(apiKey.name)}</td>
                            <td><span class="pill ${apiKey.enabled ? 'success' : 'warn'}">${apiKey.enabled ? 'enabled' : 'revoked'}</span></td>
                            <td>${escapeHtml(formatDate(apiKey.created_at))}</td>
                            <td>
                                <div class="row-actions">
                                    <button class="ghost" data-action="copy-key-value" data-key="${escapeHtml(apiKey.key || '')}" ${apiKey.copy_available ? '' : 'disabled'}>${apiKey.copy_available ? '复制完整 Key' : '需重建后复制'}</button>
                                    <button class="secondary" data-action="toggle-key" data-prefix="${escapeHtml(apiKey.prefix)}" data-enabled="${apiKey.enabled ? 'true' : 'false'}">${apiKey.enabled ? '吊销' : '启用'}</button>
                                    <button class="danger" data-action="delete-key" data-prefix="${escapeHtml(apiKey.prefix)}">删除</button>
                                </div>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    },

    async submitKey(event) {
        event.preventDefault();
        const result = await requestJson('/admin/api/api-keys', {
            method: 'POST',
            body: JSON.stringify({ name: this.els.keyNameInput?.value.trim() }),
        });
        if (this.els.keyNameInput) this.els.keyNameInput.value = '';
        if (result.key) {
            AdminState.latestCreatedKey = result.key;
            if (this.els.latestKeyNotice) {
                this.els.latestKeyNotice.classList.remove('hidden');
                this.els.latestKeyNotice.textContent = `新建 API Key: ${result.key}\n你也可以在下方列表中再次复制完整 key。`;
            }
            if (this.els.latestKeyActions) this.els.latestKeyActions.classList.remove('hidden');
        }
        Toast.success('API Key 创建成功');
        await AdminManager.loadState();
    },

    async handleAction(action, button) {
        if (action === 'copy-key-value') {
            await copyText(button.dataset.key, '已复制完整 Key');
            return;
        }

        if (action === 'toggle-key') {
            const enabled = button.dataset.enabled === 'true';
            const endpoint = enabled ? 'revoke' : 'enable';
            await requestJson(`/admin/api/api-keys/${encodeURIComponent(button.dataset.prefix)}/${endpoint}`, { method: 'POST' });
            Toast.success(enabled ? 'Key 已吊销' : 'Key 已启用');
            await AdminManager.loadState();
            return;
        }

        if (action === 'delete-key') {
            const confirmed = await Toast.confirm('确定删除这个 API Key 吗？此操作不可恢复。', {
                title: '删除 API Key',
                confirmText: '删除',
                type: 'danger',
            });
            if (!confirmed) return;
            await requestJson(`/admin/api/api-keys/${encodeURIComponent(button.dataset.prefix)}`, { method: 'DELETE' });
            Toast.success('API Key 已删除');
            await AdminManager.loadState();
        }
    },
};
/**
 * 设置页面逻辑
 */
const SettingsPage = {
    els: {},

    init() {
        this.els = {
            configForm: document.getElementById('configForm'),
            hostInput: document.getElementById('hostInput'),
            portInput: document.getElementById('portInput'),
            logLevelInput: document.getElementById('logLevelInput'),
            enableApiKeyInput: document.getElementById('enableApiKeyInput'),
            autoDeleteChatInput: document.getElementById('autoDeleteChatInput'),
            activeAccountInput: document.getElementById('activeAccountInput'),
        };

        this.bindEvents();
        this.render();
    },

    bindEvents() {
        this.els.configForm?.addEventListener('submit', e => this.submitConfig(e));
    },

    render() {
        this.renderConfigForm();
    },

    renderConfigForm() {
        if (this.els.hostInput) this.els.hostInput.value = AdminState.config.host || '127.0.0.1';
        if (this.els.portInput) this.els.portInput.value = AdminState.config.port || 8080;
        if (this.els.logLevelInput) this.els.logLevelInput.value = AdminState.config.log_level || 'INFO';
        if (this.els.enableApiKeyInput) this.els.enableApiKeyInput.value = String(Boolean(AdminState.config.enable_api_key));
        if (this.els.autoDeleteChatInput) this.els.autoDeleteChatInput.value = String(Boolean(AdminState.config.auto_delete_chat));

        if (this.els.activeAccountInput) {
            const options = AdminState.accounts.map(account => {
                const label = `${account.name} (${account.id}${account.enabled ? '' : ', disabled'})`;
                const selected = AdminState.activeAccountId === account.id ? 'selected' : '';
                return `<option value="${escapeHtml(account.id)}" ${selected}>${escapeHtml(label)}</option>`;
            });
            this.els.activeAccountInput.innerHTML = options.length ? options.join('') : '<option value="">No account</option>';
        }
    },

    async submitConfig(event) {
        event.preventDefault();
        await requestJson('/admin/api/config', {
            method: 'PUT',
            body: JSON.stringify({
                host: this.els.hostInput?.value.trim(),
                port: Number(this.els.portInput?.value),
                log_level: this.els.logLevelInput?.value,
                enable_api_key: this.els.enableApiKeyInput?.value === 'true',
                auto_delete_chat: this.els.autoDeleteChatInput?.value === 'true',
                active_account_id: this.els.activeAccountInput?.value,
            }),
        });
        Toast.success('配置已保存');
        await AdminManager.loadState();
    },
};
/**
 * 管理台主控制器
 * 负责页面切换、状态管理、公共渲染
 */
const AdminManager = {
    els: {},

    init() {
        this.els = {
            sidebarNav: document.getElementById('sidebarNav'),
            statusPills: document.getElementById('statusPills'),
            sidebarSummary: document.getElementById('sidebarSummary'),
            views: Array.from(document.querySelectorAll('.view')),
            contentArea: document.getElementById('contentArea'),
        };

        this.bindNavigation();
        this.resolveInitialView();
        this.renderNav();

        window.addEventListener('hashchange', () => {
            const hashView = window.location.hash.replace(/^#/, '');
            if (AdminViews[hashView]) {
                AdminState.currentView = hashView;
                this.renderNav();
            }
        });

        // 全局代理点击事件（用于列表中的操作按钮）
        document.addEventListener('click', e => this.handleGlobalAction(e));

        // 加载初始数据
        this.loadState().catch(err => {
            console.error(err);
            Toast.error(err.message || '加载管理台失败');
        });
    },

    bindNavigation() {
        this.els.sidebarNav?.addEventListener('click', event => {
            const button = event.target.closest('.nav-btn');
            if (!button) return;
            this.setView(button.dataset.view);
        });
    },

    resolveInitialView() {
        const hashView = window.location.hash.replace(/^#/, '');
        AdminState.currentView = AdminViews[hashView] ? hashView : 'overview';
    },

    setView(viewName) {
        AdminState.currentView = AdminViews[viewName] ? viewName : 'overview';
        window.location.hash = `#${AdminState.currentView}`;
        this.renderNav();
    },

    renderNav() {
        const buttons = Array.from(this.els.sidebarNav?.querySelectorAll('.nav-btn') || []);
        buttons.forEach(button => {
            button.classList.toggle('active', button.dataset.view === AdminState.currentView);
        });
        this.els.views.forEach(view => {
            view.classList.toggle('active', view.dataset.view === AdminState.currentView);
        });

        // 更新概览页 hero 区域
        OverviewPage.render();

        // 重新渲染当前页面
        this.renderCurrentPage();
    },

    renderCurrentPage() {
        switch (AdminState.currentView) {
            case 'overview': OverviewPage.render(); break;
            case 'accounts': AccountsPage.render(); break;
            case 'models': ModelsPage.render(); break;
            case 'keys': KeysPage.render(); break;
            case 'settings': SettingsPage.render(); break;
        }
    },

    renderStatusPills() {
        const config = AdminState.config || {};
        const configPath = this.getConfigFilePath();
        const pills = [
            `<span class="pill ${config.kimi_token_configured ? 'success' : 'warn'}">${config.kimi_token_configured ? 'Kimi token ready' : 'Kimi token missing'}</span>`,
            `<span class="pill accent">${escapeHtml(config.host || '127.0.0.1')}:${escapeHtml(config.port || 8080)}</span>`,
            `<span class="pill">${escapeHtml(config.log_level || 'INFO')}</span>`,
            `<span class="pill">API Key ${config.enable_api_key ? 'enabled' : 'disabled'}</span>`,
            `<span class="pill ${AdminState.activeAccountId ? 'success' : 'warn'}">${AdminState.activeAccountId ? 'Active account ready' : 'No active account'}</span>`,
        ];
        if (this.els.statusPills) this.els.statusPills.innerHTML = pills.join('');
        if (this.els.sidebarSummary) {
            this.els.sidebarSummary.textContent = `配置文件: ${configPath}\n活动账号: ${AdminState.activeAccountId || 'none'}\nToken 状态: ${config.kimi_token_configured ? 'ready' : 'missing'}`;
        }
    },

    getConfigFilePath() {
        return AdminState.config?.config_file || 'config.json';
    },

    async loadState() {
        const data = await requestJson('/admin/api/bootstrap');
        AdminState.config = data.config || {};
        AdminState.accounts = data.accounts || [];
        AdminState.models = data.models || [];
        AdminState.apiKeys = data.api_keys || [];
        AdminState.activeAccountId = data.active_account_id || '';
        this.renderAll();
    },

    renderAll() {
        this.renderStatusPills();
        this.renderCurrentPage();
        // 其他页面需要更新 pills
        AccountsPage.renderPills();
        ModelsPage.renderPills();
        KeysPage.renderPills();
    },

    async handleGlobalAction(event) {
        const button = event.target.closest('button[data-action], button[data-jump-view]');
        if (!button) return;

        if (button.dataset.jumpView) {
            this.setView(button.dataset.jumpView);
            return;
        }

        const action = button.dataset.action;
        if (!action) return;

        try {
            // 账号相关操作
            if (action.startsWith('edit-account') || action.startsWith('toggle-account') ||
                action.startsWith('validate-account') || action.startsWith('delete-account')) {
                await AccountsPage.handleAction(action, button);
                return;
            }

            // 模型相关操作
            if (action === 'delete-model') {
                await ModelsPage.handleAction(action, button);
                return;
            }

            // API Key 相关操作
            if (action.startsWith('copy-key') || action.startsWith('toggle-key') || action.startsWith('delete-key')) {
                await KeysPage.handleAction(action, button);
                return;
            }
        } catch (error) {
            Toast.error(error.message || '操作失败');
        } finally {
            button.disabled = false;
            if (action === 'validate-account') {
                button.textContent = '验证';
            }
        }
    },
};

// ── 页面加载完成后初始化 ──
document.addEventListener('DOMContentLoaded', () => {
    OverviewPage.init();
    AccountsPage.init();
    ModelsPage.init();
    KeysPage.init();
    SettingsPage.init();
    AdminManager.init();
});
