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
