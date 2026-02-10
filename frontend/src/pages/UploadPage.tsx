import React, { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiService } from '../services/api';

export const UploadPage: React.FC = () => {
    const navigate = useNavigate();
    const [file, setFile] = useState<File | null>(null);
    const [uploadedData, setUploadedData] = useState<Record<string, any>[]>([]);
    const [columns, setColumns] = useState<string[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string>('');
    const [isDragging, setIsDragging] = useState(false);

    const handleDragOver = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(true);
    }, []);

    const handleDragLeave = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
    }, []);

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);

        const droppedFile = e.dataTransfer.files[0];
        if (droppedFile) {
            handleFileSelection(droppedFile);
        }
    }, []);

    const handleFileSelection = async (selectedFile: File) => {
        // Validate file type
        const validTypes = ['.csv', '.xlsx', '.xls'];
        const fileExtension = selectedFile.name.substring(selectedFile.name.lastIndexOf('.')).toLowerCase();

        if (!validTypes.includes(fileExtension)) {
            setError('Invalid file type. Please upload a CSV or Excel file.');
            return;
        }

        setFile(selectedFile);
        setError('');
        setIsLoading(true);

        try {
            const response = await apiService.uploadFile(selectedFile);
            setUploadedData(response.data);
            setColumns(response.columns);
            setError('');
        } catch (err: any) {
            // Ensure error is always a string
            const errorDetail = err.response?.data?.detail;
            if (typeof errorDetail === 'string') {
                setError(errorDetail);
            } else if (typeof errorDetail === 'object') {
                // Handle Pydantic validation errors
                setError(JSON.stringify(errorDetail, null, 2));
            } else {
                setError('Failed to upload file');
            }
            setUploadedData([]);
            setColumns([]);
        } finally {
            setIsLoading(false);
        }
    };

    const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const selectedFile = e.target.files?.[0];
        if (selectedFile) {
            handleFileSelection(selectedFile);
        }
    };

    const handleCellEdit = (rowIndex: number, column: string, value: string) => {
        const newData = [...uploadedData];
        newData[rowIndex][column] = value;
        setUploadedData(newData);
    };

    const handleCompute = async () => {
        if (uploadedData.length === 0) {
            setError('Please upload a file first');
            return;
        }

        setIsLoading(true);
        setError('');

        try {
            // Update data on backend
            await apiService.updateData(uploadedData);

            // Trigger computation
            await apiService.computeRoutes();

            // Navigate to results page
            navigate('/results');
        } catch (err: any) {
            // Ensure error is always a string
            const errorDetail = err.response?.data?.detail;
            if (typeof errorDetail === 'string') {
                setError(errorDetail);
            } else if (typeof errorDetail === 'object') {
                // Handle Pydantic validation errors
                setError(JSON.stringify(errorDetail, null, 2));
            } else {
                setError('Failed to compute routes');
            }
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 p-8">
            <div className="max-w-7xl mx-auto">
                {/* Header */}
                <div className="text-center mb-8">
                    <h1 className="text-4xl font-bold text-white mb-2">
                        Vehicle Routing Optimization
                    </h1>
                    <p className="text-gray-400">
                        Upload your delivery data to optimize vehicle routes
                    </p>
                </div>

                {/* Upload Section */}
                <div className="bg-gray-800 rounded-lg shadow-xl p-8 mb-8">
                    <h2 className="text-2xl font-semibold text-white mb-4">Upload Data</h2>

                    {/* Drag and Drop Area */}
                    <div
                        onDragOver={handleDragOver}
                        onDragLeave={handleDragLeave}
                        onDrop={handleDrop}
                        className={`border-2 border-dashed rounded-lg p-12 text-center transition-all ${isDragging
                            ? 'border-blue-500 bg-blue-500/10'
                            : 'border-gray-600 hover:border-gray-500'
                            }`}
                    >
                        <div className="flex flex-col items-center">
                            <svg
                                className="w-16 h-16 text-gray-400 mb-4"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                            >
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                                />
                            </svg>
                            <p className="text-gray-300 mb-2">
                                Drag and drop your file here, or
                            </p>
                            <label className="cursor-pointer bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-lg transition-colors">
                                Browse Files
                                <input
                                    type="file"
                                    accept=".csv,.xlsx,.xls"
                                    onChange={handleFileInputChange}
                                    className="hidden"
                                />
                            </label>
                            <p className="text-gray-500 text-sm mt-2">
                                Supported formats: CSV, Excel (.xlsx, .xls)
                            </p>
                        </div>
                    </div>

                    {/* File Info */}
                    {file && (
                        <div className="mt-4 p-4 bg-gray-700 rounded-lg flex items-center justify-between">
                            <div className="flex items-center">
                                <svg
                                    className="w-8 h-8 text-green-500 mr-3"
                                    fill="none"
                                    stroke="currentColor"
                                    viewBox="0 0 24 24"
                                >
                                    <path
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                        strokeWidth={2}
                                        d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                                    />
                                </svg>
                                <div>
                                    <p className="text-white font-medium">{file.name}</p>
                                    <p className="text-gray-400 text-sm">
                                        {(file.size / 1024).toFixed(2)} KB
                                    </p>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Error Message */}
                    {error && (
                        <div className="mt-4 p-4 bg-red-500/10 border border-red-500 rounded-lg">
                            <p className="text-red-400">{error}</p>
                        </div>
                    )}
                </div>

                {/* Data Table */}
                {uploadedData.length > 0 && (
                    <div className="bg-gray-800 rounded-lg shadow-xl p-8 mb-8">
                        <div className="flex justify-between items-center mb-4">
                            <h2 className="text-2xl font-semibold text-white">
                                Data Preview & Edit
                            </h2>
                            <span className="text-gray-400">
                                {uploadedData.length} rows
                            </span>
                        </div>

                        <div className="overflow-x-auto max-h-96 overflow-y-auto">
                            <table className="data-table">
                                <thead className="sticky top-0">
                                    <tr>
                                        <th className="w-12">#</th>
                                        {columns.map((col) => (
                                            <th key={col}>{col}</th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {uploadedData.map((row, rowIndex) => (
                                        <tr key={rowIndex} className="hover:bg-gray-700/50">
                                            <td className="text-gray-400 text-center">{rowIndex + 1}</td>
                                            {columns.map((col) => (
                                                <td key={col}>
                                                    <input
                                                        type="text"
                                                        value={row[col] ?? ''}
                                                        onChange={(e) =>
                                                            handleCellEdit(rowIndex, col, e.target.value)
                                                        }
                                                        className="text-white"
                                                    />
                                                </td>
                                            ))}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}

                {/* Compute Button */}
                {uploadedData.length > 0 && (
                    <div className="flex justify-center">
                        <button
                            onClick={handleCompute}
                            disabled={isLoading}
                            className="bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white px-12 py-4 rounded-lg text-lg font-semibold transition-all transform hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed disabled:transform-none flex items-center"
                        >
                            {isLoading ? (
                                <>
                                    <div className="spinner mr-3"></div>
                                    Computing Routes...
                                </>
                            ) : (
                                <>
                                    <svg
                                        className="w-6 h-6 mr-2"
                                        fill="none"
                                        stroke="currentColor"
                                        viewBox="0 0 24 24"
                                    >
                                        <path
                                            strokeLinecap="round"
                                            strokeLinejoin="round"
                                            strokeWidth={2}
                                            d="M13 10V3L4 14h7v7l9-11h-7z"
                                        />
                                    </svg>
                                    Compute Optimal Routes
                                </>
                            )}
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
};
