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
