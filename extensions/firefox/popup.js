const OMNICONV_API_INFO = "http://127.0.0.1:5000/api/youtube/info";

document.addEventListener('DOMContentLoaded', async () => {
    let url = "";
    let selectedFormatId = "best";
    let isPlaylist = false;

    const loadingInfo = document.getElementById('loadingInfo');
    const videoInfo = document.getElementById('videoInfo');
    const formatList = document.getElementById('formatList');
    const actionArea = document.getElementById('actionArea');
    const downloadBtn = document.getElementById('downloadBtn');
    
    try {
        let tabs = await browser.tabs.query({ active: true, currentWindow: true });
        if (tabs && tabs[0]) {
            url = tabs[0].url;
            if(!url.startsWith('http')) throw new Error();
        } else {
            throw new Error();
        }
    } catch(err) {
        loadingInfo.textContent = "Please open a valid page with media.";
        document.getElementById('openAppBtn').style.display = 'flex';
        return;
    }

    document.getElementById('openAppBtn').addEventListener('click', () => {
        browser.tabs.create({ url: `http://127.0.0.1:5000/youtube?url=${encodeURIComponent(url)}` });
        window.close();
    });

    try {
        const res = await fetch(OMNICONV_API_INFO, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        });
        const data = await res.json();
        
        if(!data.success) {
            loadingInfo.textContent = data.error || "Cannot find media on this page.";
            document.getElementById('openAppBtn').style.display = 'flex';
            return;
        }

        loadingInfo.style.display = 'none';
        videoInfo.style.display = 'block';
        actionArea.style.display = 'block';
        document.getElementById('openAppBtn').style.display = 'flex';

        if(data.thumbnail) {
            document.getElementById('vThumb').src = data.thumbnail;
        } else {
            document.getElementById('vThumb').style.display = 'none';
        }
        
        document.getElementById('vTitle').textContent = data.title || "Unknown";
        document.getElementById('vAuthor').textContent = data.uploader || "";
        isPlaylist = !!data.is_playlist;

        if (data.formats && data.formats.length > 0 && !isPlaylist) {
            formatList.innerHTML = '';
            const seen = new Set();
            data.formats.forEach((f, idx) => {
                const label = f.resolution || f.note || f.ext || 'unknown';
                if(seen.has(label)) return;
                seen.add(label);
                
                const btn = document.createElement('button');
                btn.className = 'format-option' + (idx === 0 ? ' active' : '');
                let text = label;
                if(f.filesize) {
                    text += ` (${(f.filesize / 1048576).toFixed(1)} MB)`;
                }
                btn.textContent = text;
                
                if (idx === 0) selectedFormatId = f.format_id || 'best';

                btn.onclick = () => {
                    document.querySelectorAll('.format-option').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    selectedFormatId = f.format_id || 'best';
                };
                formatList.appendChild(btn);
            });
        } else {
            formatList.innerHTML = '<div class="format-option active">Best Quality</div>';
            selectedFormatId = 'best';
        }

    } catch(err) {
        loadingInfo.textContent = "Cannot connect to OmniConv. Is server running on port 5000?";
        document.getElementById('openAppBtn').style.display = 'flex';
    }

    downloadBtn.addEventListener('click', async () => {
        downloadBtn.disabled = true;
        document.getElementById('btnText').textContent = "Triggering...";
        document.getElementById('loader').style.display = "block";

        try {
            browser.runtime.sendMessage({
                action: "START_DOWNLOAD",
                payload: {
                    url: url,
                    format_id: selectedFormatId,
                    is_playlist: isPlaylist
                }
            });
            
            document.getElementById('btnText').textContent = "Started! Downloading...";
            downloadBtn.style.background = "#10b981";
            setTimeout(() => { window.close(); }, 1500);

        } catch(e) {
            document.getElementById('btnText').textContent = "Error communicating with extension.";
        }
    });
});
