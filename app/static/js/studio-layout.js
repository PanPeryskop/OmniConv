document.addEventListener('DOMContentLoaded', () => {
    const leftPanel = document.querySelector('.panel-left');
    const rightPanel = document.querySelector('.panel-right');
    const studioWrapper = document.querySelector('.studio-wrapper');

    if (!leftPanel || !rightPanel || !studioWrapper) return;

    const savedLeftWidth = localStorage.getItem('studio-nav-width');
    const savedRightWidth = localStorage.getItem('studio-aside-width');

    if (savedLeftWidth) document.documentElement.style.setProperty('--studio-nav-width', savedLeftWidth);
    if (savedRightWidth) document.documentElement.style.setProperty('--studio-aside-width', savedRightWidth);

    function createGutter(direction) {
        const gutter = document.createElement('div');
        gutter.className = `gutter gutter-${direction}`;
        return gutter;
    }

    const leftGutter = createGutter('left');
    const rightGutter = createGutter('right');

    leftPanel.after(leftGutter);
    rightPanel.before(rightGutter);

    let isResizing = false;
    let currentGutter = null;
    let startX = 0;
    let startWidth = 0;

    function startResize(e) {
        isResizing = true;
        currentGutter = e.target;
        startX = e.clientX;
        
        if (currentGutter === leftGutter) {
            startWidth = leftPanel.getBoundingClientRect().width;
        } else {
            startWidth = rightPanel.getBoundingClientRect().width;
        }

        document.body.style.cursor = 'col-resize';
        studioWrapper.style.userSelect = 'none';
        
        document.addEventListener('mousemove', resize);
        document.addEventListener('mouseup', stopResize);
    }

    function resize(e) {
        if (!isResizing) return;

        if (currentGutter === leftGutter) {
            const diff = e.clientX - startX;
            const newWidth = Math.max(200, Math.min(600, startWidth + diff));
            document.documentElement.style.setProperty('--studio-nav-width', `${newWidth}px`);
        } else {
            const diff = startX - e.clientX;
            const newWidth = Math.max(200, Math.min(600, startWidth + diff));
            document.documentElement.style.setProperty('--studio-aside-width', `${newWidth}px`);
        }
    }

    function stopResize() {
        isResizing = false;
        document.body.style.cursor = '';
        studioWrapper.style.userSelect = '';
        
        localStorage.setItem('studio-nav-width', getComputedStyle(document.documentElement).getPropertyValue('--studio-nav-width').trim());
        localStorage.setItem('studio-aside-width', getComputedStyle(document.documentElement).getPropertyValue('--studio-aside-width').trim());

        document.removeEventListener('mousemove', resize);
        document.removeEventListener('mouseup', stopResize);
    }

    leftGutter.addEventListener('mousedown', startResize);
    rightGutter.addEventListener('mousedown', startResize);

    leftGutter.addEventListener('dblclick', () => {
        const currentWidth = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--studio-nav-width'));
        if (currentWidth < 50) {
            document.documentElement.style.setProperty('--studio-nav-width', '320px');
        } else {
            document.documentElement.style.setProperty('--studio-nav-width', '0px');
        }
    });


    const timeline = document.querySelector('.timeline-area');
    if (timeline) {
        const savedTimelineHeight = localStorage.getItem('studio-timeline-height');
        if (savedTimelineHeight) timeline.style.height = savedTimelineHeight;

        const timelineGutter = document.createElement('div');
        timelineGutter.className = 'gutter gutter-bottom';
        timeline.before(timelineGutter);

        timelineGutter.addEventListener('mousedown', (e) => {
            isResizing = true;
            currentGutter = timelineGutter;
            
            const startY = e.clientY;
            const startHeight = timeline.getBoundingClientRect().height;

            document.body.style.cursor = 'row-resize';
            studioWrapper.style.userSelect = 'none';

            const resizeTimeline = (e) => {
                if (!isResizing) return;
                const diff = startY - e.clientY;
                const newHeight = Math.max(100, Math.min(600, startHeight + diff));
                timeline.style.height = `${newHeight}px`;
            };

            const stopTimelineResize = () => {
                isResizing = false;
                document.body.style.cursor = '';
                studioWrapper.style.userSelect = '';
                localStorage.setItem('studio-timeline-height', timeline.style.height);
                document.removeEventListener('mousemove', resizeTimeline);
                document.removeEventListener('mouseup', stopTimelineResize);
            };

            document.addEventListener('mousemove', resizeTimeline);
            document.addEventListener('mouseup', stopTimelineResize);
        });

        timelineGutter.addEventListener('dblclick', () => {
            if (timeline.style.height === '36px') {
                timeline.style.height = '200px';
            } else {
                timeline.style.height = '36px';
            }
        });
    }
});
