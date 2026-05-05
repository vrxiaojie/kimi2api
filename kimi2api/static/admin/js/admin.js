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
            case 'oauth': OauthPage.render(); break;
            case 'models': ModelsPage.render(); break;
            case 'keys': KeysPage.render(); break;
            case 'settings': SettingsPage.render(); break;
        }
    },

    renderStatusPills() {
        const config = AdminState.config || {};
        const oauthSession = AdminState.oauth?.session;
        const pills = [
            `<span class="pill ${config.kimi_token_configured ? 'success' : 'warn'}">${config.kimi_token_configured ? 'Kimi token ready' : 'Kimi token missing'}</span>`,
            `<span class="pill accent">${escapeHtml(config.host || '127.0.0.1')}:${escapeHtml(config.port || 8080)}</span>`,
            `<span class="pill">${escapeHtml(config.log_level || 'INFO')}</span>`,
            `<span class="pill">API Key ${config.enable_api_key ? 'enabled' : 'disabled'}</span>`,
            `<span class="pill ${AdminState.oauth?.active ? 'warn' : 'success'}">OAuth ${escapeHtml(oauthSession?.status || (AdminState.oauth?.active ? 'running' : 'idle'))}</span>`,
        ];
        if (this.els.statusPills) this.els.statusPills.innerHTML = pills.join('');
        if (this.els.sidebarSummary) {
            this.els.sidebarSummary.textContent = `配置文件: d:\\kimi2api\\config.json\n活动账号: ${AdminState.activeAccountId || 'none'}\nOAuth 状态: ${oauthSession?.message || 'idle'}`;
        }
    },

    async loadState() {
        const data = await requestJson('/admin/api/bootstrap');
        AdminState.config = data.config || {};
        AdminState.accounts = data.accounts || [];
        AdminState.models = data.models || [];
        AdminState.apiKeys = data.api_keys || [];
        AdminState.activeAccountId = data.active_account_id || '';
        AdminState.oauth = data.oauth || { active: false, session: null };
        this.renderAll();
        this.ensureOauthPolling();
    },

    async refreshOauthStatus() {
        const data = await requestJson('/admin/api/oauth/status');
        AdminState.oauth = data || { active: false, session: null };
        OverviewPage.renderStats();
        this.renderStatusPills();
        OauthPage.render();
        this.ensureOauthPolling();

        const session = AdminState.oauth.session;
        if (session?.status === 'success') {
            await this.loadState();
        }
    },

    ensureOauthPolling() {
        const shouldPoll = AdminState.oauth?.active || oauthPendingStatuses.has(AdminState.oauth?.session?.status || '');
        if (shouldPoll && !AdminState.oauthPollTimer) {
            AdminState.oauthPollTimer = window.setInterval(() => {
                this.refreshOauthStatus().catch(err => console.error(err));
            }, 2000);
        }
        if (!shouldPoll && AdminState.oauthPollTimer) {
            window.clearInterval(AdminState.oauthPollTimer);
            AdminState.oauthPollTimer = null;
        }
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
    OauthPage.init();
    ModelsPage.init();
    KeysPage.init();
    SettingsPage.init();
    AdminManager.init();
});
