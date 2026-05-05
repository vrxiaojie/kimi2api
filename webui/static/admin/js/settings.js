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
                active_account_id: this.els.activeAccountInput?.value,
            }),
        });
        Toast.success('配置已保存');
        await AdminManager.loadState();
    },
};
