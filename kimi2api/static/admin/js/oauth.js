/**
 * OAuth 登录页面逻辑
 */
const OauthPage = {
    els: {},

    init() {
        this.els = {
            oauthForm: document.getElementById('oauthForm'),
            oauthNameInput: document.getElementById('oauthNameInput'),
            oauthNotesInput: document.getElementById('oauthNotesInput'),
            oauthActivateInput: document.getElementById('oauthActivateInput'),
            oauthStartBtn: document.getElementById('oauthStartBtn'),
            oauthCancelBtn: document.getElementById('oauthCancelBtn'),
            oauthStatusPillRow: document.getElementById('oauthStatusPillRow'),
            oauthProgress: document.getElementById('oauthProgress'),
            oauthNotice: document.getElementById('oauthNotice'),
            oauthDetails: document.getElementById('oauthDetails'),
        };

        this.bindEvents();
        this.render();
    },

    bindEvents() {
        this.els.oauthForm?.addEventListener('submit', e => this.startOauth(e));
        this.els.oauthCancelBtn?.addEventListener('click', () => this.cancelOauth());
    },

    render() {
        const oauth = AdminState.oauth || { active: false, session: null };
        const session = oauth.session;
        const status = session?.status || 'idle';
        const active = oauth.active || oauthPendingStatuses.has(status);
        const accountId = session?.account_id || '';
        const savedName = session?.account_name_saved || session?.account_name || '-';

        if (this.els.oauthStatusPillRow) {
            this.els.oauthStatusPillRow.innerHTML = [
                `<span class="pill ${active ? 'warn' : 'success'}">status: ${escapeHtml(status)}</span>`,
                `<span class="pill accent">session: ${escapeHtml(session?.session_id || '-')}</span>`,
                accountId ? `<span class="pill success">saved: ${escapeHtml(savedName)}</span>` : '',
            ].join('');
        }

        if (this.els.oauthProgress) this.els.oauthProgress.classList.toggle('hidden', !active);
        if (this.els.oauthCancelBtn) this.els.oauthCancelBtn.classList.toggle('hidden', !active);
        if (this.els.oauthStartBtn) this.els.oauthStartBtn.disabled = active;

        const lines = [];
        if (session?.message) lines.push(`状态: ${session.message}`);
        if (session?.token_source) lines.push(`来源: ${session.token_source}`);
        if (session?.validation?.account_info?.user_id) lines.push(`用户 ID: ${session.validation.account_info.user_id}`);
        if (session?.completed_at) lines.push(`完成时间: ${formatDate(session.completed_at)}`);

        if (this.els.oauthDetails) {
            this.els.oauthDetails.textContent = lines.length ? lines.join('\n') : '还没有进行 OAuth 登录。点击"启动浏览器登录"后，浏览器窗口会自动打开到 Kimi 登录页。';
        }

        if (session?.error) {
            this.showNotice(session.error, true);
        } else if (status === 'success') {
            const userId = session?.validation?.account_info?.user_id || 'unknown';
            this.showNotice(`OAuth 登录成功。已保存账号 ${savedName}，用户 ID: ${userId}。`);
        } else if (active) {
            this.showNotice(session?.message || '浏览器窗口已打开，请在新窗口中完成登录。');
        } else {
            this.clearNotice();
        }
    },

    showNotice(message, isError = false) {
        if (!this.els.oauthNotice) return;
        this.els.oauthNotice.classList.remove('hidden');
        this.els.oauthNotice.classList.toggle('error', isError);
        this.els.oauthNotice.textContent = message;
    },

    clearNotice() {
        if (!this.els.oauthNotice) return;
        this.els.oauthNotice.classList.add('hidden');
        this.els.oauthNotice.classList.remove('error');
        this.els.oauthNotice.textContent = '';
    },

    async startOauth(event) {
        event.preventDefault();
        this.clearNotice();
        await requestJson('/admin/api/oauth/start', {
            method: 'POST',
            body: JSON.stringify({
                name: this.els.oauthNameInput?.value.trim(),
                notes: this.els.oauthNotesInput?.value.trim(),
                activate: this.els.oauthActivateInput?.value === 'true',
            }),
        });
        Toast.info('OAuth 登录已启动，请在弹出的浏览器窗口中完成登录');
        await AdminManager.refreshOauthStatus();
    },

    async cancelOauth() {
        await requestJson('/admin/api/oauth/cancel', { method: 'POST' });
        Toast.info('OAuth 登录已取消');
        await AdminManager.refreshOauthStatus();
    },
};
