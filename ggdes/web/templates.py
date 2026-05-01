"""HTML templates for the web interface."""


# Main dashboard HTML
INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GGDes Web</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        header h1 { font-size: 2.5em; margin-bottom: 10px; }
        header p { opacity: 0.9; font-size: 1.1em; }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            text-align: center;
        }
        .stat-card .number {
            font-size: 2.5em;
            font-weight: bold;
            color: #667eea;
        }
        .stat-card .label { color: #666; margin-top: 5px; }
        
        .section {
            background: white;
            padding: 25px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        .section h2 {
            margin-bottom: 20px;
            color: #333;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }
        
        .analysis-list {
            list-style: none;
        }
        .analysis-item {
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            padding: 15px;
            margin-bottom: 15px;
            transition: box-shadow 0.2s;
        }
        .analysis-item:hover {
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }
        .analysis-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        .analysis-name {
            font-weight: bold;
            font-size: 1.1em;
            color: #333;
        }
        .analysis-id {
            color: #999;
            font-size: 0.85em;
            font-family: monospace;
        }
        .progress-bar {
            background: #e0e0e0;
            height: 8px;
            border-radius: 4px;
            overflow: hidden;
            margin: 10px 0;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            transition: width 0.3s;
        }
        .status-badges {
            display: flex;
            gap: 10px;
            margin-top: 10px;
            font-size: 0.85em;
        }
        .badge {
            padding: 3px 10px;
            border-radius: 12px;
            font-weight: 500;
        }
        .badge.completed { background: #d4edda; color: #155724; }
        .badge.failed { background: #f8d7da; color: #721c24; }
        .badge.pending { background: #fff3cd; color: #856404; }
        .badge.in-progress { background: #d1ecf1; color: #0c5460; }
        
        .actions {
            display: flex;
            gap: 10px;
            margin-top: 15px;
        }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.9em;
            transition: all 0.2s;
            text-decoration: none;
            display: inline-block;
        }
        .btn-primary {
            background: #667eea;
            color: white;
        }
        .btn-primary:hover { background: #5a6fd6; }
        .btn-danger {
            background: #dc3545;
            color: white;
        }
        .btn-danger:hover { background: #c82333; }
        .btn-secondary {
            background: #6c757d;
            color: white;
        }
        .btn-secondary:hover { background: #545b62; }
        
        .status-connected {
            display: inline-block;
            width: 10px;
            height: 10px;
            background: #28a745;
            border-radius: 50%;
            margin-right: 5px;
            animation: pulse 2s infinite;
        }
        .status-disconnected {
            display: inline-block;
            width: 10px;
            height: 10px;
            background: #dc3545;
            border-radius: 50%;
            margin-right: 5px;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #666;
        }
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        @media (max-width: 768px) {
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
            .analysis-header { flex-direction: column; align-items: flex-start; }
            .actions { flex-wrap: wrap; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>GGDes Web</h1>
            <p>Git-based Design Documentation Generator - Web Interface</p>
            <div style="margin-top: 15px; font-size: 0.9em;">
                <span id="ws-status" class="status-disconnected"></span>
                <span id="ws-text">Disconnected</span>
            </div>
        </header>
        
        <div class="stats-grid" id="stats-container">
            <div class="loading">
                <div class="spinner"></div>
                <p>Loading statistics...</p>
            </div>
        </div>
        
        <div class="section">
            <h2>Analyses</h2>
            <div id="analyses-list">
                <div class="loading">
                    <div class="spinner"></div>
                    <p>Loading analyses...</p>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>Quick Actions</h2>
            <div class="actions">
                <button class="btn btn-secondary" onclick="loadAnalyses()">Refresh</button>
                <button class="btn btn-secondary" onclick="previewCleanup()">Preview Cleanup</button>
                <button class="btn btn-danger" onclick="runCleanup()">Cleanup Old Worktrees</button>
            </div>
            <div id="cleanup-preview" style="margin-top: 15px; display: none;"></div>
        </div>
    </div>
    
    <script>
        let ws = null;
        
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
            
            ws.onopen = () => {
                document.getElementById('ws-status').className = 'status-connected';
                document.getElementById('ws-text').textContent = 'Connected';
            };
            
            ws.onclose = () => {
                document.getElementById('ws-status').className = 'status-disconnected';
                document.getElementById('ws-text').textContent = 'Disconnected';
                setTimeout(connectWebSocket, 3000);
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleWebSocketMessage(data);
            };
        }
        
        function handleWebSocketMessage(data) {
            if (data.type === 'analysis_updated' || data.type === 'analysis_created' || data.type === 'analysis_deleted') {
                loadAnalyses();
                loadStats();
            }
        }
        
        async function loadStats() {
            try {
                const response = await fetch('/api/stats');
                const stats = await response.json();
                
                document.getElementById('stats-container').innerHTML = `
                    <div class="stat-card">
                        <div class="number">${stats.analyses.total}</div>
                        <div class="label">Total Analyses</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">${stats.analyses.completed}</div>
                        <div class="label">Completed</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">${stats.analyses.in_progress}</div>
                        <div class="label">In Progress</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">${stats.analyses.failed}</div>
                        <div class="label">Failed</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">${stats.worktrees.count}</div>
                        <div class="label">Active Worktrees</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">${stats.worktrees.total_size_mb} MB</div>
                        <div class="label">Worktree Size</div>
                    </div>
                `;
            } catch (error) {
                console.error('Failed to load stats:', error);
            }
        }
        
        async function loadAnalyses() {
            try {
                const response = await fetch('/api/analyses');
                const analyses = await response.json();
                
                if (analyses.length === 0) {
                    document.getElementById('analyses-list').innerHTML = `
                        <p style="text-align: center; color: #666; padding: 40px;">
                            No analyses yet. Use the CLI to create one:<br>
                            <code>ggdes analyze --feature &lt;name&gt; &lt;commits&gt;</code>
                        </p>
                    `;
                    return;
                }
                
                document.getElementById('analyses-list').innerHTML = analyses.map(a => `
                    <div class="analysis-item">
                        <div class="analysis-header">
                            <span class="analysis-name">${escapeHtml(a.name)}</span>
                            <span class="analysis-id">${a.id.substring(0, 8)}...</span>
                        </div>
                        <div style="color: #666; font-size: 0.9em; margin-bottom: 10px;">
                            <strong>Commits:</strong> ${escapeHtml(a.commit_range)}<br>
                            <strong>Created:</strong> ${new Date(a.created_at).toLocaleString()}
                        </div>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${a.progress.percent}%"></div>
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 0.85em; color: #666;">
                            <span>${a.progress.completed}/${a.progress.total} stages</span>
                            <span>${Math.round(a.progress.percent)}%</span>
                        </div>
                        <div class="status-badges">
                            ${a.progress.completed > 0 ? `<span class="badge completed">${a.progress.completed} Complete</span>` : ''}
                            ${a.progress.failed > 0 ? `<span class="badge failed">${a.progress.failed} Failed</span>` : ''}
                            ${a.progress.pending > 0 ? `<span class="badge pending">${a.progress.pending} Pending</span>` : ''}
                        </div>
                        <div class="actions">
                            ${a.progress.pending > 0 ? `<button class="btn btn-primary" onclick="resumeAnalysis('${a.id}')">Resume</button>` : ''}
                            <button class="btn btn-secondary" onclick="viewDetails('${a.id}')">Details</button>
                            <button class="btn btn-secondary" onclick="openFeedback('${a.id}')">📝 Feedback</button>
                            <button class="btn btn-danger" onclick="deleteAnalysis('${a.id}')">Delete</button>
                        </div>
                    </div>
                `).join('');
            } catch (error) {
                console.error('Failed to load analyses:', error);
                document.getElementById('analyses-list').innerHTML = `
                    <p style="text-align: center; color: #721c24; padding: 40px;">
                        Failed to load analyses. Please try again.
                    </p>
                `;
            }
        }
        
        async function resumeAnalysis(id) {
            if (!confirm('Resume this analysis?')) return;
            
            try {
                const response = await fetch(`/api/analyses/${id}/resume`, {
                    method: 'POST'
                });
                const result = await response.json();
                
                if (result.success) {
                    alert('Analysis completed successfully!');
                } else {
                    alert('Analysis did not complete. Check logs for details.');
                }
                loadAnalyses();
            } catch (error) {
                alert('Failed to resume analysis: ' + error.message);
            }
        }
        
        async function deleteAnalysis(id) {
            if (!confirm('Delete this analysis? This cannot be undone.')) return;
            
            try {
                const response = await fetch(`/api/analyses/${id}/delete`, {
                    method: 'POST'
                });
                const result = await response.json();
                
                if (result.deleted) {
                    loadAnalyses();
                    loadStats();
                }
            } catch (error) {
                alert('Failed to delete analysis: ' + error.message);
            }
        }
        
        function viewDetails(id) {
            window.location.href = `/analysis/${id}`;
        }
        
        function openFeedback(id) {
            window.location.href = `/feedback/${id}`;
        }
        
        async function previewCleanup() {
            try {
                const response = await fetch('/api/worktrees/cleanup-preview?days=7');
                const preview = await response.json();
                
                const previewDiv = document.getElementById('cleanup-preview');
                
                if (preview.would_cleanup === 0) {
                    previewDiv.innerHTML = '<p style="color: #155724;">No old worktrees to clean up.</p>';
                } else {
                    previewDiv.innerHTML = `
                        <p style="color: #856404;">Would clean up ${preview.would_cleanup} worktree(s):</p>
                        <ul style="margin-left: 20px; color: #666;">
                            ${preview.worktrees.map(w => `<li>${w.analysis_id} (${w.age_days} days old)</li>`).join('')}
                        </ul>
                    `;
                }
                previewDiv.style.display = 'block';
            } catch (error) {
                alert('Failed to preview cleanup: ' + error.message);
            }
        }
        
        async function runCleanup() {
            if (!confirm('Clean up worktrees older than 7 days?')) return;
            
            try {
                const response = await fetch('/api/worktrees/cleanup?days=7', {
                    method: 'POST'
                });
                const result = await response.json();
                
                alert(`Cleaned up ${result.cleaned} worktree(s)`);
                loadStats();
                document.getElementById('cleanup-preview').style.display = 'none';
            } catch (error) {
                alert('Failed to cleanup: ' + error.message);
            }
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Initialize
        connectWebSocket();
        loadStats();
        loadAnalyses();
    </script>
</body>
</html>
"""


# Feedback page HTML
FEEDBACK_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Feedback - {analysis_name}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px 30px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        header h1 {{ font-size: 1.5em; margin-bottom: 5px; }}
        header p {{ opacity: 0.9; }}
        .back-link {{
            display: inline-block;
            margin-top: 10px;
            color: white;
            text-decoration: underline;
            opacity: 0.9;
        }}
        .back-link:hover {{ opacity: 1; }}
        .feedback-layout {{
            display: grid;
            grid-template-columns: 40% 60%;
            gap: 20px;
            height: calc(100vh - 180px);
        }}
        @media (max-width: 768px) {{
            .feedback-layout {{
                grid-template-columns: 1fr;
                height: auto;
            }}
            .section-panel, .output-panel {{
                max-height: 50vh;
            }}
        }}
        .section-panel, .output-panel {{
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }}
        .panel-header {{
            background: #f8f9fa;
            padding: 15px 20px;
            border-bottom: 1px solid #e0e0e0;
            font-weight: bold;
            font-size: 1em;
        }}
        .sections-scroll {{
            flex: 1;
            overflow-y: auto;
            padding: 20px;
        }}
        .section-block {{
            margin-bottom: 25px;
            padding-bottom: 20px;
            border-bottom: 1px solid #e0e0e0;
        }}
        .section-block:last-child {{ border-bottom: none; }}
        .section-title {{
            font-size: 1.05em;
            color: #333;
            margin-bottom: 5px;
            font-weight: 600;
        }}
        .section-description {{
            color: #666;
            font-size: 0.9em;
            margin-bottom: 10px;
        }}
        .section-feedback {{
            width: 100%;
            min-height: 100px;
            border: 1px solid #ddd;
            border-radius: 6px;
            padding: 12px;
            font-family: inherit;
            font-size: 0.95em;
            resize: vertical;
            transition: border-color 0.2s;
        }}
        .section-feedback:focus {{
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.15);
        }}
        .output-layout {{
            display: flex;
            flex: 1;
            overflow: hidden;
        }}
        .file-tree-panel {{
            width: 35%;
            border-right: 1px solid #e0e0e0;
            overflow-y: auto;
            padding: 10px;
        }}
        .file-tree-panel ul {{ list-style: none; }}
        .file-tree-panel li {{
            padding: 8px 12px;
            cursor: pointer;
            border-radius: 4px;
            font-size: 0.9em;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .file-tree-panel li:hover {{ background: #f0f0f0; }}
        .file-tree-panel li.active {{ background: #e8eaf6; color: #667eea; }}
        .file-tree-panel .tree-dir {{ font-weight: 600; color: #555; }}
        .output-content {{
            flex: 1;
            overflow: auto;
            padding: 20px;
            background: #fafafa;
        }}
        .output-content pre {{
            white-space: pre-wrap;
            word-break: break-word;
            font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
            font-size: 0.85em;
            line-height: 1.5;
        }}
        .actions-bar {{
            padding: 15px 20px;
            background: #f8f9fa;
            border-top: 1px solid #e0e0e0;
            display: flex;
            gap: 10px;
            align-items: center;
        }}
        .btn {{
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.95em;
            font-weight: 500;
            transition: all 0.2s;
        }}
        .btn-primary {{
            background: #667eea;
            color: white;
        }}
        .btn-primary:hover {{ background: #5a6fd6; }}
        .btn-warning {{
            background: #ffc107;
            color: #333;
        }}
        .btn-warning:hover {{ background: #e0a800; }}
        .btn-secondary {{
            background: #6c757d;
            color: white;
        }}
        .btn-secondary:hover {{ background: #545b62; }}
        .status-message {{ margin-left: auto; font-weight: 500; font-size: 0.9em; }}
        .status-success {{ color: #28a745; }}
        .status-error {{ color: #dc3545; }}
        .loading {{ color: #666; padding: 20px; text-align: center; }}
        .empty-state {{ color: #999; padding: 40px; text-align: center; }}
        .output-title {{ font-weight: 600; margin-bottom: 10px; color: #333; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📝 Section Feedback</h1>
            <p>Analysis: <strong>{analysis_name}</strong></p>
            <a href="/" class="back-link">← Back to Dashboard</a>
        </header>

        <div class="feedback-layout">
            <div class="section-panel">
                <div class="panel-header">📄 Document Sections</div>
                <div class="sections-scroll" id="sections-container">
                    <div class="loading">Loading sections...</div>
                </div>
                <div class="actions-bar">
                    <button class="btn btn-primary" onclick="saveAllFeedback()">💾 Save All Feedback</button>
                    <button class="btn btn-warning" onclick="saveAndRegenerate()">🔄 Save & Regenerate</button>
                    <span id="save-status" class="status-message"></span>
                </div>
            </div>

            <div class="output-panel">
                <div class="panel-header">📁 Live Output Files</div>
                <div class="output-layout">
                    <div class="file-tree-panel">
                        <ul id="file-tree"></ul>
                    </div>
                    <div class="output-content" id="output-content">
                        <p class="empty-state">Select a file to view its content</p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const ANALYSIS_ID = '{analysis_id}';
        const PLAN_DATA = {plan_json};
        const EXISTING_FEEDBACK = {feedback_json};

        let feedbackInputs = {{}};
        let activeFileLi = null;

        function loadSections() {{
            const container = document.getElementById('sections-container');

            if (!PLAN_DATA || !PLAN_DATA.sections || PLAN_DATA.sections.length === 0) {{
                container.innerHTML = '<p class="empty-state">No document plan found. Run an analysis first.</p>';
                return;
            }}

            container.innerHTML = PLAN_DATA.sections.map((section, i) => `
                <div class="section-block">
                    <div class="section-title">${{i + 1}}. ${{esc(section.title)}}</div>
                    <div class="section-description">${{esc(section.description || '')}}</div>
                    <textarea
                        class="section-feedback"
                        id="feedback_${{i}}"
                        placeholder="Feedback for this section..."
                    >${{esc(EXISTING_FEEDBACK[section.title] || '')}}</textarea>
                </div>
            `).join('');

            PLAN_DATA.sections.forEach((section, i) => {{
                feedbackInputs[section.title] = document.getElementById(`feedback_${{i}}`);
            }});
        }}

        async function saveAllFeedback() {{
            const statusEl = document.getElementById('save-status');
            statusEl.textContent = 'Saving...';
            statusEl.className = 'status-message';

            const feedbackItems = Object.entries(feedbackInputs)
                .map(([section, textarea]) => ({{
                    section: section,
                    feedback: textarea.value.trim()
                }}))
                .filter(item => item.feedback);

            try {{
                const response = await fetch(`/api/analyses/${{ANALYSIS_ID}}/feedback/bulk`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ feedback_items: feedbackItems }})
                }});

                const result = await response.json();

                if (result.success) {{
                    statusEl.textContent = `✓ Saved ${{result.count}} feedback entries`;
                    statusEl.className = 'status-message status-success';
                }} else {{
                    throw new Error('Save failed');
                }}
            }} catch (error) {{
                statusEl.textContent = '✗ Save failed: ' + error.message;
                statusEl.className = 'status-message status-error';
            }}
        }}

        async function loadOutputFiles() {{
            try {{
                const response = await fetch(`/api/analyses/${{ANALYSIS_ID}}/outputs`);
                const data = await response.json();
                const treeEl = document.getElementById('file-tree');

                if (!data.files || data.files.length === 0) {{
                    treeEl.innerHTML = '<li class="empty-state">No output files yet</li>';
                    return;
                }}

                // Group files by directory
                const groups = {{}};
                data.files.forEach(f => {{
                    const parts = f.relative.split('/');
                    const dir = parts.length > 1 ? parts[0] : 'root';
                    if (!groups[dir]) groups[dir] = [];
                    groups[dir].push(f);
                }});

                let html = '';
                for (const [dir, files] of Object.entries(groups)) {{
                    if (dir !== 'root') {{
                        html += `<li class="tree-dir">📁 ${{esc(dir)}}</li>`;
                    }}
                    files.forEach(f => {{
                        html += `<li onclick="viewFile('${{f.path}}', '${{esc(f.name)}}')" data-path="${{f.path}}">📄 ${{esc(f.name)}}</li>`;
                    }});
                }}
                treeEl.innerHTML = html;
            }} catch (error) {{
                console.error('Failed to load files:', error);
            }}
        }}

        async function viewFile(filePath, fileName) {{
            // Update active state
            if (activeFileLi) activeFileLi.classList.remove('active');
            const li = document.querySelector(`li[data-path="${{filePath}}"]`);
            if (li) {{ li.classList.add('active'); activeFileLi = li; }}

            const contentEl = document.getElementById('output-content');
            contentEl.innerHTML = '<p class="loading">Loading...</p>';

            try {{
                const response = await fetch(`/api/analyses/${{ANALYSIS_ID}}/outputs/content?path=${{encodeURIComponent(filePath)}}`);
                const data = await response.json();

                contentEl.innerHTML = `
                    <div class="output-title">${{esc(fileName)}}</div>
                    <pre>${{esc(data.content)}}</pre>
                `;
            }} catch (error) {{
                contentEl.innerHTML = `<p class="status-error">Error loading file: ${{error.message}}</p>`;
            }}
        }}

        async function saveAndRegenerate() {{
            const statusEl = document.getElementById('save-status');
            statusEl.textContent = 'Saving and regenerating...';
            statusEl.className = 'status-message';

            const feedbackItems = Object.entries(feedbackInputs)
                .map(([section, textarea]) => ({{
                    section: section,
                    feedback: textarea.value.trim()
                }}))
                .filter(item => item.feedback);

            if (feedbackItems.length === 0) {{
                statusEl.textContent = '⚠ No feedback to regenerate from';
                statusEl.className = 'status-message status-error';
                return;
            }}

            // Build section_feedback dict
            const sectionFeedback = {{}};
            feedbackItems.forEach(item => {{ sectionFeedback[item.section] = item.feedback; }});

            if (!confirm('Regenerate documents with ' + feedbackItems.length + ' feedback items?')) return;

            try {{
                const response = await fetch(`/api/analyses/${{ANALYSIS_ID}}/regenerate`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        section_feedback: sectionFeedback,
                        affects_structure: false,
                        summary: 'Web feedback regeneration'
                    }})
                }});
                const result = await response.json();
                if (result.success) {{
                    statusEl.textContent = '✓ Regenerated as ' + (result.revision_id || '') + ' — reloading...';
                    statusEl.className = 'status-message status-success';
                    setTimeout(() => location.reload(), 2000);
                }} else {{
                    statusEl.textContent = '✗ Regeneration failed';
                    statusEl.className = 'status-message status-error';
                }}
            }} catch (error) {{
                statusEl.textContent = '✗ Error: ' + error.message;
                statusEl.className = 'status-message status-error';
            }}
        }}

        function esc(text) {{
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}

        // Poll for new output files every 5 seconds
        setInterval(loadOutputFiles, 5000);

        // Initialize
        loadSections();
        loadOutputFiles();
    </script>
</body>
</html>
"""


# Analysis detail page HTML
DETAIL_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{analysis_name} - Analysis Detail</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px 30px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        header h1 {{ font-size: 1.5em; margin-bottom: 5px; }}
        header p {{ opacity: 0.9; font-size: 0.95em; }}
        .back-link {{
            display: inline-block;
            margin-top: 10px;
            color: white;
            text-decoration: underline;
            opacity: 0.9;
        }}
        .back-link:hover {{ opacity: 1; }}
        .grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }}
        @media (max-width: 768px) {{
            .grid {{ grid-template-columns: 1fr; }}
        }}
        .card {{
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            padding: 20px;
        }}
        .card h2 {{
            font-size: 1.1em;
            margin-bottom: 15px;
            color: #333;
            border-bottom: 2px solid #667eea;
            padding-bottom: 8px;
        }}
        .info-row {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #f0f0f0;
        }}
        .info-row:last-child {{ border-bottom: none; }}
        .info-label {{ color: #666; font-weight: 500; }}
        .info-value {{ color: #333; }}
        .stage-list {{ list-style: none; }}
        .stage-item {{
            display: flex;
            align-items: center;
            padding: 10px;
            margin-bottom: 8px;
            border-radius: 6px;
            background: #f8f9fa;
        }}
        .stage-icon {{
            width: 24px;
            height: 24px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 12px;
            font-size: 0.8em;
            font-weight: bold;
        }}
        .stage-completed {{ background: #d4edda; color: #155724; }}
        .stage-pending {{ background: #e2e3e5; color: #383d41; }}
        .stage-in_progress {{ background: #fff3cd; color: #856404; }}
        .stage-failed {{ background: #f8d7da; color: #721c24; }}
        .stage-skipped {{ background: #d1ecf1; color: #0c5460; }}
        .stage-name {{ font-weight: 500; }}
        .stage-time {{ margin-left: auto; color: #999; font-size: 0.85em; }}
        .actions {{
            display: flex;
            gap: 10px;
            margin-top: 20px;
            flex-wrap: wrap;
        }}
        .btn {{
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.95em;
            transition: all 0.2s;
            text-decoration: none;
            display: inline-block;
        }}
        .btn-primary {{ background: #667eea; color: white; }}
        .btn-primary:hover {{ background: #5a6fd6; }}
        .btn-secondary {{ background: #6c757d; color: white; }}
        .btn-secondary:hover {{ background: #545b62; }}
        .btn-warning {{ background: #ffc107; color: #333; }}
        .btn-warning:hover {{ background: #e0a800; }}
        .btn-danger {{ background: #dc3545; color: white; }}
        .btn-danger:hover {{ background: #c82333; }}
        .progress-bar {{
            background: #e9ecef;
            border-radius: 10px;
            height: 20px;
            overflow: hidden;
            margin: 10px 0;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            border-radius: 10px;
            transition: width 0.3s;
        }}
        .doc-list {{ list-style: none; }}
        .doc-item {{
            display: flex;
            align-items: center;
            padding: 10px;
            margin-bottom: 8px;
            border-radius: 6px;
            background: #f8f9fa;
        }}
        .doc-icon {{ margin-right: 10px; font-size: 1.2em; }}
        .doc-name {{ font-weight: 500; }}
        .doc-size {{ margin-left: auto; color: #999; font-size: 0.85em; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📋 {analysis_name}</h1>
            <p>Analysis Detail View</p>
            <a href="/" class="back-link">← Back to Dashboard</a>
        </header>

        <div class="grid">
            <!-- Info Card -->
            <div class="card">
                <h2>ℹ️ Analysis Info</h2>
                <div class="info-row">
                    <span class="info-label">ID</span>
                    <span class="info-value" style="font-family: monospace; font-size: 0.85em;">{analysis_id}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Repository</span>
                    <span class="info-value">{repo_path}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Commit Range</span>
                    <span class="info-value" style="font-family: monospace;">{commit_range}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Created</span>
                    <span class="info-value">{created_at}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Target Formats</span>
                    <span class="info-value">{target_formats}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Facts</span>
                    <span class="info-value">{facts_count} technical facts</span>
                </div>
            </div>

            <!-- Stage Progress Card -->
            <div class="card">
                <h2>📊 Stage Progress</h2>
                <div id="progress-bar" class="progress-bar">
                    <div class="progress-fill" id="progress-fill" style="width: 0%"></div>
                </div>
                <ul class="stage-list" id="stage-list"></ul>
            </div>
        </div>

        <div class="grid">
            <!-- Documents Card -->
            <div class="card">
                <h2>📄 Generated Documents</h2>
                <ul class="doc-list" id="doc-list"></ul>
                <p id="no-docs" style="color: #999; display: none;">No documents generated yet.</p>
            </div>

            <!-- Plans Card -->
            <div class="card">
                <h2>📋 Document Plans</h2>
                <ul class="stage-list" id="plan-list"></ul>
                <p id="no-plans" style="color: #999; display: none;">No plans generated yet.</p>
            </div>
        </div>

        <div class="actions">
            <button class="btn btn-primary" onclick="openResumeModal()">🔄 Regenerate</button>
            <a href="/feedback/{analysis_id}" class="btn btn-warning">📝 Feedback</a>
            <button class="btn btn-danger" onclick="deleteAnalysis()">🗑 Delete</button>
        </div>
    </div>

    <!-- Resume Format Modal -->
    <div id="resume-modal" class="modal" style="display:none;">
        <div class="modal-content">
            <h3>Regenerate Documents</h3>
            <p style="margin: 10px 0; color: #666;">Select formats to generate. If unchanged, only document output re-runs.</p>
            <div class="format-options" style="margin: 15px 0;">
                <label class="format-checkbox"><input type="checkbox" id="fmt-md" checked> Markdown</label>
                <label class="format-checkbox"><input type="checkbox" id="fmt-docx"> DOCX</label>
                <label class="format-checkbox"><input type="checkbox" id="fmt-pdf"> PDF</label>
                <label class="format-checkbox"><input type="checkbox" id="fmt-pptx"> PPTX</label>
            </div>
            <div class="modal-buttons">
                <button class="btn btn-default" onclick="closeResumeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="resumeAnalysisWithFormats()">Regenerate</button>
            </div>
        </div>
    </div>

    <style>
        .modal { position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; }
        .modal-content { background: white; padding: 25px; border-radius: 10px; min-width: 400px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }
        .format-options { display: flex; gap: 15px; flex-wrap: wrap; }
        .format-checkbox { display: flex; align-items: center; gap: 5px; padding: 8px 12px;
            border: 1px solid #ddd; border-radius: 6px; cursor: pointer; }
        .format-checkbox:hover { background: #f0f0ff; }
        .modal-buttons { display: flex; gap: 10px; justify-content: flex-end; margin-top: 20px; }
        .btn-default { background: #f0f0f0; color: #333; border: 1px solid #ddd; padding: 8px 16px;
            border-radius: 6px; cursor: pointer; }
        .btn-default:hover { background: #e0e0e0; }
    </style>

    <script>
        const ANALYSIS_ID = '{analysis_id}';
        const CURRENT_FORMATS = '{target_formats}';
        const STAGES = {stages_json};
        const DOCUMENTS = {documents_json};
        const PLANS = {plans_json};

        function openResumeModal() {{
            // Pre-check current formats
            const current = CURRENT_FORMATS.split(', ').map(s => s.trim().toLowerCase());
            document.getElementById('fmt-md').checked = current.includes('markdown');
            document.getElementById('fmt-docx').checked = current.includes('docx');
            document.getElementById('fmt-pdf').checked = current.includes('pdf');
            document.getElementById('fmt-pptx').checked = current.includes('pptx');
            document.getElementById('resume-modal').style.display = 'flex';
        }}

        function closeResumeModal() {{
            document.getElementById('resume-modal').style.display = 'none';
        }}

        function resumeAnalysisWithFormats() {{
            const formats = [];
            if (document.getElementById('fmt-md').checked) formats.push('markdown');
            if (document.getElementById('fmt-docx').checked) formats.push('docx');
            if (document.getElementById('fmt-pdf').checked) formats.push('pdf');
            if (document.getElementById('fmt-pptx').checked) formats.push('pptx');
            if (formats.length === 0) {{ alert('Please select at least one format.'); return; }}
            closeResumeModal();
            resumeAnalysis(formats);
        }}

        async function resumeAnalysis(formats) {{
            try {{
                const body = formats ? JSON.stringify({{ formats }}) : '{{}}';
                const resp = await fetch(`/api/analyses/${{ANALYSIS_ID}}/resume`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: body,
                }});
                const data = await resp.json();
                if (data.success) {{
                    alert('Analysis regenerated successfully!');
                    location.reload();
                }} else {{
                    alert('Regeneration failed: ' + (data.error || 'Unknown error'));
                }}
            }} catch (e) {{
                alert('Error: ' + e.message);
            }}
        }}

        // Render stages
        function renderStages() {{
            const list = document.getElementById('stage-list');
            const statusIcons = {{
                completed: '✓', pending: '○', in_progress: '◐',
                failed: '✗', skipped: '⊘'
            }};
            let completed = 0;
            STAGES.forEach(s => {{
                if (s.status === 'completed') completed++;
                const li = document.createElement('li');
                li.className = 'stage-item';
                const iconClass = 'stage-' + s.status;
                li.innerHTML = `
                    <div class="stage-icon ${{iconClass}}">${{statusIcons[s.status] || '?'}}</div>
                    <span class="stage-name">${{s.name}}</span>
                    <span class="stage-time">${{s.completed_at ? new Date(s.completed_at).toLocaleTimeString() : s.status}}</span>
                `;
                list.appendChild(li);
            }});
            const pct = STAGES.length > 0 ? (completed / STAGES.length * 100) : 0;
            document.getElementById('progress-fill').style.width = pct + '%';
        }}

        // Render documents
        function renderDocuments() {{
            const list = document.getElementById('doc-list');
            if (DOCUMENTS.length === 0) {{
                document.getElementById('no-docs').style.display = 'block';
                return;
            }}
            const icons = {{ md: '📝', docx: '📘', pdf: '📕', pptx: '📊' }};
            DOCUMENTS.forEach(d => {{
                const li = document.createElement('li');
                li.className = 'doc-item';
                li.innerHTML = `
                    <span class="doc-icon">${{icons[d.format] || '📄'}}</span>
                    <span class="doc-name">${{d.name}}</span>
                    <span class="doc-size">${{(d.size / 1024).toFixed(1)}} KB</span>
                `;
                list.appendChild(li);
            }});
        }}

        // Render plans
        function renderPlans() {{
            const list = document.getElementById('plan-list');
            if (PLANS.length === 0) {{
                document.getElementById('no-plans').style.display = 'block';
                return;
            }}
            PLANS.forEach(p => {{
                const li = document.createElement('li');
                li.className = 'stage-item';
                li.innerHTML = `
                    <div class="stage-icon stage-completed">📋</div>
                    <span class="stage-name">${{p.format}}</span>
                    <span class="stage-time">${{p.sections}} sections, ${{p.diagrams}} diagrams</span>
                `;
                list.appendChild(li);
            }});
        }}

        async function resumeAnalysis() {{
            try {{
                const resp = await fetch(`/api/analyses/${{ANALYSIS_ID}}/resume`, {{ method: 'POST' }});
                const data = await resp.json();
                if (data.success) {{
                    alert('Analysis resumed successfully!');
                    location.reload();
                }} else {{
                    alert('Resume failed: ' + (data.error || 'Unknown error'));
                }}
            }} catch (e) {{
                alert('Error: ' + e.message);
            }}
        }}

        async function deleteAnalysis() {{
            if (!confirm('Delete this analysis? This cannot be undone.')) return;
            try {{
                const resp = await fetch(`/api/analyses/${{ANALYSIS_ID}}/delete`, {{ method: 'POST' }});
                const data = await resp.json();
                if (data.success) {{
                    window.location.href = '/';
                }} else {{
                    alert('Delete failed: ' + (data.error || 'Unknown error'));
                }}
            }} catch (e) {{
                alert('Error: ' + e.message);
            }}
        }}

        renderStages();
        renderDocuments();
        renderPlans();
    </script>
</body>
</html>
"""
