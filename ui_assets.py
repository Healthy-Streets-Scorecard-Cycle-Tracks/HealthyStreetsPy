from shiny import ui


def map_bridge_script() -> ui.Tag:
    return ui.tags.script(
        """
        function hssLoadPrefs() {
            try {
                return JSON.parse(localStorage.getItem('hss_prefs_v1') || '{}');
            } catch (e) {
                return {};
            }
        }
        function hssSavePrefs(prefs) {
            try {
                localStorage.setItem('hss_prefs_v1', JSON.stringify(prefs || {}));
            } catch (e) {
                return;
            }
        }
        function hssUpdatePref(key, value) {
            const prefs = hssLoadPrefs();
            prefs[key] = value;
            hssSavePrefs(prefs);
        }
        function hssApplyInputValue(id, value) {
            const el = document.getElementById(id);
            if (!el) return false;
            if (el.value === value) return true;
            el.value = value;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }
        function hssApplySelectSafe(id, value) {
            const el = document.getElementById(id);
            if (!el) return false;
            const options = Array.from(el.options || []).map(opt => opt.value);
            if (!options.includes(value)) return false;
            return hssApplyInputValue(id, value);
        }
        function hssApplyNumberSafe(id, value, min, max) {
            const el = document.getElementById(id);
            if (!el) return false;
            const num = Number(value);
            if (!Number.isFinite(num)) return false;
            if (min !== null && num < min) return false;
            if (max !== null && num > max) return false;
            return hssApplyInputValue(id, String(num));
        }
        function hssApplyDateSafe(id, value) {
            if (!value || typeof value !== 'string') return false;
            if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
            return hssApplyInputValue(id, value);
        }

        window.addEventListener('message', function(event) {
            if (!event || !event.data || !event.data.type) return;
            if (!window.Shiny || !window.Shiny.setInputValue) return;
            const type = event.data.type;
            const payload = event.data.payload;
            if (['selected_route', 'edited_geojson', 'created_geojson', 'map_click'].includes(type)) {
                console.log('HSS parent received', type, payload);
            }
            if (type === 'basemap_change') {
                if (payload && payload.name) {
                    hssUpdatePref('basemap', payload.name);
                }
                return;
            }
            if (type === 'overlay_change') {
                if (payload && payload.name) {
                    const prefs = hssLoadPrefs();
                    const overlays = prefs.overlays || {};
                    overlays[payload.name] = !!payload.visible;
                    prefs.overlays = overlays;
                    hssSavePrefs(prefs);
                }
                return;
            }
            if (['selected_route', 'edited_geojson', 'created_geojson', 'map_click'].includes(type)) {
                console.log('HSS parent forwarding to Shiny', type);
                window.Shiny.setInputValue(type, payload, {priority: 'event'});
            }
        });
        function hssSendHighlightToIframe(payload) {
            const iframe = document.querySelector('iframe');
            if (!iframe || !iframe.contentWindow) {
                console.log('HSS parent highlight: iframe missing');
                return false;
            }
            iframe.contentWindow.postMessage({ type: 'set_highlight', payload: payload }, '*');
            return true;
        }

        function hssSendSelectToIframe(payload) {
            const iframe = document.querySelector('iframe');
            if (!iframe || !iframe.contentWindow) {
                return false;
            }
            let message = payload;
            if (typeof payload === 'string') {
                message = { guid: payload };
            }
            if (!message || !message.guid) return false;
            iframe.contentWindow.postMessage({ type: 'select_route', payload: message }, '*');
            return true;
        }

        function hssActivateMapTab() {
            const mapTab = document.querySelector('[data-value="Map"]') || document.querySelector('a.nav-link[data-value="Map"]');
            if (mapTab && typeof mapTab.click === 'function') {
                mapTab.click();
                return true;
            }
            return false;
        }

        if (window.Shiny && window.Shiny.addCustomMessageHandler) {
            window.Shiny.addCustomMessageHandler('hss_set_highlight', function(payload) {
                console.log('HSS parent received hss_set_highlight', payload);
                window.hssLastHighlightPayload = payload;
                hssSendHighlightToIframe(payload);
            });
            window.Shiny.addCustomMessageHandler('hss_nav_to_map', function(payload) {
                const guid = payload && payload.guid ? payload.guid : null;
                const message = payload || (guid ? { guid: guid } : null);
                window.hssPendingSelect = message;
                hssActivateMapTab();
                if (message) {
                    hssSendSelectToIframe(message);
                }
            });
            window.Shiny.addCustomMessageHandler('hss_select_route', function(payload) {
                const iframe = document.querySelector('iframe');
                if (!iframe || !iframe.contentWindow) return;
                iframe.contentWindow.postMessage({ type: 'select_route', payload: payload }, '*');
            });
            window.Shiny.addCustomMessageHandler('hss_clear_selection', function(payload) {
                const iframe = document.querySelector('iframe');
                if (!iframe || !iframe.contentWindow) return;
                iframe.contentWindow.postMessage({ type: 'clear_selection', payload: payload || {} }, '*');
            });
            window.Shiny.addCustomMessageHandler('hss_update_style', function(payload) {
                console.log('HSS parent received hss_update_style', payload);
                const iframe = document.querySelector('iframe');
                if (!iframe || !iframe.contentWindow) {
                    console.log('HSS parent update_style: iframe missing');
                    return;
                }
                iframe.contentWindow.postMessage({ type: 'update_style', payload: payload }, '*');
                console.log('HSS parent update_style: forwarded to iframe');
            });
            window.Shiny.addCustomMessageHandler('hss_set_route_style', function(payload) {
                console.log('HSS parent received hss_set_route_style', payload);
                const iframe = document.querySelector('iframe');
                if (!iframe || !iframe.contentWindow) return;
                iframe.contentWindow.postMessage({ type: 'set_route_style', payload: payload }, '*');
            });
            window.Shiny.addCustomMessageHandler('hss_replace_geometry', function(payload) {
                console.log('HSS parent received hss_replace_geometry', payload);
                const iframe = document.querySelector('iframe');
                if (!iframe || !iframe.contentWindow) return;
                iframe.contentWindow.postMessage({ type: 'replace_geometry', payload: payload }, '*');
            });
            window.Shiny.addCustomMessageHandler('hss_created_update', function(payload) {
                console.log('HSS parent received hss_created_update', payload);
                const iframe = document.querySelector('iframe');
                if (!iframe || !iframe.contentWindow) return;
                iframe.contentWindow.postMessage({ type: 'created_update', payload: payload }, '*');
            });
            window.Shiny.addCustomMessageHandler('hss_discard_created', function(payload) {
                console.log('HSS parent received hss_discard_created', payload);
                const iframe = document.querySelector('iframe');
                if (!iframe || !iframe.contentWindow) return;
                iframe.contentWindow.postMessage({ type: 'discard_created', payload: payload }, '*');
            });
            window.Shiny.addCustomMessageHandler('hss_set_disabled', function(payload) {
                if (!payload || !payload.id) return;
                const el = document.getElementById(payload.id);
                if (!el) return;
                el.disabled = !!payload.disabled;
            });
        }

        function hssHookIframeLoad() {
            const iframe = document.querySelector('iframe');
            if (!iframe) return;
            if (iframe.dataset.hssBound) return;
            iframe.dataset.hssBound = "true";
            iframe.addEventListener('load', function() {
                const prefs = hssLoadPrefs();
                if (prefs.basemap) {
                    iframe.contentWindow.postMessage({ type: 'set_basemap', payload: { name: prefs.basemap } }, '*');
                }
                if (prefs.overlays) {
                    iframe.contentWindow.postMessage({ type: 'set_overlays', payload: { overlays: prefs.overlays } }, '*');
                }
                if (window.hssLastHighlightPayload) {
                    console.log('HSS parent iframe load: reapplying highlight');
                    hssSendHighlightToIframe(window.hssLastHighlightPayload);
                }
                if (window.hssPendingSelect) {
                    hssSendSelectToIframe(window.hssPendingSelect);
                }
            });

            const styleControls = document.querySelector('.hss-map-style-controls');
            if (styleControls) {
                styleControls.addEventListener('mouseenter', function() {
                    if (iframe) iframe.style.pointerEvents = 'none';
                });
                styleControls.addEventListener('mouseleave', function() {
                    if (iframe) iframe.style.pointerEvents = 'auto';
                });
            }
        }

        document.addEventListener('DOMContentLoaded', function() {
            hssHookIframeLoad();
            const observer = new MutationObserver(function() {
                hssHookIframeLoad();
            });
            observer.observe(document.body, { childList: true, subtree: true });

            const prefs = hssLoadPrefs();
            if (prefs.route_scheme) hssApplySelectSafe('route_scheme', prefs.route_scheme);
            if (prefs.route_width !== undefined) hssApplyNumberSafe('route_width', prefs.route_width, 1, 12);
            if (prefs.highlight_mode) hssApplySelectSafe('highlight_mode', prefs.highlight_mode);
            if (prefs.highlight_dim !== undefined) hssApplyNumberSafe('highlight_dim', prefs.highlight_dim, 0, 80);
            if (prefs.highlight_date) hssApplyDateSafe('highlight_date', prefs.highlight_date);
            if (prefs.highlight_owner) hssApplySelectSafe('highlight_owner', prefs.highlight_owner);
            if (prefs.highlight_audit) hssApplySelectSafe('highlight_audit', prefs.highlight_audit);

            if (window.Shiny && window.Shiny.setInputValue) {
                if (prefs.route_scheme) window.Shiny.setInputValue('route_scheme', prefs.route_scheme, {priority: 'event'});
                if (prefs.route_width !== undefined) window.Shiny.setInputValue('route_width', prefs.route_width, {priority: 'event'});
                if (prefs.highlight_mode) window.Shiny.setInputValue('highlight_mode', prefs.highlight_mode, {priority: 'event'});
                if (prefs.highlight_dim !== undefined) window.Shiny.setInputValue('highlight_dim', prefs.highlight_dim, {priority: 'event'});
                if (prefs.highlight_date) window.Shiny.setInputValue('highlight_date', prefs.highlight_date, {priority: 'event'});
                if (prefs.highlight_owner) window.Shiny.setInputValue('highlight_owner', prefs.highlight_owner, {priority: 'event'});
                if (prefs.highlight_audit) window.Shiny.setInputValue('highlight_audit', prefs.highlight_audit, {priority: 'event'});
            }

            const regionValue = prefs.region || null;
            (function sendRegionPref(attempt) {
                if (window.Shiny && window.Shiny.setInputValue) {
                    window.Shiny.setInputValue('region_pref', regionValue, {priority: 'event'});
                    return;
                }
                if (attempt >= 40) return;
                setTimeout(function() { sendRegionPref(attempt + 1); }, 50);
            })(0);
            if (regionValue && !window.hssRegionPrefApplied) {
                window.hssRegionPrefApplied = false;
                const regionObserver = new MutationObserver(function() {
                    if (window.hssRegionPrefApplied) {
                        regionObserver.disconnect();
                        return;
                    }
                    const el = document.getElementById('region');
                    if (!el || el.dataset.hssPrefApplied === '1') return;
                    const options = Array.from(el.options || []).map(opt => opt.value);
                    if (options.includes(regionValue)) {
                        hssApplyInputValue('region', regionValue);
                        el.dataset.hssPrefApplied = '1';
                        window.hssRegionPrefApplied = true;
                        regionObserver.disconnect();
                    }
                });
                regionObserver.observe(document.body, { childList: true, subtree: true });
            }

            document.addEventListener('change', function(ev) {
                const target = ev.target;
                if (!target || !target.id) return;
                if (target.id === 'route_scheme') hssUpdatePref('route_scheme', target.value);
                if (target.id === 'route_width') hssUpdatePref('route_width', target.value);
                if (target.id === 'highlight_mode') hssUpdatePref('highlight_mode', target.value);
                if (target.id === 'highlight_dim') hssUpdatePref('highlight_dim', target.value);
                if (target.id === 'highlight_date') hssUpdatePref('highlight_date', target.value);
                if (target.id === 'highlight_owner') hssUpdatePref('highlight_owner', target.value);
                if (target.id === 'highlight_audit') hssUpdatePref('highlight_audit', target.value);
                if (target.id === 'region') hssUpdatePref('region', target.value);
            });
        });

        function hssStartDraw() {
            const iframe = document.querySelector('iframe');
            if (!iframe || !iframe.contentWindow) return;
            iframe.contentWindow.postMessage({ type: 'start_draw' }, '*');
        }
        """
    )


