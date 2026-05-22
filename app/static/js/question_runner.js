// ============================================================
// Question Runner - LeetCode Style with Resizable Panels
// ============================================================

(function () {
  // ============================================================
  // Context and Configuration
  // ============================================================
  
  const codeEl = document.getElementById("codeEditor");
  const PROBLEM_ID = Number(codeEl?.dataset?.problemId || window.PROBLEM_ID || 0);
  let LANG = String(codeEl?.dataset?.language || window.PROBLEM_LANGUAGE || "python").toLowerCase();

  const API_JUDGE = "/api/v1/judge/run";
  const API_SUBMIT = (id) => `/api/v1/problems/${id}/submit`;
  const API_PROBLEM = (id, language) => `/api/v1/problems/${id}?language=${encodeURIComponent(language)}`;

  let allSubmissionCases = [];
  let currentSubmissionIndex = 0;
  let allTestResults = [];
  let currentTestIndex = 0;
  let submissionScore = 0;
  let submissionPassedCount = 0;
  let submissionTotalCount = 0;
  let submissionTotalTime = 0;
  // Auth utilities
  const AUTH = window.__auth || {
    getToken: () => {
      try { return localStorage.getItem("token") || ""; } catch (_) { return ""; }
    },
    authHeaders: () => {
      const t = AUTH.getToken();
      const h = { "Content-Type": "application/json" };
      if (t) h.Authorization = "Bearer " + t;
      return h;
    },
    clearToken: () => { try { localStorage.removeItem("token"); } catch (_) { } }
  };

  // Theme configuration
  const THEMES = ['darcula', 'monokai', 'solarized light', 'solarized dark', 'default'];
  let currentThemeIndex = 0;

  // ============================================================
  // DOM Elements
  // ============================================================
  
  const els = {
    code: codeEl,
    editorTab: document.getElementById("editorTab"),
    error: document.getElementById("errorMsg"),
    tlimit: document.getElementById("tlimit"),
    runBtn: document.getElementById("runBtn"),
    submitBtn: document.getElementById("submitBtn"),
    themeBtn: document.getElementById("themeBtn"),
    consoleOutput: document.getElementById("consoleOutput"),
    box: document.getElementById("evaluationResults"),
    processing: document.getElementById("processingSection"),
    placeholderSection: document.getElementById("placeholderSection"),
    scoreBox: document.getElementById("scoreSection"),
    score: document.getElementById("scoreDisplay"),
    passedTests: document.getElementById("passedTests"),
    failedTests: document.getElementById("failedTests"),
    totalTime: document.getElementById("totalTime"),
    testsBox: document.getElementById("testResultsSection"),
    tests: document.getElementById("testCases"),
    errorBox: document.getElementById("errorSection"),
    errorDetail: document.getElementById("errorDetail"),
    editorTabs: document.querySelectorAll(".editor-tab"),
    solutionTab: document.getElementById("solutionTab"),
    solutionLocked: document.getElementById("solutionLocked"),
    solutionUnlocked: document.getElementById("solutionUnlocked"),
    solutionCode: document.getElementById("solutionCode"),
    solutionLanguage: document.getElementById("solutionLanguage"),
    copySolutionBtn: document.getElementById("copySolutionBtn"),
    caseInputs: document.getElementById("caseInputs"),
    addCaseBtn: document.getElementById("addCaseBtn"),
  };

  // Test cases state
  let testCases = [
    { id: 1, params: {} }
  ];
  let currentCaseId = 1;
  let maxCaseId = 1;

  // ============================================================
  // CodeMirror Setup
  // ============================================================
  
  let cm = null;

  function cmModeFor(lang) {
    switch ((lang || "").toLowerCase()) {
      case "c": return "text/x-csrc";
      case "cpp":
      case "c++": return "text/x-c++src";
      case "java": return "text/x-java";
      case "python": return "python";
      default: return "python";
    }
  }

  function ensureEditor() {
    if (!window.CodeMirror || !els.code) return;
    cm = window.CodeMirror.fromTextArea(els.code, {
      lineNumbers: true,
      theme: THEMES[currentThemeIndex],
      mode: cmModeFor(LANG),
      matchBrackets: true,
      autoCloseBrackets: true,
      indentUnit: 2,
      tabSize: 2,
      indentWithTabs: false,
      viewportMargin: Infinity,
    });
    cm.setSize("100%", "100%");
  }

  // ============================================================
  // Theme Switching
  // ============================================================
  
  function switchTheme() {
    if (!cm) return;
    
    currentThemeIndex = (currentThemeIndex + 1) % THEMES.length;
    const newTheme = THEMES[currentThemeIndex];
    
    cm.setOption("theme", newTheme);
    
    // Save preference
    try {
      localStorage.setItem('editorTheme', newTheme);
    } catch (e) {
    }
    
    // Visual feedback
    if (els.themeBtn) {
      const originalHTML = els.themeBtn.innerHTML;
      els.themeBtn.innerHTML = '<i class="bi bi-check"></i>';
      setTimeout(() => {
        els.themeBtn.innerHTML = originalHTML;
      }, 500);
    }
  }

  // Load saved theme
  function loadSavedTheme() {
    try {
      const saved = localStorage.getItem('editorTheme');
      if (saved) {
        const index = THEMES.indexOf(saved);
        if (index !== -1) {
          currentThemeIndex = index;
        }
      }
    } catch (e) {
    }
  }

  // ============================================================
  // Tab Switching
  // ============================================================
  
  function switchEditorTab(tab) {
    if (tab === 'solution') {
      const solutionTab = document.querySelector('.editor-tab[data-tab="solution"]');
      if (solutionTab && solutionTab.classList.contains('locked')) {
        alert('Submit your solution to unlock the reference solution.');
        return;
      }
      
      // If switching to solution tab, make sure solution content is visible
      if (els.solutionUnlocked && els.solutionCode && els.solutionCode.textContent) {
        els.solutionLocked.style.display = "none";
        els.solutionUnlocked.style.display = "block";
      }
    }
    
    els.editorTabs.forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === tab);
    });
    
    if (els.editorTab) {
      els.editorTab.style.display = tab === "editor" ? "block" : "none";
    }
    
    const solutionTabContent = document.getElementById('solutionTabContent');
    if (solutionTabContent) {
      solutionTabContent.style.display = tab === "solution" ? "block" : "none";
    }
    
    if (tab === "editor" && cm) {
      setTimeout(() => cm.refresh(), 50);
    }
  }

  // ============================================================
  // Test Cases Management 
  // ============================================================
  
  async function initTestCases() {
    try {
      // Load test cases from API
      const response = await fetch(API_PROBLEM(PROBLEM_ID, LANG), {
        headers: AUTH.authHeaders()
      });
      if (!response.ok) {
        // Fallback to default params
        renderDefaultTestCases();
        return;
      }
      
      const data = await response.json();
      LANG = data.selected_language || LANG;
      if (cm) {
        cm.setValue(data.starter_code || "");
        cm.setOption("mode", cmModeFor(LANG));
      } else if (els.code) {
        els.code.value = data.starter_code || "";
      }
      
      // Check if test_cases exist
      if (data.test_cases && data.test_cases.length > 0) {
        // Load test cases from backend
        testCases = data.test_cases.map((tc, index) => {
          // Parse input to extract parameters
          const normalizedInput = tc.input.replace(/\\n/g, '\n');
          const params = parseTestCaseInput(normalizedInput);
          return {
            id: index + 1,
            testCaseId: tc.id, // Backend test case ID
            params: params,
            expectedOutput: tc.expected_output
          };
        });
        
        currentCaseId = 1;
        maxCaseId = testCases.length;
        
        // Get parameter names from first test case
        const paramNames = Object.keys(testCases[0].params);
        renderCaseInputs(paramNames);
        updateCaseButtons();
        
      } else {
        // No test cases from backend, use default
        renderDefaultTestCases();
      }
    } catch (error) {
      renderDefaultTestCases();
    }
  }
  
  function parseTestCaseInput(input) {
    /**
     * Parse test case input string to extract parameters
     * Expected format: "param1 = value1\nparam2 = value2"
     * or just multi-line values
     */
    const params = {};
    const lines = input.trim().split('\n');
    
    if (lines.length === 0) return params;
    
    // Try to parse as param = value format
    let hasParamFormat = false;
    for (const line of lines) {
      if (line.includes('=')) {
        const parts = line.split('=');
        if (parts.length >= 2) {
          const key = parts[0].trim();
          const value = parts.slice(1).join('=').trim();
          params[key] = value;
          hasParamFormat = true;
        }
      }
    }
    
    // If no param format found, use generic numbering
    if (!hasParamFormat) {
      if (lines.length === 1) {
        params['input'] = lines[0].trim();
      } else {
        lines.forEach((line, index) => {
          if (line.trim()) {
            params[`input${index + 1}`] = line.trim();
          }
        });
      }
    }
    
    return params;
  }
  
  function renderDefaultTestCases() {
    // Initialize with default parameters
    const defaultParams = ['nums', 'target'];
    testCases = [
      { id: 1, params: {} }
    ];
    currentCaseId = 1;
    maxCaseId = 1;
    
    renderCaseInputs(defaultParams);
    updateCaseButtons();
  }
  
  function renderCaseInputs(params = ['input']) {
    if (!els.caseInputs) return;
    
    els.caseInputs.innerHTML = '';
    
    const currentCase = testCases.find(tc => tc.id === currentCaseId);
    if (!currentCase) return;
    
    const caseDiv = document.createElement('div');
    caseDiv.className = 'case-input-field active';
    caseDiv.dataset.caseId = currentCase.id;
    
    params.forEach(param => {
      const paramDiv = document.createElement('div');
      paramDiv.className = 'input-param';
      
      const label = document.createElement('label');
      label.textContent = `${param} =`;
      
      const textarea = document.createElement('textarea');
      textarea.placeholder = `Enter ${param}`;
      textarea.rows = 3;  
      textarea.style.resize = 'vertical';  
      textarea.style.minHeight = '60px';
      textarea.value = currentCase.params[param] || '';
      textarea.dataset.param = param;
      
      textarea.addEventListener('input', (e) => {
        currentCase.params[param] = e.target.value;
      });
      
      paramDiv.appendChild(label);
      paramDiv.appendChild(textarea);
      caseDiv.appendChild(paramDiv);
    });
    
    // add Expected Output input area
    const outputDiv = document.createElement('div');
    outputDiv.className = 'expected-output-input';
    outputDiv.style.marginTop = '16px';
    
    const label = document.createElement('label');
    label.textContent = 'Expected Output =';
    label.style.display = 'block';
    label.style.marginBottom = '4px';
    label.style.color = '#64748B';
    label.style.fontWeight = '500';
    
    const textarea = document.createElement('textarea');
    textarea.placeholder = 'Enter expected output (optional)';
    textarea.rows = 3;
    textarea.style.resize = 'vertical';
    textarea.style.minHeight = '60px';
    textarea.value = currentCase.expectedOutput || '';
    textarea.dataset.param = 'expectedOutput';
    
    textarea.addEventListener('input', (e) => {
      currentCase.expectedOutput = e.target.value;
    });
    
    outputDiv.appendChild(label);
    outputDiv.appendChild(textarea);
    caseDiv.appendChild(outputDiv);
    
    els.caseInputs.appendChild(caseDiv);
  }

  function updateCaseButtons() {
    const caseSelector = document.querySelector('.case-selector');
    if (!caseSelector) return;
    
    // Remove existing case buttons (except add button)
    const existingButtons = caseSelector.querySelectorAll('.case-btn');
    existingButtons.forEach(btn => btn.remove());
    
    // Add case buttons
    testCases.forEach(testCase => {
      const btn = document.createElement('button');
      btn.className = 'case-btn';
      btn.dataset.caseNum = testCase.id;
      btn.textContent = `Case ${testCase.id}`;
      if (testCase.id === currentCaseId) {
        btn.classList.add('active');
      }
      
      btn.addEventListener('click', () => {
        switchCase(testCase.id);
      });
      
      caseSelector.insertBefore(btn, els.addCaseBtn);
    });
  }

  function switchCase(caseId) {
    currentCaseId = caseId;
    
    // Update button states
    document.querySelectorAll('.case-btn').forEach(btn => {
      btn.classList.toggle('active', parseInt(btn.dataset.caseNum) === caseId);
    });
    
    // Re-render input fields to show selected case's parameters
    const params = Array.from(document.querySelectorAll('.input-param label'))
      .map(label => label.textContent.replace(' =', '').trim());
    
    if (params.length === 0) {
      // If no parameters found, try to get from testCases
      const anyCase = testCases[0];
      if (anyCase && anyCase.params) {
        const paramNames = Object.keys(anyCase.params);
        if (paramNames.length > 0) {
          renderCaseInputs(paramNames);
          return;
        }
      }
      renderCaseInputs(['input']);
    } else {
      renderCaseInputs(params);
    }
  }


  function addNewCase() {
    maxCaseId++;
    const newCase = { id: maxCaseId, params: {} };
    testCases.push(newCase);
    
    const params = Array.from(document.querySelectorAll('.input-param label'))
      .map(label => label.textContent.replace(' =', '').trim());
    
    renderCaseInputs(params.length > 0 ? params : ['input']);
    updateCaseButtons();
    switchCase(maxCaseId);
  }

  // ============================================================
  // Run Code (Quick Test)
  // ============================================================
  
  async function runCode() {
    const code = cm ? cm.getValue() : els.code?.value || "";
    const tlimit = parseFloat(els.tlimit?.value || "2.0");

    if (!code.trim()) {
      setError("Please write some code first.");
      return;
    }

    // get all test cases
    const casesToRun = testCases.filter(tc => {
      // check input
      return Object.values(tc.params).some(v => v && v.trim());
    });

    if (casesToRun.length === 0) {
      setError("No valid test cases to run.");
      return;
    }

    setLoading(true);
    clearError();
    allTestResults = [];

    const runResults = document.getElementById('runResults');
    if (runResults) {
      runResults.innerHTML = `
        <div style="display: flex; align-items: center; justify-content: center; gap: 1rem; padding: 3rem;">
          <div class="spinner-border spinner-border-sm text-primary" role="status">
            <span class="visually-hidden">Running...</span>
          </div>
          <span>Running ${casesToRun.length} test case(s)...</span>
        </div>
      `;
    }

    // Execute all cases sequentially
    for (let i = 0; i < casesToRun.length; i++) {
      const testCase = casesToRun[i];
      
      // Format input
      const inputLines = Object.entries(testCase.params)
        .filter(([_, value]) => value && value.trim())
        .map(([_, value]) => value);
      const input = inputLines.join('\n');

      const payload = {
        code: code,
        language: LANG,
        input: input,
        expected_output: testCase.expectedOutput || null,
        time_limit_sec: tlimit
      };

      try {
        const response = await fetch(API_JUDGE, {
          method: "POST",
          headers: AUTH.authHeaders(),
          body: JSON.stringify(payload),
        });

        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || data.message || `HTTP ${response.status}`);
        }

        // save result
        allTestResults.push({
          caseId: testCase.id,
          caseIndex: i + 1,
          params: testCase.params,
          expectedOutput: testCase.expectedOutput,  // expected output
          ...data
        });

      } catch (err) {
        allTestResults.push({
          caseId: testCase.id,
          caseIndex: i + 1,
          params: testCase.params,
          expectedOutput: testCase.expectedOutput,  // add expected output
          error: err.message,
          status: 'ERROR'
        });
      }
    }

    setLoading(false);
    
    // Display results
    if (allTestResults.length > 0) {
      currentTestIndex = 0;
      displayAllTestResults();
    }
  }

  function displayAllTestResults() {
    const runResults = document.getElementById('runResults');
    if (!runResults) return;

    // Display first result directly (no navigation bar needed)
    if (allTestResults.length > 0) {
      currentTestIndex = 0;
      displaySingleTestResult(0);
    }
  }


  function displaySingleTestResult(index) {
    if (index < 0 || index >= allTestResults.length) return;
    
    currentTestIndex = index;
    const result = allTestResults[index];
    const runResults = document.getElementById('runResults');
    
    if (!runResults) return;

    const { stdout, stderr, status, compiled, passed } = result;
    
    const hasCompileError = !compiled || status === 'CE' || status === 'ERROR';
    const hasRuntimeError = stderr || result.error;
    
    const isTestPassed = result.expectedOutput 
      ? (passed === true && status === 'AC')
      : (!hasCompileError && !hasRuntimeError && status !== 'WA' && status !== 'TLE' && status !== 'RE');
    
    const hasError = hasCompileError || hasRuntimeError || !isTestPassed;

 runResults.innerHTML = `
  <div class="test-case-header-full">
    <!-- left section: Test Case info + status + nav -->
    <div class="header-left-group">
      <!-- Test Case title -->
      <div class="test-case-title-inline">
        <i class="bi bi-${hasError ? 'x-circle-fill' : 'check-circle-fill'}" 
           style="color: ${hasError ? '#ef4444' : '#22c55e'}"></i>
        Test Case ${result.caseIndex}
      </div>
      
      <!-- status Badge -->
      ${status ? `<span class="test-status-inline ${isTestPassed ? 'passed' : 'failed'}">${status}</span>` : ''}
      
      <!-- nav btn -->
      <div class="test-header-nav">
        <button class="btn btn-sm" id="prevTestBtnInline"
                ${index === 0 ? 'disabled' : ''}>
          <i class="bi bi-chevron-left"></i>
        </button>
        <span class="case-indicator-compact">
          <strong>${index + 1}</strong> / ${allTestResults.length}
        </span>
        <button class="btn btn-sm" id="nextTestBtnInline"
                ${index >= allTestResults.length - 1 ? 'disabled' : ''}>
          <i class="bi bi-chevron-right"></i>
        </button>
      </div>
    </div>
  </div>

  <div class="output-container">
    <!-- Input (if any) -->
    ${Object.keys(result.params || {}).length > 0 ? `
    <div class="output-block">
      <div class="output-label">
        <i class="bi bi-box-arrow-in-right"></i> Input
      </div>
      <div class="output-content">
${Object.entries(result.params).filter(([_, v]) => v && v.trim()).map(([k, v]) => `${k} = ${escapeHtml(v)}`).join('\n')}
      </div>
    </div>
    ` : ''}

    <!-- Your Output -->
    <div class="output-block your-output">
      <div class="output-label">
        <i class="bi bi-code-square"></i> Your Output
      </div>
      <div class="output-content ${!stdout || stdout.trim() === '' ? 'empty' : ''}">
${escapeHtml(stdout || result.output || '(empty)')}
      </div>
    </div>

    <!-- Expected Output (if provided) -->
    ${result.expectedOutput ? `
    <div class="output-block target-output">
      <div class="output-label">
        <i class="bi bi-bullseye"></i> Expected Output
      </div>
      <div class="output-content">
${escapeHtml(result.expectedOutput)}
      </div>
    </div>
    ` : ''}

    ${hasError && stderr ? `
    <!-- Error -->
    <div class="output-block error-output">
      <div class="output-label">
        <i class="bi bi-exclamation-triangle"></i> Error
      </div>
      <div class="output-content">
${escapeHtml(stderr)}
      </div>
    </div>
    ` : ''}

    ${result.error ? `
    <!-- Error Message -->
    <div class="output-block error-output">
      <div class="output-label">
        <i class="bi bi-exclamation-triangle"></i> Error
      </div>
      <div class="output-content">
${escapeHtml(result.error)}
      </div>
    </div>
    ` : ''}
  </div>
`;

  setupInlineTestNav();
}

  function setupInlineTestNav() {
    const prevBtn = document.getElementById('prevTestBtnInline');
    const nextBtn = document.getElementById('nextTestBtnInline');

    if (prevBtn) {
      prevBtn.onclick = () => {
        if (currentTestIndex > 0) {
          displaySingleTestResult(currentTestIndex - 1);
        }
      };
    }

    if (nextBtn) {
      nextBtn.onclick = () => {
        if (currentTestIndex < allTestResults.length - 1) {
          displaySingleTestResult(currentTestIndex + 1);
        }
      };
    }
  }

  function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
  }


  // ============================================================
  // Submit Solution
  // ============================================================
  
  async function submitSolution() {
    const code = cm ? cm.getValue() : els.code?.value || "";
    const tlimit = parseFloat(els.tlimit?.value || "2.0");
    
    if (!code.trim()) {
      setError("Please write some code first.");
      return;
    }

    setLoading(true);
    clearError();
    
    // Switch to Submission Result tab
    const submissionTab = document.querySelector('.results-tab[data-result-tab="submission"]');
    if (submissionTab) {
      submissionTab.click();
    }
    
    // Show processing state
    showEvaluationState("processing");

    const payload = {
      code: code,
      language: LANG,
      time_limit_sec: tlimit
    };

    try {
      const response = await fetch(API_SUBMIT(PROBLEM_ID), {
        method: "POST",
        headers: AUTH.authHeaders(),
        body: JSON.stringify(payload),
      });

      const data = await response.json();

      if (!response.ok) {
        const errorMsg = data.error || data.message || `HTTP ${response.status}: ${response.statusText}`;
        throw new Error(errorMsg);
      }

      // Ensure data is valid
      if (!data || typeof data !== 'object') {
        throw new Error("Invalid response format from server");
      }

      displaySubmissionResult(data);
      
      // Unlock solution tab
      if (data.score !== undefined || data.status === "completed") {
        unlockSolution();
        checkAndLoadSolution();
      }
    } catch (err) {
    
      showEvaluationState("error");
      if (els.errorDetail) {
        els.errorDetail.textContent = err.message || "Failed to submit solution. Please try again.";
      }
    } finally {
      setLoading(false);
    }
  }

  function showEvaluationState(state) {
    const states = ["processing", "score", "tests", "error"];
    states.forEach((s) => {
      const el = {
        processing: els.processing,
        score: els.scoreBox,
        tests: els.testsBox,
        error: els.errorBox
      }[s];
      if (el) {
        el.style.display = s === state ? "block" : "none";
      }
    });
  }

  function displaySubmissionResult(data) {

    const tests = data.cases || data.test_results || [];
    const passed = tests.filter(t => t.passed).length;
    const total = tests.length;
    const score = data.score !== undefined ? data.score : 0;

    // Save to global variables
    allSubmissionCases = tests;
    currentSubmissionIndex = 0;
    submissionScore = score;
    submissionPassedCount = passed;
    submissionTotalCount = total;
    
    // Calculate total time
    submissionTotalTime = tests.reduce((sum, t) => sum + (t.time_ms || 0), 0);

    // Hide processing and error states
    const processing = document.getElementById('processingSection');
    const errorBox = document.getElementById('errorSection');
    if (processing) processing.style.display = 'none';
    if (errorBox) errorBox.style.display = 'none';

    // Show test results area
    if (tests && tests.length > 0) {
      setTimeout(() => {
        const testsBox = document.getElementById('testResultsSection');
        if (testsBox) testsBox.style.display = 'block';
        displaySingleSubmissionCase(0);
      }, 500);
    }
  }

