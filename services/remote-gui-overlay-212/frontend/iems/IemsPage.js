// IEMS plugin page for AnyLog remote-gui.
//
// The IEMS live dashboard is a self-contained page: its own stylesheet, its own
// markup and a controller that draws the SVG charts and drives the polling.
// Rather than re-implement that in React and let the two drift apart, this page
// mounts the generated module in ./iems_dash.js, which carries the dashboard's
// own CSS, markup and controller with DOM access scoped to this page and its
// network calls routed through the plugin's proxy routes.

import React, { useEffect, useRef, useState } from 'react';
import { getApiBaseUrl } from '../../utils/runtimeConfig';
import { DASH_HTML, injectDashStyle, mountIemsDashboard } from './iems_dash';

// No icon: the sidebar renders `{item.icon && ...}{item.name}`, so omitting it
// leaves a plain text entry like the rest of the GUI's navigation.
export const pluginMetadata = {
  name: 'IEMS',
};

const IemsPage = () => {
  const hostRef = useRef(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;

    let unmount = null;
    try {
      injectDashStyle();
      host.innerHTML = DASH_HTML;
      unmount = mountIemsDashboard(host, getApiBaseUrl());
    } catch (err) {
      setError(err && err.message ? err.message : String(err));
    }

    return () => {
      try {
        if (typeof unmount === 'function') unmount();
      } catch (err) {
        /* tearing down a page that already failed is not worth reporting */
      }
      if (host) host.innerHTML = '';
    };
  }, []);

  return (
    <div style={{ height: '100%', width: '100%', overflow: 'auto' }}>
      {error && (
        <div
          style={{
            margin: '12px 16px',
            padding: '10px 14px',
            border: '1px solid #a64f3a',
            borderRadius: 8,
            color: '#a64f3a',
            fontFamily: 'ui-monospace, monospace',
            fontSize: 12,
          }}
        >
          IEMS page failed to start: {error}
        </div>
      )}
      <div className="iems-dash-root" ref={hostRef} />
    </div>
  );
};

export default IemsPage;
