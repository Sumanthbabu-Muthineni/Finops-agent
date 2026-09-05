import React, { useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry, AllCommunityModule, ValidationModule } from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import { CsvExportButton } from './CsvExportButton';

// Register all community features and validation module
ModuleRegistry.registerModules([AllCommunityModule, ValidationModule]);

// Internal and duplicate schema columns to hide from the business UI
const INTERNAL_COLUMNS = new Set([
  'account_id',
  'entity_id',
  'transaction_id',
  'is_outlier',
  'masked_account_number', // account_number is already masked with ****<last_4>
  'masked_utr_number',     // utr_number is already masked with prefix...
  'amount',                // redundant with transaction_amount / available_balance
  'reference_id',          // redundant with transaction_reference_id
  'txn_year',
  'txn_month'
]);

// Preferred visual order for columns
const COLUMN_ORDER = [
  'bank_name',
  'account_number',
  'program_id',
  'available_balance',
  'transaction_amount',
  'transaction_type',
  'transaction_date',
  'transaction_day',
  'description',
  'transaction_reference_id',
  'utr_number'
];

export const FinancialAgGrid = ({ rowData }) => {
  if (!rowData || rowData.length === 0) return null;

  // Filter and sort column definitions cleanly
  const columnDefs = useMemo(() => {
    const sample = rowData[0];
    const availableKeys = Object.keys(sample).filter(key => !INTERNAL_COLUMNS.has(key));

    // Sort keys based on preferred order
    const sortedKeys = availableKeys.sort((a, b) => {
      const idxA = COLUMN_ORDER.indexOf(a);
      const idxB = COLUMN_ORDER.indexOf(b);
      if (idxA !== -1 && idxB !== -1) return idxA - idxB;
      if (idxA !== -1) return -1;
      if (idxB !== -1) return 1;
      return a.localeCompare(b);
    });

    return sortedKeys.map(key => {
      let headerName = key
        .split('_')
        .map(w => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' ');

      if (key === 'bank_name') headerName = 'Bank';
      if (key === 'account_number') headerName = 'Account Number';
      if (key === 'program_id') headerName = 'Program';
      if (key === 'transaction_type') headerName = 'Type';
      if (key === 'transaction_reference_id') headerName = 'Reference ID';
      if (key === 'utr_number') headerName = 'UTR';

      const def = {
        field: key,
        headerName: headerName,
        sortable: true,
        filter: true,
        resizable: true,
        minWidth: 120
      };

      // Format currency / balance / amount columns
      if (key.toLowerCase().includes('amount') || key.toLowerCase().includes('balance')) {
        def.headerName = `${headerName} ($)`;
        def.valueFormatter = p => (p.value !== null && p.value !== undefined ? `$${Number(p.value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—');
        def.type = 'numericColumn';
        def.width = 155;
      }

      // Format date columns
      if (key.toLowerCase().includes('date') || key.toLowerCase().includes('day')) {
        def.width = 145;
        def.valueFormatter = p => (p.value ? String(p.value).replace('T', ' ') : '—');
      }

      // Format transaction type badges
      if (key.toLowerCase().includes('type') || key.toLowerCase().includes('status')) {
        def.width = 120;
        def.cellRenderer = p => {
          const val = String(p.value || '').toLowerCase();
          if (val === 'credit' || val === 'completed' || val === 'reconciled') {
            return <span style={{ color: '#34d399', fontWeight: 600, background: 'rgba(52, 211, 153, 0.12)', padding: '3px 8px', borderRadius: '4px', fontSize: '0.78rem' }}>CREDIT</span>;
          }
          if (val === 'debit') {
            return <span style={{ color: '#f87171', fontWeight: 600, background: 'rgba(248, 113, 113, 0.12)', padding: '3px 8px', borderRadius: '4px', fontSize: '0.78rem' }}>DEBIT</span>;
          }
          return <span style={{ color: '#94a3b8', fontWeight: 600 }}>{p.value}</span>;
        };
      }

      // Format masked account numbers
      if (key === 'account_number') {
        def.width = 145;
        def.cellRenderer = p => (
          <code style={{ color: '#60a5fa', background: 'rgba(96, 165, 250, 0.12)', padding: '2px 7px', borderRadius: '4px', fontSize: '0.82rem', fontWeight: 600 }}>
            {p.value}
          </code>
        );
      }

      // Format reference IDs & UTRs
      if (key.includes('reference') || key.includes('utr')) {
        def.width = 150;
        def.cellRenderer = p => (
          <span style={{ color: '#e2e8f0', fontFamily: 'monospace', fontSize: '0.82rem' }}>
            {p.value || '—'}
          </span>
        );
      }

      // Format description column
      if (key === 'description') {
        def.minWidth = 220;
        def.flex = 2;
      }

      return def;
    });
  }, [rowData]);

  // Clean data for CSV export without internal UUIDs
  const exportableData = useMemo(() => {
    return rowData.map(row => {
      const clean = {};
      Object.keys(row).forEach(k => {
        if (!INTERNAL_COLUMNS.has(k)) {
          clean[k] = row[k];
        }
      });
      return clean;
    });
  }, [rowData]);

  // Highlight outlier rows with custom CSS class
  const rowClassRules = useMemo(() => ({
    'outlier-row': params => params.data?.is_outlier === true
  }), []);

  // Limit export to reasonable client-side volume (<= 100 rows)
  const canExportCsv = rowData.length > 0 && rowData.length <= 100;

  return (
    <div className="table-section">
      <div className="table-toolbar">
        <span className="table-title">
          {rowData.length === 1 ? 'Transaction Details' : `Matching Records (${rowData.length} items)`}
        </span>
        {canExportCsv ? (
          <CsvExportButton data={exportableData} filename="financial_records.csv" />
        ) : (
          <span style={{ fontSize: '0.75rem', color: '#94a3b8', background: 'rgba(148, 163, 184, 0.1)', padding: '4px 10px', borderRadius: '4px' }}>
            Large dataset ({rowData.length} rows) — export restricted on client-side
          </span>
        )}
      </div>
      <div className="ag-theme-alpine-dark" style={{ height: Math.min(320, Math.max(160, rowData.length * 48 + 70)), width: '100%' }}>
        <AgGridReact
          theme="legacy"
          rowData={rowData}
          columnDefs={columnDefs}
          pagination={rowData.length > 5}
          paginationPageSize={5}
          paginationPageSizeSelector={[5, 10, 25, 50]}
          rowClassRules={rowClassRules}
          animateRows={true}
          defaultColDef={{
            flex: 1,
            minWidth: 110,
          }}
        />
      </div>
    </div>
  );
};
