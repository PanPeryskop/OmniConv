const OMNICONV_API_BASE = "http://127.0.0.1:5000/api/youtube";

browser.contextMenus.create({
    id: "omniconv-download-link",
    title: "Download with OmniConv",
    contexts: ["link", "video", "audio", "page"]
});

browser.contextMenus.onClicked.addListener((info, tab) => {
    const url = info.linkUrl || info.srcUrl || info.pageUrl;
    if (info.menuItemId === "omniconv-download-link" && url) {
        startOmniConvJob({url: url, format_id: "best", is_playlist: false});
    }
});

browser.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "START_DOWNLOAD") {
        startOmniConvJob(request.payload);
    }
});

function startOmniConvJob(payload) {
    browser.notifications.create({
        type: "basic",
        title: "OmniConv",
        message: "Server is processing your download request..."
    });

    fetch(`${OMNICONV_API_BASE}/download`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(data => {
        if(data.success && data.job_id) {
            pollJobStatus(data.job_id);
        } else {
            showErrorNotification(data.error || "Failed to start");
        }
    })
    .catch(err => {
        showErrorNotification("Cannot connect to server. Is OmniConv running?");
    });
}

function pollJobStatus(jobId) {
    const pollInterval = setInterval(() => {
        fetch(`${OMNICONV_API_BASE}/status/${jobId}`)
        .then(res => res.json())
        .then(data => {
            if (data.status === 'error') {
                clearInterval(pollInterval);
                showErrorNotification(data.error || "Download error");
            } else if (data.status === 'completed') {
                clearInterval(pollInterval);
                browser.notifications.create({
                    type: "basic",
                    title: "OmniConv",
                    message: "Server finished! Native download starting..."
                });
                
                const downloadUrl = `${OMNICONV_API_BASE}/download-file/${jobId}`;
                const downloadOptions = {
                    url: downloadUrl,
                    saveAs: false
                };
                
                if (data.filename) {
                    downloadOptions.filename = data.filename.replace(/[\\/:"*?<>|]/g, '');
                }
                
                browser.downloads.download(downloadOptions);
            }
        })
        .catch(err => {
            clearInterval(pollInterval);
            showErrorNotification("Lost connection during download.");
        });
    }, 2000);
}

function showErrorNotification(msg) {
    browser.notifications.create({
        type: "basic",
        title: "OmniConv Error",
        message: msg
    });
}