function displaySingleSubmissionCase(index) {
  if (index < 0 || index >= allSubmissionCases.length) return;
  
  currentSubmissionIndex = index;
  const testCase = allSubmissionCases[index];
  const singleTestCaseEl = document.getElementById('singleTestCase');

  const isHidden = !!testCase.hidden;

  if (!singleTestCaseEl) return;

  const isPassed = testCase.passed || testCase.status === "AC";
  const statusClass = isPassed ? "passed" : "failed";
  const statusText = isPassed ? "Passed" : "Failed";

  // Parse \n symbols in output and expected output for proper display
  const parsedOutput = testCase.output ? String(testCase.output).replace(/\\n/g, '\n') : '';
  const parsedExpected = testCase.expected ? String(testCase.expected).replace(/\\n/g, '\n') : '';
  const parsedStderr = testCase.stderr ? String(testCase.stderr).replace(/\\n/g, '\n') : '';

  singleTestCaseEl.innerHTML = `
  <div class="test-case-header-full">
    <!-- left: Test Case + status + nav -->
    <div class="header-left-group">
      <!-- Test Case title -->
      <div class="test-case-title-inline">
        Test Case ${testCase.index || index + 1}
      </div>
      
      <!-- status -->
      <span class="test-status-inline ${statusClass}">${statusText}</span>
      
      <!-- navbar -->
      <div class="test-header-nav">
        <button class="btn btn-sm" id="prevCaseBtnInline" 
                ${index === 0 ? 'disabled' : ''}>
          <i class="bi bi-chevron-left"></i>
        </button>
        <span class="case-num-inline">
          <strong>${index + 1}</strong>/<span class="total-count">${allSubmissionCases.length}</span>
        </span>
        <button class="btn btn-sm" id="nextCaseBtnInline"
                ${index >= allSubmissionCases.length - 1 ? 'disabled' : ''}>
          <i class="bi bi-chevron-right"></i>
        </button>
      </div>
    </div>

    <!-- right section: Score + pass rate + execute time -->
    <div class="header-right-group ms-auto">
      <!-- pass rate -->
      <div class="pass-rate-inline">
        <span class="pass-count">${submissionPassedCount}</span> / 
        <span class="total-count">${submissionTotalCount}</span> testcases passed
      </div>
      
      <!-- Score -->
      <div class="score-inline">
        Score: 
        <strong>${Math.round(submissionScore)}</strong>
      </div>
      
  
      <!-- Time -->
      <div class="time-inline">
        <i class="bi bi-clock-fill"></i>
        ${submissionTotalTime.toFixed(0)}ms
      </div>
    </div>
  </div>

  <div class="output-container">
    <!-- Your Output -->
    <div class="output-block your-output">
      <div class="output-label">
        <i class="bi bi-code-square"></i> Your Output
      </div>
      <div class="output-content ${!parsedOutput || parsedOutput === 'None' ? 'empty' : ''}">
${escapeHtml(parsedOutput || '(empty)')}
      </div>
    </div>

    <!-- Target Output -->
    <div class="output-block target-output">
      <div class="output-label">
        <i class="bi bi-bullseye"></i> Target
      </div>
      <div class="output-content${isHidden ? ' empty' : ''}">
${isHidden 
  ? escapeHtml('This is a hidden test case. Expected output is not shown.')
  : escapeHtml(parsedExpected || '(empty)')}
      </div>
    </div>

    ${parsedStderr && parsedStderr.trim() ? `
    <!-- Error -->
    <div class="output-block error-output">
      <div class="output-label">
        <i class="bi bi-exclamation-triangle"></i> Error
      </div>
      <div class="output-content">
${escapeHtml(parsedStderr)}
      </div>
    </div>
    ` : ''}
  </div>
`;

  // Bind navigation button events
  setupInlineSubmissionNav();
}

  function setupInlineSubmissionNav() {
    const prevBtn = document.getElementById('prevCaseBtnInline');
    const nextBtn = document.getElementById('nextCaseBtnInline');

    if (prevBtn) {
      prevBtn.onclick = () => {
        if (currentSubmissionIndex > 0) {
          displaySingleSubmissionCase(currentSubmissionIndex - 1);
        }
      };
    }

    if (nextBtn) {
      nextBtn.onclick = () => {
        if (currentSubmissionIndex < allSubmissionCases.length - 1) {
          displaySingleSubmissionCase(currentSubmissionIndex + 1);
        }
      };
    }
  }

  function setupResultsTabs() {
    const tabs = document.querySelectorAll('.results-tab');
    const testResultTab = document.getElementById('testResultTabContent');
    const submissionResultTab = document.getElementById('submissionResultTabContent');
    
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const tabType = tab.dataset.resultTab;
        
        // Update tab state
        tabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        
        // Switch content display
        if (tabType === 'testresult') {
          testResultTab.style.display = 'block';
          submissionResultTab.style.display = 'none';
        } else if (tabType === 'submission') {
          testResultTab.style.display = 'none';
          submissionResultTab.style.display = 'block';
        }
      });
    });
  }


  // ============================================================
  // Solution Tab
  // ============================================================
  
  /**
   * Check if user has submitted and load solution if available
   * Called on page load to restore solution state
   */
  async function checkAndLoadSolution() {
    try {
      const token = AUTH.getToken();
      if (!token) {
        return;
      }
      
      const response = await fetch(API_PROBLEM(PROBLEM_ID, LANG), {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });


      if (!response.ok) {
        return;
      }

      const data = await response.json();
      
      // If solution exists, unlock the tab and preload the solution
      if (data.solution || data.solution_code) {
        
        // Unlock solution tab
        const solutionTab = document.querySelector('.editor-tab[data-tab="solution"]');
        if (solutionTab) {
          solutionTab.classList.remove('locked');
        }
        
        // Preload solution content
        const solutionCode = data.solution_code || data.solution || "No solution available";
        const solutionLang = data.selected_language || data.programming_language || LANG;
        
        if (els.solutionCode) els.solutionCode.textContent = solutionCode;
        if (els.solutionLanguage) els.solutionLanguage.textContent = solutionLang.toUpperCase();
      } else {
      }
    } catch (err) {
    }
  }

  /**
   * Unlock and load solution (called after submission)
   */
  async function unlockSolution() {
    const solutionTab = document.querySelector('.editor-tab[data-tab="solution"]');
    if (solutionTab) {
      solutionTab.classList.remove('locked');
    }

    try {
      const token = AUTH.getToken();
      
      const response = await fetch(API_PROBLEM(PROBLEM_ID, LANG), {
        headers: token ? {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        } : {
          'Content-Type': 'application/json'
        }
      });


      if (!response.ok) {
        throw new Error('Failed to load solution');
      }

      const data = await response.json();
      
      // Extract solution from response
      const solutionCode = data.solution_code || data.solution || "No solution available";
      const solutionLang = data.selected_language || data.programming_language || LANG;
      
      if (els.solutionLocked) els.solutionLocked.style.display = "none";
      if (els.solutionUnlocked) els.solutionUnlocked.style.display = "block";
      if (els.solutionCode) els.solutionCode.textContent = solutionCode;
      if (els.solutionLanguage) els.solutionLanguage.textContent = solutionLang.toUpperCase();
    } catch (err) {
      // Still unlock tab but show error message
      if (els.solutionLocked) els.solutionLocked.style.display = "none";
      if (els.solutionUnlocked) els.solutionUnlocked.style.display = "block";
      if (els.solutionCode) {
        els.solutionCode.textContent = "Failed to load solution. Please try again later.";
      }
    }
  }

  function copySolution() {
    const code = els.solutionCode?.textContent || "";
    if (!code) return;

    navigator.clipboard.writeText(code).then(() => {
      if (els.copySolutionBtn) {
        const originalText = els.copySolutionBtn.innerHTML;
        els.copySolutionBtn.innerHTML = '<i class="bi bi-check"></i> Copied!';
        els.copySolutionBtn.style.background = "#3b82f6";
        
        setTimeout(() => {
          els.copySolutionBtn.innerHTML = originalText;
          els.copySolutionBtn.style.background = "#16a34a";
        }, 2000);
      }
    });
  }

  function setLoading(loading) {
    if (els.runBtn) els.runBtn.disabled = loading;
    if (els.submitBtn) els.submitBtn.disabled = loading;
  }

  function setError(message) {
    if (els.error) {
      els.error.textContent = message;
      els.error.classList.add("show");
    }
  }

  function clearError() {
    if (els.error) {
      els.error.textContent = "";
      els.error.classList.remove("show");
    }
  }

  // ============================================================
  // Resizable Panels
  // ============================================================

  function setupResizablePanels() {
    const container = document.querySelector('.code-runner-container');
    const leftPanel = document.querySelector('.left-panel');
    const rightPanel = document.querySelector('.right-panel');
    const verticalDivider = document.getElementById('verticalDivider');
    
    const descriptionSection = document.querySelector('.description-section');
    const testcaseSection = document.querySelector('.testcase-section');
    const horizontalDivider = document.getElementById('horizontalDivider');
    
    const editorSection = document.querySelector('.editor-section');
    const resultsSection = document.querySelector('.results-section');
    const horizontalDividerRight = document.getElementById('horizontalDividerRight');

    // Minimum width settings (pixels)
    const MIN_LEFT_WIDTH = 350;
    const MIN_RIGHT_WIDTH = 450;

    if (verticalDivider && leftPanel && rightPanel && container) {
      let isResizing = false;
      let startX = 0;
      let startLeftWidth = 0;

      verticalDivider.addEventListener('mousedown', (e) => {
        isResizing = true;
        startX = e.clientX;
        startLeftWidth = leftPanel.offsetWidth;
        document.body.classList.add('dragging');
        e.preventDefault();
      });

      document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const containerWidth = container.offsetWidth;
        const deltaX = e.clientX - startX;
        const newLeftWidth = startLeftWidth + deltaX;
        const newRightWidth = containerWidth - newLeftWidth;
        
        // Check if minimum width is reached
        if (newLeftWidth < MIN_LEFT_WIDTH) {
          // Hide left panel
          leftPanel.style.width = '0';
          leftPanel.classList.add('collapsed');
          rightPanel.classList.remove('collapsed');
        } else if (newRightWidth < MIN_RIGHT_WIDTH) {
          // Hide right panel
          rightPanel.style.width = '0';
          rightPanel.classList.add('collapsed');
          leftPanel.classList.remove('collapsed');
          leftPanel.style.width = '100%';
        } else {
          // Show both panels
          leftPanel.classList.remove('collapsed');
          rightPanel.classList.remove('collapsed');
          const newLeftWidthPercent = (newLeftWidth / containerWidth) * 100;
          if (newLeftWidthPercent >= 25 && newLeftWidthPercent <= 75) {
            leftPanel.style.width = `${newLeftWidthPercent}%`;
          }
        }
      });

      document.addEventListener('mouseup', () => {
        if (isResizing) {
          isResizing = false;
          document.body.classList.remove('dragging');
          if (cm) cm.refresh();
        }
      });
    }

    if (horizontalDivider && descriptionSection && testcaseSection && leftPanel) {
      let isResizing = false;
      let startY = 0;
      let startDescHeight = 0;

      horizontalDivider.addEventListener('mousedown', (e) => {
        isResizing = true;
        startY = e.clientY;
        startDescHeight = descriptionSection.offsetHeight;
        document.body.classList.add('dragging-horizontal');
        e.preventDefault();
      });

      document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const panelHeight = leftPanel.offsetHeight;
        const deltaY = e.clientY - startY;
        const newDescHeight = startDescHeight + deltaY;
        const newDescHeightPercent = (newDescHeight / panelHeight) * 100;
        if (newDescHeightPercent >= 30 && newDescHeightPercent <= 70) {
          descriptionSection.style.flex = `${newDescHeightPercent} 1 0px`;
          testcaseSection.style.flex = `${100 - newDescHeightPercent} 1 0px`;
        }
      });

      document.addEventListener('mouseup', () => {
        if (isResizing) {
          isResizing = false;
          document.body.classList.remove('dragging-horizontal');
        }
      });
    }

    if (horizontalDividerRight && editorSection && resultsSection && rightPanel) {
      let isResizing = false;
      let startY = 0;
      let startEditorHeight = 0;

      horizontalDividerRight.addEventListener('mousedown', (e) => {
        isResizing = true;
        startY = e.clientY;
        startEditorHeight = editorSection.offsetHeight;
        document.body.classList.add('dragging-horizontal');
        e.preventDefault();
      });

      document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const panelHeight = rightPanel.offsetHeight;
        const deltaY = e.clientY - startY;
        const newEditorHeight = startEditorHeight + deltaY;
        const newEditorHeightPercent = (newEditorHeight / panelHeight) * 100;
        if (newEditorHeightPercent >= 30 && newEditorHeightPercent <= 70) {
          editorSection.style.flex = `${newEditorHeightPercent} 1 0px`;
          resultsSection.style.flex = `${100 - newEditorHeightPercent} 1 0px`;
        }
      });

      document.addEventListener('mouseup', () => {
        if (isResizing) {
          isResizing = false;
          document.body.classList.remove('dragging-horizontal');
          if (cm) cm.refresh();
        }
      });
    }
  }

  function setupEventListeners() {
    els.editorTabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        switchEditorTab(tab.dataset.tab);
      });
    });

    // Add case button
    if (els.addCaseBtn) {
      els.addCaseBtn.addEventListener('click', addNewCase);
    }

    if (els.runBtn) {
      els.runBtn.addEventListener('click', runCode);
    }

    if (els.submitBtn) {
      els.submitBtn.addEventListener('click', submitSolution);
    }

    if (els.themeBtn) {
      els.themeBtn.addEventListener('click', switchTheme);
    }

    if (els.copySolutionBtn) {
      els.copySolutionBtn.addEventListener('click', copySolution);
    }

    const languageSelect = document.getElementById("problemLanguageSelect");
    if (languageSelect) {
      languageSelect.addEventListener("change", () => {
        const next = languageSelect.value || "python";
        window.location.href = `/problem/${PROBLEM_ID}?language=${encodeURIComponent(next)}`;
      });
    }

    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        runCode();
      }
    });
  }

  function init() {
    loadSavedTheme();
    ensureEditor();
    initTestCases();
    setupEventListeners();
    setupResizablePanels();
    setupResultsTabs();
    // Check if solution is available (user has submitted before)
    checkAndLoadSolution();
    
    setTimeout(() => {
      if (cm) cm.refresh();
    }, 100);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
