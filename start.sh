#!/bin/bash
# Quick Start Script for Auction Property Analyzer

echo "================================"
echo "Auction Property Analyzer"
echo "================================"
echo ""

# Run the analyzer
echo "Step 1: Running property analyzer..."
python3 property_analyzer.py
echo ""

# Check if successful
if [ -f "property_analysis.json" ]; then
    echo "✅ Analysis complete!"
    echo ""
    echo "Step 2: Starting web server..."
    echo "Dashboard will be available at: http://localhost:8000/dashboard.html"
    echo ""
    echo "Press Ctrl+C to stop the server"
    echo ""
    python3 -m http.server 8000
else
    echo "❌ Error: Analysis failed to generate data"
    exit 1
fi
