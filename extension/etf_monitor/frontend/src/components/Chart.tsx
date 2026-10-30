import { useEffect, useRef } from 'react';
import { init, type ECharts, type EChartsOption } from 'echarts';
import { download, Empty, useToast } from '../ui';

/** 功能：显示独立绘制的 ECharts 并导出 PNG；输入：标题、图形配置、是否有数据；输出：图表面板。 */
export function Chart({ title, option, hasData, description }: { title: string; option: EChartsOption; hasData: boolean; description?: string }) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<ECharts | null>(null);
  const notify = useToast();
  useEffect(() => {
    if (!hasData || !container.current) return;
    const chart = init(container.current, undefined, { renderer: 'canvas' }); instance.current = chart;
    chart.setOption({ backgroundColor: '#111b2c', textStyle: { color: '#a7b7d0', fontFamily: 'sans-serif' }, animation: false, ...option });
    const resize = () => chart.resize();
    const observer = new ResizeObserver(resize); observer.observe(container.current);
    window.addEventListener('resize', resize);
    return () => { observer.disconnect(); window.removeEventListener('resize', resize); chart.dispose(); instance.current = null; };
  }, [option, hasData]);
  /** 功能：导出当前真实图表；输入：无；输出：PNG 下载或失败提示。 */
  const exportPNG = async () => {
    try {
      if (!instance.current) throw new Error('图表无数据，不能导出 PNG');
      const url = instance.current.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#111b2c' });
      const blob = await (await fetch(url)).blob(); download(blob, `ETF-${title}.png`);
      notify('PNG 图表已导出');
    } catch (error) { notify(error instanceof Error ? error.message : 'PNG 导出失败', 'error'); }
  };
  return <section className="panel chart-panel"><div className="panel-title"><h2>{title}</h2><button onClick={() => void exportPNG()} disabled={!hasData}>导出 PNG</button></div>{description && <p className="muted">{description}</p>}{hasData ? <div ref={container} className="chart" role="img" aria-label={title} /> : <Empty>当前范围没有可绘制数据；缺失不等于零。</Empty>}</section>;
}
