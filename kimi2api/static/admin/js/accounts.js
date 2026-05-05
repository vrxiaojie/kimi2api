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
            this.els.accountsList.innerHTML = '<div class="muted-box">还没有账号。你可以在这里添加 JWT 账号，或者切换到 OAuth 登录页自动获取 token。</div>';
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
