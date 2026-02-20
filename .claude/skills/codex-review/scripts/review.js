#!/usr/bin/env node

/**
 * OpenAI CLI を使用してコードレビューを実行するスクリプト
 *
 * 前提条件:
 *   npm install -g @openai/codex  または  pip install openai
 *
 * 使用方法:
 *   node review.js --files <file1> [file2...] [--diff] [--output <file>]
 */

const fs = require('fs');
const path = require('path');
const { execSync, spawnSync } = require('child_process');

// =============================================================================
// 引数パース
// =============================================================================
function parseArgs(args) {
    const result = {
        files: [],
        diff: false,
        output: null
    };

    for (let i = 0; i < args.length; i++) {
        switch (args[i]) {
            case '--files':
                while (args[i + 1] && !args[i + 1].startsWith('--')) {
                    result.files.push(args[++i]);
                }
                break;
            case '--diff':
                result.diff = true;
                break;
            case '--output':
                result.output = args[++i];
                break;
        }
    }

    return result;
}

// =============================================================================
// ファイル読み込み
// =============================================================================
function readFile(filePath) {
    try {
        return fs.readFileSync(filePath, 'utf-8');
    } catch (error) {
        console.error(`Error reading file: ${filePath}`);
        return null;
    }
}

// =============================================================================
// Git diff 取得
// =============================================================================
function getGitDiff() {
    try {
        const staged = execSync('git diff --cached', { encoding: 'utf-8' });
        if (staged.trim()) return staged;
        return execSync('git diff', { encoding: 'utf-8' });
    } catch (error) {
        return null;
    }
}

// =============================================================================
// OpenAI CLI でレビュー実行
// =============================================================================
function runCodexCLI(content) {
    const prompt = `You are an expert code reviewer. Analyze the following code and return a JSON response:

{
  "ok": boolean (true if no critical issues),
  "summary": "Brief summary",
  "issues": [
    {
      "severity": "error" | "warning" | "info",
      "file": "filename",
      "line": line_number or null,
      "message": "Issue description",
      "suggestion": "How to fix"
    }
  ],
  "passed_checks": ["List of passed checks"]
}

Check for: security vulnerabilities, error handling, code style, performance, best practices.
Return ONLY valid JSON.

Code to review:
${content}`;

    // 一時ファイルにプロンプトを保存
    const tmpFile = `/tmp/codex-review-${Date.now()}.txt`;
    fs.writeFileSync(tmpFile, prompt, 'utf-8');

    try {
        // openai CLI を試行
        const result = spawnSync('openai', [
            'api', 'chat.completions.create',
            '-m', 'gpt-4',
            '-g', 'user', prompt
        ], {
            encoding: 'utf-8',
            timeout: 120000,
            maxBuffer: 10 * 1024 * 1024
        });

        if (result.status === 0 && result.stdout) {
            return parseCliOutput(result.stdout);
        }

        // 代替: curl で直接 API 呼び出し
        return runWithCurl(prompt);

    } finally {
        // 一時ファイル削除
        try { fs.unlinkSync(tmpFile); } catch (e) {}
    }
}

// =============================================================================
// curl で API 呼び出し
// =============================================================================
function runWithCurl(prompt) {
    const apiKey = process.env.OPENAI_API_KEY;
    if (!apiKey) {
        throw new Error('OPENAI_API_KEY environment variable is not set');
    }

    const payload = JSON.stringify({
        model: 'gpt-4',
        messages: [
            { role: 'user', content: prompt }
        ],
        temperature: 0.3,
        max_tokens: 2048
    });

    // payload を一時ファイルに保存（長いプロンプト対策）
    const tmpPayload = `/tmp/codex-payload-${Date.now()}.json`;
    fs.writeFileSync(tmpPayload, payload, 'utf-8');

    try {
        const result = execSync(`curl -s https://api.openai.com/v1/chat/completions \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer ${apiKey}" \
            -d @${tmpPayload}`, {
            encoding: 'utf-8',
            timeout: 120000
        });

        const response = JSON.parse(result);
        const content = response.choices?.[0]?.message?.content;

        if (!content) {
            throw new Error('No content in API response');
        }

        return JSON.parse(content);

    } finally {
        try { fs.unlinkSync(tmpPayload); } catch (e) {}
    }
}

// =============================================================================
// CLI 出力をパース
// =============================================================================
function parseCliOutput(output) {
    // JSON 部分を抽出
    const jsonMatch = output.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
        return JSON.parse(jsonMatch[0]);
    }
    throw new Error('Could not parse CLI output as JSON');
}

// =============================================================================
// メイン
// =============================================================================
async function main() {
    const args = parseArgs(process.argv.slice(2));

    // コンテンツ収集
    let content = '';

    if (args.diff) {
        const diff = getGitDiff();
        if (diff) {
            content += `## Git Diff\n\`\`\`diff\n${diff}\n\`\`\`\n\n`;
        }
    }

    if (args.files.length > 0) {
        for (const file of args.files) {
            const fileContent = readFile(file);
            if (fileContent) {
                const ext = path.extname(file).slice(1) || 'text';
                content += `## ${file}\n\`\`\`${ext}\n${fileContent}\n\`\`\`\n\n`;
            }
        }
    }

    if (!content) {
        console.error('Usage: node review.js --files <file1> [file2...] [--diff] [--output <file>]');
        console.error('');
        console.error('Options:');
        console.error('  --files   Files to review (can specify multiple)');
        console.error('  --diff    Include git diff in review');
        console.error('  --output  Output file path (default: stdout)');
        console.error('');
        console.error('Environment:');
        console.error('  OPENAI_API_KEY - Required for API calls');
        process.exit(1);
    }

    console.error('Reviewing code with Codex CLI...');

    try {
        const result = runCodexCLI(content);

        const output = JSON.stringify(result, null, 2);

        if (args.output) {
            fs.writeFileSync(args.output, output, 'utf-8');
            console.error(`Output written to: ${args.output}`);
        } else {
            console.log(output);
        }

        // 結果サマリー
        console.error('');
        console.error(`Review Result: ${result.ok ? '✅ PASSED' : '❌ ISSUES FOUND'}`);
        console.error(`Summary: ${result.summary}`);

        if (result.issues && result.issues.length > 0) {
            console.error(`Issues: ${result.issues.length}`);
            for (const issue of result.issues) {
                const icon = issue.severity === 'error' ? '🔴' : issue.severity === 'warning' ? '🟡' : '🔵';
                console.error(`  ${icon} [${issue.severity}] ${issue.message}`);
            }
        }

        process.exit(result.ok ? 0 : 1);

    } catch (error) {
        console.error(`Error: ${error.message}`);
        process.exit(1);
    }
}

main();
