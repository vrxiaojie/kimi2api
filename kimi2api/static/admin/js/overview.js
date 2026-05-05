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
            copyText('d:\\kimi2api\\config.json', '已复制配置文件路径');
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
        const oauthSession = AdminState.oauth?.session;
        const oauthStatus = oauthSession?.status || (AdminState.oauth?.active ? 'running' : 'idle');
        const stats = [
            { label: '配置文件', value: 'config.json', hint: '项目根目录持久化' },
            { label: '账号数', value: AdminState.accounts.length, hint: `活动账号: ${AdminState.activeAccountId || 'none'}` },
            { label: '模型映射', value: AdminState.models.length, hint: 'OpenAI 名称到 Kimi 名称' },
            { label: 'OAuth', value: oauthStatus, hint: oauthSession?.message || '等待启动' },
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
            this.els.overviewSummary.textContent = `当前共有 ${AdminState.accounts.length} 个账号、${AdminState.models.length} 条模型映射、${AdminState.apiKeys.length} 个 API Key。${config.kimi_token_configured ? '代理请求已经具备可用 token。' : '还没有可用 token，建议先去 OAuth 页完成登录。'}`;
        }
    },
};
