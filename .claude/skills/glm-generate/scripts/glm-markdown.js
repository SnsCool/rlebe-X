#!/usr/bin/env node

/**
 * GLM (Z.ai) API を使用してテキスト・コードを生成するスクリプト
 * Anthropic互換エンドポイント使用（サブスクリプション対応）
 *
 * 使用方法:
 *   node glm-markdown.js --prompt <file> [--context <file>...] [--output <file>] [--model <model>]
 *
 * 環境変数:
 *   ZAI_API_KEY - Z.ai API キー（必須）
 */

const fs = require('fs');
const path = require('path');
const https = require('https');

// =============================================================================
// 設定
// =============================================================================
const DEFAULT_MODEL = 'glm-4.7';
const API_ENDPOINT = 'https://api.z.ai/api/anthropic/v1/messages';
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 15000; // 15秒

// =============================================================================
// 引数パース
// =============================================================================
function parseArgs(args) {
    const result = {
        prompt: null,
        context: [],
        output: null,
        model: DEFAULT_MODEL
    };

    for (let i = 0; i < args.length; i++) {
        switch (args[i]) {
            case '--prompt':
                result.prompt = args[++i];
                break;
            case '--context':
                // 複数の --context をサポート
                while (args[i + 1] && !args[i + 1].startsWith('--')) {
                    result.context.push(args[++i]);
                }
                break;
            case '--output':
                result.output = args[++i];
                break;
            case '--model':
                result.model = args[++i];
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
        console.error(error.message);
        process.exit(1);
    }
}

// =============================================================================
// Z.ai API 呼び出し（Anthropic互換エンドポイント）
// =============================================================================
async function callZaiApi(prompt, contextFiles, model) {
    const apiKey = process.env.ZAI_API_KEY;

    if (!apiKey) {
        throw new Error('ZAI_API_KEY environment variable is not set');
    }

    // コンテキストを構築
    let fullPrompt = prompt;
    if (contextFiles.length > 0) {
        const contextContent = contextFiles.map(file => {
            const content = readFile(file);
            const filename = path.basename(file);
            return `--- ${filename} ---\n${content}\n`;
        }).join('\n');

        fullPrompt = `## Context Files\n\n${contextContent}\n\n## Task\n\n${prompt}`;
    }

    const requestBody = JSON.stringify({
        model: model,
        max_tokens: 8192,
        messages: [
            {
                role: 'user',
                content: fullPrompt
            }
        ]
    });

    return new Promise((resolve, reject) => {
        const url = new URL(API_ENDPOINT);

        const options = {
            hostname: url.hostname,
            port: 443,
            path: url.pathname,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'x-api-key': apiKey,
                'anthropic-version': '2023-06-01',
                'Content-Length': Buffer.byteLength(requestBody)
            }
        };

        const req = https.request(options, (res) => {
            let data = '';

            res.on('data', chunk => {
                data += chunk;
            });

            res.on('end', () => {
                if (res.statusCode === 429) {
                    reject(new Error('RATE_LIMIT'));
                    return;
                }

                if (res.statusCode !== 200) {
                    reject(new Error(`API Error: ${res.statusCode} - ${data}`));
                    return;
                }

                try {
                    const response = JSON.parse(data);

                    // Anthropic形式のレスポンスをパース
                    const content = response.content?.[0]?.text;

                    if (!content) {
                        reject(new Error('No content in API response'));
                        return;
                    }

                    resolve(content);
                } catch (e) {
                    reject(new Error(`Failed to parse API response: ${e.message}`));
                }
            });
        });

        req.on('error', reject);
        req.write(requestBody);
        req.end();
    });
}

// =============================================================================
// リトライ付き API 呼び出し
// =============================================================================
async function callWithRetry(prompt, contextFiles, model) {
    let lastError;

    for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
        try {
            return await callZaiApi(prompt, contextFiles, model);
        } catch (error) {
            lastError = error;

            if (error.message === 'RATE_LIMIT' && attempt < MAX_RETRIES) {
                console.error(`Rate limited. Waiting ${RETRY_DELAY_MS / 1000}s before retry ${attempt + 1}/${MAX_RETRIES}...`);
                await new Promise(resolve => setTimeout(resolve, RETRY_DELAY_MS));
            } else if (error.message !== 'RATE_LIMIT') {
                throw error;
            }
        }
    }

    throw new Error(`Rate limit exceeded after ${MAX_RETRIES} retries`);
}

// =============================================================================
// メイン
// =============================================================================
async function main() {
    const args = parseArgs(process.argv.slice(2));

    // バリデーション
    if (!args.prompt) {
        console.error('Usage: node glm-markdown.js --prompt <file> [--context <file>...] [--output <file>] [--model <model>]');
        console.error('');
        console.error('Options:');
        console.error('  --prompt   Path to prompt file (required)');
        console.error('  --context  Path to context files (can specify multiple)');
        console.error('  --output   Output file path (default: stdout)');
        console.error('  --model    Model to use (default: glm-4.7)');
        console.error('');
        console.error('Available models: glm-4.7, glm-4.6, glm-4.5, glm-4.5-Air');
        process.exit(1);
    }

    // プロンプト読み込み
    const promptContent = readFile(args.prompt);

    console.error(`Using model: ${args.model}`);
    console.error(`Prompt file: ${args.prompt}`);
    if (args.context.length > 0) {
        console.error(`Context files: ${args.context.join(', ')}`);
    }
    console.error('Generating...');

    try {
        // API 呼び出し
        const result = await callWithRetry(promptContent, args.context, args.model);

        // 出力
        if (args.output) {
            fs.writeFileSync(args.output, result, 'utf-8');
            console.error(`Output written to: ${args.output}`);
        } else {
            console.log(result);
        }
    } catch (error) {
        console.error(`Error: ${error.message}`);
        process.exit(1);
    }
}

main();
