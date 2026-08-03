import { render, screen } from '@testing-library/react';
import StageReportPanel from '../StageReportPanel';

jest.mock('react-markdown', () => {
  function MockReactMarkdown({ children }: { children: string }) {
    return (
      <div>
        {String(children).split('\n').map((line, i) =>
          /^# /.test(line) ? (
            <h1 key={i}>{line.replace(/^# /, '')}</h1>
          ) : /^## /.test(line) ? (
            <h2 key={i}>{line.replace(/^## /, '')}</h2>
          ) : (
            <div key={i}>{line}</div>
          )
        )}
      </div>
    );
  }
  return MockReactMarkdown;
});

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    text: async () => '# GIS 全链阶段报告\n\n## EXPLORE / explore_bridge',
  } as Response);
});

test('renders fetched markdown headings', async () => {
  render(<StageReportPanel sessionId="sess-1" />);
  expect(await screen.findByText('GIS 全链阶段报告')).toBeInTheDocument();
  expect(await screen.findByText(/EXPLORE \/ explore_bridge/)).toBeInTheDocument();
});
