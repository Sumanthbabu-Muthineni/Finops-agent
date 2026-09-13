import React from 'react';
import { Download } from 'lucide-react';

export const CsvExportButton = ({ 
  data, 
  filename = "financial_records.csv", 
  label = "Export CSV",
  disabled = false 
}) => {
  const downloadCsv = () => {
    if (!data || data.length === 0 || disabled) return;

    // Extract headers
    const rawHeaders = Object.keys(data[0]);
    
    // Format headers cleanly (e.g. transaction_amount -> Transaction Amount)
    const formattedHeaders = rawHeaders.map(h => {
      return h
        .split('_')
        .map(w => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' ');
    });

    const csvRows = [formattedHeaders.join(',')];

    // Format rows (limit to 100 max for client safety)
    const exportRows = data.slice(0, 100);
    for (const row of exportRows) {
      const values = rawHeaders.map(header => {
        const val = row[header];
        if (val === null || val === undefined) return '""';
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
    <button 
      onClick={downloadCsv} 
      className="btn-export" 
      disabled={disabled}
      title={disabled ? "Export disabled" : `Export ${Math.min(data.length, 100)} records to CSV`}
      style={disabled ? { opacity: 0.5, cursor: 'not-allowed' } : {}}
    >
      <Download size={13} />
      <span>{label}</span>
    </button>
  );
};
