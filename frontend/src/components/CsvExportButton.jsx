import React from 'react';
import { Download } from 'lucide-react';

export const CsvExportButton = ({ data, filename = "financial_breakdown.csv" }) => {
  const downloadCsv = () => {
    if (!data || data.length === 0) return;

    // Extract headers
    const headers = Object.keys(data[0]);
    const csvRows = [headers.join(',')];

    // Format rows
    for (const row of data) {
      const values = headers.map(header => {
        const val = row[header];
        if (val === null || val === undefined) return '';
        const escaped = ('' + val).replace(/"/g, '""');
        return `"${escaped}"`;
      });
      csvRows.push(values.join(','));
    }

    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  if (!data || data.length === 0) return null;

  return (
    <button onClick={downloadCsv} className="btn-export" title="Export table to CSV">
      <Download size={13} />
      <span>Export CSV</span>
    </button>
  );
};
