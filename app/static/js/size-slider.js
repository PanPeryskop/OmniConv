const SizeSlider = (() => {
    const KB = 1024;
    const MB = 1048576;

    function formatSize(bytes) {
        if (bytes < KB) return bytes + ' B';
        if (bytes < MB) return (bytes / KB).toFixed(1) + ' KB';
        return (bytes / MB).toFixed(2) + ' MB';
    }

    function stepFor(mb) {
        if (mb > 500) return 5;
        if (mb > 100) return 1;
        if (mb > 10) return 0.5;
        if (mb > 1) return 0.1;
        return 'any';
    }

    function create(root) {
        const input = root.querySelector('.slider-input');
        const value = root.querySelector('.size-value');
        const unit = root.querySelector('.size-unit');
        const fill = root.querySelector('.slider-fill');
        const labels = root.querySelectorAll('.slider-labels span');
        const [originalStat, targetStat, reductionStat] = root.querySelectorAll('.size-stat-value');
        let size = 0;
        let key = null;
        let bounceTimer = null;

        function render(animate) {
            const target = Number(input.value);
            const min = Number(input.min);
            const max = Number(input.max);
            const targetBytes = Math.round(target * MB);
            const [amount, suffix] = formatSize(targetBytes).split(' ');
            fill.style.width = `${max > min ? (target - min) / (max - min) * 100 : 100}%`;
            value.textContent = Number(amount);
            unit.textContent = suffix;
            if (targetStat) targetStat.textContent = formatSize(targetBytes);
            if (reductionStat) reductionStat.textContent = `${size ? Math.max(0, Math.round((1 - targetBytes / size) * 100)) : 0}%`;
            if (animate) {
                value.classList.add('bounce');
                clearTimeout(bounceTimer);
                bounceTimer = setTimeout(() => value.classList.remove('bounce'), 300);
            }
        }

        function configure(bytes, { ratio = 0.3, minRatio = 0.01, id = null } = {}) {
            const keep = id !== null && id === key ? Number(input.value) : null;
            size = Math.round(bytes);
            key = id;
            const mb = size / MB;
            const min = Math.min(mb, Math.max(mb * minRatio, 1 / KB));
            input.min = min;
            input.max = mb;
            input.step = stepFor(mb);
            input.value = keep !== null && keep >= min && keep <= mb ? keep : Math.max(min, mb * ratio);
            if (labels[0]) labels[0].textContent = formatSize(Math.round(min * MB));
            if (labels[labels.length - 1]) labels[labels.length - 1].textContent = formatSize(size);
            if (originalStat) originalStat.textContent = formatSize(size);
            render(false);
        }

        input.addEventListener('input', () => render(true));

        return { configure, target: () => Number(input.value), input };
    }

    return { create, formatSize };
})();
