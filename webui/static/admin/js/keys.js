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
