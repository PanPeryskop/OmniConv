document.addEventListener('DOMContentLoaded', () => {
    const chatWidget = document.getElementById('omni-chat-widget');
    if (!chatWidget) return;

    const toggleBtn = document.getElementById('chat-toggle-btn');
    const chatWindow = document.getElementById('chat-window');
    const closeBtn = document.querySelector('.close-chat-btn');
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-chat-btn');
    const messagesContainer = document.querySelector('.chat-messages');

    let currentResponseId = null;
    let isSending = false;

    function toggleChat() {
        chatWindow.classList.toggle('open');
        if (chatWindow.classList.contains('open')) {
            setTimeout(() => input.focus(), 300);
        }
    }

    toggleBtn.addEventListener('click', toggleChat);
    closeBtn.addEventListener('click', toggleChat);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && chatWindow.classList.contains('open')) {
            chatWindow.classList.remove('open');
        }
    });

    async function sendMessage() {
        const text = input.value.trim();
        if (!text || isSending) return;

        isSending = true;
        input.disabled = true;
        sendBtn.disabled = true;

        addMessage(text, 'user');
        input.value = '';

        const loadingId = addLoadingIndicator();
        let botMessageDiv = null;

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    response_id: currentResponseId
                })
            });

            if (!response.ok) throw new Error(`HTTP Error: ${response.status}`);

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let accumulatedText = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                if (!botMessageDiv) {
                    removeLoadingIndicator(loadingId);
                    botMessageDiv = addMessage('', 'bot');
                }

                const chunk = decoder.decode(value, { stream: true });
                accumulatedText += chunk;
                botMessageDiv.innerHTML = parseMarkdown(accumulatedText);
                scrollToBottom();
            }

            if (!botMessageDiv) {
                removeLoadingIndicator(loadingId);
                addMessage("No response.", 'bot');
            }

        } catch (error) {
            removeLoadingIndicator(loadingId);
            if (!botMessageDiv) botMessageDiv = addMessage('', 'bot');
            botMessageDiv.innerHTML += `<div class="chat-error">Error: ${error.message}</div>`;
            scrollToBottom();
        } finally {
            isSending = false;
            input.disabled = false;
            sendBtn.disabled = false;
            input.focus();
        }
    }

    sendBtn.addEventListener('click', sendMessage);
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });

    function addMessage(text, sender) {
        const div = document.createElement('div');
        div.classList.add('message', sender);

        if (sender === 'bot') {
            div.innerHTML = parseMarkdown(text);
        } else {
            div.textContent = text;
        }

        messagesContainer.appendChild(div);
        scrollToBottom();
        return div;
    }

    function addLoadingIndicator() {
        const id = 'loading-' + Date.now();
        const div = document.createElement('div');
        div.id = id;
        div.classList.add('message', 'bot', 'typing-indicator');
        div.innerHTML = '<span></span><span></span><span></span>';
        messagesContainer.appendChild(div);
        scrollToBottom();
        return id;
    }

    function removeLoadingIndicator(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    function scrollToBottom() {
        messagesContainer.scrollTo({
            top: messagesContainer.scrollHeight,
            behavior: 'smooth'
        });
    }

    function parseMarkdown(text) {
        let html = text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");

        html = html.replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>');
        html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

        html = html.replace(/^### (.*$)/gm, '<h3>$1</h3>');
        html = html.replace(/^## (.*$)/gm, '<h2>$1</h2>');
        html = html.replace(/^# (.*$)/gm, '<h1>$1</h1>');

        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');

        html = html.replace(/^\s*[-*]\s+(.*)$/gm, '<li>$1</li>');
        html = html.replace(/^\s*\d+\.\s+(.*)$/gm, '<li>$1</li>');
        html = html.replace(/(<li>[\s\S]*?<\/li>\n?)+/g, '<ul>$&</ul>');

        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');

        html = html.replace(/\n/g, '<br>');
        html = html.replace(/<\/h(\d)><br>/g, '</h$1>');
        html = html.replace(/<\/ul><br>/g, '</ul>');
        html = html.replace(/<\/pre><br>/g, '</pre>');

        return html;
    }
});
