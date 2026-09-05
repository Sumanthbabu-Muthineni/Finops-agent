import React, { useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule } from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import { CsvExportButton } from './CsvExportButton';

// Register all community features
ModuleRegistry.registerModules([AllCommunityModule]);

export const FinancialAgGrid = ({ rowData }) => {
  if (!rowData || rowData.length === 0) return null;

  // Dynamically generate column definitions from row keys
  const columnDefs = useMemo(() => {
    const sample = rowData[0];
    const keys = Object.keys(sample);

    return keys
      .filter(key => key !== 'is_outlier') // Don't show is_outlier as a separate text column
      .map(key => {
        const headerName = key
          .split('_')
          .map(w => w.charAt(0).toUpperCase() + w.slice(1))
          .join(' ');

        const def = {
          field: key,
          headerName: headerName,
          sortable: true,
          filter: true,
          resizable: true,
          minWidth: 120
        };

        // Format currency/amount/balance columns
        if (key.toLowerCase().includes('amount') || key.toLowerCase().includes('balance')) {
          def.headerName = `${headerName} ($)`;
          def.valueFormatter = p => (p.value !== null && p.value !== undefined ? `$${Number(p.value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—');
          def.type = 'numericColumn';
          def.width = 145;
        }

        // Format date columns
        if (key.toLowerCase().includes('date') || key.toLowerCase().includes('day')) {
          def.width = 140;
          def.valueFormatter = p => p.value || '—';
        }

        // Format transaction type and status badges
        if (key.toLowerCase().includes('type') || key.toLowerCase().includes('status')) {
          def.width = 130;
          def.cellRenderer = p => {
            const val = String(p.value || '').toLowerCase();
            if (val === 'credit' || val === 'completed' || val === 'reconciled') {
              return <span style={{ color: '#34d399', fontWeight: 600, background: 'rgba(52, 211, 153, 0.12)', padding: '3px 8px', borderRadius: '4px', fontSize: '0.78rem' }}>CREDIT</span>;
            }
            if (val === 'debit') {
              return <span style={{ color: '#f87171', fontWeight: 600, background: 'rgba(248, 113, 113, 0.12)', padding: '3px 8px', borderRadius: '4px', fontSize: '0.78rem' }}>DEBIT</span>;
            }
            if (val === 'pending') {
              return <span style={{ color: '#fbbf24', fontWeight: 600, background: 'rgba(251, 191, 36, 0.12)', padding: '3px 8px', borderRadius: '4px', fontSize: '0.78rem' }}>PENDING</span>;
            }
            return <span style={{ color: '#94a3b8', fontWeight: 600 }}>{p.value}</span>;
          };
        }

        // Format masked account numbers
        if (key.toLowerCase().includes('account')) {
          def.width = 140;
          def.cellRenderer = p => (
            <code style={{ color: '#60a5fa', background: 'rgba(96, 165, 250, 0.1)', padding: '2px 6px', borderRadius: '4px', fontSize: '0.8rem' }}>
              {p.value}
            </code>
          );
        }

        // Format reference IDs
        if (key.toLowerCase().includes('reference') || key.toLowerCase().includes('ref')) {
          def.width = 150;
          def.cellRenderer = p => (
            <span style={{ color: '#e2e8f0', fontFamily: 'monospace', fontSize: '0.82rem' }}>
              {p.value || '—'}
            </span>
          );
        }

        return def;
      });
  }, [rowData]);

  // Highlight outlier rows with custom CSS class
  const rowClassRules = useMemo(() => ({
    'outlier-row': params => params.data?.is_outlier === true
  }), []);

  return (
    <div className="table-section">
      <div className="table-toolbar">
        <span className="table-title">Source Financial Records ({rowData.length} rows)</span>
        <CsvExportButton data={rowData} filename="finops_breakdown.csv" />
      </div>
      <div className="ag-theme-alpine-dark" style={{ height: 260, width: '100%' }}>
        <AgGridReact
          rowData={rowData}
          columnDefs={columnDefs}
          pagination={true}
          paginationPageSize={5}
          paginationPageSizeSelector={[5, 10, 25, 50]}
          rowClassRules={rowClassRules}
          animateRows={true}
          defaultColDef={{
            flex: 1,
            minWidth: 100,
          }}
        />
      </div>
    </div>
  );
};
