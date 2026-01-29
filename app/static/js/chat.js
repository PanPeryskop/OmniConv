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

    function toggleChat() {
        chatWindow.classList.toggle('open');
        if (chatWindow.classList.contains('open')) {
            setTimeout(() => input.focus(), 300);
        }
    }

    toggleBtn.addEventListener('click', toggleChat);
    closeBtn.addEventListener('click', toggleChat);

    async function sendMessage() {
        const text = input.value.trim();
        if (!text) return;

        addMessage(text, 'user');
        input.value = '';

        const loadingId = addLoadingIndicator();

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    response_id: currentResponseId
                })
            });

            const data = await response.json();
            
            removeLoadingIndicator(loadingId);

            if (data.success) {
                const result = data.data;
                currentResponseId = result.response_id;
                addMessage(result.response || "No response text.", 'bot');
            } else {
                addMessage("Error: " + (data.error?.message || "Unknown error"), 'bot');
            }

        } catch (error) {
            removeLoadingIndicator(loadingId);
            addMessage("Network Error: " + error.message, 'bot');
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
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function parseMarkdown(text) {
        let html = text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");

        // Code Blocks
        html = html.replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>');
        html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
        
        // Inline Code
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        
        // Headers
        html = html.replace(/^### (.*$)/gm, '<h3>$1</h3>');
        html = html.replace(/^## (.*$)/gm, '<h2>$1</h2>');
        html = html.replace(/^# (.*$)/gm, '<h1>$1</h1>');
        
        // Bold & Italic
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
        
        // Lists
        html = html.replace(/^\s*[-*]\s+(.*)$/gm, '<li>$1</li>');
        html = html.replace(/^\s*\d+\.\s+(.*)$/gm, '<li>$1</li>');
        
        // Wrap lists in ul (simple hack: adjacent lis)
        // Note: This is a simple regex parser, not a full AST parser.
        // We will wrap groups of <li> in <ul>.
        html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>'); 
        // Better list wrapping for multiple items:
        html = html.replace(/(<li>[\s\S]*?<\/li>\n?)+/g, '<ul>$&</ul>');

        // Links
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
        
        // Newlines to br (but not inside pre/ul)
        // A bit tricky with regex. Let's just do simple replacement for now, 
        // relying on the fact that pre blocks are already formatted.
        // We actually need to protect pre blocks.
        
        // Re-simplification for robust "no dependency" approach: 
        // relying on pre-wrap CSS for strict newlines is safer than regex replace all \n.
        // But for normal text, we usually want <p> or <br>.
        
        // Let's go with paragraph splitting for non-code text.
        // (However, for this specific request, just fixing headers/code/wrapping is key)
        
        // Basic newline support for simple text:
        html = html.replace(/\n/g, '<br>');
        
        // Cleanup extra br inside headers/lists/pre
        html = html.replace(/<\/h(\d)><br>/g, '</h$1>');
        html = html.replace(/<\/ul><br>/g, '</ul>');
        html = html.replace(/<\/pre><br>/g, '</pre>');
        
        return html;
    }
});
