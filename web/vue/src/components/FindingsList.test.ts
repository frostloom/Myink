import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import FindingsList from './FindingsList.vue'
afterEach(cleanup)
it('sorts severities and emits evidence chapter navigation while preserving quotes and suggestions',async()=>{const nav=vi.fn();const base={conflict_type:'timeline',scope:'local' as const,source:'validator',evidence:[{chapter:3,quote:'证据'}],suggestion:'修正时间'};render(FindingsList,{props:{findings:[{...base,conflict_key:'minor',severity:'minor'},{...base,conflict_key:'critical',severity:'critical'}],onNavigateChapter:nav}});const rows=screen.getAllByRole('listitem');expect(rows[0]?.textContent).toContain('致命');expect(rows[0]?.textContent).toContain('证据');await fireEvent.click(screen.getAllByRole('button')[0]!);expect(nav).toHaveBeenCalledWith(3)})
it('shows an empty result',()=>{render(FindingsList,{props:{findings:[]}});expect(screen.getByText('未发现冲突。')).toBeTruthy()})
