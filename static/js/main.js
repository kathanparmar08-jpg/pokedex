/**
 * Pokédex Frontend Controller
 * Handles:
 *  - Dark mode persistence (Bootstrap data-bs-theme + Tailwind .dark class)
 *  - AOS (Animate On Scroll) initialization & refresh on page/filter changes
 *  - Touch & keyboard 3D card flip toggling (while keeping "More Details" clickable)
 *  - Live search, type chips, advanced filters (generation, rarity, egg group,
 *    color, habitat, min base stat total), sorting, and strict 20-per-page pagination
 *  - URL state sync so browser Back preserves current page & filters
 *  - Detail page base stat bar entrance animation
 */

(function () {
    'use strict';

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function debounce(fn, delay) {
        let timerId = null;
        return function (...args) {
            clearTimeout(timerId);
            timerId = setTimeout(() => fn.apply(this, args), delay);
        };
    }

    // -------------------------------------------------------------------------
    // 1. Dark Mode Toggle
    // -------------------------------------------------------------------------
    function initThemeToggle() {
        const btn = document.getElementById('themeToggleBtn');
        const icon = document.getElementById('themeToggleIcon');
        if (!btn || !icon) return;

        function syncIcon() {
            const isDark = document.documentElement.classList.contains('dark');
            icon.className = isDark
                ? 'bi bi-sun-fill tw-text-amber-500'
                : 'bi bi-moon-stars-fill tw-text-slate-700';
            btn.setAttribute('aria-pressed', String(isDark));
        }

        syncIcon();

        btn.addEventListener('click', () => {
            const isDark = document.documentElement.classList.toggle('dark');
            const nextTheme = isDark ? 'dark' : 'light';
            document.documentElement.setAttribute('data-bs-theme', nextTheme);
            localStorage.setItem('pokedex-theme', nextTheme);
            syncIcon();
        });
    }

    // -------------------------------------------------------------------------
    // 2. AOS & Back-to-Top Button
    // -------------------------------------------------------------------------
    function initAOS() {
        if (typeof AOS !== 'undefined') {
            AOS.init({
                duration: 500,
                easing: 'ease-out-cubic',
                once: true,
                offset: 32,
            });
        }
    }

    function initBackToTop() {
        const btn = document.getElementById('backToTopBtn');
        if (!btn) return;

        window.addEventListener(
            'scroll',
            () => {
                btn.classList.toggle('visible', window.scrollY > 420);
            },
            { passive: true }
        );

        btn.addEventListener('click', () => {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }

    // -------------------------------------------------------------------------
    // 3. Detail Page: Animated Base Stat Bars
    // -------------------------------------------------------------------------
    function initDetailStatBars() {
        const bars = document.querySelectorAll('.stat-bar-fill[data-target-width]');
        if (!bars.length) return;

        const animateBars = () => {
            bars.forEach((bar, idx) => {
                setTimeout(() => {
                    bar.style.width = bar.dataset.targetWidth || '0%';
                }, idx * 70);
            });
        };

        if ('IntersectionObserver' in window) {
            const container = document.getElementById('baseStatsContainer') || bars[0];
            const observer = new IntersectionObserver(
                (entries) => {
                    if (entries.some((e) => e.isIntersecting)) {
                        animateBars();
                        observer.disconnect();
                    }
                },
                { threshold: 0.15 }
            );
            observer.observe(container);
        } else {
            requestAnimationFrame(animateBars);
        }
    }

    // -------------------------------------------------------------------------
    // 4. Card HTML Renderer (matches index.html server template 1:1)
    // -------------------------------------------------------------------------
    function renderPokemonCardColumn(p, index) {
        const delay = (index % 4) * 65;
        const rareBadge = p.is_legendary
            ? '<span class="poke-rare-dot" title="Legendary Pokémon"><i class="bi bi-star-fill"></i></span>'
            : p.is_mythical
                ? '<span class="poke-rare-dot" title="Mythical Pokémon"><i class="bi bi-gem"></i></span>'
                : '';

        const typeBadges = (p.types || [])
            .map(
                (t) =>
                    `<span class="type-badge type-badge-sm" style="--badge-bg: ${escapeHtml(t.color)};">${escapeHtml(t.display_name)}</span>`
            )
            .join('');

        const miniStats = [
            { label: 'HP', val: p.stats.hp, color: '#22C55E' },
            { label: 'ATK', val: p.stats.attack, color: '#F97316' },
            { label: 'DEF', val: p.stats.defense, color: '#3B82F6' },
        ]
            .map((s) => {
                const pct = Math.min(Math.round((s.val / 180) * 1000) / 10, 100);
                return `
                    <div class="mini-stat-row">
                        <span class="mini-stat-label tw-font-mono">${s.label}</span>
                        <div class="mini-stat-track">
                            <div class="mini-stat-fill" style="width: ${pct}%; background-color: ${s.color};"></div>
                        </div>
                        <span class="mini-stat-num tw-font-mono">${s.val}</span>
                    </div>
                `;
            })
            .join('');

        const heightStr = Number(p.height || 0).toFixed(1);
        const weightStr = Number(p.weight || 0).toFixed(1);
        const detailUrl = `/pokemon/${encodeURIComponent(p.id)}`;

        return `
            <div class="col-12 col-sm-6 col-lg-3" data-aos="fade-up" data-aos-delay="${delay}">
                <div class="poke-card-scene" style="--type-color: ${escapeHtml(p.primary_color)};" tabindex="0" role="button" aria-label="${escapeHtml(p.display_name)} card. Activate to flip for details.">
                    <div class="poke-card-inner">
                        <!-- FRONT FACE -->
                        <div class="poke-card-face poke-card-front">
                            <div class="poke-card-watermark" aria-hidden="true"></div>
                            <div class="d-flex justify-content-between align-items-center tw-w-full">
                                <span class="poke-id-pill tw-font-mono">${escapeHtml(p.formatted_id)}</span>
                                ${rareBadge}
                            </div>
                            <div class="poke-artwork-wrap">
                                <img
                                    src="${escapeHtml(p.artwork_url)}"
                                    alt="${escapeHtml(p.display_name)}"
                                    class="poke-artwork-img"
                                    loading="lazy"
                                />
                            </div>
                            <div class="tw-text-center tw-w-full">
                                <h2 class="poke-card-name tw-mb-0">${escapeHtml(p.display_name)}</h2>
                            </div>
                        </div>

                        <!-- BACK FACE -->
                        <div class="poke-card-face poke-card-back">
                            <div class="d-flex justify-content-between align-items-start tw-gap-2 tw-mb-2">
                                <h3 class="poke-back-name tw-mb-0">${escapeHtml(p.display_name)}</h3>
                                <span class="poke-id-pill tw-font-mono tw-text-xs">${escapeHtml(p.formatted_id)}</span>
                            </div>
                            <div class="d-flex flex-wrap tw-gap-1.5 tw-mb-2.5">${typeBadges}</div>
                            <div class="poke-back-metrics tw-mb-2.5">
                                <div>
                                    <span class="metric-label">Height</span>
                                    <span class="metric-val tw-font-mono">${heightStr} m</span>
                                </div>
                                <div class="metric-divider"></div>
                                <div>
                                    <span class="metric-label">Weight</span>
                                    <span class="metric-val tw-font-mono">${weightStr} kg</span>
                                </div>
                            </div>
                            <div class="poke-mini-stats tw-mb-2.5">${miniStats}</div>
                            <p class="poke-back-desc tw-mb-3">${escapeHtml(p.flavor_text)}</p>
                            <a href="${detailUrl}" class="poke-details-btn tw-mt-auto tw-w-full">
                                More Details <i class="bi bi-arrow-right ms-1"></i>
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    // -------------------------------------------------------------------------
    // 5. Touch & Keyboard 3D Card Flip Interaction
    // -------------------------------------------------------------------------
    function initCardFlipInteractions(gridEl) {
        if (!gridEl) return;

        gridEl.addEventListener('click', (event) => {
            if (event.target.closest('a.poke-details-btn')) {
                return;
            }

            const cardScene = event.target.closest('.poke-card-scene');
            if (!cardScene) return;

            const wasFlipped = cardScene.classList.contains('is-flipped');

            gridEl.querySelectorAll('.poke-card-scene.is-flipped').forEach((el) => {
                if (el !== cardScene) el.classList.remove('is-flipped');
            });

            cardScene.classList.toggle('is-flipped', !wasFlipped);
        });

        gridEl.addEventListener('keydown', (event) => {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            if (event.target.closest('a.poke-details-btn')) return;

            const cardScene = event.target.closest('.poke-card-scene');
            if (!cardScene) return;

            event.preventDefault();
            cardScene.classList.toggle('is-flipped');
        });
    }

    // -------------------------------------------------------------------------
    // 6. Smart Page Range Builder (e.g. [1, '...', 4, 5, 6, 7, 8, '...', 52])
    // -------------------------------------------------------------------------
    function buildPageSequence(currentPage, totalPages) {
        if (totalPages <= 7) {
            return Array.from({ length: totalPages }, (_, i) => i + 1);
        }

        const pages = [1];
        const left = Math.max(2, currentPage - 1);
        const right = Math.min(totalPages - 1, currentPage + 1);

        if (left > 2) {
            pages.push('ellipsis');
        }
        for (let p = left; p <= right; p++) {
            pages.push(p);
        }
        if (right < totalPages - 1) {
            pages.push('ellipsis');
        }
        pages.push(totalPages);

        return pages;
    }

    // -------------------------------------------------------------------------
    // 7. Home Page: Filters, Sorting & Strict 20-per-page Pagination
    // -------------------------------------------------------------------------
    function initHomeGridController() {
        const gridEl = document.getElementById('pokemonGrid');
        const searchInput = document.getElementById('searchInput');
        const searchForm = document.getElementById('navbarSearchForm');
        const clearSearchBtn = document.getElementById('clearSearchBtn');

        // On detail/404 pages, navbar search redirects to home with ?search=
        if (!gridEl) {
            if (searchForm && searchInput) {
                searchForm.addEventListener('submit', (e) => {
                    e.preventDefault();
                    const q = searchInput.value.trim();
                    window.location.href = q ? `/?search=${encodeURIComponent(q)}` : '/';
                });
            }
            return;
        }

        const gridSectionEl = document.getElementById('pokedexGridSection');
        const skeletonEl = document.getElementById('skeletonGrid');
        const emptyStateEl = document.getElementById('emptyState');
        const typeFilterBar = document.getElementById('typeFilterBar');
        const sortSelect = document.getElementById('sortSelect');

        // Advanced filter elements
        const generationFilter = document.getElementById('generationFilter');
        const rarityFilter = document.getElementById('rarityFilter');
        const eggGroupFilter = document.getElementById('eggGroupFilter');
        const colorFilter = document.getElementById('colorFilter');
        const habitatFilter = document.getElementById('habitatFilter');
        const minStatFilter = document.getElementById('minStatFilter');
        const clearAllFiltersBtn = document.getElementById('clearAllFiltersBtn');
        const activeFilterCountEl = document.getElementById('activeFilterCount');

        // Pagination elements
        const paginationWrapper = document.getElementById('paginationWrapper');
        const paginationList = document.getElementById('paginationList');
        const pageMetaEl = document.getElementById('pageMeta');
        const jumpPageForm = document.getElementById('jumpPageForm');
        const jumpPageInput = document.getElementById('jumpPageInput');
        const rangeTextEl = document.getElementById('rangeText');
        const totalCountEl = document.getElementById('totalCount');
        const resetFiltersBtn = document.getElementById('resetFiltersBtn');

        let initial = {
            page: 1,
            limit: 20,
            total: 0,
            totalPages: 1,
            startIndex: 0,
            endIndex: 0,
        };
        const stateScript = document.getElementById('initialPokedexState');
        if (stateScript) {
            try {
                initial = Object.assign(initial, JSON.parse(stateScript.textContent));
            } catch (_err) {
                // ignore malformed JSON
            }
        }

        const state = {
            search: '',
            type: 'all',
            generation: 'all',
            rarity: 'all',
            egg_group: 'all',
            color: 'all',
            habitat: 'all',
            min_stat: '0',
            sort: 'id_asc',
            page: initial.page,
            limit: 20, // strictly 20 Pokémon per page
            total: initial.total,
            totalPages: initial.totalPages,
            startIndex: initial.startIndex,
            endIndex: initial.endIndex,
            loading: false,
        };

        let activeController = null;

        function setSkeletonVisible(visible) {
            if (!skeletonEl) return;
            skeletonEl.classList.toggle('tw-hidden', !visible);
            gridEl.classList.toggle('tw-hidden', visible);
            if (visible && emptyStateEl) {
                emptyStateEl.classList.add('tw-hidden');
            }
        }

        function syncClearSearchBtn() {
            if (!clearSearchBtn || !searchInput) return;
            clearSearchBtn.classList.toggle('tw-hidden', searchInput.value.trim().length === 0);
        }

        function syncActiveFilterIndicators() {
            let count = 0;
            if (state.search) count++;
            if (state.type !== 'all') count++;
            if (state.generation !== 'all') count++;
            if (state.rarity !== 'all') count++;
            if (state.egg_group !== 'all') count++;
            if (state.color !== 'all') count++;
            if (state.habitat !== 'all') count++;
            if (state.min_stat !== '0') count++;

            const selectPairs = [
                [generationFilter, state.generation !== 'all'],
                [rarityFilter, state.rarity !== 'all'],
                [eggGroupFilter, state.egg_group !== 'all'],
                [colorFilter, state.color !== 'all'],
                [habitatFilter, state.habitat !== 'all'],
                [minStatFilter, state.min_stat !== '0'],
            ];
            selectPairs.forEach(([el, active]) => {
                if (el) el.classList.toggle('is-filtered', active);
            });

            if (activeFilterCountEl) activeFilterCountEl.textContent = String(count);
            if (clearAllFiltersBtn) clearAllFiltersBtn.classList.toggle('tw-hidden', count === 0);
        }

        function syncUrlQueryParams() {
            const params = new URLSearchParams();
            if (state.search) params.set('search', state.search);
            if (state.type !== 'all') params.set('type', state.type);
            if (state.generation !== 'all') params.set('generation', state.generation);
            if (state.rarity !== 'all') params.set('rarity', state.rarity);
            if (state.egg_group !== 'all') params.set('egg_group', state.egg_group);
            if (state.color !== 'all') params.set('color', state.color);
            if (state.habitat !== 'all') params.set('habitat', state.habitat);
            if (state.min_stat !== '0') params.set('min_stat', state.min_stat);
            if (state.sort !== 'id_asc') params.set('sort', state.sort);
            if (state.page > 1) params.set('page', String(state.page));

            const qs = params.toString();
            const nextUrl = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
            window.history.replaceState(null, '', nextUrl);
        }

        function renderPagination() {
            if (!paginationWrapper || !paginationList) return;

            if (state.total === 0) {
                paginationWrapper.classList.add('tw-hidden');
                return;
            }
            paginationWrapper.classList.remove('tw-hidden');

            const itemsHtml = [];

            // Previous button
            itemsHtml.push(`
                <li>
                    <button type="button" class="page-pill" data-page="${state.page - 1}" ${state.page <= 1 ? 'disabled' : ''} aria-label="Previous page">
                        <i class="bi bi-chevron-left"></i>
                        <span class="d-none d-sm-inline">Prev</span>
                    </button>
                </li>
            `);

            // Numbered page buttons with ellipses
            const seq = buildPageSequence(state.page, state.totalPages);
            for (const entry of seq) {
                if (entry === 'ellipsis') {
                    itemsHtml.push('<li class="page-ellipsis" aria-hidden="true">…</li>');
                } else {
                    const isActive = entry === state.page;
                    itemsHtml.push(`
                        <li>
                            <button
                                type="button"
                                class="page-pill tw-font-mono ${isActive ? 'active' : ''}"
                                data-page="${entry}"
                                ${isActive ? 'aria-current="page"' : ''}
                            >
                                ${entry}
                            </button>
                        </li>
                    `);
                }
            }

            // Next button
            itemsHtml.push(`
                <li>
                    <button type="button" class="page-pill" data-page="${state.page + 1}" ${state.page >= state.totalPages ? 'disabled' : ''} aria-label="Next page">
                        <span class="d-none d-sm-inline">Next</span>
                        <i class="bi bi-chevron-right"></i>
                    </button>
                </li>
            `);

            paginationList.innerHTML = itemsHtml.join('');

            if (pageMetaEl) {
                pageMetaEl.textContent = `Page ${state.page} of ${state.totalPages} • ${state.limit} per page`;
            }
            if (jumpPageInput) {
                jumpPageInput.max = String(state.totalPages);
                jumpPageInput.value = String(state.page);
            }
        }

        function updateCounters() {
            if (rangeTextEl) {
                rangeTextEl.textContent =
                    state.total > 0 ? `${state.startIndex}–${state.endIndex}` : '0';
            }
            if (totalCountEl) {
                totalCountEl.textContent = state.total.toLocaleString();
            }
            if (emptyStateEl) {
                emptyStateEl.classList.toggle('tw-hidden', state.total > 0);
            }
            renderPagination();
            syncActiveFilterIndicators();
        }

        async function fetchPage({ scrollToGrid = false } = {}) {
            if (activeController) {
                activeController.abort();
            }
            activeController = new AbortController();
            state.loading = true;
            setSkeletonVisible(true);

            const params = new URLSearchParams({
                page: String(state.page),
                limit: String(state.limit),
                sort: state.sort,
            });
            if (state.search) params.set('search', state.search);
            if (state.type !== 'all') params.set('type', state.type);
            if (state.generation !== 'all') params.set('generation', state.generation);
            if (state.rarity !== 'all') params.set('rarity', state.rarity);
            if (state.egg_group !== 'all') params.set('egg_group', state.egg_group);
            if (state.color !== 'all') params.set('color', state.color);
            if (state.habitat !== 'all') params.set('habitat', state.habitat);
            if (state.min_stat !== '0') params.set('min_stat', state.min_stat);

            syncUrlQueryParams();

            try {
                const response = await fetch(`/api/pokemon?${params.toString()}`, {
                    signal: activeController.signal,
                    headers: { Accept: 'application/json' },
                });
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                const data = await response.json();

                state.page = data.page;
                state.total = data.total;
                state.totalPages = data.total_pages;
                state.startIndex = data.start_index;
                state.endIndex = data.end_index;

                // Strictly replace grid with ONLY the current page's 20 Pokémon
                gridEl.innerHTML = (data.items || [])
                    .map((item, i) => renderPokemonCardColumn(item, i))
                    .join('');

                updateCounters();

                if (scrollToGrid && gridSectionEl) {
                    const top = gridSectionEl.getBoundingClientRect().top + window.scrollY - 84;
                    window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
                }

                if (typeof AOS !== 'undefined') {
                    AOS.refreshHard();
                }
            } catch (err) {
                if (err.name === 'AbortError') return;
                console.error('Failed to fetch Pokémon page:', err);
            } finally {
                state.loading = false;
                setSkeletonVisible(false);
            }
        }

        function goToPage(targetPage) {
            const clamped = Math.max(1, Math.min(state.totalPages, Number(targetPage) || 1));
            if (clamped === state.page && !state.loading) return;
            state.page = clamped;
            fetchPage({ scrollToGrid: true });
        }

        function resetAllFilters() {
            if (searchInput) searchInput.value = '';
            syncClearSearchBtn();
            if (sortSelect) sortSelect.value = 'id_asc';
            if (generationFilter) generationFilter.value = 'all';
            if (rarityFilter) rarityFilter.value = 'all';
            if (eggGroupFilter) eggGroupFilter.value = 'all';
            if (colorFilter) colorFilter.value = 'all';
            if (habitatFilter) habitatFilter.value = 'all';
            if (minStatFilter) minStatFilter.value = '0';
            if (typeFilterBar) {
                typeFilterBar.querySelectorAll('.type-chip').forEach((c) => {
                    c.classList.toggle('active', c.dataset.type === 'all');
                });
            }

            state.search = '';
            state.type = 'all';
            state.generation = 'all';
            state.rarity = 'all';
            state.egg_group = 'all';
            state.color = 'all';
            state.habitat = 'all';
            state.min_stat = '0';
            state.sort = 'id_asc';
            state.page = 1;
            fetchPage({ scrollToGrid: false });
        }

        // Event Listeners: Search
        if (searchForm) {
            searchForm.addEventListener('submit', (e) => e.preventDefault());
        }

        if (searchInput) {
            const onSearchChange = debounce(() => {
                state.search = searchInput.value.trim();
                state.page = 1;
                fetchPage({ scrollToGrid: false });
            }, 260);

            searchInput.addEventListener('input', () => {
                syncClearSearchBtn();
                onSearchChange();
            });
        }

        if (clearSearchBtn && searchInput) {
            clearSearchBtn.addEventListener('click', () => {
                searchInput.value = '';
                syncClearSearchBtn();
                state.search = '';
                state.page = 1;
                fetchPage({ scrollToGrid: false });
                searchInput.focus();
            });
        }

        // Event Listeners: Type Chips
        if (typeFilterBar) {
            typeFilterBar.addEventListener('click', (event) => {
                const chip = event.target.closest('.type-chip');
                if (!chip) return;

                const selectedType = chip.dataset.type || 'all';
                if (selectedType === state.type) return;

                typeFilterBar.querySelectorAll('.type-chip').forEach((c) => c.classList.remove('active'));
                chip.classList.add('active');

                state.type = selectedType;
                state.page = 1;
                fetchPage({ scrollToGrid: false });
            });
        }

        // Event Listeners: Advanced Filter Dropdowns
        const dropdownBindings = [
            [generationFilter, 'generation'],
            [rarityFilter, 'rarity'],
            [eggGroupFilter, 'egg_group'],
            [colorFilter, 'color'],
            [habitatFilter, 'habitat'],
            [minStatFilter, 'min_stat'],
            [sortSelect, 'sort'],
        ];
        dropdownBindings.forEach(([el, key]) => {
            if (!el) return;
            el.addEventListener('change', () => {
                state[key] = el.value;
                state.page = 1;
                fetchPage({ scrollToGrid: false });
            });
        });

        // Event Listeners: Clear / Reset Filters
        if (clearAllFiltersBtn) {
            clearAllFiltersBtn.addEventListener('click', resetAllFilters);
        }
        if (resetFiltersBtn) {
            resetFiltersBtn.addEventListener('click', resetAllFilters);
        }

        // Event Listeners: Numbered Pagination & Jump-to-Page
        if (paginationList) {
            paginationList.addEventListener('click', (event) => {
                const btn = event.target.closest('button.page-pill[data-page]');
                if (!btn || btn.disabled || btn.classList.contains('active')) return;
                goToPage(btn.dataset.page);
            });
        }

        if (jumpPageForm && jumpPageInput) {
            jumpPageForm.addEventListener('submit', (event) => {
                event.preventDefault();
                goToPage(jumpPageInput.value);
            });
        }

        // Restore filters & page from URL query string (deep links / browser Back)
        const urlParams = new URLSearchParams(window.location.search);
        let needsFetchFromUrl = false;

        const paramSetters = [
            ['type', (val) => {
                const lower = val.toLowerCase();
                const chip = typeFilterBar && typeFilterBar.querySelector(`.type-chip[data-type="${CSS.escape(lower)}"]`);
                if (chip) {
                    typeFilterBar.querySelectorAll('.type-chip').forEach((c) => c.classList.remove('active'));
                    chip.classList.add('active');
                    state.type = lower;
                    needsFetchFromUrl = true;
                }
            }],
            ['search', (val) => {
                if (searchInput) {
                    searchInput.value = val;
                    syncClearSearchBtn();
                    state.search = val;
                    needsFetchFromUrl = true;
                }
            }],
            ['generation', (val) => {
                if (generationFilter && [...generationFilter.options].some((o) => o.value === val)) {
                    generationFilter.value = val;
                    state.generation = val;
                    needsFetchFromUrl = true;
                }
            }],
            ['rarity', (val) => {
                if (rarityFilter && [...rarityFilter.options].some((o) => o.value === val)) {
                    rarityFilter.value = val;
                    state.rarity = val;
                    needsFetchFromUrl = true;
                }
            }],
            ['egg_group', (val) => {
                if (eggGroupFilter && [...eggGroupFilter.options].some((o) => o.value === val)) {
                    eggGroupFilter.value = val;
                    state.egg_group = val;
                    needsFetchFromUrl = true;
                }
            }],
            ['color', (val) => {
                if (colorFilter && [...colorFilter.options].some((o) => o.value === val)) {
                    colorFilter.value = val;
                    state.color = val;
                    needsFetchFromUrl = true;
                }
            }],
            ['habitat', (val) => {
                if (habitatFilter && [...habitatFilter.options].some((o) => o.value === val)) {
                    habitatFilter.value = val;
                    state.habitat = val;
                    needsFetchFromUrl = true;
                }
            }],
            ['min_stat', (val) => {
                if (minStatFilter && [...minStatFilter.options].some((o) => o.value === val)) {
                    minStatFilter.value = val;
                    state.min_stat = val;
                    needsFetchFromUrl = true;
                }
            }],
            ['sort', (val) => {
                if (sortSelect && [...sortSelect.options].some((o) => o.value === val)) {
                    sortSelect.value = val;
                    state.sort = val;
                    needsFetchFromUrl = true;
                }
            }],
            ['page', (val) => {
                const parsed = parseInt(val, 10);
                if (!Number.isNaN(parsed) && parsed > 1) {
                    state.page = parsed;
                    needsFetchFromUrl = true;
                }
            }],
        ];

        paramSetters.forEach(([key, apply]) => {
            const val = (urlParams.get(key) || '').trim();
            if (val) apply(val);
        });

        // Initial pagination bar render
        renderPagination();
        syncActiveFilterIndicators();
        initCardFlipInteractions(gridEl);

        if (needsFetchFromUrl) {
            fetchPage({ scrollToGrid: false });
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        initThemeToggle();
        initAOS();
        initBackToTop();
        initDetailStatBars();
        initHomeGridController();
    });
})();