def app_styles() -> ui.Tag:
    return ui.tags.style(
        """
        html, body {
            margin: 0;
            padding: 0;
            height: 100%;
        }
        .container-fluid {
            padding-left: 0 !important;
            padding-right: 0 !important;
        }
        .bslib-page-fill {
            padding: 0 !important;
        }
        .hss-metrics-list {
            list-style: none;
            padding-left: 0;
            margin: 8px 0 0 0;
            display: grid;
            grid-template-columns: 1fr;
            gap: 6px;
        }
        .hss-metrics-list li {
            font-size: 14px;
            display: flex;
            justify-content: space-between;
            padding: 4px 6px;
            border-radius: 6px;
            background: #f7f7f7;
        }
        .hss-metrics-list .metric-label {
            color: #555;
        }
        .hss-metrics-list .metric-value {
            font-weight: 600;
        }
        .hss-map-wrap {
            position: relative;
            height: 100%;
        }
        .hss-map-wrap iframe {
            display: block;
            height: 100% !important;
        }
        .hss-map-add {
            position: absolute;
            top: 10px;
            left: 54px;
            z-index: 1000;
            width: 30px;
            height: 30px;
            padding: 0;
            font-size: 18px;
            line-height: 28px;
            border-radius: 6px;
            background: #ffffff;
            border: 1px solid #c9c9c9;
            font-weight: 600;
        }
        .hss-map-style-controls {
            position: absolute;
            left: 12px;
            bottom: 12px;
            z-index: 1000;
            display: flex;
            flex-direction: column;
            gap: 4px;
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid #d0d0d0;
            border-radius: 8px;
            padding: 4px 6px;
            width: 92px;
            pointer-events: auto;
        }
        .hss-map-style-controls * {
            pointer-events: auto;
        }
        .hss-map-style-controls .shiny-input-container {
            margin-bottom: 0 !important;
        }
        .hss-map-style-controls .form-label {
            display: none;
        }
        .hss-map-style-controls .shiny-input-container[data-input-type="slider"] {
            margin-top: -20px;
        }
        .hss-map-style-controls .irs {
            margin-top: -20px;
        }
        .hss-map-style-controls .form-select {
            font-size: 11px;
            padding: 1px 16px 1px 6px;
            height: 22px;
            width: 100%;
        }
        .hss-map-style-controls input[type="range"] {
            width: 100%;
            height: 18px;
        }
        .hss-map-style-controls output {
            display: none !important;
        }
        .hss-map-style-controls .irs-min,
        .hss-map-style-controls .irs-max,
        .hss-map-style-controls .irs-from,
        .hss-map-style-controls .irs-to,
        .hss-map-style-controls .irs-single {
            display: none !important;
        }
        .hss-map-style-controls output {
            display: none;
        }
        .sidebar .shiny-input-container,
        .card .shiny-input-container {
            margin-bottom: 0.2rem !important;
        }
        .sidebar .form-label,
        .card .form-label {
            margin-bottom: 0.1rem;
        }
        .sidebar .mb-3,
        .card .mb-3 {
            margin-bottom: 0.2rem !important;
        }
        .hss-save-discard {
            display: grid;
            gap: 0.35rem;
        }
        .hss-save-discard .btn {
            margin-bottom: 0;
        }
        .hss-change-summary {
            font-size: 0.85rem;
            color: #666;
        }
        """
    )


__all__ = ["map_bridge_script", "app_styles"]
