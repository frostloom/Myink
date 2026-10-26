import { h } from 'vue'

// @vitest-environment jsdom
import { cleanup, render, screen } from '../workspaceTestUtils';
import { afterEach, expect, it } from 'vitest';
import TaskTimeline from './TaskTimeline.vue';
import FindingsList from './FindingsList.vue';
import type { AgentRun } from '../../../src/types';
afterEach(cleanup);
it('shows patch routing and application metrics as part of the real flow', async () => {
    const base: AgentRun = { node: 'patch', model_id: 'test', input_tokens: 17, output_tokens: 11,
        cache_hit: false, duration_ms: 2, cost_est: 0, retry_count: 0, degraded: false, error: null,
        detail: { patch_applied: 1, patch_skipped: 2, revise_mode: 'patch' } };
    render(h(TaskTimeline, { "taskId": "t", "phase": "terminal", "status": "done", "nodes": [], "runs": [{ ...base, node: 'route', detail: { route: 'patch' } }, base], "progress": null, "error": null, "onRetry": () => { }, "refresh": () => { } }, []));
    expect(screen.getByText('局部修订')).toBeTruthy();
    expect(screen.getByText('局部修订并复审')).toBeTruthy();
    expect(screen.getByText('应用 1 · 跳过 2')).toBeTruthy();
});
it('shows finding scope without an extra explanation paragraph', async () => {
    render(h(FindingsList, { "findings": [{ conflict_key: 'a', conflict_type: 'style', severity: 'major',
                source: 'L1', scope: 'local', evidence: [], suggestion: null }] }, []));
    expect(screen.getByText('局部')).toBeTruthy();
});
