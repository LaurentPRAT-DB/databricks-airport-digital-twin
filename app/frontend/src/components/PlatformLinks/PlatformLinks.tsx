import { useState, useEffect } from 'react';

interface PlatformConfig {
  workspace_url: string;
  catalog: string;
  schema: string;
  dashboard_id: string;
  genie_space_id: string;
  lakebase_project_id: string;
}

interface PlatformLink {
  id: string;
  label: string;
  icon: string;
  url: string;
  description: string;
}

function buildLinks(cfg: PlatformConfig): PlatformLink[] {
  const w = cfg.workspace_url;
  return [
    {
      id: 'dashboard',
      label: 'Flight Dashboard',
      icon: '📊',
      url: `${w}/sql/dashboardsv3/${cfg.dashboard_id}/pages/overview`,
      description: 'View real-time flight metrics in Lakeview',
    },
    {
      id: 'genie',
      label: 'Airport Ops Genie',
      icon: '🗣️',
      url: `${w}/genie/spaces/${cfg.genie_space_id}`,
      description: 'Ask natural language questions about flight ops',
    },
    {
      id: 'mlflow',
      label: 'ML Experiments',
      icon: '📈',
      url: `${w}/ml/experiments`,
      description: 'View model experiments in MLflow',
    },
    {
      id: 'catalog',
      label: 'Unity Catalog',
      icon: '📁',
      url: `${w}/explore/data/${cfg.catalog}/${cfg.schema}`,
      description: 'Browse tables in Unity Catalog',
    },
    {
      id: 'lakebase',
      label: 'Lakebase',
      icon: '🐘',
      url: `${w}/lakebase/projects/${cfg.lakebase_project_id}`,
      description: 'Manage Lakebase PostgreSQL endpoint',
    },
  ];
}

export default function PlatformLinks() {
  const [isOpen, setIsOpen] = useState(false);
  const [links, setLinks] = useState<PlatformLink[]>([]);

  useEffect(() => {
    fetch('/api/config')
      .then(res => res.json())
      .then(data => {
        if (data.platform?.workspace_url) {
          setLinks(buildLinks(data.platform));
        }
      })
      .catch(() => {}); // silent — links just won't appear
  }, []);

  if (links.length === 0) return null;

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors"
        title="Databricks Platform Links"
      >
        <span className="text-lg">🔧</span>
        <span className="text-sm font-medium">Platform</span>
        <svg
          className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
          />

          {/* Dropdown */}
          <div className="absolute right-0 mt-2 w-72 bg-slate-800 rounded-lg shadow-xl z-50 border border-slate-700 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-700">
              <h3 className="text-sm font-semibold text-slate-200">Databricks Platform</h3>
              <p className="text-xs text-slate-400 mt-0.5">Access platform features</p>
            </div>

            <div className="py-2">
              {links.map((link) => (
                <a
                  key={link.id}
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-start gap-3 px-4 py-2.5 hover:bg-slate-700 transition-colors"
                  onClick={() => setIsOpen(false)}
                >
                  <span className="text-xl">{link.icon}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-slate-200">{link.label}</div>
                    <div className="text-xs text-slate-400 truncate">{link.description}</div>
                  </div>
                  <svg
                    className="w-4 h-4 text-slate-500 flex-shrink-0 mt-0.5"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
                    />
                  </svg>
                </a>
              ))}
            </div>

            <div className="px-4 py-2 border-t border-slate-700 bg-slate-800/50">
              <p className="text-xs text-slate-500">
                Links open in new tabs
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
